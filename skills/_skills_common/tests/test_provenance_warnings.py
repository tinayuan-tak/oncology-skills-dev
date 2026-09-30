"""run_health.provenance_warnings (2026-08-13 multi-pair review, finding #4).

resolved_release_governance records a per-family catalog-head resolution failure fail-open in
provenance.resolved_releases[<fam>].resolution_error (it must never sink emission). Before this fix
run_health never read it, so a run whose DGE family failed to resolve its head still reported
status='ok'. `_provenance_warnings` surfaces it as a DISTINCT run_health signal (it does NOT flip
status — a head-resolution failure is a governance gap, not a missing verdict card)."""

from __future__ import annotations

import _skills_common.dispatcher as D  # noqa: E402


def test_warns_on_resolution_error():
    prov = {
        "resolved_releases": {
            "luad-dge-tumor-vs-normal-sensitivity": {
                "used": ["x"],
                "head": None,
                "resolution_error": "ReleaseResolutionError: no head",
            },
            "cptac-protein": {"used": ["y"], "head": "cptac-protein-v3", "is_stale": False},
        }
    }
    warns = D._provenance_warnings(prov)
    assert warns == [{"family": "luad-dge-tumor-vs-normal-sensitivity", "error": "ReleaseResolutionError: no head"}]


def test_clean_provenance_yields_empty_list():
    prov = {"resolved_releases": {"fam-a": {"used": ["x"], "head": "fam-a-v2", "is_stale": False}}}
    assert D._provenance_warnings(prov) == []


def test_missing_or_empty_provenance_is_safe():
    assert D._provenance_warnings({}) == []
    assert D._provenance_warnings(None) == []
    assert D._provenance_warnings({"resolved_releases": {}}) == []


def test_multiple_errors_sorted_by_family():
    prov = {
        "resolved_releases": {
            "zeta": {"resolution_error": "E: z"},
            "alpha": {"resolution_error": "E: a"},
        }
    }
    fams = [w["family"] for w in D._provenance_warnings(prov)]
    assert fams == ["alpha", "zeta"]
