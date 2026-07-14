# Subskill Critical-Review Defect Register — 2026-07-14

Produced from a read-only deep-dive of every scoped subskill in the v2
target-evaluation framework (each subskill's `SKILL.md` + `scripts/run.py`
+ referenced cards + dispatched methods, reviewed against a fixed rubric:
question coherence, SKILL.md↔run.py consistency, data reality, verdict
logic, output honesty, demo-readiness). All root causes below were
re-verified by direct code inspection, not accepted on review say-so.

## The one-line summary

**The blocker is the decision layer, not data coverage.** Multiple skills
have real data flowing in but emit null/wrong verdicts because of a small
number of shared bugs in rule-firing and coverage-accounting. Four root
causes explain most per-skill symptoms; fixing them repairs many skills at
once.

## Root causes (shared layer) — ranked by leverage

### RC1 — `_live_read_error` counted as "available" [HIGH, framework-wide]
`skills/_skills_common/__init__.py` `resolve_cards` flags a card `_missing`
only when the dispatcher returns `None`. A dispatcher that throws returns
`{"_live_read_error": "..."}` (a dict, not None), so the card is counted as
PRESENT. Effect: headline `cards_available` / `cards_missing` overstate
coverage on every skill. Worst instance: on-target-safety-liability reports
"1/1 cards available" while its dispatcher is raising `ModuleNotFoundError`.

**Fix**: treat `_live_read_error` (and `data_unavailable`-class values) as
missing in `resolve_cards`.

### RC2 — bool vs YAML-string rule comparison [HIGH, load-bearing rules]
`__init__.py` `fired_rules` matches with bare `actual == equals`. Rules
encode `equals: 'true'` (YAML string) at 4 sites (2 intracellular + 2
surface); readers emit Python `bool True`. `True == 'true'` is `False`, so
all 4 boolean-keyed rules are dead — including the load-bearing
`has-cooccurring-driver-supportive` (breaks differentiation-landscape) and
`has-pd-marker-supportive` (mechanism).

**Fix**: coerce booleans to their lowercase-string form (or vice versa)
before comparison in the matcher.

### RC3 — categorical coverage holes in interpretation-rules [HIGH, target-contracts]
`cooccurrence_class` has 7 vocabulary values but only 2 have rules
(`strong_mutually_exclusive`, `data_unavailable`); the common
`both_patterns_present` / `strong_cooccurring` / `modest_*` values have no
rule. `network_class` has no rule for `partial`. Real data landing on an
unhandled value fires nothing → verdict silently collapses to `insufficient`.

**Fix**: add the missing supportive/neutral rule rows for the uncovered
categorical values.

### RC4 — contract test is shape-only (false-green) [HIGH, meta]
`skills/tests/test_graduated_skills_run_wired.py` self-describes as "a
CONTRACT check, not a data-quality check". It asserts exit-0 + wired-shape
keys + absence of the placeholder shape, and explicitly accepts
`verdict: insufficient` as passing. So a skill returning `insufficient` on
real data is GREEN. This is why the broken skills went undetected. The
dispatcher docstring's claim that SKILL.md↔run.py drift is "structurally
impossible" is false — nothing enforces it.

**Fix**: add a data-quality assertion so a wired skill on the reference
target (KRAS/COADREAD) must fire ≥1 rule / not collapse to `insufficient`
when its cards return real data.

## Per-subskill demo verdict

| Subskill | Data | Verdict layer | Demo |
|---|---|---|---|
| mutation-profile | REAL | correct (biomarker_stratified_dependency) | SHIP |
| tumor-presence | REAL | correct (broadly_moderate) | SHIP w/ doc fix (prose says 2 cards, runs 3) |
| mechanism-and-pharmacology | REAL (4-source) | correct (well_characterized) | SHIP w/ doc fix (SKILL.md provenance wrong: claims SIGNOR/OmniPath single-source; is 4-source mechanism_composed) |
| tumor-selectivity | REAL | correct (discordant) | fix docs first ("four-cell" label on 3-cell data; off-catalog parquet; dead `micro-` path) |
| patient-population-and-access | REAL (prevalence) | honest partial | prevalence-only (advertises co-mutation "neighborhoods" but emits empty lists) |
| functional-requirement | REAL (dependency) | dep correct; paralog invalid | drop paralog card (invalid `moderate` call; `lineage_selectivity: null` from field-name bug `lineage_selectivity_class`→`enrichment_class`) |
| differentiation-landscape | REAL (709 cooc hits) | BROKEN → insufficient (RC2+RC3) | NOT demo-ready until RC2+RC3 fixed (then likely SHIP) |
| on-target-safety-liability | BROKEN (imports nonexistent methods.gnomad_constraint) | never reached | NOT wired — needs the gnomad_constraint method module written |
| tractability-and-modality | 4/9 real | degrades poorly | NOT demo-ready (2 surface cards fail on code bugs; overstates coverage) |
| surfaceome-cohort-ranking | none | honest empty | honest but hollow (reads dead /tmp path) |
| combo-and-resistance, translational-readiness | — | — | honest placeholders (good design; keep) |

## Secondary defects (not root-cause; per-skill cleanup)

- Version drift SKILL.md vs run.py (e.g. 1.1.0 vs 1.2.0) across most skills.
- Phantom figures: every SKILL.md promises `figures/*.png`; the dispatcher
  invokes no emitter and `write_package` globs an empty dir → 0 figures.
- Dead `on_dependency_status` config: declared in front-matter + implemented
  in dispatcher, but run.py never passes it; the arch-A4 "skip placeholders"
  story is achieved by omission, not by the advertised mechanism.
- `provenance.yaml` omits the S3 URIs / manifest IDs / release pins its own
  docstring promises — no release-level audit trail.
- functional-requirement paralog-buffering: wrong-quantity computation +
  phantom manifest + dead rules — needs a genuine paired-vs-single-KO rebuild
  before it belongs in stakeholder output.
- on-target-safety-liability: the gnomad-constraint SOURCE manifest landed
  (gnomad-constraint-snapshot-2026-07-02) but the method that reads it was
  never written — a dispatcher stub pointing at a nonexistent module.

## A defensible demo exists today

KRAS/COADREAD on **mutation-profile + tumor-presence + mechanism-and-pharmacology**
(+ tumor-selectivity after the label fix) is a real proof-of-work:
real DepMap/MC3/SIGNOR data → deterministic rule-fired verdicts → LLM
synthesis. Fixing RC2+RC3 is expected to add **differentiation-landscape**
(real, strong co-mutation data). Do NOT demo differentiation-landscape,
on-target-safety, or tractability in their current state — a skeptic running
KRAS gets `insufficient` sitting on visibly-real data.
