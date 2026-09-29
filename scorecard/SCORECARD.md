# Component scorecard

GENERATED — do not edit. Source of truth = the per-skill shards in `scorecard/<skill>.json`;
regenerate with `pixi run python scripts/regenerate_scorecard.py` (verify with `--check`).

Cell = (skill × layer). Per-criterion statuses: (a) accuracy vs re-derivation ·
(b) utilization/disposition · (c) fail-open · (d) panel-consistency — each GREEN/RED/NULL.
NULL = not yet measured and NEVER counts as GREEN. NOT_BUILT = the layer does not exist for
this skill (architecture gap, not a defect — distinct from RED). A cell is GREEN only when
built and all four criteria are GREEN. Cells are never scored by verdict movement.

| skill | L1 | L2a | L2b | L3 | L4 |
|---| --- | --- | --- | --- | --- |
| catalog-query | NULL | NULL | NULL | NULL | NULL |
| cis-feature-coherence | NULL | NULL | NULL | NULL | NULL |
| combination-and-vulnerability | NULL | NULL | NULL | NULL | NULL |
| cross-evidence-hypothesis | NULL | NULL | NULL | NULL | NULL |
| differentiation-landscape | NULL | NULL | NULL | NULL | NULL |
| example-gallery | NULL | NULL | NULL | NULL | NULL |
| functional-requirement | NULL | NULL | NULL | NULL | NULL |
| genomic-alteration-profile | NULL | NULL | NULL | NULL | NULL |
| immune-context | NULL | NULL | NULL | NULL | NULL |
| literature-context | NULL | NULL | NULL | NULL | NULL |
| literature-risk-assessment | NULL | NULL | NULL | NULL | NULL |
| mechanism-and-pharmacology | NULL (a:- u:G f:G p:G) | NOT_BUILT | NOT_BUILT | NOT_BUILT | NOT_BUILT |
| on-target-safety-liability | NULL | NULL | NULL | NULL | NULL |
| query-target-evidence | NULL | NULL | NULL | NULL | NULL |
| render-evidence-package | NULL | NULL | NULL | NULL | NULL |
| surface-modality-fit | NULL (a:- u:G f:G p:G) | NOT_BUILT | NOT_BUILT | NOT_BUILT | NOT_BUILT |
| target-intrinsic | NULL (a:- u:G f:G p:G) | NOT_BUILT | NOT_BUILT | NOT_BUILT | NOT_BUILT |
| target-profile | NULL | NULL | NULL | NULL | NULL |
| tractability-small-molecule | NULL | NULL | NULL | NULL | NULL |
| translational-readiness | NULL | NULL | NULL | NULL | NULL |
| tumor-presence | GREEN (a:G u:G f:G p:G) | NULL (a:- u:G f:G p:-) | NULL (a:- u:G f:G p:-) | NULL (a:- u:G f:G p:-) | NOT_BUILT |
| tumor-selectivity | NULL (a:- u:G f:G p:-) | NOT_BUILT | NOT_BUILT | NOT_BUILT | NOT_BUILT |

## Summary

- cells: 110 (22 skills × 5 layers)
- GREEN: 1
- RED: 0
- NULL: 92
- NOT_BUILT: 17
