"""Literature screen: price and avoided burden per mole of electrons for products that
have been made bioelectrochemically or electrochemically, against the ideal-bound
bars of this study.

For each product in data/external/literature_products.csv:
    PPE  = value added per kg x M / (z * 1000)            [$ per mol e-]
    EPE  = avoided burden per kg x M / (z * 1000)          [kg CO2e per mol e-]
where value added = price - feedstock cost (for reductions of a purchased
intermediate) and avoided burden = conventional route - feedstock burden.

The bar each product must clear at the ideal bound (10 A m-2, CE 1, 0.20 V ohmic,
zero kinetic loss) is built from the same model constants as the main analysis:
    stack (by cathode class) + cell electricity at the product's applied voltage
    + pumping + downstream processing (class model) + CO2 handling.
Writes results/tables/literature_screen.csv.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bescl import electrochem as ec  # noqa: E402
from bescl import stack as stack_mod  # noqa: E402
from bescl.config import TABLES_DIR, load_all  # noqa: E402

SRC = ROOT / "data" / "external" / "literature_products.csv"

# Downstream-processing class models per kg of product (Section S4; Table S13 analogues).
GAS_DSP = {"usd_per_kg": 0.60, "kg_co2e_per_kg": 0.50}                       # CO/CH4-class purification + compression
METAL_DSP = {"usd_per_kg": 0.60, "kg_co2e_per_kg": 0.46}                     # strip, remelt/refine, refining charge
DISTILL_DSP = {"usd_per_kg": 0.435, "kg_co2e_per_kg": 1.78}                  # volatile liquid from 1 wt% (methanol analogue)
ORGANIC_PURIFY = {"steam_MJ_per_kg": 3.0, "capex_mult": 1.5}                 # concentrated organic catholyte: final purification
SALT_ACID = {"h2so4_kg_per_kg": 1.0, "h2so4_usd_per_kg": 0.10, "h2so4_gwp": 0.13, "distill_MJ_per_kg": 4.0}


def dsp_per_kg(row, en, dsp_cfg, grid_ci):
    """Return (USD per kg, kg CO2e per kg) of downstream processing for the product class."""
    cls = row["dsp_class"]
    steam_usd, steam_gwp = en["steam_usd_per_GJ"] / 1000.0, en["steam_kg_co2e_per_MJ"]
    ev = dsp_cfg["evaporation"]
    if cls == "none":
        return 0.0, 0.0
    if cls == "gas":
        return GAS_DSP["usd_per_kg"], GAS_DSP["kg_co2e_per_kg"] * grid_ci / 0.6105
    if cls == "solid_metal":
        return METAL_DSP["usd_per_kg"], METAL_DSP["kg_co2e_per_kg"] * grid_ci / 0.6105
    if cls == "liquid_distill":
        return DISTILL_DSP["usd_per_kg"], DISTILL_DSP["kg_co2e_per_kg"]
    x_in, x_out = float(row["catholyte_wt_pct"]) / 100.0, float(row["product_wt_pct"]) / 100.0
    water = max(1.0 / x_in - 1.0 / x_out, 0.0)
    e_kwh = water * ev["mee_electricity_kWh_per_kg_water"]
    steam = water * ev["mee_steam_MJ_per_kg_water"]
    usd = 1.25 * (steam * steam_usd + e_kwh * en["electricity_usd_per_kWh"])         # x1.25 for evaporator capital
    gwp = steam * steam_gwp + e_kwh * grid_ci
    if cls == "liquid_salt":
        usd += SALT_ACID["h2so4_kg_per_kg"] * SALT_ACID["h2so4_usd_per_kg"] + SALT_ACID["distill_MJ_per_kg"] * steam_usd
        gwp += SALT_ACID["h2so4_kg_per_kg"] * SALT_ACID["h2so4_gwp"] + SALT_ACID["distill_MJ_per_kg"] * steam_gwp
    if cls == "liquid_organic":
        usd += ORGANIC_PURIFY["capex_mult"] * ORGANIC_PURIFY["steam_MJ_per_kg"] * steam_usd
        gwp += ORGANIC_PURIFY["steam_MJ_per_kg"] * steam_gwp
    return usd, gwp


def main() -> int:
    cfg = load_all()
    plant, cell, dsp_cfg = cfg["plant"], cfg["cell"], cfg["dsp"]
    p, en = plant["plant"], plant["energy"]
    hours = p["operating_h_per_yr"]
    j = cell["operation"]["current_density_A_per_m2"]
    K = ec.K_mol_e_per_A_m2_yr(hours)
    n_e = j * K
    grids = {"2020": en["electricity_kg_co2e_per_kWh"], "2050": en["grid_scenarios"]["2050 deep decarbonization"]}
    anode_E = cell["operation"]["anode_potential_V_SHE"]
    r_total = ec.area_resistance(cell).total
    kwh_pump = (ec.recirculation(cell)["power_W_per_m2"] * hours / 1000.0
                + p["feed_pumping_kWh_per_m3"] * n_e / (p["bod_in_mg_per_L"] * p["bod_removal"] / 8.0))
    per_V_kwh = j * hours / 1000.0

    stack_cost = {ct: stack_mod.stack_totals(stack_mod.stack_annual(cell, plant, ct)) for ct in cell["cathode_types"]}

    df = pd.read_csv(SRC)
    rows = []
    for _, r in df.iterrows():
        m_e = r["M_g_per_mol"] / r["electrons_per_mol"] / 1000.0                       # kg product per mol e-
        value_added = r["price_usd_per_kg"] - r["feedstock_kg_per_kg"] * r["feedstock_usd_per_kg"]
        gwp_avoided = r["gwp_conventional_kg_per_kg"] - r["feedstock_kg_per_kg"] * r["gwp_feedstock_kg_per_kg"]
        ppe = value_added * m_e
        epe = gwp_avoided * m_e
        st = stack_cost[r["cathode_class"]]
        stack_usd = st["annual_usd_per_m2"] / n_e
        stack_gwp = st["annual_gwp_kg_per_m2"] / n_e
        e_cell = r["E_cathode_V_SHE"] - anode_E
        v_app = j * r_total - e_cell
        kwh_cell = (v_app * per_V_kwh / en["rectifier_efficiency"]) if v_app > 0 else (v_app * per_V_kwh * en["inverter_efficiency"])
        elec_usd = kwh_cell * en["electricity_usd_per_kWh"] / n_e
        pump_usd = kwh_pump * en["electricity_usd_per_kWh"] / n_e
        co2_usd = r["co2_kg_per_kg"] * plant["co2_feed"]["handling_usd_per_t"] / 1000.0 * m_e
        out = {
            "key": r["key"], "product": r["product"], "group": r["group"], "phase": r["phase"], "electrons": r["electrons_per_mol"],
            "M_g_per_mol": r["M_g_per_mol"], "kg_per_mol_e": m_e, "price_usd_per_kg": r["price_usd_per_kg"],
            "value_added_usd_per_kg": value_added, "gwp_avoided_kg_per_kg": gwp_avoided,
            "ppe_usd_per_mol_e": ppe, "epe_kg_co2e_per_mol_e": epe, "E_cell_thermo_V": e_cell, "V_applied_ideal_V": v_app,
            "bar_stack_usd_per_mol_e": stack_usd, "bar_electricity_usd_per_mol_e": elec_usd,
        }
        for tag, ci in grids.items():
            dsp_usd_kg, dsp_gwp_kg = dsp_per_kg(r, en, dsp_cfg, ci)
            dsp_usd, dsp_gwp = dsp_usd_kg * m_e, dsp_gwp_kg * m_e
            elec_gwp = kwh_cell * ci / n_e
            pump_gwp = kwh_pump * ci / n_e
            if tag == "2020":
                out["bar_dsp_usd_per_mol_e"] = dsp_usd
                out["bar_econ_usd_per_mol_e"] = stack_usd + elec_usd + pump_usd + dsp_usd + co2_usd
                out["clears_economic"] = ppe >= out["bar_econ_usd_per_mol_e"]
                out["ppe_over_bar"] = ppe / out["bar_econ_usd_per_mol_e"]
            out[f"bar_climate_{tag}_kg_per_mol_e"] = stack_gwp + elec_gwp + pump_gwp + dsp_gwp
            out[f"clears_climate_{tag}"] = epe >= out[f"bar_climate_{tag}_kg_per_mol_e"]
            out[f"epe_over_bar_{tag}"] = epe / out[f"bar_climate_{tag}_kg_per_mol_e"]
        out.update({"demonstration": r["demonstration"], "demonstration_ref": r["demonstration_ref"],
                    "price_source": r["price_source"], "gwp_source": r["gwp_source"], "market_note": r["market_note"],
                    "verified": r["verified"]})
        rows.append(out)
    res = pd.DataFrame(rows).sort_values("ppe_usd_per_mol_e", ascending=False)
    res.to_csv(TABLES_DIR / "literature_screen.csv", index=False)

    pd.set_option("display.width", 250)
    show = ["product", "group", "electrons", "ppe_usd_per_mol_e", "bar_econ_usd_per_mol_e", "clears_economic",
            "epe_kg_co2e_per_mol_e", "bar_climate_2020_kg_per_mol_e", "clears_climate_2020", "clears_climate_2050"]
    print(res[show].to_string(index=False, float_format=lambda v: f"{v:.4g}"))
    both = res[res.clears_economic & res.clears_climate_2020]
    print(f"\nclear both bars (2020 grid): {len(both)} of {len(res)}: " + ", ".join(both["product"]))
    print("wrote", TABLES_DIR / "literature_screen.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
