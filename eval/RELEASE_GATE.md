# eval/RELEASE_GATE.md — the framework-level definition of done

`docs/DEFINITION_OF_DONE.md` defines when a *single change* is done. This defines when the **framework
as a whole is release-ready** — the bar to call the target-profile system "mature and complete." Its
engine is `eval/run_scorecard.py`; this doc is the human-readable contract around it.

## The gate — all must hold

| # | Criterion | How it's checked | Owner instrument |
|---|-----------|------------------|------------------|
| 1 | **Structural health clean** — 0 error/warn drift; no orphan cards / broken dataset refs / missing sort-keys | `framework_health --check` green | `target-contracts/validators/framework_health/` |
| 2 | **Runs-clean** — every wired subskill's `run.py` executes clean on stubbed cards | runs-clean smoke `--check` green | `_skills_common/framework_health_smoke.py` |
| 3 | **Known-target regression held** — the calibration snapshots pass their typed assertions | `tests/calibration/` green | `target-contracts` calibration suite |
| 4 | **Predictive-validity floors held** — no regression past the documented discrimination floors (dangerous-FP / silent-FN / approved-agreement) | `validate_framework_discrimination --check` green | discrimination harness |
| 5 | **Fresh-output backtest** — the live known-target panel scores no NEW regression (a `validated_lane` target hard-vetoed), decoys hold (specificity), signal ledger + per-family capture computed | `run_known_target_panel` (score) green; no `REGRESSION` drift | `eval/run_known_target_panel.py` |
| 6 | **Artifact fidelity** — all canonical-panel examples regenerate cleanly: complete `target_profile.md` (no blank LLM sections), valid `evidence_package.json`, `llm_synthesis._source == "llm_synthesized"` | `eval/run_example.sh --full-package` over the panel | `eval/CONVENTION.md` |
| 7 | **Case log triaged** — every open `CASE_LOG.md` entry is either closed, or a queued build with a named owner/next-step; no un-triaged fresh error | manual review of `eval/CASE_LOG.md` | the cadence |

Criteria 1–5 are machine-checked by **`python eval/run_scorecard.py`** (exit non-zero on any red).
6–7 are the human-facing checks a maintainer runs before declaring a release.

## What "done" does NOT mean
- **Not** "every axis captured." The framework has HONEST CEILINGS — e.g. surface-antigen density is
  `partial` (proxies, not the clinical CDx-threshold), IO/TME context is blind, non-cell-autonomous
  metabolic dependencies (CNDP2/KEAP1-NRF2) are out of scope. `run_known_target_panel`'s per-family
  coverage map (`capture_by_family`) reports these honestly — the hand-curated coverage distribution
  per deciding-axis family; a family whose distribution skews `blind` is a *known gap*, not a gate
  failure. (It is deliberately NOT joined to the live capture vector: those bands are keyed by
  framework axis shorts, an incommensurable vocabulary from the curated deciding axis.) Done = the
  gaps are MEASURED and TRIAGED, not that they are all closed.
- **Not** "the LLM narrative is perfect." The deterministic spine (verdicts, gate, signal vector) is
  the audited product; the LLM narrative rides in separate slots and is best-effort.

## The improvement cadence (how the framework gets MORE done over time)
Each turn (see `CASE_LOG.md`): read the per-family capture map + the discrimination
`blind_axis_load_bearingness`; pick the highest-leverage gap; **verify it with a live emit BEFORE
building** (the discipline that repeatedly caught mis-scoped/false-alarm fixes); close it; flip its
calibration assertion; tighten its floor; re-run the scorecard to prove the gain with no regression.

## Open finalization decision (Phase-4, deferred)
Retiring the positive `overall_recommendation` scalar in favour of a negative-cross-axis-`block`-only
target verdict (ranking as a consumer projection; `target-profile/docs/TARGET_ROLLUP_DESIGN_2026-08-25.md`)
is an approved *direction* but a large output-contract change. This session's finding — the nomination
gate is healthy and the deterministic layer already emits only negative veto/hold (nominate is
LLM/consumer-chosen, not a deterministic positive claim) — makes its marginal value uncertain. Treat it
as a deliberate, separately-scoped decision, not a prerequisite for release.
