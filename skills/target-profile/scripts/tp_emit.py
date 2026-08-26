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
    `--ground` and (PR-4) `--full-package` add the evidence_package envelope as substrate."""
    kinds = set(MODE_WRITE_SETS[run_mode(args)])
    if getattr(args, "ground", None) or getattr(args, "full_package", False):
        kinds.add("evidence_package")
    return frozenset(kinds)


def write_artifact(out: Path, kind: str, text: str) -> Path:
    """The ONE write path for a dashboard/spine artifact. Caller passes already-serialized text
    (json.dumps / yaml.safe_dump / rendered md|html); this owns only the filename + the write."""
    if kind not in ARTIFACT_FILENAMES:
        raise KeyError(f"unknown artifact kind {kind!r} (known: {sorted(ARTIFACT_FILENAMES)})")
    path = Path(out) / ARTIFACT_FILENAMES[kind]
    path.write_text(text)
    return path


def assert_write_set(out: Path, args, *, extra_present: Optional[set] = None) -> None:
    """Post-run guard: the dashboard/spine artifacts on disk match `expected_artifacts(args)` exactly.
    `extra_present` lets the caller include kinds written by their own emitter (e.g. evidence_package via
    _write_evidence_package). Raises AssertionError on drift so a mode never silently gains/drops a file."""
    on_disk = {k for k, fn in ARTIFACT_FILENAMES.items() if (Path(out) / fn).exists()}
    on_disk |= (extra_present or set())
    want = set(expected_artifacts(args))
    assert on_disk == want, (
        f"artifact write-set drift for mode {run_mode(args)!r}: on_disk={sorted(on_disk)} "
        f"expected={sorted(want)} (missing={sorted(want - on_disk)} unexpected={sorted(on_disk - want)})")


__all__ = ["ARTIFACT_FILENAMES", "MODE_WRITE_SETS", "run_mode", "expected_artifacts",
           "write_artifact", "assert_write_set"]
