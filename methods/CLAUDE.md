# Claude Code — Domain Rules for methods/

> **Process (worktrees, branch/PR discipline, landing, the WIP registry) lives in one
> place: root [CLAUDE.md](../CLAUDE.md).** Read that first. This file holds only the
> rules specific to the `methods/` package (the former `analysis-methods` repo, now
> in-tree — SK#2063).

## What belongs here

**Deterministic analytical code**, packaged as CLIs. A method has a single CLI
entrypoint, takes catalog manifest IDs + parameters as input, and emits a structured,
idempotent output bundle. See [DEVELOPMENT_GUIDELINES.md](DEVELOPMENT_GUIDELINES.md)
for the full authoring contract.

## Domain rules to remember

- **`--import-mode=importlib` is required.** Several method test files share a
  basename and collide under pytest's default import mode:
  ```bash
  pixi run pytest methods/ tests/ -q --import-mode=importlib -n 8
  ```
  Always run `methods/ tests/` **together** — running `methods/` alone under-collects
  and can hide a red.
- **Live-data tests need `AWS_PROFILE=cbg`** locally; CI sets
  `SKILLS_SKIP_LIVE_DATA=1` so those tests self-skip on a credential-less runner —
  a local run without the profile set will silently skip the same tests, which
  reads as green for the wrong reason. Reconcile the SKIP column, not just the exit
  code.
- **Gate with the dispatcher, not bare pytest**: `scripts/preland.sh methods` from
  the repo root (or `methods/scripts/preland.sh` from inside `methods/`) — see root
  CLAUDE.md's Testing section for the full `{skills|methods|contracts|all}` dispatcher.
- **Public vs private helpers.** A method's library entry (`read.py`) is separated
  from its CLI + figure emission (`cli.py`); helpers called by both the CLI and the
  skill figure-emitter registry keep a no-underscore name (e.g. `load_depmap_files`,
  `emit_waterfall_plot`) — internal-only helpers keep the `_` prefix.
- **Card summary-output schema is opt-in.** A method's `summary` dict validates
  against `contracts/schemas/methods/<card_id>.summary.schema.json` only when that
  file exists — cards without one are unaffected until a schema is committed.
