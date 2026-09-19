"""Required value of each lever at break-even, economic and climate, for the
ideal bound (with and without the treatment credit) and the realistic case."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bescl.breakeven import required_values_table, treatment_only_breakeven_stack_cost  # noqa: E402
from bescl.config import TABLES_DIR, load_all  # noqa: E402


def main() -> int:
    cfg = load_all()
    out = []
    for mode in ("ideal", "realistic"):
        for credit in (False, True):
            for metric in ("margin", "env_margin"):
                df = pd.DataFrame(required_values_table(cfg, mode, metric, treatment_credit=credit))
                df.insert(0, "treatment_credit", credit)
                df.insert(0, "mode", mode)
                out.append(df)
    req = pd.concat(out, ignore_index=True)
    req.to_csv(TABLES_DIR / "required_values.csv", index=False)

    # treatment-service-only break-even: what the stack may cost to compete with activated sludge
    js = np.geomspace(0.1, 10.0, 41)
    pd.DataFrame({"j_A_m2": js, "stack_cost_max_usd_per_m2_yr": [treatment_only_breakeven_stack_cost(cfg, j) for j in js]}
                 ).to_csv(TABLES_DIR / "treatment_only_breakeven.csv", index=False)

    pd.set_option("display.width", 250)
    econ = req[(req["mode"] == "ideal") & (~req["treatment_credit"]) & (req["metric"] == "margin")]
    cols = ["label", "margin_baseline", "stack_cost_max_usd_per_m2_yr", "stack_cost_reduction_factor", "current_density_min_A_m2",
            "extra_loss_max_V", "sandwich_thickness_max_mm", "coulombic_efficiency_min", "catholyte_wt_pct_min",
            "price_breakeven_usd_per_kg", "price_multiple_needed"]
    print("ECONOMIC required values, ideal bound\n", econ[cols].round(3).to_string(index=False))
    env = req[(req["mode"] == "ideal") & (~req["treatment_credit"]) & (req["metric"] == "env_margin")]
    cols = ["label", "env_margin_baseline", "extra_loss_max_V", "sandwich_thickness_max_mm", "current_density_min_A_m2",
            "coulombic_efficiency_min", "catholyte_wt_pct_min", "grid_ci_max_kg_per_kWh", "avoided_gwp_multiple_needed"]
    print("\nCLIMATE required values, ideal bound\n", env[cols].round(3).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
