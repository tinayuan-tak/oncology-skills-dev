"""VERDICT-INERT bulk-CD8-fraction annotation-INFLATION surface (v1.6.0) — the immune-context analog of
surface-modality-fit's surface_confirmation_caveat and mechanism's mechanism_confirmation_caveat.

A bulk CIBERSORT LM22 CD8 FRACTION over-calls actual SPATIAL T-cell infiltration: it reports the SHARE
(relative, reference-model-dependent, non-spatial, function-blind), not the LOCALIZATION (inflamed
tumour-nest CD8 vs immune-EXCLUDED stroma/margin CD8 vs DESERT) or the FUNCTION (functional vs exhausted).
These tests pin the three-tier caveat + the spatial_localization_caveat + the immune_provenance quorum, and
assert the immune_context_verdict SPINE stays byte-stable (the skill is gateless; the verdict is a direct
read of immune_context_class — the enrichment is a one-way projection that NEVER moves it).

Live panel these fixtures mirror (2026-09-04 baseline reads):
  SKCM immune_hot + Saltz til_intermediate → orthogonally_corroborated (the false-demote guard spares the
    genuinely-inflamed, ICI-validated positive control) + presence!=function note;
  BLCA immune_intermediate + Saltz til_high → orthogonally_corroborated (density confirmed — but the
    spatial_localization_caveat still fires: the excluded-driver, IMvigor210 Mariathasan 2018);
  PRAD immune_hot + Saltz til_low → bulk_fraction_til_discordant (the sharpest catch: relative CD8-rich
    SHARE but low ABSOLUTE lymphocyte density);
  LIHC/KIRC + Saltz data_unavailable → bulk_fraction_spatially_unconfirmed (no orthogonal check);
  GBM immune_cold → None (byte-stable negative path).
"""
from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

ic = load_run_py(Path(__file__).resolve().parent.parent, "ic_run_caveat")


def _cards(immune_class, cd8, til_class=None, til_pct=None, til_n=None):
    ic_card = {"card_id": "immune-context",
               "summary": {"immune_context_class": immune_class, "median_cd8_fraction": cd8,
                           "median_total_t_cell_fraction": (cd8 or 0) * 2, "n_samples": 400,
                           "tumor_studies": ["TCGA-XXXX"]}}
    saltz = {"card_id": "tcga-til-fraction-saltz",
             "summary": {"til_fraction_class": til_class, "median_til_percentage": til_pct,
                         "n_samples": til_n}}
    return [ic_card, saltz]


def _hl(immune_class, cd8, rule_id, til_class=None, til_pct=None, til_n=None):
    return ic._headline(_cards(immune_class, cd8, til_class, til_pct, til_n), [], ic._verdict([{"rule_id": rule_id}]))


_HOT = "immune-context-hot-tce-supportive"
_INT = "immune-context-intermediate-tce-neutral"
_COLD = "immune-context-cold-tce-opposing"


# ── the three tiers ───────────────────────────────────────────────────────────────────────────────────
def test_skcm_hot_til_intermediate_is_orthogonally_corroborated_and_spared():
    """SKCM-like: immune_hot + absolute-TIL MEASURED (til_intermediate, non-contradicting) → the MILDER
    orthogonally_corroborated tier (the false-demote guard: a genuinely-inflamed, ICI-validated positive
    control is NOT sharp-flagged). The presence!=function note rides on the hot class."""
    hl = _hl("immune_hot", 0.154, _HOT, til_class="til_intermediate", til_pct=3.2, til_n=380)
    cav = hl["immune_confirmation_caveat"]
    assert cav and cav["reason"] == "orthogonally_corroborated", cav
    assert "not an over-call of density" in cav["detail"].lower()
    assert "presence != function" in cav["detail"].lower()   # hot class → exhaustion sub-note
    # spared: no alarming spatially-unconfirmed top-tension
    tension = (hl["headline_block"] or {}).get("top_tension") or {}
    assert tension.get("source") != "immune_confirmation_caveat"


def test_blca_intermediate_til_high_is_orthogonally_corroborated_but_localization_blind():
    """BLCA-like excluded driver: immune_intermediate + Saltz til_high → both DENSITY platforms agree
    (orthogonally_corroborated), yet the spatial_localization_caveat STILL fires — the decisive
    inflamed-vs-EXCLUDED distinction neither bulk platform can make (IMvigor210 Mariathasan 2018)."""
    hl = _hl("immune_intermediate", 0.110, _INT, til_class="til_high", til_pct=6.1, til_n=410)
    cav = hl["immune_confirmation_caveat"]
    assert cav["reason"] == "orthogonally_corroborated"
    assert "presence != function" not in cav["detail"].lower()   # not a hot class → no exhaustion sub-note
    assert hl["spatial_localization_caveat"] and "excluded" in hl["spatial_localization_caveat"].lower()


