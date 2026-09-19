"""Configuration loading. All numbers live in config/*.yaml, never in code."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
RESULTS_DIR = ROOT / "results"
TABLES_DIR = RESULTS_DIR / "tables"

NAMES = ("plant", "cell", "products", "dsp", "sweeps")


def load(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / f"{name}.yaml"
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_all() -> dict[str, dict[str, Any]]:
    return {name: load(name) for name in NAMES}


def product_keys(cfg: dict[str, Any]) -> list[str]:
    return list(cfg["products"].keys())


def lookup(cfg: dict[str, Any], dotted: str) -> Any:
    """Value at a dotted path such as plant.energy.electricity_usd_per_kWh (keys may contain spaces)."""
    node: Any = cfg
    for key in dotted.split("."):
        node = node[key]
    return node
