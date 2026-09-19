"""One-at-a-time sweeps from the ideal bound, for every product and lever."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bescl.config import TABLES_DIR, load_all  # noqa: E402
from bescl.sweeps import run_sweeps  # noqa: E402


def main() -> int:
    cfg = load_all()
    df = run_sweeps(cfg, "ideal")
    df.to_csv(TABLES_DIR / "sweeps_ideal.csv", index=False)
    dfc = run_sweeps(cfg, "ideal", treatment_credit=True)
    dfc.to_csv(TABLES_DIR / "sweeps_ideal_with_credit.csv", index=False)
    print(f"sweeps: {len(df)} rows, {df['lever'].nunique()} levers, {df['product'].nunique()} products")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
