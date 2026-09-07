"""Tests for the coessentiality_context lane in mechanism_composed/read.py.

These tests mock all sub-readers so no S3 or file access is needed.
They verify:
  - coessentiality_context is present and correctly shaped
  - data_available=True when read_coessential_partners succeeds
  - data_available=False (graceful) when the reader raises or gene is absent
  - sources_wired includes depmap_coessentiality only when data_available
  - source_counts includes depmap_coessentiality key
  - existing mechanism-edge output is unaffected by co-essentiality failure
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

import methods.mechanism_composed.read as mc_read


# ---------------------------------------------------------------------------
# Stubs for every sub-reader
# ---------------------------------------------------------------------------


def _stub_signor(target, indication=None):
    return {
        "network_class": "partial",
        "upstream_regulators": [
            {
                "partner_gene_symbol": "EGFR",
                "direction": "up",
                "moa_class": "phosphorylation",
                "raw_mechanism": "phosphorylation",
                "modality_relevance": None,
                "references": "12345",
            }
        ],
        "downstream_effectors": [],
        "moa_ontology_unmapped_fraction": 0.0,
    }


def _stub_collectri(target, indication=None):
    return {
        "network_class": "sparse",
        "upstream_regulators": [],
        "downstream_effectors": [],
        "moa_ontology_unmapped_fraction": 0.0,
    }


def _stub_reactome(target, indication=None):
    return {
        "pathway_class": "signaling",
        "pathway_count": 3,
        "top_level_pathways": ["Signal Transduction"],
        "is_signaling": True,
    }


def _stub_kinome_atlas(target, indication=None):
    return {
        "network_class": "data_unavailable",
        "upstream_regulators": [],
        "downstream_effectors": [],
        "_source_note": "no kinase substrate data",
    }


def _stub_coessentiality_ok(target, top_n=25, **kwargs):
    return {
        "gene_symbol": target,
        "partners": [
            {"symbol": "NAE1", "pearson_r": 0.345, "abs_rank": 1, "direction": "co-essential"},
            {"symbol": "NEDD8", "pearson_r": 0.336, "abs_rank": 2, "direction": "co-essential"},
        ],
        "n_partners": 2,
        "n_cell_lines": 1538,
        "method_version": "0.1.0",
        "substrate_uri": "s3://onc-compbio/.../coessentiality_edges.parquet",
    }


def _stub_coessentiality_unavailable(target, top_n=25, **kwargs):
    return {
        "gene_symbol": target,
        "partners": [],
        "n_partners": 0,
        "_data_unavailable": True,
        "_reason": f"gene '{target}' not found in coessentiality substrate",
        "method_version": "0.1.0",
        "substrate_uri": "s3://onc-compbio/.../coessentiality_edges.parquet",
    }


# ---------------------------------------------------------------------------
# Helper: run read_target_summary with all sub-readers mocked
# ---------------------------------------------------------------------------


@contextmanager
def _all_mocked(coess_stub):
    with (
        patch("methods.mechanism_composed.read.signor_read.read_target_summary", side_effect=_stub_signor),
        patch("methods.mechanism_composed.read.collectri_read.read_target_summary", side_effect=_stub_collectri),
        patch("methods.mechanism_composed.read.reactome_read.read_target_summary", side_effect=_stub_reactome),
        patch("methods.mechanism_composed.read.kinome_atlas_read.read_target_summary", side_effect=_stub_kinome_atlas),
        patch("methods.mechanism_composed.read.coessentiality_read.read_coessential_partners", side_effect=coess_stub),
    ):
        yield


def _run(target, coess_stub):
    with _all_mocked(coess_stub):
        return mc_read.read_target_summary(target)


# ---------------------------------------------------------------------------
# Tests: coessentiality_context structure
# ---------------------------------------------------------------------------


class TestCoessentialityContextShape:
    def test_key_present(self):
        result = _run("UBA3", _stub_coessentiality_ok)
        assert "coessentiality_context" in result

    def test_data_available_true_when_success(self):
        result = _run("UBA3", _stub_coessentiality_ok)
        assert result["coessentiality_context"]["data_available"] is True

    def test_n_partners_populated(self):
        result = _run("UBA3", _stub_coessentiality_ok)
        assert result["coessentiality_context"]["n_partners"] == 2

    def test_n_cell_lines_populated(self):
        result = _run("UBA3", _stub_coessentiality_ok)
        assert result["coessentiality_context"]["n_cell_lines"] == 1538

    def test_top_partners_list(self):
        result = _run("UBA3", _stub_coessentiality_ok)
        partners = result["coessentiality_context"]["top_partners"]
        assert len(partners) == 2
        assert partners[0]["symbol"] == "NAE1"
        assert partners[0]["pearson_r"] == pytest.approx(0.345, abs=1e-4)
        assert partners[0]["direction"] == "co-essential"

    def test_source_note_contains_depmap(self):
        result = _run("UBA3", _stub_coessentiality_ok)
        note = result["coessentiality_context"]["source_note"]
        assert "DepMap" in note and "1,538" in note


# ---------------------------------------------------------------------------
# Tests: sources_wired + source_counts
# ---------------------------------------------------------------------------


class TestSourcesWired:
    def test_depmap_coessentiality_in_sources_wired_when_available(self):
        result = _run("UBA3", _stub_coessentiality_ok)
        assert mc_read.SOURCE_KEY_COESSENTIALITY in result["sources_wired"]

    def test_depmap_coessentiality_absent_when_unavailable(self):
        result = _run("NOTREAL", _stub_coessentiality_unavailable)
        assert mc_read.SOURCE_KEY_COESSENTIALITY not in result["sources_wired"]

    def test_source_counts_has_coessentiality_key(self):
        result = _run("UBA3", _stub_coessentiality_ok)
        assert mc_read.SOURCE_KEY_COESSENTIALITY in result["source_counts"]

    def test_source_counts_coessentiality_reflects_n_partners(self):
        result = _run("UBA3", _stub_coessentiality_ok)
        assert result["source_counts"][mc_read.SOURCE_KEY_COESSENTIALITY] == 2

    def test_source_counts_zero_when_unavailable(self):
        result = _run("NOTREAL", _stub_coessentiality_unavailable)
        assert result["source_counts"][mc_read.SOURCE_KEY_COESSENTIALITY] == 0


# ---------------------------------------------------------------------------
# Tests: graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    def test_data_available_false_when_gene_missing(self):
        result = _run("NOTREAL", _stub_coessentiality_unavailable)
        ctx = result["coessentiality_context"]
        assert ctx["data_available"] is False
        assert ctx["n_partners"] == 0

    def test_reader_exception_does_not_crash_composed(self):
        def _raise(target, **kwargs):
            raise RuntimeError("S3 read failed")

        result = _run("UBA3", _raise)
        assert "coessentiality_context" in result
        assert result["coessentiality_context"]["data_available"] is False

    def test_existing_upstream_regulators_unaffected_by_coessentiality_failure(self):
        """Mechanism edge union must be intact even if co-essentiality read fails."""

        def _raise(target, **kwargs):
            raise RuntimeError("substrate unavailable")

        result = _run("UBA3", _raise)
        assert "upstream_regulators" in result
        assert len(result["upstream_regulators"]) == 1  # EGFR from signor stub
        assert "downstream_effectors" in result

    def test_existing_network_class_unaffected(self):
        def _raise(target, **kwargs):
            raise RuntimeError("substrate unavailable")

        result = _run("UBA3", _raise)
        assert result["network_class"] in ("well_characterized", "partial", "sparse", "data_unavailable")
