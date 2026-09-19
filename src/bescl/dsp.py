"""Downstream processing (DSP) with standard engineering models.

Gases    : compression + purification; electricity per kg; recovery < 1.
Liquids  : concentration from the catholyte concentration to sale grade by
           multiple-effect evaporation (non-volatile products and salts), or by
           distillation with feed-heat recovery (volatile products). Carboxylate
           salts are acidified with sulfuric acid before final distillation.
Solids   : cathode harvesting, remelting/casting and a refining charge.

All variable quantities are per kg of product FORMED at the cathode; the sold
mass is recovery x formed mass. Capital is a plant-level installed cost scaled
by a power law on capacity, then levelised.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .stack import crf


@dataclass
class DSPResult:
    route: str
    recovery: float
    capex_usd: float                      # plant-level installed
    annual_capex_usd: float               # levelised capital + fixed opex, plant-level
    electricity_kWh_per_kg: float = 0.0   # per kg formed
    steam_MJ_per_kg: float = 0.0
    chemicals_usd_per_kg: float = 0.0
    chemicals_gwp_per_kg: float = 0.0
    water_removed_kg_per_kg: float = 0.0
    detail: dict[str, float] = field(default_factory=dict)

    def variable_usd_per_kg(self, energy: dict[str, Any]) -> float:
        return (self.electricity_kWh_per_kg * energy["electricity_usd_per_kWh"]
                + self.steam_MJ_per_kg * energy["steam_usd_per_GJ"] / 1000.0
                + self.chemicals_usd_per_kg)

    def variable_gwp_per_kg(self, energy: dict[str, Any], grid_ci: float) -> float:
        return (self.electricity_kWh_per_kg * grid_ci
                + self.steam_MJ_per_kg * energy["steam_kg_co2e_per_MJ"]
                + self.chemicals_gwp_per_kg)


def _capex(ref_usd: float, ref_capacity: float, capacity: float, exponent: float) -> float:
    if capacity <= 0:
        return 0.0
    return ref_usd * (capacity / ref_capacity) ** exponent


def _levelise(capex: float, plant: dict[str, Any], dsp_cfg: dict[str, Any]) -> float:
    p = plant["plant"]
    return capex * (crf(p["discount_rate"], p["project_life_yr"]) + dsp_cfg["capex"]["fixed_opex_fraction"])


def _evaporation_energy(water_kg: float, dsp_cfg: dict[str, Any], mode: str | None) -> tuple[float, float]:
    """Returns (electricity kWh, steam MJ) per kg product for removing `water_kg` of water."""
    ev = dsp_cfg["evaporation"]
    mode = mode or ev["mode"]
    if mode == "mvr":
        return water_kg * ev["mvr_electricity_kWh_per_kg_water"], 0.0
    return water_kg * ev["mee_electricity_kWh_per_kg_water"], water_kg * ev["mee_steam_MJ_per_kg_water"]


def evaluate_dsp(product: dict[str, Any], dsp_cfg: dict[str, Any], plant: dict[str, Any],
                 mass_formed_kg_per_h: float, *, catholyte_wt_pct: float | None = None,
                 evaporation_mode: str | None = None, enabled: bool = True) -> DSPResult:
    d = product["dsp"]
    route = d["route"]
    if not enabled:
        return DSPResult(route="none", recovery=1.0, capex_usd=0.0, annual_capex_usd=0.0)

    if route == "gas":
        capex = _capex(d["capex_ref_usd"], d["capex_ref_capacity_kg_per_h"], mass_formed_kg_per_h, d["capex_exponent"])
        return DSPResult(route, d["recovery"], capex, _levelise(capex, plant, dsp_cfg),
                         electricity_kWh_per_kg=d["electricity_kWh_per_kg"])

    if route == "solid_metal":
        capex = _capex(d["capex_ref_usd"], d["capex_ref_capacity_kg_per_h"], mass_formed_kg_per_h, d["capex_exponent"])
        return DSPResult(route, d["recovery"], capex, _levelise(capex, plant, dsp_cfg),
                         electricity_kWh_per_kg=d["electricity_kWh_per_kg"],
                         chemicals_usd_per_kg=d["harvesting_usd_per_kg"] + d["refining_charge_usd_per_kg"])

    x_in = (catholyte_wt_pct if catholyte_wt_pct is not None else d["catholyte_wt_pct"]) / 100.0

    if route == "liquid_evaporation":
        x_out = d["product_wt_pct"] / 100.0
        water = max(1.0 / x_in - 1.0 / x_out, 0.0)
        elec, steam = _evaporation_energy(water, dsp_cfg, evaporation_mode)
        water_rate = water * mass_formed_kg_per_h
        capex = _capex(d["capex_ref_usd"], d["capex_ref_capacity_kg_water_per_h"], water_rate, d["capex_exponent"])
        return DSPResult(route, d["recovery"], capex, _levelise(capex, plant, dsp_cfg),
                         electricity_kWh_per_kg=elec, steam_MJ_per_kg=steam, water_removed_kg_per_kg=water)

    if route == "liquid_salt_acid":
        x_mid = d["intermediate_wt_pct"] / 100.0
        water = max(1.0 / x_in - 1.0 / x_mid, 0.0)
        elec, steam = _evaporation_energy(water, dsp_cfg, evaporation_mode)
        steam += d["final_distillation_MJ_per_kg"]
        acid = dsp_cfg["acidification"]
        chem_usd = d["acid_kg_h2so4_per_kg"] * acid["h2so4_usd_per_kg"]
        chem_gwp = d["acid_kg_h2so4_per_kg"] * acid["h2so4_kg_co2e_per_kg"]
        water_rate = water * mass_formed_kg_per_h
        capex = 1.3 * _capex(d["capex_ref_usd"], d["capex_ref_capacity_kg_water_per_h"], water_rate, d["capex_exponent"])
        return DSPResult(route, d["recovery"], capex, _levelise(capex, plant, dsp_cfg),
                         electricity_kWh_per_kg=elec, steam_MJ_per_kg=steam,
                         chemicals_usd_per_kg=chem_usd, chemicals_gwp_per_kg=chem_gwp,
                         water_removed_kg_per_kg=water)

    if route == "liquid_distillation":
        feed = 1.0 / x_in                                   # kg feed per kg product
        cp = dsp_cfg["distillation"]["water_cp_kJ_per_kg_K"]
        preheat_MJ = feed * cp * d["feed_delta_T_K"] * (1.0 - d["feed_heat_recovery"]) / 1000.0
        steam = preheat_MJ + d["reboiler_MJ_per_kg"]
        elec = 0.005 * feed                                 # pumps, kWh per kg product
        feed_rate = feed * mass_formed_kg_per_h
        capex = _capex(d["capex_ref_usd"], d["capex_ref_capacity_kg_feed_per_h"], feed_rate, d["capex_exponent"])
        return DSPResult(route, d["recovery"], capex, _levelise(capex, plant, dsp_cfg),
                         electricity_kWh_per_kg=elec, steam_MJ_per_kg=steam,
                         water_removed_kg_per_kg=feed - 1.0, detail={"feed_kg_per_kg": feed})

    raise ValueError(f"unknown DSP route {route!r}")
