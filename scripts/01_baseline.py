"""Baseline evaluations: ideal bound, realistic case, treatment-credit variant,
grid scenarios, evaporation-mode and on-site-use variants, plus the stack,
DSP and voltage-budget breakdowns."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bescl import stack as stack_mod  # noqa: E402
from bescl.config import TABLES_DIR, load_all  # noqa: E402
from bescl.model import evaluate_with  # noqa: E402


def table(cfg, mode, **kw) -> pd.DataFrame:
    return pd.DataFrame([evaluate_with(cfg, k, mode, **kw) for k in cfg["products"]])


def main() -> int:
    cfg = load_all()
    TABLES_DIR.mkdir(parents=True, exist_ok=True)

    ideal = table(cfg, "ideal")
    ideal.to_csv(TABLES_DIR / "baseline_ideal.csv", index=False)
    real = table(cfg, "realistic")
    real.to_csv(TABLES_DIR / "baseline_realistic.csv", index=False)
    table(cfg, "ideal", treatment_credit=True).to_csv(TABLES_DIR / "baseline_ideal_with_credit.csv", index=False)
    table(cfg, "realistic", treatment_credit=True).to_csv(TABLES_DIR / "baseline_realistic_with_credit.csv", index=False)

    # grid scenarios
    rows = []
    for mode in ("ideal", "realistic"):
        for name, ci in cfg["plant"]["energy"]["grid_scenarios"].items():
            df = table(cfg, mode, grid_ci=ci)
            df.insert(0, "grid", name)
            rows.append(df)
    pd.concat(rows).to_csv(TABLES_DIR / "grid_scenarios.csv", index=False)

    # evaporation mode variant (electric MVR instead of steam MEE) for liquids
    liq = [k for k, p in cfg["products"].items() if p["phase"] == "liquid"]
    mvr = pd.DataFrame([evaluate_with(cfg, k, "ideal", evaporation_mode="mvr") for k in liq])
    mvr.insert(0, "variant", "mvr")
    mee = ideal[ideal["phase"] == "liquid"].copy()
    mee.insert(0, "variant", "mee")
    pd.concat([mee, mvr]).to_csv(TABLES_DIR / "evaporation_variant.csv", index=False)

    # on-site use (no DSP) upper bound for the two products a treatment plant could use itself
    onsite = pd.DataFrame([evaluate_with(cfg, k, "ideal", onsite_fraction=1.0) for k in ("hydrogen_peroxide", "caustic_soda")])
    onsite.to_csv(TABLES_DIR / "onsite_use_variant.csv", index=False)

    # stack breakdown for every cathode type
    frames = []
    for ct in cfg["cell"]["cathode_types"]:
        df = stack_mod.stack_annual(cfg["cell"], cfg["plant"], ct)
        df.insert(0, "cathode_type", ct)
        frames.append(df)
    pd.concat(frames).to_csv(TABLES_DIR / "stack_cost_breakdown.csv", index=False)

    # DSP breakdown per kg formed
    cols = ["product", "label", "phase", "dsp_route", "dsp_recovery", "catholyte_wt_pct", "dsp_water_removed_kg_per_kg",
            "dsp_electricity_kWh_per_kg", "dsp_steam_MJ_per_kg", "dsp_chemicals_usd_per_kg", "dsp_capex_usd",
            "kg_formed_per_m2_yr", "product_t_per_yr", "cost_dsp_var", "cost_dsp_capex", "gwp_dsp", "revenue", "gwp_avoided"]
    d = ideal[cols].copy()
    d["dsp_var_usd_per_kg"] = d["cost_dsp_var"] / d["kg_formed_per_m2_yr"]
    d["dsp_capex_usd_per_kg"] = d["cost_dsp_capex"] / d["kg_formed_per_m2_yr"]
    d["dsp_gwp_kg_per_kg"] = d["gwp_dsp"] / d["kg_formed_per_m2_yr"]
    d["dsp_cost_over_price"] = (d["cost_dsp_var"] + d["cost_dsp_capex"]) / d["revenue"]
    d["dsp_gwp_over_avoided"] = d["gwp_dsp"] / d["gwp_avoided"]
    d.to_csv(TABLES_DIR / "dsp_breakdown.csv", index=False)

    # voltage budgets
    vcols = ["product", "label", "mode", "j_A_m2", "E_thermo_V", "eta_ohm_V", "eta_ph_V", "eta_kin_V", "V_applied_V",
             "kWh_cell_per_m2_yr", "cost_elec_cell", "gwp_elec_cell"]
    pd.concat([ideal[vcols], real[vcols]]).to_csv(TABLES_DIR / "voltage_budget.csv", index=False)

    pd.set_option("display.width", 220)
    show = ["label", "V_applied_V", "revenue", "cost_stack", "cost_elec_cell", "cost_dsp_var", "cost_dsp_capex", "margin",
            "gwp_avoided", "gwp_total", "env_margin", "breakeven_price_mult"]
    print("IDEAL BOUND, per m2 per yr\n", ideal[show].round(2).to_string(index=False))
    print("\nREALISTIC CASE, per m2 per yr\n", real[show].round(2).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
