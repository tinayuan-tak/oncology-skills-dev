"""has_actionable_moa / has_pd_marker require a MAPPED MoA class (not just >= 1 edge).

Regression guard for the 2026-09-12 fix: the fields promise a CLASSIFIED mechanism / PD
hook, so an edge set in which EVERY edge fell to the ontology's 'unmapped' bucket must NOT
flip them True. All sub-readers are mocked — no S3 / file access.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import onc_methods.mechanism_composed.read as mc_read


def _stub_reactome(target, indication=None):
    return {"pathway_class": "data_unavailable", "pathway_count": 0, "top_level_pathways": [], "is_signaling": False}


def _stub_empty(target, indication=None):
    return {
        "network_class": "data_unavailable",
        "upstream_regulators": [],
        "downstream_effectors": [],
        "moa_ontology_unmapped_fraction": 0.0,
    }


def _stub_coess_unavailable(target, top_n=25, **kwargs):
    return {"partners": [], "n_partners": 0, "_data_unavailable": True}


@contextmanager
def _mocked(signor_stub):
    with (
        patch("onc_methods.mechanism_composed.read.signor_read.read_target_summary", side_effect=signor_stub),
        patch("onc_methods.mechanism_composed.read.collectri_read.read_target_summary", side_effect=_stub_empty),
        patch("onc_methods.mechanism_composed.read.reactome_read.read_target_summary", side_effect=_stub_reactome),
        patch("onc_methods.mechanism_composed.read.kinome_atlas_read.read_target_summary", side_effect=_stub_empty),
        patch(
            "onc_methods.mechanism_composed.read.coessentiality_read.read_coessential_partners",
            side_effect=_stub_coess_unavailable,
        ),
    ):
        yield


def _edge(symbol, direction, moa_class):
    return {"partner_gene_symbol": symbol, "direction": direction, "moa_class": moa_class, "raw_mechanism": "x"}


def test_all_unmapped_edges_do_not_flip_actionable_moa():
    def _signor(target, indication=None):
        return {
            "network_class": "well_characterized",
            "upstream_regulators": [_edge("A", "upstream", "unmapped"), _edge("B", "upstream", "unmapped")],
            "downstream_effectors": [_edge("C", "downstream", "unmapped")],
            "moa_ontology_unmapped_fraction": 1.0,
        }

    with _mocked(_signor):
        s = mc_read.read_target_summary("FOO")
    # counts (verdict axis) still reflect the edges — network_class unchanged
    assert s["n_upstream_regulators"] == 2 and s["n_downstream_effectors"] == 1
    # but the actionable / PD calls are honest: no MAPPED class present
    assert s["has_actionable_moa"] is False
    assert s["has_pd_marker"] is False


def test_one_mapped_upstream_edge_flips_actionable_moa():
    def _signor(target, indication=None):
        return {
            "network_class": "partial",
            "upstream_regulators": [
                _edge("A", "upstream", "unmapped"),
                _edge("B", "upstream", "upstream_kinase_modulation"),
            ],
            "downstream_effectors": [_edge("C", "downstream", "downstream_pd_kinase")],
            "moa_ontology_unmapped_fraction": 0.5,
        }

    with _mocked(_signor):
        s = mc_read.read_target_summary("FOO")
    assert s["has_actionable_moa"] is True
    assert s["has_pd_marker"] is True
