"""Unit tests for the VERDICT-INERT actionable-MoA INFLATION surfacing added in v1.9.0
(mechanism_confirmation_caveat / prediction_lane_caveat / curation_gap_note), mirroring the
tractability directness_caveat + surface surface_confirmation_caveat tests.

THE TRAP under test: `has_actionable_moa` is composed upstream as (n_upstream_curated_edges >= 1), so it
fires True for a validated-drugged kinase (BRAF/EGFR) AND an undruggable pleiotropic hub / metabolic enzyme
(MYC/MTAP) alike. These caveats name WHY the actionable-MoA call may be inflated WITHOUT moving the verdict
(the mechanism resolver keys only on network_class). Field-combinations mirror the live 2026-09-04 panel:
  MYC/COADREAD    has_actionable_moa=True, network_class=well_characterized, NOT precedented → sharp caveat
  BRAF/COADREAD   has_actionable_moa=True, precedented                     → clinically_precedented (spared)
  EGFR/LUAD       has_actionable_moa=True, precedented, big kinome lane     → precedented + prediction lane
  FGFR2/CHOL      has_actionable_moa=True, precedented, fusion (curation gap not detectable by shape)
  MTAP/PAAD       has_actionable_moa=True, network_class=partial, NOT precedented → sharp caveat _thin_network
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

SKILL_DIR = Path(__file__).resolve().parent.parent

RUN = load_run_py(SKILL_DIR, "mech_run_under_test")


# ── mechanism_confirmation_caveat ────────────────────────────────────────────────────────────────────
def test_no_actionable_moa_is_none():
    """has_actionable_moa False/None → no over-call to flag → None (byte-stable on the negative path)."""
    assert RUN._mechanism_confirmation_caveat(False, "FOO", "well_characterized", 5, 0, ["x"]) is None
    assert RUN._mechanism_confirmation_caveat(None, "FOO", "sparse", 0, 0, []) is None


def test_myc_pleiotropic_hub_is_sharp_context_free():
    """MYC/COADREAD: has_actionable_moa=True off a rich curated network, NOT in the precedent set →
    the SHARP context-free caveat (looks-actionable-but-UNVALIDATED). The driver over-call."""
    c = RUN._mechanism_confirmation_caveat(
        True,
        "MYC",
        "well_characterized",
        195,
        0,
        ["upstream_kinase_modulation", "upstream_transcriptional_activator", "molecular_glue_disruptor"],
    )
    assert c is not None
    assert c["reason"] == "actionable_moa_curated_context_free_unvalidated"
    assert "single-source" in c["curated_provenance"]  # high_conf_edges=0 → single-source note
    assert "UNVALIDATED" in c["note"] and "tractability-small-molecule" in c["note"]


def test_mtap_thin_network_is_sharp_thin_variant():
    """MTAP/PAAD: has_actionable_moa=True off a THIN (partial) network, NOT precedented → the sharp caveat
    with the _thin_network flavour (even the curated network is thin)."""
    c = RUN._mechanism_confirmation_caveat(True, "MTAP", "partial", 2, 0, ["upstream_transcriptional_activator"])
    assert c["reason"] == "actionable_moa_curated_context_free_unvalidated_thin_network"
    assert "THIN" in c["note"]


def test_braf_precedented_is_spared_false_demote_guard():
    """BRAF/COADREAD: has_actionable_moa=True AND BRAF has an approved directly-acting agent → the milder
    clinically_precedented tier (NOT flagged as inflated). The false-demote guard (BRAF/DLL3 analog)."""
    c = RUN._mechanism_confirmation_caveat(True, "BRAF", "well_characterized", 22, 0, ["upstream_kinase_modulation"])
    assert c["reason"] == "actionable_moa_curated_clinically_precedented"
    assert "NOT" in c["note"] and "over-call" in c["note"]


def test_precedent_guard_is_case_insensitive():
    assert (
        RUN._mechanism_confirmation_caveat(True, "egfr", "well_characterized", 147, 4, ["x"])["reason"]
        == "actionable_moa_curated_clinically_precedented"
    )


def test_no_target_defaults_to_sharp():
    """Composed-facet path (target=None) has no symbol for the guard → the honest sharp default, never a
    silent spare."""
    c = RUN._mechanism_confirmation_caveat(True, None, "well_characterized", 10, 2, ["x"])
    assert c["reason"] == "actionable_moa_curated_context_free_unvalidated"
    assert "2 of 10" in c["curated_provenance"]  # multi-source provenance string


# ── prediction_lane_caveat ───────────────────────────────────────────────────────────────────────────
def test_prediction_lane_fires_on_kinome_and_coessentiality():
    """BRAF-like: a large kinome-atlas prediction lane + a co-essentiality lane are carried alongside but
    never merged into network_class/has_actionable_moa → the caveat names both."""
    c = RUN._prediction_lane_caveat(
        {
            "network_class": "well_characterized",
            "n_upstream_predicted_kinases": 737,
            "n_downstream_predicted_substrates": 4702,
        },
        {"data_available": True, "n_partners": 18},
    )
    assert c is not None and c["reason"] == "prediction_lanes_carried_alongside"
    assert len(c["lanes"]) == 2
    assert "737" in c["note"] and "NEVER merged" in c["note"]


def test_prediction_lane_none_when_no_lane():
    """No kinome prediction (data_unavailable) + no co-essentiality → None (byte-stable)."""
    assert (
        RUN._prediction_lane_caveat(
            {
                "network_class": "data_unavailable",
                "n_upstream_predicted_kinases": 0,
                "n_downstream_predicted_substrates": 0,
            },
            {"data_available": False, "n_partners": 0},
        )
        is None
    )


def test_prediction_lane_coessentiality_only():
    c = RUN._prediction_lane_caveat({"network_class": "data_unavailable"}, {"data_available": True, "n_partners": 4})
    assert c is not None and len(c["lanes"]) == 1 and "co-essentiality" in c["lanes"][0]


# ── curation_gap_note ─────────────────────────────────────────────────────────────────────────────────
def test_curation_gap_fires_on_thin_network_with_operative_signal():
    """MTAP-like: thin (partial) curated network but a functional co-essentiality signal + drug-perturbation
    engagement → the curated network under-reads an operative mechanism."""
    c = RUN._curation_gap_note("partial", "not_phosphoprotein", None, "drug_suppressed", 4)
    assert c is not None and c["reason"] == "curated_network_under_reads_operative_signal"
    assert "co-essential" in c["note"]


def test_curation_gap_none_when_network_rich():
    """A well_characterized network is not a curation gap regardless of activity."""
    assert (
        RUN._curation_gap_note("well_characterized", "phospho_active", "relatively_high", "drug_suppressed", 20) is None
    )


def test_curation_gap_none_when_thin_but_no_operative_signal():
    assert RUN._curation_gap_note("sparse", "data_unavailable", None, "not_measured", 0) is None


# ── prediction_lane_caveat MATERIALITY gate (v1.10.0) ──────────────────────────────────────────────────
def test_prediction_lane_materiality_silences_curated_dominant_hub():
    """MYC/TP53-like: non-curated lanes (443) < curated network (1105) → silenced (curated dominates)."""
    assert (
        RUN._prediction_lane_caveat(
            {
                "network_class": "well_characterized",
                "n_upstream_predicted_kinases": 418,
                "n_downstream_predicted_substrates": 0,
            },
            {"data_available": True, "n_partners": 25},
            curated_edge_count=1105,
        )
        is None
    )


def test_prediction_lane_materiality_fires_when_prediction_dominant():
    """BRAF-like: non-curated (5457) dwarfs curated (33) → fires (could inflate apparent richness)."""
    c = RUN._prediction_lane_caveat(
        {
            "network_class": "well_characterized",
            "n_upstream_predicted_kinases": 737,
            "n_downstream_predicted_substrates": 4702,
        },
        {"data_available": True, "n_partners": 18},
        curated_edge_count=33,
    )
    assert c is not None and c["reason"] == "prediction_lanes_carried_alongside"


def test_prediction_lane_fires_when_curated_empty():
    c = RUN._prediction_lane_caveat(
        {
            "network_class": "well_characterized",
            "n_upstream_predicted_kinases": 12,
            "n_downstream_predicted_substrates": 0,
        },
        {"data_available": False, "n_partners": 0},
        curated_edge_count=0,
    )
    assert c is not None


def test_prediction_lane_legacy_2arg_still_fires():
    """Backward-compat: the 2-arg call (no materiality gate) fires as before."""
    assert (
        RUN._prediction_lane_caveat(
            {"network_class": "well_characterized", "n_upstream_predicted_kinases": 5},
            {"data_available": False, "n_partners": 0},
        )
        is not None
    )


# ── precedent set is a frozenset of the panel positive controls ────────────────────────────────────────
def test_precedent_set_covers_panel_positive_controls():
    for g in ("BRAF", "EGFR", "FGFR2"):
        assert g in RUN._VALIDATED_ACTIONABLE_MOA_PRECEDENT
    for g in ("MYC", "MTAP"):
        assert g not in RUN._VALIDATED_ACTIONABLE_MOA_PRECEDENT
