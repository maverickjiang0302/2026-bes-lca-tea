"""Assemble one product under one scenario into annual cash and carbon flows.

Sign conventions
----------------
Economic margin  = revenue (+ optional treatment credit) - all costs   [$ per m2 per yr]
Climate margin   = avoided burden (+ optional credit) - all burdens     [kg CO2e per m2 per yr]
Positive margins mean the pathway pays / helps. Both are also reported per mole
of electrons and at plant scale.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from . import dsp as dsp_mod
from . import electrochem as ec
from . import stack as stack_mod


@dataclass(frozen=True)
class Scenario:
    j: float                       # A m-2
    ce: float                      # cathodic Coulombic efficiency to the product
    anodic_ce: float
    anode_thickness_m: float
    stack_cost_mult: float = 1.0
    membrane_cost_mult: float = 1.0
    extra_overpotential_V: float = 0.0
    ph_gradient_V: float = 0.0
    anode_kinetic_V: float = 0.0
    cathode_kinetic_V: float = 0.0
    grid_ci: float = 0.0           # kg CO2e per kWh
    price_mult: float = 1.0
    catholyte_wt_pct: float | None = None
    treatment_credit: bool = False
    onsite_fraction: float = 0.0   # fraction of product used on site without DSP
    evaporation_mode: str | None = None
    dsp_enabled: bool = True
    mode: str = "ideal"


def make_scenario(cfg: dict[str, Any], product_key: str, mode: str = "ideal", **overrides: Any) -> Scenario:
    cell, plant, prod = cfg["cell"], cfg["plant"], cfg["products"][product_key]
    op, g = cell["operation"], cell["geometry"]
    if mode == "ideal":
        base = Scenario(j=op["current_density_A_per_m2"], ce=1.0,
                        anodic_ce=plant["plant"]["anodic_coulombic_efficiency"],
                        anode_thickness_m=g["anode_thickness_m"],
                        grid_ci=plant["energy"]["electricity_kg_co2e_per_kWh"], mode="ideal")
    elif mode == "realistic":
        lr = cell["losses"]["realistic"]
        base = Scenario(j=op["current_density_realistic_A_per_m2"], ce=prod["realistic"]["coulombic_efficiency"],
                        anodic_ce=plant["plant"]["anodic_coulombic_efficiency"],
                        anode_thickness_m=lr["anode_thickness_m"], ph_gradient_V=lr["ph_gradient_V"],
                        anode_kinetic_V=lr["anode_kinetic_V"], cathode_kinetic_V=prod["realistic"]["cathode_kinetic_V"],
                        grid_ci=plant["energy"]["electricity_kg_co2e_per_kWh"], mode="realistic")
    else:
        raise ValueError(mode)
    return replace(base, **overrides)


def evaluate(cfg: dict[str, Any], product_key: str, sc: Scenario) -> dict[str, Any]:
    plant, cell, prod, dsp_cfg = cfg["plant"], cfg["cell"], cfg["products"][product_key], cfg["dsp"]
    p, en, const = plant["plant"], plant["energy"], plant["constants"]
    hours = p["operating_h_per_yr"]

    # --- electrons -----------------------------------------------------------------
    K = ec.K_mol_e_per_A_m2_yr(hours)
    n_e = sc.j * K                                                    # mol e- per m2 per yr
    mol_e_per_m3 = p["bod_in_mg_per_L"] * p["bod_removal"] / const["g_bod_per_mol_e"] * sc.anodic_ce
    m3_treated = n_e / mol_e_per_m3                                   # m3 wastewater per m2 per yr
    current_plant_A = (p["flow_m3_per_h"] * mol_e_per_m3) * ec.FARADAY / 3600.0
    area_m2 = current_plant_A / sc.j
    volume_m3 = area_m2 * cell["geometry"]["chamber_depth_m"]
    hrt_h = volume_m3 / p["flow_m3_per_h"]

    # --- product -------------------------------------------------------------------
    mol_product = n_e * sc.ce / prod["electrons"]
    kg_formed = mol_product * prod["M_g_per_mol"] / 1000.0            # per m2 per yr
    kg_formed_plant_per_h = kg_formed * area_m2 / hours

    # --- voltage and cell electricity ---------------------------------------------
    vb = ec.voltage_budget(prod, cell, sc.j, anode_thickness_m=sc.anode_thickness_m,
                           ph_gradient_V=sc.ph_gradient_V, anode_kinetic_V=sc.anode_kinetic_V,
                           cathode_kinetic_V=sc.cathode_kinetic_V, extra_overpotential_V=sc.extra_overpotential_V)
    kwh_cell = ec.cell_electricity_kWh_per_m2_yr(sc.j, vb.V_applied, hours, en["rectifier_efficiency"],
                                                 en["inverter_efficiency"])
    cost_elec_cell = kwh_cell * en["electricity_usd_per_kWh"]
    gwp_elec_cell = kwh_cell * sc.grid_ci

    # --- pumping -------------------------------------------------------------------
    recirc = ec.recirculation(cell)
    kwh_pump = recirc["power_W_per_m2"] * hours / 1000.0 + p["feed_pumping_kWh_per_m3"] * m3_treated
    cost_pump = kwh_pump * en["electricity_usd_per_kWh"]
    gwp_pump = kwh_pump * sc.grid_ci

    # --- stack ---------------------------------------------------------------------
    stack_df = stack_mod.stack_annual(cell, plant, prod["cathode_type"], stack_cost_mult=sc.stack_cost_mult,
                                      membrane_cost_mult=sc.membrane_cost_mult)
    st = stack_mod.stack_totals(stack_df)
    cost_stack, gwp_stack = st["annual_usd_per_m2"], st["annual_gwp_kg_per_m2"]

    # --- downstream processing -----------------------------------------------------
    dsp_fraction = 1.0 - sc.onsite_fraction
    dsp = dsp_mod.evaluate_dsp(prod, dsp_cfg, plant, kg_formed_plant_per_h * dsp_fraction,
                               catholyte_wt_pct=sc.catholyte_wt_pct, evaporation_mode=sc.evaporation_mode,
                               enabled=sc.dsp_enabled and dsp_fraction > 0)
    kg_to_dsp = kg_formed * dsp_fraction
    kg_sold = kg_to_dsp * dsp.recovery + kg_formed * sc.onsite_fraction
    cost_dsp_var = kg_to_dsp * dsp.variable_usd_per_kg(en)
    gwp_dsp_var = kg_to_dsp * dsp.variable_gwp_per_kg(en, sc.grid_ci)
    cost_dsp_capex = dsp.annual_capex_usd / area_m2 if area_m2 > 0 else 0.0
    co2 = plant["co2_feed"]
    cost_co2 = kg_formed * prod["co2_kg_per_kg_product"] * co2["handling_usd_per_t"] / 1000.0
    gwp_co2 = kg_formed * prod["co2_kg_per_kg_product"] * co2["kg_co2e_per_kg"]

    # --- revenue and credits -------------------------------------------------------
    price = prod["price_usd_per_kg"] * sc.price_mult
    revenue = kg_sold * price
    gwp_avoided = kg_sold * prod["avoided_gwp_kg_co2e_per_kg"]
    tc = plant["treatment_credit"]
    credit_usd = tc["usd_per_m3"] * m3_treated if sc.treatment_credit else 0.0
    credit_gwp = tc["kg_co2e_per_m3"] * m3_treated if sc.treatment_credit else 0.0

    cost_total = cost_stack + cost_elec_cell + cost_pump + cost_dsp_var + cost_dsp_capex + cost_co2
    gwp_total = gwp_stack + gwp_elec_cell + gwp_pump + gwp_dsp_var + gwp_co2
    margin = revenue + credit_usd - cost_total
    env_margin = gwp_avoided + credit_gwp - gwp_total
    breakeven_price = (cost_total - credit_usd) / kg_sold if kg_sold > 0 else float("nan")

    return {
        "product": product_key, "label": prod["label"], "phase": prod["phase"], "mode": sc.mode,
        # scenario echo
        "j_A_m2": sc.j, "ce": sc.ce, "anode_thickness_mm": sc.anode_thickness_m * 1000.0,
        "stack_cost_mult": sc.stack_cost_mult, "price_mult": sc.price_mult, "grid_ci": sc.grid_ci,
        "catholyte_wt_pct": sc.catholyte_wt_pct if sc.catholyte_wt_pct is not None else prod["dsp"].get("catholyte_wt_pct", float("nan")),
        # electrons and product
        "mol_e_per_m2_yr": n_e, "m3_treated_per_m2_yr": m3_treated, "kg_formed_per_m2_yr": kg_formed,
        "kg_sold_per_m2_yr": kg_sold, "dsp_recovery": dsp.recovery,
        # voltage
        "E_thermo_V": vb.E_thermo, "eta_ohm_V": vb.eta_ohm, "eta_ph_V": vb.eta_ph, "eta_kin_V": vb.eta_kin,
        "V_applied_V": vb.V_applied, "kWh_cell_per_m2_yr": kwh_cell, "kWh_pump_per_m2_yr": kwh_pump,
        # economics, $ per m2 per yr
        "revenue": revenue, "credit_treatment": credit_usd, "cost_stack": cost_stack, "cost_elec_cell": cost_elec_cell,
        "cost_pump": cost_pump, "cost_dsp_var": cost_dsp_var, "cost_dsp_capex": cost_dsp_capex, "cost_co2": cost_co2,
        "cost_total": cost_total, "margin": margin, "margin_per_mol_e": margin / n_e,
        "revenue_per_mol_e": revenue / n_e, "cost_per_mol_e": cost_total / n_e,
        "margin_over_revenue": margin / revenue if revenue > 0 else float("nan"),
        "breakeven_price_usd_per_kg": breakeven_price, "breakeven_price_mult": breakeven_price / price if price > 0 else float("nan"),
        # climate, kg CO2e per m2 per yr
        "gwp_avoided": gwp_avoided, "gwp_credit_treatment": credit_gwp, "gwp_stack": gwp_stack,
        "gwp_elec_cell": gwp_elec_cell, "gwp_pump": gwp_pump, "gwp_dsp": gwp_dsp_var, "gwp_co2": gwp_co2,
        "gwp_total": gwp_total, "env_margin": env_margin, "env_margin_per_mol_e": env_margin / n_e,
        "gwp_avoided_per_mol_e": gwp_avoided / n_e, "gwp_total_per_mol_e": gwp_total / n_e,
        "env_margin_over_avoided": env_margin / gwp_avoided if gwp_avoided > 0 else float("nan"),
        # DSP detail per kg formed
        "dsp_route": dsp.route, "dsp_electricity_kWh_per_kg": dsp.electricity_kWh_per_kg,
        "dsp_steam_MJ_per_kg": dsp.steam_MJ_per_kg, "dsp_chemicals_usd_per_kg": dsp.chemicals_usd_per_kg,
        "dsp_water_removed_kg_per_kg": dsp.water_removed_kg_per_kg, "dsp_capex_usd": dsp.capex_usd,
        # plant scale
        "area_m2": area_m2, "volume_m3": volume_m3, "hrt_h": hrt_h, "current_plant_A": current_plant_A,
        "product_t_per_yr": kg_sold * area_m2 / 1000.0, "stack_tic_usd": st["tic_usd_per_m2"] * area_m2,
        "margin_plant_usd_per_yr": margin * area_m2, "env_margin_plant_t_per_yr": env_margin * area_m2 / 1000.0,
    }


def evaluate_with(cfg: dict[str, Any], product_key: str, mode: str = "ideal", **overrides: Any) -> dict[str, Any]:
    return evaluate(cfg, product_key, make_scenario(cfg, product_key, mode, **overrides))