def test_prad_hot_til_low_is_bulk_fraction_til_discordant():
    """PRAD-like: CIBERSORT immune_hot (relative CD8-rich SHARE) but Saltz til_low (low ABSOLUTE lymphocyte
    density) → til_cibersort_agreement is False → the SHARPEST tier bulk_fraction_til_discordant."""
    hl = _hl("immune_hot", 0.131, _HOT, til_class="til_low", til_pct=1.4, til_n=330)
    assert hl["til_cibersort_agreement"] is False
    cav = hl["immune_confirmation_caveat"]
    assert cav["reason"] == "bulk_fraction_til_discordant"
    assert "over-calls" in cav["detail"].lower()


def test_lihc_intermediate_no_saltz_is_spatially_unconfirmed():
    """LIHC/KIRC-like: a positive bulk read with NO orthogonal absolute-TIL check (Saltz data_unavailable)
    → bulk_fraction_spatially_unconfirmed, and it FEEDS the headline top_tension (severity 2)."""
    hl = _hl("immune_intermediate", 0.107, _INT, til_class="data_unavailable")
    cav = hl["immune_confirmation_caveat"]
    assert cav["reason"] == "bulk_fraction_spatially_unconfirmed"
    assert "no orthogonal absolute-til" in cav["detail"].lower()
    tension = (hl["headline_block"] or {}).get("top_tension") or {}
    assert tension.get("source") == "immune_confirmation_caveat"


def test_kirc_hot_no_saltz_spatially_unconfirmed_with_exhaustion_note():
    """KIRC ccRCC paradox: immune_hot, Saltz data_unavailable → spatially_unconfirmed + presence!=function
    (the high-fraction-but-exhausted case, Şenbabaoğlu 2016)."""
    hl = _hl("immune_hot", 0.143, _HOT, til_class="data_unavailable")
    cav = hl["immune_confirmation_caveat"]
    assert cav["reason"] == "bulk_fraction_spatially_unconfirmed"
    assert "presence != function" in cav["detail"].lower()


# ── byte-stable negative paths ──────────────────────────────────────────────────────────────────────────
def test_immune_cold_caveat_is_none():
    """GBM-like immune_cold: a NEGATIVE read has no positive infiltration to over-call → caveat None,
    spatial_localization_caveat None (byte-stable negative path)."""
    hl = _hl("immune_cold", 0.041, _COLD, til_class="data_unavailable")
    assert hl["immune_confirmation_caveat"] is None
    assert hl["spatial_localization_caveat"] is None


def test_insufficient_caveat_is_none():
    """CHOL-like thin coverage → insufficient (no rule fired) → caveat None (never a false positive-read)."""
    hl = ic._headline(_cards("data_unavailable", None), [], ("insufficient", None))
    assert hl["immune_confirmation_caveat"] is None
    assert hl["spatial_localization_caveat"] is None


# ── the verdict spine is byte-stable across every path (gateless; enrichment is inert) ────────────────────
def test_verdict_spine_byte_stable_across_all_tiers():
    for cls, cd8, rule, til in [
        ("immune_hot", 0.154, _HOT, "til_intermediate"),
        ("immune_intermediate", 0.110, _INT, "til_high"),
        ("immune_hot", 0.131, _HOT, "til_low"),
        ("immune_intermediate", 0.107, _INT, "data_unavailable"),
        ("immune_cold", 0.041, _COLD, "data_unavailable"),
    ]:
        hl = _hl(cls, cd8, rule, til_class=til)
        expected = {"immune_hot": "immune_hot", "immune_intermediate": "immune_intermediate",
                    "immune_cold": "immune_cold"}[cls]
        assert hl["immune_context_verdict"] == expected   # verdict token unchanged by the enrichment


# ── immune_provenance quorum ─────────────────────────────────────────────────────────────────────────────
def test_immune_provenance_never_confirms_nest_infiltration():
    """confirmed_tumor_nest_infiltration is ALWAYS False (bulk deconvolution is never spatial), and the
    orthogonal_agreement reflects the Saltz corroboration state."""
    hl = _hl("immune_hot", 0.131, _HOT, til_class="til_low", til_pct=1.4)
    prov = hl["immune_provenance"]
    assert prov["confirmed_tumor_nest_infiltration"] is False
    assert prov["absolute_til_corroboration"]["orthogonal_agreement"] == "contradicts"
    assert prov["bulk_cibersort"]["immune_context_class"] == "immune_hot"

    hl2 = _hl("immune_intermediate", 0.107, _INT, til_class="data_unavailable")
    assert hl2["immune_provenance"]["absolute_til_corroboration"]["orthogonal_agreement"] == "unmeasured"

    # immune_hot + til_high → directional agreement True → "corroborates"
    hl3 = _hl("immune_hot", 0.21, _HOT, til_class="til_high", til_pct=6.1)
    assert hl3["til_cibersort_agreement"] is True
    assert hl3["immune_provenance"]["absolute_til_corroboration"]["orthogonal_agreement"] == "corroborates"

    # immune_intermediate + til_high → agreement is None (middle band) → "not_comparable" (measured, no
    # directional call) yet the caveat still SPARES it (orthogonally_corroborated)
    hl4 = _hl("immune_intermediate", 0.110, _INT, til_class="til_high", til_pct=6.1)
    assert hl4["immune_provenance"]["absolute_til_corroboration"]["orthogonal_agreement"] == "not_comparable"
    assert hl4["immune_confirmation_caveat"]["reason"] == "orthogonally_corroborated"
