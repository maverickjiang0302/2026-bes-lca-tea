# 2026-bes-lca-tea

Model and data for **Commodity chemicals cannot repay a wastewater bioanode even at
its theoretical ceiling, but commodity metals can: a coupled techno-economic and
climate bound for bioelectrochemical reduction** (Chen, Khatami and Jiang, University
of Alabama). Python package `bescl`.

Repository: https://github.com/maverickjiang0302/2026-bes-lca-tea. Archived at Zenodo:
concept DOI https://doi.org/10.5281/zenodo.22850937 (all versions); v1.0.2 https://doi.org/10.5281/zenodo.22861477; v1.0.1 https://doi.org/10.5281/zenodo.22860830; v1.0.0 https://doi.org/10.5281/zenodo.22850938.

The question the code answers: *if a biofilm anode ran at its theoretical ceiling in
an ideal zero-gap cell, could any commodity product repay the reactor and reduce
climate burden, and what would each loss cost?* Everything is normalized per m² of
membrane per year and per mole of electrons, so the results are properties of the
technology class rather than of one plant.

## Reproduce every number

```bash
pip install -r requirements.txt      # exact versions used for the release: requirements.lock
python run_all.py
```

`run_all.py` runs the five scripts in `scripts/` in order and then the regression
tests (`pytest -q tests`). It rewrites `data/external/{products,stack_items,dsp_standards}.csv`
from the YAML configuration and every table in `results/tables/`. Runtime is a few
seconds.

## What is here

```
config/            every number the model uses (YAML) -- edit here, never in code
  plant.yaml       plant anchor, financing, energy prices, grid factors, treatment credit
  cell.yaml        zero-gap cell geometry, conductivities, losses, stack cost items, cathodes
  products.yaml    13 commodity products: stoichiometry, potentials, prices, DSP route
  dsp.yaml         downstream-processing engineering constants
  sweeps.yaml      one-at-a-time sweep definitions
data/external/     inputs as CSV
  products.csv, stack_items.csv, dsp_standards.csv   exported from config/ by scripts/00
  tea_parameters.csv        techno-economic parameters with units, descriptions, sources (SI Table S6)
  lca_datasets.csv          life-cycle datasets and characterization factors (SI Table S7)
  literature_products.csv   40 literature products for the per-electron screen (SI Table S26)
src/bescl/         the model
  config.py        YAML loading and dotted-path lookup
  electrochem.py   thermodynamic voltages, area resistances, voltage budget, recirculation
  stack.py         bottom-up levelized stack cost and embodied climate burden
  dsp.py           downstream processing: gas purification, liquid concentration, metal harvest
  model.py         one product / one scenario -> annual cash and carbon flows per m2
  breakeven.py     required value of each lever at economic and climate break-even
  sweeps.py        one-at-a-time sweeps
scripts/
  00_export_inputs.py       config -> CSV, anchor numbers, checks the source tables against config
  01_baseline.py            ideal bound, realistic case, treatment credit, grid scenarios, variants
  02_breakeven.py           required values of every lever
  03_sweeps.py              one-at-a-time sweeps
  04_literature_screen.py   value and avoided burden per mole of electrons for 40 products
tests/test_model.py         regression and unit tests (golden values, identities, source tables)
results/tables/             every CSV the article quotes (tracked so referees can see each number)
```

The figures and the manuscript and SI documents of the article were drawn and rendered
from `results/tables/*.csv` with separate plotting and typesetting scripts that are not
part of this archive; nothing in them adds a number to the analysis.

## Model in one paragraph

Electrons per m² per year are `j · 3600 · h / F`. The voltage budget is the
thermodynamic cell voltage of each product against an acetate-oxidizing anode at
pH 7, minus ohmic (anode pores + membrane + catholyte), pH-gradient and kinetic
losses; positive applied voltage is bought from the grid, negative is exported. The
stack is costed bottom-up per m² (membrane, felt anode, product-specific cathode,
frames, power electronics, tanks) and levelized at 10 % over 20 years with
replacements. Downstream processing uses standard unit models: compression +
purification for gases, multiple-effect evaporation or distillation for liquids (from
the achievable catholyte concentration to sale grade), and harvesting + refining
charge for metals. Break-even values of each lever are solved in closed form where
the margin is linear and by bracketed root-finding otherwise. The literature screen
applies the same stack, electricity, pumping and downstream-class constants to 40
products reported in the bioelectrochemical and electrochemical literature.

## Version history

- **v1.0.2 (2026-09-20).** The 1.5 capital multiplier is stated as what it is, one lumped factor for
  installation plus indirect capital, and cross-checked against the H2A version 3.2018 distributed-model
  defaults, which give 1.44–1.49 at this stack's equipment scale (`h2a_check` in `config/plant.yaml`,
  `bescl.stack.h2a_lumped_multiplier`, new rows in `results/tables/anchor_numbers.csv` and
  `data/external/tea_parameters.csv`). No model result changed. DOI 10.5281/zenodo.22861477.

- **v1.0.1 (2026-09-20).** The 1.5 capital multiplier (installed cost = 1.5 × direct equipment
  cost, `plant.indirect_factor: 0.50`) is now sourced to the H2A Hydrogen Analysis Production
  Models of the National Laboratory of the Rockies (https://www.nlr.gov/hydrogen/h2a-production-models)
  in `data/external/tea_parameters.csv` and `config/plant.yaml`. No numerical result changed. DOI 10.5281/zenodo.22860830.
- **v1.0.0 (2026-09-19).** First archived release.

## Licenses

Code: MIT (`LICENSE`). Configuration, input tables and results: CC BY 4.0
(`LICENSE-DATA`). No ecoinvent datasets are redistributed; only aggregated
characterization factors appear, as single numbers per flow (`data/external/lca_datasets.csv`).

## Citation

See `CITATION.cff` (authors, version, DOI of the archived release) and cite the
associated article.
