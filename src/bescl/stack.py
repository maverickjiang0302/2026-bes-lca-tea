"""Bottom-up levelised stack cost and embodied climate burden per m2 of membrane."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd


def crf(rate: float, years: int | float) -> float:
    """Capital recovery factor."""
    if rate == 0:
        return 1.0 / years
    return rate * (1 + rate) ** years / ((1 + rate) ** years - 1)


def pv_replacements(direct_cost: float, life_yr: float, project_yr: float, rate: float,
                    install_factor: float) -> float:
    """Present value of replacing an item at the end of each life within the project."""
    pv, t = 0.0, life_yr
    while t < project_yr - 1e-9:
        pv += direct_cost * install_factor / (1 + rate) ** t
        t += life_yr
    return pv


def units_over_life(life_yr: float, project_yr: float) -> int:
    return int(math.ceil(project_yr / life_yr - 1e-9))


def stack_items(cell: dict[str, Any], cathode_type: str) -> dict[str, dict[str, Any]]:
    items = dict(cell["stack_items"])
    items["cathode"] = dict(cell["cathode_types"][cathode_type])
    return items


def stack_annual(cell: dict[str, Any], plant: dict[str, Any], cathode_type: str, *,
                 stack_cost_mult: float = 1.0, membrane_cost_mult: float = 1.0) -> pd.DataFrame:
    """One row per item with direct cost, installed cost, levelised capital, fixed
    opex and embodied GWP, all per m2 of membrane per year."""
    p = plant["plant"]
    rate, n_yr = p["discount_rate"], p["project_life_yr"]
    indirect, fixed_frac, repl = p["indirect_factor"], p["fixed_opex_fraction_of_tic"], p["replacement_install_factor"]
    rows = []
    for name, it in stack_items(cell, cathode_type).items():
        mult = stack_cost_mult * (membrane_cost_mult if name == "membrane_cem" else 1.0)
        direct = it["usd_per_m2"] * mult
        tic = direct * (1 + indirect)
        life = min(it["life_yr"], n_yr)
        annual_capital = tic * crf(rate, n_yr) + pv_replacements(direct, life, n_yr, rate, repl) * crf(rate, n_yr)
        fixed_opex = fixed_frac * tic
        gwp = it["kg_per_m2"] * it["gwp_kg_co2e_per_kg"] * units_over_life(life, n_yr) / n_yr
        rows.append({"item": name, "direct_usd_per_m2": direct, "tic_usd_per_m2": tic, "life_yr": life,
                     "annual_capital_usd_per_m2": annual_capital, "fixed_opex_usd_per_m2": fixed_opex,
                     "annual_usd_per_m2": annual_capital + fixed_opex,
                     "kg_per_m2": it["kg_per_m2"], "annual_gwp_kg_per_m2": gwp})
    return pd.DataFrame(rows)


def stack_totals(df: pd.DataFrame) -> dict[str, float]:
    return {"direct_usd_per_m2": float(df["direct_usd_per_m2"].sum()),
            "tic_usd_per_m2": float(df["tic_usd_per_m2"].sum()),
            "annual_usd_per_m2": float(df["annual_usd_per_m2"].sum()),
            "annual_gwp_kg_per_m2": float(df["annual_gwp_kg_per_m2"].sum())}

def h2a_lumped_multiplier(cell: dict[str, Any], plant: dict[str, Any], cathode_type: str, area_m2: float) -> float:
    """Total depreciable capital / uninstalled equipment cost implied by the H2A v3.2018
    distributed-model defaults (plant['h2a_check']) for this stack at plant scale.

    H2A multiplies uninstalled cost by an installation cost factor to get installed direct
    capital, then adds site preparation and engineering (fixed sums), process and project
    contingency (fractions of direct capital) and initial spares and pre-paid royalties
    (fractions of the total, hence the division). The result is the cross-check behind the
    single lumped ``indirect_factor``."""
    h = plant["h2a_check"]
    uninstalled = stack_totals(stack_annual(cell, plant, cathode_type))["direct_usd_per_m2"] * area_m2
    direct = uninstalled * (1 + h["installation_fraction_of_uninstalled"])
    total = (direct * (1 + h["process_contingency_fraction_of_direct"] + h["project_contingency_fraction_of_direct"])
             + h["site_preparation_usd"] + h["engineering_design_usd"]) \
        / (1 - h["initial_spares_fraction_of_total"] - h["prepaid_royalties_fraction_of_total"])
    return total / uninstalled
