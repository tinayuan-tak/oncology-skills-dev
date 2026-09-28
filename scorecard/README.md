# Component scorecard (epic #1985)

The recompute-able instrument for the component-iterator walk. **Checkmarks are OUTPUTS of a
harness, never static notes** — every cell here is regenerated from machine evidence, not edited.

- **Source of truth:** the per-skill shards `scorecard/<skill>.json` — ONE file per skill, written
  only by that skill's adapter via `_skills_common.component_scorecard.write_skill_shard` (this is
  what makes the adapter wave parallel-safe by construction; adapters never write a shared file).
- **Aggregate:** `SCORECARD.md` is rendered at read time by the SINGLE regenerate entrypoint —
  `pixi run python scripts/regenerate_scorecard.py` (`--check` verifies it is current; the
  `_skills_common` test suite enforces that on every CI run). Deterministic: no timestamps,
  byte-stable for unchanged shards.
- **Schema, statuses, and the adapter interface** are documented in
  `skills/_skills_common/component_scorecard.py` (module docstring). The tumor-presence exemplar
  (A0c, #1988) is the normative adapter example. In brief: per cell `(skill × layer L1..L4)`, four
  independent criteria — (a) accuracy vs re-derivation, (b) utilization/disposition, (c) fail-open,
  (d) panel-consistency — each `GREEN | RED | NULL`; cell-level `NOT_BUILT` (architecture gap) is
  distinct from `RED` (defect); **NULL never renders GREEN** — unmeasured must not promote.
- **Governing directive:** components are never scored by verdict movement; "moves a verdict" is
  not a criterion and must never become one.
