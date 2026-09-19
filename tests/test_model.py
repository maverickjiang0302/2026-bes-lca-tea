"""Regression and consistency tests. Golden values pin the model; unit tests guard
the class of error (units, signs, linearity) that a referee would look for."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bescl import electrochem as ec  # noqa: E402
from bescl import stack as st  # noqa: E402
from bescl.breakeven import required_values, treatment_only_breakeven_stack_cost  # noqa: E402
from bescl.config import load_all, lookup  # noqa: E402
from bescl.dsp import evaluate_dsp  # noqa: E402
from bescl.model import evaluate_with, make_scenario  # noqa: E402


@pytest.fixture(scope="module")
def cfg():
    return load_all()


# --- electrochemistry ---------------------------------------------------------------

def test_K_value(cfg):
    assert ec.K_mol_e_per_A_m2_yr(8030.0) == pytest.approx(299.61, rel=1e-4)


def test_area_resistance_baseline(cfg):
    r = ec.area_resistance(cfg["cell"])
    assert r.anode == pytest.approx(0.001 * 1.5 / (0.9 * 0.10), rel=1e-9)
    assert r.membrane == pytest.approx(0.003)
    assert r.total * 10.0 == pytest.approx(0.20, abs=0.01)          # ~0.2 V ohmic at 10 A/m2


def test_ohmic_scales_with_thickness(cfg):
    r1 = ec.area_resistance(cfg["cell"], 0.001).anode
    r10 = ec.area_resistance(cfg["cell"], 0.010).anode
    assert r10 / r1 == pytest.approx(10.0)


def test_thermodynamic_voltages(cfg):
    assert ec.thermodynamic_cell_voltage(cfg["products"]["hydrogen"], cfg["cell"]) == pytest.approx(-0.134, abs=1e-6)
    assert ec.thermodynamic_cell_voltage(cfg["products"]["hydrogen_peroxide"], cfg["cell"]) == pytest.approx(0.561, abs=1e-6)
    assert ec.thermodynamic_cell_voltage(cfg["products"]["acetic_acid"], cfg["cell"]) == pytest.approx(0.0, abs=1e-9)


def test_electricity_sign_convention():
    assert ec.cell_electricity_kWh_per_m2_yr(10.0, 0.5, 8030.0, 0.95, 0.90) > 0
    assert ec.cell_electricity_kWh_per_m2_yr(10.0, -0.5, 8030.0, 0.95, 0.90) < 0
    consumed = ec.cell_electricity_kWh_per_m2_yr(10.0, 1.0, 8030.0, 1.0, 1.0)
    assert consumed == pytest.approx(80.3)


def test_recirculation_is_small(cfg):
    rec = ec.recirculation(cfg["cell"])
    assert rec["reynolds"] < 2300
    assert 0.05 < rec["power_W_per_m2"] < 1.0


# --- stack -------------------------------------------------------------------------

def test_crf():
    assert st.crf(0.10, 20) == pytest.approx(0.11746, rel=1e-4)
    assert st.crf(0.0, 20) == pytest.approx(0.05)


def test_replacements_counted(cfg):
    df = st.stack_annual(cfg["cell"], cfg["plant"], "ss_mesh")
    mem = df[df["item"] == "membrane_cem"].iloc[0]
    # 4 membranes over 20 years at 5-yr life
    assert mem["annual_gwp_kg_per_m2"] == pytest.approx(0.4725 * 2.3219 * 4 / 20, rel=1e-6)
    assert mem["annual_capital_usd_per_m2"] > 150 * st.crf(0.10, 20)


def test_stack_cost_multiplier_is_linear(cfg):
    a = st.stack_totals(st.stack_annual(cfg["cell"], cfg["plant"], "ss_mesh"))["annual_usd_per_m2"]
    b = st.stack_totals(st.stack_annual(cfg["cell"], cfg["plant"], "ss_mesh", stack_cost_mult=0.5))["annual_usd_per_m2"]
    assert b == pytest.approx(0.5 * a)


# --- DSP ---------------------------------------------------------------------------

def test_water_removed(cfg):
    prod = cfg["products"]["hydrogen_peroxide"]
    r = evaluate_dsp(prod, cfg["dsp"], cfg["plant"], 10.0)
    assert r.water_removed_kg_per_kg == pytest.approx(1 / 0.01 - 1 / 0.35, rel=1e-9)
    assert r.steam_MJ_per_kg == pytest.approx(r.water_removed_kg_per_kg * 0.80)


def test_mvr_uses_no_steam(cfg):
    prod = cfg["products"]["caustic_soda"]
    r = evaluate_dsp(prod, cfg["dsp"], cfg["plant"], 10.0, evaporation_mode="mvr")
    assert r.steam_MJ_per_kg == 0.0 and r.electricity_kWh_per_kg > 0


def test_capex_power_law(cfg):
    prod = cfg["products"]["hydrogen"]
    a = evaluate_dsp(prod, cfg["dsp"], cfg["plant"], 4.17).capex_usd
    b = evaluate_dsp(prod, cfg["dsp"], cfg["plant"], 41.7).capex_usd
    assert a == pytest.approx(150000.0, rel=1e-3)
    assert b / a == pytest.approx(10 ** 0.7, rel=1e-3)


# --- model -------------------------------------------------------------------------

def test_electron_bookkeeping(cfg):
    r = evaluate_with(cfg, "hydrogen", "ideal")
    n_e = 10.0 * ec.K_mol_e_per_A_m2_yr(8030.0)
    assert r["mol_e_per_m2_yr"] == pytest.approx(n_e)
    assert r["kg_formed_per_m2_yr"] == pytest.approx(n_e / 2 * 2.016 / 1000)
    assert r["m3_treated_per_m2_yr"] == pytest.approx(n_e / 21.25)


def test_plant_anchor(cfg):
    r = evaluate_with(cfg, "hydrogen", "ideal")
    assert r["current_plant_A"] == pytest.approx(100 * 21.25 * 96485 / 3600, rel=1e-6)
    assert r["area_m2"] == pytest.approx(r["current_plant_A"] / 10.0)
    assert 4.5 < r["hrt_h"] < 6.0


def test_margin_identity(cfg):
    r = evaluate_with(cfg, "copper", "ideal")
    parts = r["cost_stack"] + r["cost_elec_cell"] + r["cost_pump"] + r["cost_dsp_var"] + r["cost_dsp_capex"] + r["cost_co2"]
    assert r["cost_total"] == pytest.approx(parts)
    assert r["margin"] == pytest.approx(r["revenue"] - r["cost_total"])
    assert r["env_margin"] == pytest.approx(r["gwp_avoided"] - r["gwp_total"])


def test_spontaneous_cell_exports_power(cfg):
    r = evaluate_with(cfg, "hydrogen_peroxide", "ideal")
    assert r["V_applied_V"] < 0 and r["cost_elec_cell"] < 0 and r["gwp_elec_cell"] < 0


def test_golden_ideal_margins(cfg):
    """Pin the headline ideal-bound results (USD per m2 per yr)."""
    assert evaluate_with(cfg, "hydrogen", "ideal")["margin"] == pytest.approx(-98.06, abs=0.5)
    assert evaluate_with(cfg, "copper", "ideal")["margin"] == pytest.approx(695.4, abs=2.0)
    assert evaluate_with(cfg, "hydrogen_peroxide", "ideal")["env_margin"] == pytest.approx(-423.4, abs=2.0)


def test_all_chemicals_negative_metals_positive_ideal(cfg):
    for key, p in cfg["products"].items():
        r = evaluate_with(cfg, key, "ideal")
        if p["phase"] == "solid":
            assert r["margin"] > 0, key
        else:
            assert r["margin"] < 0, key


def test_treatment_credit_adds_expected_amount(cfg):
    a = evaluate_with(cfg, "hydrogen", "ideal")
    b = evaluate_with(cfg, "hydrogen", "ideal", treatment_credit=True)
    assert b["margin"] - a["margin"] == pytest.approx(0.20 * a["m3_treated_per_m2_yr"])


# --- break-even ---------------------------------------------------------------------

def test_stack_cost_breakeven_is_consistent(cfg):
    base = make_scenario(cfg, "copper", "ideal")
    req = required_values(cfg, "copper", base, "margin")
    mult = req["stack_cost_max_usd_per_m2_yr"] / evaluate_with(cfg, "copper", "ideal")["cost_stack"]
    r = evaluate_with(cfg, "copper", "ideal", stack_cost_mult=mult)
    assert r["margin"] == pytest.approx(0.0, abs=1e-6)


def test_loss_budget_root_is_a_root(cfg):
    base = make_scenario(cfg, "copper", "ideal")
    req = required_values(cfg, "copper", base, "margin")
    r = evaluate_with(cfg, "copper", "ideal", extra_overpotential_V=req["extra_loss_max_V"])
    assert r["margin"] == pytest.approx(0.0, abs=1e-4)


def test_infeasible_products_return_nan(cfg):
    base = make_scenario(cfg, "methane", "ideal")
    req = required_values(cfg, "methane", base, "margin")
    assert math.isnan(req["extra_loss_max_V"]) and math.isnan(req["current_density_min_A_m2"])
    assert req["stack_cost_max_usd_per_m2_yr"] < 0


def test_treatment_only_breakeven(cfg):
    c = treatment_only_breakeven_stack_cost(cfg, 10.0)
    assert c == pytest.approx(0.20 * 10 * 299.61 / 21.25, rel=1e-3)


# --- SI source tables ---------------------------------------------------------------

@pytest.mark.parametrize("name,col", [("tea_parameters.csv", "value"), ("lca_datasets.csv", "gwp100_kg_co2e_per_unit")])
def test_source_tables_match_config(cfg, name, col):
    """SI Tables S6 and S7 are hand-curated (values with sources); every value that names a config path must equal it."""
    df = pd.read_csv(ROOT / "data" / "external" / name, dtype=str, keep_default_na=False)
    checked = 0
    for _, r in df.iterrows():
        if r["config_path"]:
            assert float(lookup(cfg, r["config_path"])) == pytest.approx(float(r[col]), rel=1e-3), r["config_path"]
            checked += 1
    assert checked >= 5


# --- literature screen --------------------------------------------------------------

def test_literature_screen_agrees_with_model(cfg):
    """The per-electron screen must reproduce the verdicts of the full model for the 13
    modelled products: metals clear the economic bar, chemicals do not, and the value per
    electron equals the model's revenue per electron."""
    import pandas as pd
    path = ROOT / "results" / "tables" / "literature_screen.csv"
    if not path.exists():
        pytest.skip("run scripts/04_literature_screen.py first")
    ls = pd.read_csv(path).set_index("key")
    for key, p in cfg["products"].items():
        r = evaluate_with(cfg, key, "ideal")
        row = ls.loc[key]
        assert row["ppe_usd_per_mol_e"] == pytest.approx(r["revenue_per_mol_e"] / r["dsp_recovery"], rel=1e-6)
        assert bool(row["clears_economic"]) == (p["phase"] == "solid"), key
