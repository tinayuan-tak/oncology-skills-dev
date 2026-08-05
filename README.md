# rnd-computational-biology-oncology-target-contracts

**The governance layer of the Takeda v2 oncology target-evaluation framework.**

This repo holds the *contracts* — the declarative definitions that every downstream artifact
must conform to. It contains **no analysis code and no data**: only the schemas, evidence-card
definitions, interpretation rules, controlled vocabularies, and dashboard specs that pin down
*what* a piece of evidence is, *how* it maps to a verdict, and *what vocabulary* the framework
is allowed to speak. Analysis code lives in `analysis-methods`; data lives in `data-catalog`;
generated outputs live in `data-products`. This repo is the shared language the other three agree on.

---

## The four-repo ecosystem

| Repo | Owns | Relationship to this repo |
|---|---|---|
| [`data-catalog`](https://github.com/oneTakeda/rnd-computational-biology-oncology-data-catalog) | Versioned source + derived-product **manifests** | Cards reference its manifest IDs as their data provenance |
| [`analysis-methods`](https://github.com/oneTakeda/rnd-computational-biology-oncology-analysis-methods) | **Method modules** — the deterministic compute | Cards' `methods:` list names method modules; methods validate output against product schemas here |
| **target-contracts** (here) | **Cards, rules, schemas, vocabularies, dashboard specs** | The governance spine — everything else conforms to it |
| [`claude-oncology-skills`](https://github.com/oneTakeda/rnd-computational-biology-oncology-claude-oncology-skills) | **Skills** — one biological question each; composition | Skills' `cards_used:` / `rules_scope:` reference IDs defined here |
| [`data-products`](https://github.com/oneTakeda/rnd-computational-biology-oncology-data-products) | Generated **evidence packages** per target × indication | Emitted by `compose-dashboard` against a `dashboard_spec` from here |

The dependency arrow points *into* this repo from `analysis-methods` and `claude-oncology-skills`.
A card rename or deletion here is a breaking change for both — see [CLAUDE.md](CLAUDE.md) for the
cross-session coordination ritual that must precede any card/rule ID change.

---

## What's in here

```
target-contracts/
├── cards/                       # 64 evidence-card definitions (*.card.yaml)
├── interpretation-rules/        # signal → verdict rule sets (intracellular + surface intrinsic)
├── resolvers/                   # per-gate declarative verdict resolvers (*.resolver.yaml)
├── schemas/                     # JSON Schemas for every contract type
│   └── products/                #   per-method output ("result") schemas
├── vocabularies/                # controlled enums + lookup tables the framework may speak
├── dashboards/                  # dashboard_spec.yaml + modality-modules/ (per-modality lenses)
├── validators/                  # Python validators (run in CI + pre-commit)
├── coverage/                    # per-indication card-coverage matrices
├── health/                      # framework-health dashboard (derived from ground truth)
├── plot_styles/                 # shared figure styling contracts
└── docs/                        # design notes
```

### Cards — the unit of evidence

A **card** (`cards/*.card.yaml`) is a declarative contract for one piece of evidence. Its identity is
**`(measurement_type × entity_grain)`** — e.g. *CRISPR dependency score, at cell-line grain*. A card declares:

- **which measurement** it represents and at what **entity grain** (cell-line / tumor / normal; pooled / per-subtype);
- **which method module** produces it (`methods:`) and **which data manifest** that method reads;
- its **`biology_axis`** and **`modality_relevance`** (which biology gate it serves, which modalities it informs);
- an **`applies_when`** predicate (e.g. only when a subtype shard exists);
- the **output schema** its result must validate against (`schemas/products/`).

The 64 cards span the biology gates: presence & selectivity (`cellline-rna-distribution`,
`tumor-rna-vs-adjacent`, `tumor-vs-normal-selectivity`, …), requirement/dependency
(`pan-cancer-crispr-dependency-distribution`, `dependency-lineage-selectivity`, `paralog-buffering`, …),
genomic alteration (`mutation-hotspot-frequency`, `copy-number-distribution`,
`fusion-rearrangement-landscape`, …), mechanism, differentiation, tractability & surface modality
(`adc-tce-modality-fit`, `surface-abundance-density`, …), safety (`gnomad-lof-constraint`,
`normal-tissue-liability-gtex`, `clinvar-pathogenicity-safety`, …), and the indication-independent
target-intrinsic set (`reactome-pathway-membership`, `ppi-interactome`, `gene-ontology-annotation`,
`protein-domains-class`).

### Interpretation rules & resolvers — signal → verdict

Cards carry *numbers*; **interpretation rules** and **resolvers** turn them into *verdicts*, deterministically.

- **`interpretation-rules/*.rules.yaml`** — the rule sets (split by intrinsic axis: `intracellular-intrinsic`,
  `surface-intrinsic`). Each rule is a `when → then` mapping keyed on card outputs, producing a class label.
- **`resolvers/*.resolver.yaml`** — one declarative resolver per gate (`dependency`, `selectivity`,
  `genomic_alteration`, `mechanism`, `safety`, `differentiation`, `surface_modality`,
  `synthetic_lethal_partners`). A single shared interpreter executes these, so both the skill engine and
  `compose-dashboard` fire the *same* rule kernel. This is what keeps a verdict byte-stable across callers.

### Vocabularies — the controlled language

`vocabularies/` pins the enums the framework is allowed to emit, so no card or skill invents ad-hoc terms:
`biology_axis.enum.yaml`, `modality.enum.yaml`, `data_mode.enum.yaml`, `availability_state.enum.yaml`,
`validation_state.enum.yaml`, `concurrence_state.enum.yaml`, plus lookup tables
(`measurement_types.yaml`, `indication_crosswalk.yaml`, `nomination_verdict_gate.yaml`,
`gate_coverage.yaml`, `known_target_calibration_set.yaml`, `tumor_presence_controls.yaml`,
`card_id_aliases.yaml` for safe forward renames, …).

### Dashboards & modality modules

`dashboards/*.dashboard_spec.yaml` declare which cards compose into an evaluation
(`target-in-indication`, plus intrinsic-base specs). `dashboards/modality-modules/*.module.yaml`
supply the **per-modality lens** (`small_molecule`, `adc`, `bite_tce`, `antibody`, `degrader`) —
which cards are required and how `synthesis_emphasis` shifts — without changing the underlying
modality-agnostic measurements.

### Schemas

`schemas/` holds the JSON Schemas (Draft 2020-12) for every contract type: `card.schema.json`,
`interpretation_rules.schema.json`, `resolver.schema.json`, `dashboard_spec.schema.json`,
`modality_module.schema.json`, `evidence_package.schema.json`, `run_plan.schema.json`,
`subgroup_catalog.schema.json`, `human_concurrence.schema.json`, and the per-method
`schemas/products/*.result.schema.json`. A method's output is validated against its product schema
at compose-time, so schema drift is caught before it reaches a rendered evidence package.

---

## Validation

Every contract type has a validator under `validators/`, run in CI (`.github/workflows/`) and via
the pre-commit hook:

```bash
pixi install
pixi run python validators/validate_cards.py                 # cards + biology_axis/modality_relevance enforcement
pixi run python validators/validate_interpretation_rules.py  # rule sets vs rule schema
pixi run python validators/validate_resolvers.py             # resolver sets vs resolver schema
pixi run python validators/validate_measurement_types.py     # measurement_type registry consistency
pixi run python validators/validate_subgroup_assignments.py  # subgroup catalog integrity
```

The `validators/framework_health/` module derives component health from ground truth (does the card
actually fire in a real package? does its dispatcher import?) and flags drift against declared status;
its rendered output lives in `health/framework_health.html`.

---

## Conventions

- **Never rename or delete a card/rule ID in place.** Downstream skills reference IDs by string.
  Use `vocabularies/card_id_aliases.yaml` for forward renames and coordinate via the WIP registry.
- **Cards and rules live on separate branches.** A card addition is a data-contract change; a rule
  addition is a signal-mapping change; they should be reviewable independently.
- **Card identity = `(measurement_type × entity_grain)`.** Gates *pull* measurement types; data
  *pushes* providers. This is what lets a new data source slot in without touching the gate logic.
- **Indication = a literal AACR OncoTree code** (uppercase): `COADREAD`, `LUAD`, `NSCLC`, … —
  see https://oncotree.mskcc.org/. Molecular subtype is a separate path axis.

---

## Local development

```bash
git clone https://github.com/oneTakeda/rnd-computational-biology-oncology-target-contracts.git
cd rnd-computational-biology-oncology-target-contracts
pixi install
pixi run python validators/validate_cards.py   # sanity-check the contracts
```

This repo is pure YAML + JSON + Python validators — no S3 access or AWS credentials required.

---

## License

Internal use only — Computational Biology Oncology Team, Takeda Pharmaceuticals.

---

## Author

- **v2 framework governance layer:** Ryan Abo (ryan.abo@takeda.com)
