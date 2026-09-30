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
  pixi run pytest onc_methods/ tests/ -rsfE --import-mode=importlib -n 8
  ```
  Run it from `methods/`; `pixi` resolves the ONE workspace manifest at the repo root
  (SK#2145 deleted `methods/pixi.toml` — there is no per-package env any more), and
  `pixi run` preserves your cwd so pytest's rootdir stays `methods/`.
  **Do not add `-q`**: `methods/pyproject.toml`'s `addopts` already carries it, and a second
  `-q` means `-qq`, at which pytest prints NO `N passed, M skipped` line at all — the run
  then looks green to anything reading the tail of the log.
  **Use `-rsfE`, not `-rs`**: pytest's default `-r` value is `fE`, and passing `-rs` *replaces*
  it instead of adding to it — so `-rs` alone names every skip and no failure, and a red run
  reports `1 failed` with the failing node id nowhere in the log (measured, SK#2145).
  Always run `onc_methods/ tests/` **together** — running `onc_methods/` alone under-collects
  and can hide a red.
- **Live-data tests need `AWS_PROFILE=cbg`** locally; CI sets
  `SKILLS_SKIP_LIVE_DATA=1` so those tests self-skip on a credential-less runner —
  a local run without the profile set will silently skip the same tests, which
  reads as green for the wrong reason. Reconcile the SKIP column, not just the exit
  code.
- **A worktree gate tests the WORKTREE — enforced, not by convention (skills#2266).**
  `oncology-analysis-methods` is installed EDITABLE, and depending on how the env was
  built its finder can resolve `onc_methods` to a DIFFERENT checkout than the tree you
  are running from (classically the primary checkout a `/tmp` worktree was branched
  off). Historically that made a `methods/` suite run from a worktree silently exercise
  TRUNK — a green branch proved nothing (measured: six planted mutations of production
  constants all survived at 42/42 green). Neither cwd nor invocation form was a reliable
  guard: the `pytest` console script puts its `bin/` dir (not cwd) on `sys.path[0]`, so
  even `cd methods/` did not shadow the editable finder — only `python -m pytest` did, by
  luck. **`methods/conftest.py` now binds `onc_methods` to the tree the conftest lives in
  before importing it, and asserts it loudly at collection time.** So a worktree gate is
  correct by construction, and if the binding ever cannot be established the run ERRORS
  ("methods/ gate is BLIND") rather than reporting a false green. You no longer need
  per-module `spec_from_file_location` / `sys.path` shims to gate a worktree correctly;
  if the guard fires, re-run `pixi install` in the worktree.
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
