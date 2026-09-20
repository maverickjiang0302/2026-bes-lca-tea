"""Export the YAML inputs as flat CSV tables (data/external/) so that the shared
data and the configuration can never diverge. Also writes the plant/electron
anchor numbers used throughout the text (results/tables/anchor_numbers.csv)."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bescl import electrochem as ec  # noqa: E402
from bescl import stack as st  # noqa: E402
from bescl.config import TABLES_DIR, load_all, lookup  # noqa: E402

EXTERNAL = ROOT / "data" / "external"


def main() -> int:
    cfg = load_all()
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)

    rows = []
    for key, p in cfg["products"].items():
        d = p["dsp"]
        rows.append({
            "key": key, "product": p["label"], "phase": p["phase"], "formula": p["formula"],
            "M_g_per_mol": p["M_g_per_mol"], "electrons_per_mol": p["electrons"], "half_reaction": p["half_reaction"],
            "E_cathode_V_SHE_pH7": p["E_cathode_V_SHE"], "price_usd_per_kg": p["price_usd_per_kg"],
            "avoided_gwp_kg_co2e_per_kg": p["avoided_gwp_kg_co2e_per_kg"], "cathode_type": p["cathode_type"],
            "co2_kg_per_kg_product": p["co2_kg_per_kg_product"], "dsp_route": d["route"], "dsp_recovery": d["recovery"],
            "dsp_catholyte_wt_pct": d.get("catholyte_wt_pct", ""), "dsp_product_wt_pct": d.get("product_wt_pct", d.get("intermediate_wt_pct", "")),
            "dsp_electricity_kWh_per_kg": d.get("electricity_kWh_per_kg", ""), "dsp_note": d.get("note", ""),
            "realistic_cathode_kinetic_V": p["realistic"]["cathode_kinetic_V"],
            "realistic_coulombic_efficiency": p["realistic"]["coulombic_efficiency"],
            "price_verified": p["verified"]["price"], "gwp_verified": p["verified"]["gwp"], "source": p["source"],
        })
    pd.DataFrame(rows).to_csv(EXTERNAL / "products.csv", index=False)

    items = []
    for name, it in cfg["cell"]["stack_items"].items():
        items.append({"item": name, "group": "stack", **{k: v for k, v in it.items()}})
    for name, it in cfg["cell"]["cathode_types"].items():
        items.append({"item": name, "group": "cathode", **{k: v for k, v in it.items()}})
    pd.DataFrame(items).to_csv(EXTERNAL / "stack_items.csv", index=False)

    dsp = cfg["dsp"]
    flat = []
    for group, block in dsp.items():
        for k, v in block.items():
            flat.append({"group": group, "parameter": k, "value": v})
    pd.DataFrame(flat).to_csv(EXTERNAL / "dsp_standards.csv", index=False)

    # anchor numbers
    p, cell = cfg["plant"]["plant"], cfg["cell"]
    K = ec.K_mol_e_per_A_m2_yr(p["operating_h_per_yr"])
    mol_e_per_m3 = p["bod_in_mg_per_L"] * p["bod_removal"] / cfg["plant"]["constants"]["g_bod_per_mol_e"] * p["anodic_coulombic_efficiency"]
    j = cell["operation"]["current_density_A_per_m2"]
    r = ec.area_resistance(cell)
    rec = ec.recirculation(cell)
    current = p["flow_m3_per_h"] * mol_e_per_m3 * ec.FARADAY / 3600.0
    anchor = {
        "K_mol_e_per_A_m2_yr": K, "mol_e_per_m2_yr_at_j": j * K, "mol_e_per_m3_wastewater": mol_e_per_m3,
        "m3_treated_per_m2_yr": j * K / mol_e_per_m3, "plant_current_A": current, "area_m2": current / j,
        "hrt_h": current / j * cell["geometry"]["chamber_depth_m"] / p["flow_m3_per_h"],
        "R_anode_ohm_m2": r.anode, "R_membrane_ohm_m2": r.membrane, "R_cathode_ohm_m2": r.cathode, "R_total_ohm_m2": r.total,
        "eta_ohm_V_at_j": j * r.total, "recirculation": rec,
        "electricity_usd_per_m2_yr_per_V": j * p["operating_h_per_yr"] / 1000.0 * cfg["plant"]["energy"]["electricity_usd_per_kWh"],
        "electricity_kg_co2e_per_m2_yr_per_V": j * p["operating_h_per_yr"] / 1000.0 * cfg["plant"]["energy"]["electricity_kg_co2e_per_kWh"],
        "electricity_kg_co2e_per_mol_e_per_V": ec.FARADAY / 3.6e6 * cfg["plant"]["energy"]["electricity_kg_co2e_per_kWh"],
        "treatment_credit_usd_per_m2_yr": cfg["plant"]["treatment_credit"]["usd_per_m3"] * j * K / mol_e_per_m3,
    }
    # cross-check of the lumped indirect_factor (installed = 1.5 x direct) against the H2A v3.2018
    # distributed-model defaults applied to this stack's uninstalled cost at plant scale (config: plant.h2a_check)
    plant_cfg, area = cfg["plant"], anchor["area_m2"]
    uninstalled = {ct: st.stack_totals(st.stack_annual(cell, plant_cfg, ct))["direct_usd_per_m2"] * area for ct in cell["cathode_types"]}
    h2a = {ct: st.h2a_lumped_multiplier(cell, plant_cfg, ct, area) for ct in cell["cathode_types"]}
    anchor.update({"stack_uninstalled_usd_plant_min": min(uninstalled.values()), "stack_uninstalled_usd_plant_max": max(uninstalled.values()),
                   "h2a_v3_distributed_multiplier_min": min(h2a.values()), "h2a_v3_distributed_multiplier_max": max(h2a.values())})
    # hand-curated source tables (SI Tables S6 and S7): every value that carries a config_path must equal the configuration
    for name, col in (("tea_parameters.csv", "value"), ("lca_datasets.csv", "gwp100_kg_co2e_per_unit")):
        df = pd.read_csv(EXTERNAL / name, dtype=str, keep_default_na=False)
        for _, r in df.iterrows():
            if r["config_path"]:
                ref, val = float(lookup(cfg, r["config_path"])), float(r[col])
                if not math.isclose(ref, val, rel_tol=1e-3):
                    raise SystemExit(f"{name}: {r['config_path']} = {ref} in config but {val} in the table")
    print("data/external/tea_parameters.csv and lca_datasets.csv agree with config/")

    flat = {k: v for k, v in anchor.items() if not isinstance(v, dict)}
    flat.update({f"recirculation_{k}": v for k, v in anchor["recirculation"].items()})
    table = pd.DataFrame({"quantity": list(flat), "value": list(flat.values())})
    table.to_csv(TABLES_DIR / "anchor_numbers.csv", index=False)
    print(table.to_string(index=False))
    print("wrote data/external/{products,stack_items,dsp_standards}.csv and results/tables/anchor_numbers.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
