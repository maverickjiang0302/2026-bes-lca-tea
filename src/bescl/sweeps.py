"""One-at-a-time sweeps of each lever from a base scenario."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .model import Scenario, evaluate, make_scenario

KEEP = ["margin", "margin_per_mol_e", "margin_over_revenue", "env_margin", "env_margin_per_mol_e",
        "env_margin_over_avoided", "V_applied_V", "eta_ohm_V", "revenue", "cost_total", "gwp_avoided", "gwp_total",
        "kg_sold_per_m2_yr", "breakeven_price_usd_per_kg"]


def grid_values(spec: dict[str, Any]) -> np.ndarray:
    g = spec["grid"]
    if g["type"] == "log":
        return np.geomspace(g["start"], g["stop"], g["n"])
    return np.linspace(g["start"], g["stop"], g["n"])


def run_sweeps(cfg: dict[str, Any], mode: str = "ideal", products: list[str] | None = None,
               levers: list[str] | None = None, **overrides: Any) -> pd.DataFrame:
    sw = cfg["sweeps"]["levers"]
    products = products or list(cfg["products"])
    levers = levers or list(sw)
    rows = []
    for key in products:
        base = make_scenario(cfg, key, mode, **overrides)
        phase = cfg["products"][key]["phase"]
        for lever in levers:
            spec = sw[lever]
            if "phases" in spec and phase not in spec["phases"]:
                continue
            for x in grid_values(spec):
                sc = Scenario(**{**base.__dict__, spec["parameter"]: float(x)})
                r = evaluate(cfg, key, sc)
                rows.append({"product": key, "label": r["label"], "phase": phase, "lever": lever,
                             "value": float(x) * spec.get("display_scale", 1.0), **{k: r[k] for k in KEEP}})
    return pd.DataFrame(rows)
