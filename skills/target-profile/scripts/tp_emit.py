"""target-profile — artifact EMIT sink (PR-2 of the composed-dashboard restructure).

ONE place that owns (a) the canonical artifact filenames, (b) the single `write_artifact` helper every
write goes through, and (c) the declarative `MODE_WRITE_SETS` table + `expected_artifacts()` that says
exactly which artifacts a run should produce in each mode — so per-mode write-sets are pinned by an
assertion instead of being implied by scattered `.write_text` calls and an early `return` in main().

Scope: the DASHBOARD/spine artifacts (nomination.json, target_profile.md/.html, provenance.yaml,
evidence_package.json). The machine envelope is still WRITTEN by the pinned
`tp_evidence_package._write_evidence_package` (this module only records that it happened); figures are
owned by `tp_figures`; run.log by `_skills_common.run_log`; grounded_<axis>.json by `tp_grounding`;
the full-package manifest by `tp_manifest` (folds in at PR-4). Verdict-inert — writing bytes never
changes the nomination spine.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

# artifact KIND → canonical filename (single source; kills per-call filename literals).
ARTIFACT_FILENAMES = {
    "nomination": "nomination.json",
    "markdown": "target_profile.md",
    "html": "target_profile.html",
    "provenance": "provenance.yaml",
    "evidence_package": "evidence_package.json",
}

# The dashboard/spine artifacts each RUN MODE produces (run.log is always written; figures/, grounded_*,
# and the full-package manifest are owned by their own emitters and asserted there). `--ground` and
# `--full-package` are MODIFIERS layered on the base mode via `expected_artifacts`.
MODE_WRITE_SETS = {
    "evidence-package": frozenset({"evidence_package"}),                       # --emit: envelope only
    "verdict-only":     frozenset({"nomination", "markdown", "html", "provenance"}),
    "no-figures":       frozenset({"nomination", "markdown", "html", "provenance"}),
    "default":          frozenset({"nomination", "markdown", "html", "provenance"}),
}


def run_mode(args) -> str:
    """The base emit mode (mutually exclusive), highest-precedence first."""
    if getattr(args, "emit", None) == "evidence-package":
        return "evidence-package"
    if getattr(args, "verdict_only", False):
        return "verdict-only"
    if getattr(args, "no_figures", False):
        return "no-figures"
    return "default"


def expected_artifacts(args) -> frozenset:
    """The set of dashboard/spine artifact KINDS this run should produce = base mode + modifiers.
    `--ground`, `--full-package`, AND the DEFAULT-ON grounded-substrate chain each add the
    evidence_package envelope as substrate. The chain assembles the evidence_package as its grounding
    input, so a *default* run legitimately emits it (run.py:764) — mirror run.py's exact write predicate
    by reading the `substrate_chain_on` it stashes on args from tp_grounding.plan_substrate, so this
    guard cannot drift from the writer."""
    kinds = set(MODE_WRITE_SETS[run_mode(args)])
    if (getattr(args, "ground", None) or getattr(args, "full_package", False)
            or getattr(args, "substrate_chain_on", False)):
        kinds.add("evidence_package")
    return frozenset(kinds)


# Artifacts whose emitter is BEST-EFFORT (fail-open): the write-set guard requires everything ELSE, but
# tolerates these being absent (e.g. the HTML render is wrapped try/except — a render failure must not
# abort a run that already wrote its md/nomination/provenance).
BEST_EFFORT_ARTIFACTS = frozenset({"html"})


def write_artifact(out: Path, kind: str, text: str, written: Optional[set] = None) -> Path:
    """The ONE write path for a dashboard/spine artifact. Caller passes already-serialized text
    (json.dumps / yaml.safe_dump / rendered md|html); this owns only the filename + the write. When a
    `written` set is passed, records this kind into it (so assert_write_set checks THIS RUN's writes,
    not stale files in a reused --out)."""
    if kind not in ARTIFACT_FILENAMES:
        raise KeyError(f"unknown artifact kind {kind!r} (known: {sorted(ARTIFACT_FILENAMES)})")
    path = Path(out) / ARTIFACT_FILENAMES[kind]
    path.write_text(text)
    if written is not None:
        written.add(kind)
    return path


def assert_write_set(args, written: set) -> None:
    """Post-run guard: the artifacts WRITTEN THIS RUN match this mode's declared MODE_WRITE_SET. Keys on
    the run-scoped `written` set (NOT filesystem existence — so a reused --out with stale artifacts from a
    prior mode does NOT trigger a false failure). Required = expected minus BEST_EFFORT; a best-effort
    artifact (html) may be absent. Raises AssertionError on genuine drift (a mode gained/dropped a write)."""
    want = set(expected_artifacts(args))
    required = want - BEST_EFFORT_ARTIFACTS
    extra = written - want
    missing = required - written
    assert not extra and not missing, (
        f"artifact write-set drift for mode {run_mode(args)!r}: written={sorted(written)} "
        f"expected={sorted(want)} (missing_required={sorted(missing)} unexpected={sorted(extra)})")


__all__ = ["ARTIFACT_FILENAMES", "MODE_WRITE_SETS", "BEST_EFFORT_ARTIFACTS", "run_mode",
           "expected_artifacts", "write_artifact", "assert_write_set"]
