"""v1.6.1 VERDICT-INERT display follow-ups: the Saltz spatial-aggregation hint (median_number_of_clusters)
and the antigen-CONDITIONED heterogeneity facet (the documented v2 facet the card already computes). Both are
verdict-inert projections over already-emitted card fields; the antigen-conditioned block is the ONLY
target-dependent surface and degrades to data_unavailable when the join is thin. The immune_context_verdict
spine stays byte-stable (gateless skill)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

RUN = Path(__file__).resolve().parent.parent / "scripts" / "run.py"
SKILLS_DIR = RUN.resolve().parent.parent.parent


def _load():
    if str(SKILLS_DIR) not in sys.path:
        sys.path.insert(0, str(SKILLS_DIR))
    spec = importlib.util.spec_from_file_location("ic_run_v161", RUN)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ic = _load()

_HOT = "immune-context-hot-tce-supportive"
_INT = "immune-context-intermediate-tce-neutral"


def _cards(ic_summary, saltz_summary):
    return [{"card_id": "immune-context", "summary": ic_summary},
            {"card_id": "tcga-til-fraction-saltz", "summary": saltz_summary}]


def test_antigen_conditioned_surfaced_when_join_succeeds():
    """SKCM-like: the join succeeds (join_fraction=1.0), antigen-high patients are WARMER (cd8_high_minus_low
    positive) — the fields flow into the headline + immune_provenance.antigen_conditioned."""
    cards = _cards(
        {"immune_context_class": "immune_hot", "median_cd8_fraction": 0.154,
         "median_total_t_cell_fraction": 0.38, "n_samples": 473, "tumor_studies": ["TCGA-SKCM"],
         "antigen_conditioned_call": "antigen_high_immune_hot", "cd8_high_minus_low": 0.0255,
         "antigen_high_immune_context_class": "immune_hot"},
        {"til_fraction_class": "til_intermediate", "median_til_percentage": 4.3, "n_samples": 384,
         "median_number_of_clusters": 12.0})
    hl = ic._headline(cards, [], ic._verdict([{"rule_id": _HOT}]))
    assert hl["antigen_conditioned_call"] == "antigen_high_immune_hot"
    assert hl["cd8_high_minus_low"] == 0.0255
    ac = hl["immune_provenance"]["antigen_conditioned"]
    assert ac["antigen_conditioned_call"] == "antigen_high_immune_hot"
    assert ac["cd8_high_minus_low"] == 0.0255
    # spatial-aggregation hint lifted
    assert hl["median_number_of_clusters"] == 12.0
    assert hl["immune_provenance"]["absolute_til_corroboration"]["median_number_of_clusters"] == 12.0
    # verdict spine unchanged
    assert hl["immune_context_verdict"] == "immune_hot"


def test_antigen_conditioned_degrades_when_join_thin():
    """BLCA-like: the CIBERSORT↔expression join is too thin → the card reports data_unavailable; the surfaced
    fields carry that honestly (never a fabricated per-patient call)."""
    cards = _cards(
        {"immune_context_class": "immune_intermediate", "median_cd8_fraction": 0.110,
         "median_total_t_cell_fraction": 0.30, "n_samples": 433, "tumor_studies": ["TCGA-BLCA"],
         "antigen_conditioned_call": "data_unavailable", "cd8_high_minus_low": None,
         "antigen_high_immune_context_class": "data_unavailable"},
        {"til_fraction_class": "til_high", "median_til_percentage": 5.19, "n_samples": 298,
         "median_number_of_clusters": 16.0})
    hl = ic._headline(cards, [], ic._verdict([{"rule_id": _INT}]))
    assert hl["antigen_conditioned_call"] == "data_unavailable"
    assert hl["cd8_high_minus_low"] is None
    assert hl["immune_provenance"]["antigen_conditioned"]["antigen_conditioned_call"] == "data_unavailable"
    assert hl["median_number_of_clusters"] == 16.0
    assert hl["immune_context_verdict"] == "immune_intermediate"


def test_cf_returns_none_on_absent_field():
    """_cf is the defensive getter for OPTIONAL display fields — an older card lacking a newer field must
    degrade to None, NEVER abort the spine. Cards with NO antigen-conditioned / cluster fields at all."""
    cards = _cards(
        {"immune_context_class": "immune_hot", "median_cd8_fraction": 0.20,
         "median_total_t_cell_fraction": 0.4, "n_samples": 100},   # no antigen-conditioned keys
        {"til_fraction_class": "til_high", "median_til_percentage": 6.0})  # no median_number_of_clusters
    hl = ic._headline(cards, [], ic._verdict([{"rule_id": _HOT}]))
    assert hl["antigen_conditioned_call"] is None
    assert hl["cd8_high_minus_low"] is None
    assert hl["median_number_of_clusters"] is None
    # provenance still builds; the block carries Nones
    assert hl["immune_provenance"]["antigen_conditioned"]["antigen_conditioned_call"] is None
    assert hl["immune_context_verdict"] == "immune_hot"   # spine intact despite missing display fields


def test_new_display_fields_in_synthesis_facet_keys():
    for k in ("median_number_of_clusters", "antigen_conditioned_call", "cd8_high_minus_low",
              "antigen_high_immune_context_class"):
        assert k in ic._SYNTHESIS_FACET_KEYS
