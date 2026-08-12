"""Regression tests for the evidence_package envelope integrity fixes (2026-08-10 code review).

L3 — the composer advertised governance.lockfile_ref="lockfile.yaml", but nothing ever wrote that
     file (phantom provenance pointer). The envelope must not claim a lockfile it doesn't produce.
L4 — renderings.markdown pointed at "renderings/dashboard.md", but main() writes the rendering to
     the package ROOT ("dashboard.md"); the self-describing pointer must match the actual file.

These assert the envelope shape directly (no live reads, no S3) via the shared
_skills_common.envelope.assemble_evidence_package writer (extracted from compose-dashboard's
former local _assemble_evidence_package in Phase D D1a).
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR.parent))  # skills/ — for _skills_common

from _skills_common.envelope import assemble_evidence_package  # noqa: E402


def _minimal_input_context() -> dict:
    return {
        "target_symbol": "KRAS",
        "indication": "COADREAD",
        "data_mode": "latest_approved",
        "release_pin": "26q1",
        "subgroup_spec": None,
    }


def _assemble(**kw) -> dict:
    return assemble_evidence_package(
        input_context=_minimal_input_context(),
        dashboard_spec_ref="intracellular-intrinsic-base",
        card_outputs=kw.get("card_outputs", []),
        synthesis_block={"headline": "test", "caveats_summary": [], "modality_fit_assessment": []},
        validation_summary={"n_cards_attempted": 0, "n_cards_passed": 0,
                            "n_cards_passed_with_warnings": 0, "n_cards_failed": 0,
                            "n_cards_excluded_by_applies_when": 0},
        deterministic_timestamps=True,
        framework_version="2.0.0",
        generated_by="skills/compose-dashboard@0000000",
        unavailable_cards=None,
    )


def test_envelope_does_not_advertise_phantom_lockfile():
    """L3: governance must NOT carry a lockfile_ref pointing at a file the pipeline never writes."""
    ep = _assemble()
    assert "lockfile_ref" not in ep["governance"], (
        "governance.lockfile_ref reintroduced — the composer does not write a lockfile, so the "
        "envelope must not advertise one (phantom provenance).")
    # The required governance keys are still present.
    for k in ("data_mode", "release_pin", "validation_summary"):
        assert k in ep["governance"]


def test_renderings_markdown_points_at_the_actual_file():
    """L4: the rendering pointer must match where main() writes it (package-root dashboard.md)."""
    ep = _assemble()
    assert ep["renderings"]["markdown"] == "dashboard.md", (
        f"renderings.markdown={ep['renderings']['markdown']!r} — main() writes the rendering to the "
        "package root as 'dashboard.md', not a renderings/ subdir.")
