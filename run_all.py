"""Regenerate every result table from the configuration and run the regression tests.

    python run_all.py            # results/tables/*.csv, data/external/{products,stack_items,dsp_standards}.csv, tests
    python run_all.py --no-test  # skip the regression tests

The scripts run in order: 00 exports the YAML inputs as CSV and writes the anchor numbers,
01 evaluates the baselines and variants, 02 solves the break-even values of each lever,
03 runs the one-at-a-time sweeps and 04 screens the literature products against the
ideal-bound bars. Every number quoted in the article comes from the CSV files these
scripts write.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STEPS = [
    "scripts/00_export_inputs.py",
    "scripts/01_baseline.py",
    "scripts/02_breakeven.py",
    "scripts/03_sweeps.py",
    "scripts/04_literature_screen.py",
]


def main() -> int:
    for step in STEPS:
        print(f"\n=== {step} ===")
        subprocess.run([sys.executable, str(ROOT / step)], check=True, cwd=ROOT)
    if "--no-test" not in sys.argv:
        print("\n=== pytest ===")
        subprocess.run([sys.executable, "-m", "pytest", "-q", str(ROOT / "tests")], check=True, cwd=ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
