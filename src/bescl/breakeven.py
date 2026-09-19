"""Required value of each lever at break-even, for the economic and the climate
margin. Where the margin is linear in the lever the answer is closed-form;
otherwise a bracketed root find on the model."""

from __future__ import annotations

import math
from typing import Any, Callable

import numpy as np
from scipy.optimize import brentq

from . import electrochem as ec
from .model import Scenario, evaluate, make_scenario

NAN = float("nan")


def _root(f: Callable[[float], float], lo: float, hi: float, prefer: str = "low") -> float:
    """Smallest (prefer='low') or largest (prefer='high') root of f on [lo, hi] found by a
    coarse scan followed by brentq. NaN if no sign change."""
    grid = np.geomspace(lo, hi, 80) if lo > 0 else np.linspace(lo, hi, 80)
    vals = np.array([f(x) for x in grid])
    idx = np.where(np.sign(vals[:-1]) != np.sign(vals[1:]))[0]
    if len(idx) == 0:
        return NAN
    k = idx[0] if prefer == "low" else idx[-1]
    try:
        return brentq(f, grid[k], grid[k + 1], xtol=1e-9, rtol=1e-9, maxiter=200)
    except ValueError:
        return NAN


def _margin_fn(cfg: dict[str, Any], key: str, base: Scenario, param: str, metric: str) -> Callable[[float], float]:
    def f(x: float) -> float:
        sc = Scenario(**{**base.__dict__, param: x})
        return evaluate(cfg, key, sc)[metric]
    return f


def required_values(cfg: dict[str, Any], key: str, base: Scenario, metric: str = "margin") -> dict[str, Any]:
    """Required value of each lever for `metric` (margin or env_margin) to reach zero,
    holding every other lever at the scenario value."""
    r0 = evaluate(cfg, key, base)
    out: dict[str, Any] = {"product": key, "label": r0["label"], "phase": r0["phase"], "metric": metric,
                           f"{metric}_baseline": r0[metric]}
    cell = cfg["cell"]
    is_econ = metric == "margin"

    # 1. stack cost: margin is linear in stack cost with slope -1 (economic) ---------------
    if is_econ:
        c_be = r0["cost_stack"] + r0["margin"]
        out["stack_cost_max_usd_per_m2_yr"] = c_be
        out["stack_cost_reduction_factor"] = r0["cost_stack"] / c_be if c_be > 0 else math.inf
        # annual stack cost scales 1:1 with the cost multiplier, so the allowed installed cost
        # is the baseline installed cost times the allowed multiplier
        tic_per_m2 = r0["stack_tic_usd"] / r0["area_m2"]
        out["stack_tic_max_usd_per_m2"] = tic_per_m2 * c_be / r0["cost_stack"] if c_be > 0 else 0.0
    else:
        g_be = r0["gwp_stack"] + r0["env_margin"]
        out["stack_gwp_max_kg_per_m2_yr"] = g_be

    # 2. loss budget (extra overpotential) -> sandwich thickness -------------------------
    # bracket generously: metals tolerate tens of volts before the margin closes; the text
    # reports anything above a few volts simply as "not binding"
    f_eta = _margin_fn(cfg, key, base, "extra_overpotential_V", metric)
    eta_max = _root(f_eta, 0.0, 500.0, "low") if f_eta(0.0) > 0 else NAN
    out["extra_loss_max_V"] = eta_max
    if not math.isnan(eta_max):
        g = cell["geometry"]
        kappa = cell["electrolyte"]["wastewater_conductivity_S_per_m"]
        d_r = eta_max / base.j
        out["sandwich_thickness_max_mm"] = (base.anode_thickness_m + d_r * g["anode_porosity"] * kappa / g["anode_tortuosity"]) * 1000.0
        out["V_applied_max_V"] = r0["V_applied_V"] + eta_max
    else:
        out["sandwich_thickness_max_mm"] = NAN
        out["V_applied_max_V"] = NAN

    # 3. current density ----------------------------------------------------------------
    f_j = _margin_fn(cfg, key, base, "j", metric)
    out["current_density_min_A_m2"] = _root(f_j, 0.05, base.j, "low") if f_j(base.j) > 0 else NAN
    out[f"feasible_at_baseline_j"] = f_j(base.j) > 0

    # 4. Coulombic efficiency -----------------------------------------------------------
    f_ce = _margin_fn(cfg, key, base, "ce", metric)
    out["coulombic_efficiency_min"] = _root(f_ce, 0.01, 1.0, "low") if f_ce(1.0) > 0 else NAN

    # 5. catholyte concentration (liquids) ----------------------------------------------
    if r0["phase"] == "liquid":
        f_x = _margin_fn(cfg, key, base, "catholyte_wt_pct", metric)
        top = cfg["products"][key]["dsp"].get("product_wt_pct", cfg["products"][key]["dsp"].get("intermediate_wt_pct", 60.0))
        out["catholyte_wt_pct_min"] = _root(f_x, 0.05, min(top * 0.999, 60.0), "low") if f_x(min(top * 0.999, 60.0)) > 0 else NAN
    else:
        out["catholyte_wt_pct_min"] = NAN

    # 6. price / avoided burden multiple ------------------------------------------------
    if is_econ:
        out["price_breakeven_usd_per_kg"] = r0["breakeven_price_usd_per_kg"]
        out["price_multiple_needed"] = r0["breakeven_price_mult"]
    else:
        burden = r0["gwp_total"] - r0["gwp_credit_treatment"]
        out["avoided_gwp_multiple_needed"] = burden / r0["gwp_avoided"] if r0["gwp_avoided"] > 0 else NAN
        # grid carbon intensity at which the climate margin vanishes (linear in CI)
        kwh = r0["kWh_cell_per_m2_yr"] + r0["kWh_pump_per_m2_yr"] + r0["kg_formed_per_m2_yr"] * r0["dsp_electricity_kWh_per_kg"] * (1 - base.onsite_fraction)
        fixed = r0["gwp_total"] - kwh * base.grid_ci           # burdens independent of the grid
        avoided = r0["gwp_avoided"] + r0["gwp_credit_treatment"]
        out["grid_ci_max_kg_per_kWh"] = (avoided - fixed) / kwh if kwh > 0 else (math.inf if avoided > fixed else NAN)
    return out


def required_values_table(cfg: dict[str, Any], mode: str = "ideal", metric: str = "margin",
                          **overrides: Any) -> list[dict[str, Any]]:
    rows = []
    for key in cfg["products"]:
        base = make_scenario(cfg, key, mode, **overrides)
        rows.append(required_values(cfg, key, base, metric))
    return rows


def treatment_only_breakeven_stack_cost(cfg: dict[str, Any], j: float) -> float:
    """Maximum levelised stack cost ($ per m2 per yr) for the bioanode to compete with
    conventional secondary treatment on the treatment service alone (no product)."""
    p, tc = cfg["plant"]["plant"], cfg["plant"]["treatment_credit"]
    K = ec.K_mol_e_per_A_m2_yr(p["operating_h_per_yr"])
    mol_e_per_m3 = p["bod_in_mg_per_L"] * p["bod_removal"] / cfg["plant"]["constants"]["g_bod_per_mol_e"] * p["anodic_coulombic_efficiency"]
    return tc["usd_per_m3"] * j * K / mol_e_per_m3
