# Real-data scorecard panel roster (A7, issue #1994, epic #1985)

This is the **roster decision** for the demo-week component-iterator scorecard — domain judgment,
independent of harness code. Config WIRING into the A0a (#1987) scorecard schema is deferred until
that schema lands; this file is intentionally self-contained (plain `target`/`indication` pairs +
rationale) so A0a can consume it without this issue depending on A0a's shape.

Per the plan (`~/.claude/plans/modular-swinging-dahl.md`, "The panel"), the goal is a small,
archetype-diverse set that is big enough to catch single-target overfit and small enough to eyeball
every field — picked to **maximize red coverage**, not convenience.

## Roster (5 targets)

| target | indication | archetype | stresses |
|---|---|---|---|
| **EPCAM** | COADREAD | flagship — surface antigen | ADC/TCE surface-modality-fit path (focally/broadly expressed epithelial antigen) |
| **KRAS** | COADREAD | flagship — intrinsic driver | dependency + tractability story (oncogene addiction, not a surface play) |
| **ERBB2 (HER2)** | BRCA | amplified surface antigen | cis-dosage / amplification-driven surface story (orthogonal from EPCAM's non-amplified broad-expression story) |
| **PLK1** | COADREAD | pan-essential control | #1794 broad-tox arm — a genuine `AchillesCommonEssentialControls`-anchored killer, must NOT get nominated |
| **HTR1D** | COADREAD | thin-coverage / abstention control | #1792 fail-open confidence floor — a target whose surface derived products are data-blocked, so the honest read is `insufficient`, not a confidently-wrong reassurance |

All five pairs are drawn from `target-contracts/vocabularies/known_target_calibration_set.yaml`
(the framework's existing calibration truth-set) — not novel picks — so each has a **live-verified**
provenance trail already in the repo (see rationale below), satisfying "do not roster a target the
stack cannot run."

## Per-target rationale

### EPCAM / COADREAD — flagship, surface antigen
`known_target_calibration_set.yaml` line ~444 (`reference_profiles.EPCAM`, modality: adc). EPCAM is a
canonical epithelial-cell-adhesion-molecule ADC/TCE antigen (catumaxomab / EPCAM-targeting programs),
broadly and focally expressed across CRC — the flagship surface case fixed by the plan. Confirmed
present in the calibration corpus.

### KRAS / COADREAD — flagship, intrinsic driver
`known_target_calibration_set.yaml` reference_profiles.KRAS + the paralog-buffering fixture
(line ~810, `strongest_paralog_symbol: NRAS`). KRAS is the flagship intrinsic-driver case fixed by
the plan: dependency + tractability (G12C-class), not a surface story — the deliberate contrast
against EPCAM. Confirmed present, including live-verified functional-requirement fixtures.

### ERBB2 (HER2) / BRCA — amplified surface antigen (issue's own default; kept)
`known_target_calibration_set.yaml` reference_profiles.ERBB2 (indication: BRCA, modality: adc,
outcome: approved_class — trastuzumab/T-DXd) + a tumor-selectivity fixture
(`erbb2_brca.tumor-selectivity.json`, line ~735). ERBB2 is amplification-driven (copy-number → 
expression → surface density), which is a distinct axis from EPCAM's non-amplified broad expression
— together the two surface picks exercise both the "just highly expressed" and the "amplified"
surface-antigen sub-archetypes, per the plan's explicit suggestion. Confirmed present with two
independent calibration fixtures (reference_profiles + tumor-selectivity case).

### PLK1 / COADREAD — pan-essential control
`known_target_calibration_set.yaml` line ~591: `PLK1: {indication: multi, ..., deciding_axis:
window_pan_essential, deciding_axis_coverage: captured, agreement: agree, severity: validated_lane,
note: "Correctly-declined negative (VERIFIED live 2026-09-02, PLK1/COADREAD SM → forced_recommendation
=veto). ... Framework CAPTURES the liability: dependency=pan_essential_killer (PLK1 is genuinely
pan-essential — the mitotic kinase) ..."}`. PLK1 is a real, DepMap-curated core-essential gene
(`AchillesCommonEssentialControls` = Hart2015 ∩ Blomen2014 anchor set consumed by
`methods/depmap_chronos_distribution/cli.py::_load_curated_common_essentials`) — chosen over other
pan-essential anchors in the same file (WEE1, CHEK1, KIF11) because it has the most explicit,
already-live-verified `pan_essential_killer` capture note, giving the highest confidence the panel
run will actually exercise the #1794 broad-tox arm rather than silently landing on a NULL/NOT_BUILT
cell. Indication pinned to COADREAD to match the EPCAM/KRAS/HTR1D indication and keep the panel
indication-consistent (panel-consistency criterion (d) in A0a's schema).

### HTR1D / COADREAD — thin-coverage target
`known_target_calibration_set.yaml` `abstention_cases.HTR1D` (line ~820) + the assertion block at
line ~845 (`snapshot: htr1d_coadread.surface-modality-fit.json`, `outcome: honest_insufficient`,
note: "surface derived products not yet on S3"). HTR1D is a GPCR (5-HT1D receptor) with no
oncology-relevant surface/dependency characterization program — its surface-modality-fit read is a
confirmed, already-live-verified `insufficient` abstention (data-blocked E2/F gate), and as a
non-oncology GPCR it is plausible its on-target-safety legs beyond CONSTRAINT (gnomAD, which is
genome-wide and therefore always at least nominally measured) — BURDEN/DOSAGE/CLINVAR/MOUSE_KO/
NORMAL_TISSUE — are thin-to-absent. This is exactly the shape #1792 is about: a target where only
one critical-axis leg is measured, so the honest outcome is a coverage-demoted / `insufficient`
confidence, not a confidently reassuring `clean` verdict. Chosen over rostering an entirely novel
target because HTR1D's thin-coverage behavior is already reproducible and pinned in the corpus
(lower risk the panel run reports ERROR instead of exercising the intended red).

## Panel-consistency note
4 of 5 targets share indication COADREAD; ERBB2 is deliberately BRCA (its approved, amplification-
driven indication — running it in COADREAD would misrepresent the amplified-antigen archetype it is
meant to exercise). This mirrors the plan's own KRAS/LUAD-vs-COADREAD-style indication-per-archetype
pattern rather than forcing one indication where the biology does not fit.

## Non-goals (explicitly deferred, per issue #1994)
- No harness config wiring — that step is blocked on A0a (#1987) landing the scorecard schema +
  sharded persistence. This file is deliberately schema-agnostic (plain markdown table, no YAML tied
  to an unlanded schema) so A0a's author can consume the roster in whatever shape the schema needs.
- No re-derivation / no new cards. This is a roster decision, not an implementation.
