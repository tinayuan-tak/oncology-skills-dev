# contracts/ — target-contracts

**The governance layer of the Takeda v2 oncology target-evaluation framework.**
Formerly the standalone `target-contracts` repo; merged into `claude-oncology-skills`
as the `contracts/` package (SK#2063, 2026-09-29) — see root [CLAUDE.md](../CLAUDE.md)
for the process this package now follows.

This package holds the *contracts* — the declarative definitions that every downstream artifact
must conform to. It contains **no analysis code and no data**: only the schemas, evidence-card
definitions, interpretation rules, controlled vocabularies, and dashboard specs that pin down
*what* a piece of evidence is, *how* it maps to a verdict, and *what vocabulary* the framework
is allowed to speak. Analysis code lives in `methods/`; data lives in the sibling `data-catalog`
repo. This package is the shared language the rest of the repo agrees on.

---

## Package relationships

| Package / repo | Owns | Relationship to this package |
|---|---|---|
| [`data-catalog`](https://github.com/oneTakeda/rnd-computational-biology-oncology-data-catalog) (sibling repo) | Versioned source + derived-product **manifests** | Cards reference its manifest IDs as their data provenance |
| `methods/` (this repo) | **Method modules** — the deterministic compute | Cards' `methods:` list names method modules; methods validate output against product schemas here |
| **contracts/** (here) | **Cards, rules, schemas, vocabularies, dashboard specs** | The governance spine — everything else conforms to it |
| `skills/` (this repo) | **Skills** — one biological question each; composition | Skills' `cards_used:` / `rules_scope:` reference IDs defined here |

`skills/target-profile --emit evidence-package` writes the generated evidence
packages (the retired `compose-dashboard` orchestrator formerly wrote them into a
separate `data-products` repo, retired 2026-08-20).

The dependency arrow points *into* this package from `methods/` and `skills/`.
A card rename or deletion here is a breaking change for both — see root
[CLAUDE.md](../CLAUDE.md) for the cross-session coordination ritual that must
precede any card/rule ID change.

---

## What's in here

```
target-contracts/
├── cards/                       # 84 evidence-card definitions (*.card.yaml)
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

The cards (see `cards/` for the current set) span the biology gates: presence & selectivity (`cellline-rna-distribution`,
`tumor-rna-vs-adjacent`, `tumor-vs-normal-selectivity`, `tumor-scrna-celltype-expression` with
per-compartment and CAF-axis single-cell fields, …), requirement/dependency
(`pan-cancer-crispr-dependency-distribution`, `dependency-lineage-selectivity`, `paralog-buffering`, …),
combination & combinatorial-KO (`combo-crispr-screen` for co-targeting opportunities that emerge under
anchor-drug inhibition, `combinatorial-dependency` for dual-KO genetic interaction, …),
genomic alteration (`mutation-hotspot-frequency`, `copy-number-distribution`,
`fusion-rearrangement-landscape`, …), mechanism, differentiation, tractability & surface modality
(`adc-tce-modality-fit`, `surface-abundance-density`, plus the surface-enrichment cards
`cd-antigen-backbone`, `mutation-stratified-surface`, `pathway-stratified-surface`,
`modality-exon-window`, …), safety (`gnomad-lof-constraint`,
`normal-tissue-liability-gtex`, `clinvar-pathogenicity-safety`, …), and the indication-independent
target-intrinsic set (`reactome-pathway-membership`, `ppi-interactome`, `gene-ontology-annotation`,
`protein-domains-class`).

### Interpretation rules & resolvers — signal → verdict

Cards carry *numbers*; **interpretation rules** and **resolvers** turn them into *verdicts*, deterministically.

- **`interpretation-rules/*.rules.yaml`** — the rule sets. The two intrinsic-axis ladders
  (`intracellular-intrinsic`, `surface-intrinsic`) feed the shared nomination verdict; two self-contained
  axes (`combination-opportunity`, `combinatorial-dependency`) drive the combo skills' own verdicts and are
  deliberately isolated from that ladder. Each rule is a `when → then` mapping keyed on card outputs,
  producing a class label.
- **`resolvers/*.resolver.yaml`** — one declarative resolver per gate (`dependency`, `selectivity`,
  `genomic_alteration`, `mechanism`, `safety`, `differentiation`, `surface_modality`,
  `tractability_small_molecule`, `synthetic_lethal_partners`). A single shared interpreter
  (`skills/_skills_common/resolver.py`) executes these, so every caller — every focused
  skill and the composed `target-profile` — fires the *same* rule kernel. This is what
  keeps a verdict byte-stable across callers.

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
the pre-commit hook. This package is **bare python — no pixi**:

```bash
python validators/validate_cards.py                 # cards + biology_axis/modality_relevance enforcement
python validators/validate_interpretation_rules.py  # rule sets vs rule schema
python validators/validate_resolvers.py             # resolver sets vs resolver schema
python validators/validate_measurement_types.py     # measurement_type registry consistency
python validators/validate_subgroup_assignments.py  # subgroup catalog integrity
```

Or run the full validator pool plus ruff in one shot: `scripts/preland.sh` (from
`contracts/`) — or `scripts/preland.sh contracts` from the repo root.

The `validators/framework_health/` module derives component health from ground truth (does the card
actually fire in a real package? does its dispatcher import?) and flags drift against declared status;
its rendered output lives in `health/framework_health.html`.

---

## Regenerating & publishing the framework dashboard

The **unified framework dashboard** (`validators/architecture_dashboard/`) folds two views into one
self-contained HTML: *what's wired* (architecture — the `skill → cards → datasets · methods · rules →
verdict` graph) and *what's live* (health, computed in-process via `framework_health`). It is the
shareable artifact for collaborators. `validators/output_registry/publish_dashboard.py` regenerates it
fresh and publishes to both S3 (with a time-boxed presigned link) and a dated GitHub release.

Two `make` targets wrap the flow (reads this consolidated repo plus the sibling
`data-catalog` fresh, so keep the latter checked out and current):

```bash
make dashboard-dry                       # assemble + stamp, NO S3 / gh writes (sanity check)
make dashboard AWS_PROFILE=cbg           # full regenerate → S3 + presigned URL + dated gh release
```

`make dashboard` requires **`AWS_PROFILE=cbg`** for S3 (see the team's S3 access notes) and **`gh` on
`PATH`, authenticated** for the release. It:

1. regenerates the output-registry `catalog.json` (reads `s3://onc-compbio/skill-runs/`),
2. computes fresh `framework_health`,
3. builds the **Framework Atlas** `framework_atlas.{html,json}` — the single canonical
   dashboard (supersets the old unified dashboard: adds Flow / Gaps / Concepts / Docs tabs +
   the glossary legibility layer). Run `make atlas` to regenerate it locally,
4. uploads to `s3://onc-compbio/framework-atlas/` — a live copy plus a `history/<date>/` snapshot
   and a diffable `manifest.json` (SHAs + tallies),
5. prints a **presigned URL** (default 7-day expiry; override with `--presign-days N`), and
6. cuts a `dashboard-<date>` GitHub release with the HTML as an asset — the durable, no-expiry copy for
   anyone with repo access.

Useful flags (pass through the underlying module, e.g. `python3 -m validators.output_registry.publish_dashboard …`):
`--dry-run`, `--skip-s3`, `--skip-gh`, `--presign-days`, `--generated-at` (ISO stamp for a reproducible
manifest — `make` supplies `STAMP` automatically). The `onc-compbio` bucket blocks all public access, so
the presigned URL — not a static-website link — is how the live view is shared.

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

`contracts/` is part of the `claude-oncology-skills` monorepo — no separate clone.
From a checkout of that repo:

```bash
cd contracts
python validators/validate_cards.py   # sanity-check the contracts
```

This package is pure YAML + JSON + Python validators — no S3 access or AWS credentials required.

---

## License

Internal use only — Computational Biology Oncology Team, Takeda Pharmaceuticals.

---

## Author

- **v2 framework governance layer:** Ryan Abo (ryan.abo@takeda.com)
