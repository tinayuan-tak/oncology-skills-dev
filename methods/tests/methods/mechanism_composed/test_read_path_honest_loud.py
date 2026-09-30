"""#770: the composing reader `mechanism_composed/read.py` wrapped the verdict-driving SIGNOR
lane (read.py:203-208) and the coessentiality lane (read.py:250-255) in bare `except Exception`
blocks that swallowed *any* failure — including transient S3 throttling / 5xx / expired creds —
into an empty / `data_unavailable` result.

On the SIGNOR lane that silently (a) dropped `network_class` / `mechanism_verdict` from a rich
rung to `data_unavailable`, and (b) via the shared risk projector escalated the governance-citable
"Right Target" biological-risk bin to MED — a transient read hiccup manufactured a false
target-quality penalty.

These tests pin BOTH directions on BOTH lanes so the fix (an `is_definitively_absent`-style
discriminator, mirroring #783/#797/#712/#800/#715) cannot over- or under-correct:
  1. a genuine NoSuchKey / 404 / NoSuchBucket (true absence) still yields a clean
     `data_unavailable` — no raise.
  2. a simulated transient error (throttling / creds / broken env) RE-RAISES rather than being
     silently classified absent.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import onc_methods.mechanism_composed.read as mc_read

# ---------------------------------------------------------------------------
# Error fixtures
# ---------------------------------------------------------------------------


def _nosuchkey():
    """A genuine not-found ClientError — the ONLY failure a lane may swallow (honest data_unavailable)."""
    from botocore.exceptions import ClientError

    return ClientError({"Error": {"Code": "NoSuchKey", "Message": "not found"}}, "GetObject")


def _throttling():
    """A transient ClientError (SlowDown) — NOT a genuine-absence signal; must re-raise."""
    from botocore.exceptions import ClientError

    return ClientError({"Error": {"Code": "SlowDown", "Message": "please reduce request rate"}}, "GetObject")


# ---------------------------------------------------------------------------
# Neutral stubs for the non-lane-under-test readers so the union is well-defined
# and network_class is driven only by SIGNOR + CollecTri.
# ---------------------------------------------------------------------------


def _empty_edges(target, indication=None):
    return {"network_class": "data_unavailable", "upstream_regulators": [], "downstream_effectors": []}


def _empty_reactome(target, indication=None):
    return {"pathway_class": "data_unavailable", "pathway_count": 0, "top_level_pathways": [], "is_signaling": False}


def _rich_signor(target, indication=None):
    """A well-characterized SIGNOR result (≥3 up / ≥3 down) — the rung a transient error would drop."""
    up = [
        {"partner_gene_symbol": g, "direction": "up", "moa_class": "phosphorylation", "references": "1"}
        for g in ("A", "B", "C")
    ]
    dn = [
        {"partner_gene_symbol": g, "direction": "down", "moa_class": "phosphorylation", "references": "1"}
        for g in ("D", "E", "F")
    ]
    return {
        "network_class": "well_characterized",
        "upstream_regulators": up,
        "downstream_effectors": dn,
        "moa_ontology_unmapped_fraction": 0.0,
    }


def _ok_coess(target, top_n=25, **kwargs):
    return {
        "gene_symbol": target,
        "partners": [{"symbol": "NAE1", "pearson_r": 0.34, "abs_rank": 1, "direction": "co-essential"}],
        "n_partners": 1,
        "n_cell_lines": 1538,
        "method_version": "0.1.0",
    }


def _run(*, signor, collectri=_empty_edges, coess=_ok_coess):
    with (
        patch("onc_methods.mechanism_composed.read.signor_read.read_target_summary", side_effect=signor),
        patch("onc_methods.mechanism_composed.read.collectri_read.read_target_summary", side_effect=collectri),
        patch("onc_methods.mechanism_composed.read.reactome_read.read_target_summary", side_effect=_empty_reactome),
        patch("onc_methods.mechanism_composed.read.kinome_atlas_read.read_target_summary", side_effect=_empty_edges),
        patch("onc_methods.mechanism_composed.read.coessentiality_read.read_coessential_partners", side_effect=coess),
    ):
        return mc_read.read_target_summary("UBA3")


# ---------------------------------------------------------------------------
# SIGNOR lane (verdict-driving)
# ---------------------------------------------------------------------------


class TestSignorLane:
    def test_genuine_absence_yields_clean_data_unavailable(self):
        def _raise(target, indication=None):
            raise _nosuchkey()

        result = _run(signor=_raise)  # collectri also empty -> union empty
        assert result["network_class"] == "data_unavailable"
        assert mc_read.SOURCE_KEY_SIGNOR not in result["sources_wired"]

    def test_transient_error_reraises_not_silently_absent(self):
        def _raise(target, indication=None):
            raise _throttling()

        with pytest.raises(Exception) as ei:
            _run(signor=_raise)
        # The transient signal itself surfaces — not a swallowed data_unavailable record.
        assert "SlowDown" in str(ei.value) or "reduce request rate" in str(ei.value)

    def test_broken_env_reraises(self):
        """A non-ClientError, non-FileNotFoundError (e.g. broken env) must also re-raise."""

        def _raise(target, indication=None):
            raise RuntimeError("some import/env failure")

        with pytest.raises(RuntimeError):
            _run(signor=_raise)

    def test_filenotfound_is_genuine_absence(self):
        def _raise(target, indication=None):
            raise FileNotFoundError("no local cache")

        result = _run(signor=_raise)
        assert result["network_class"] == "data_unavailable"


# ---------------------------------------------------------------------------
# Coessentiality lane (display-only, same contract)
# ---------------------------------------------------------------------------


class TestCoessentialityLane:
    def test_genuine_absence_yields_clean_unavailable(self):
        def _raise(target, **kwargs):
            raise _nosuchkey()

        result = _run(signor=_rich_signor, coess=_raise)
        assert result["coessentiality_context"]["data_available"] is False
        # SIGNOR rung intact — coessentiality absence must not touch the verdict axis.
        assert result["network_class"] == "well_characterized"

    def test_transient_error_reraises_not_silently_absent(self):
        def _raise(target, **kwargs):
            raise _throttling()

        with pytest.raises(Exception) as ei:
            _run(signor=_rich_signor, coess=_raise)
        assert "SlowDown" in str(ei.value) or "reduce request rate" in str(ei.value)
