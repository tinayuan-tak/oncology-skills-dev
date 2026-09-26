"""SK#1514 — symmetric cross-platform protein-abundance concordance (`protein_platform_concordance`).

ProCan was added as an ORTHOGONAL 2nd cell-line protein platform whose own card values disagreement
("disagreement is a real assay/panel signal, not noise"), but the skill used it in ONE direction only —
an UPWARD rescue of a lone Gygi bottom-decile in `_abundance_floor`. A Gygi-HIGH / ProCan-LOW conflict
produced no datum anywhere. These pin the new SYMMETRIC facet computed off the two platforms' RAW all-gene
percentiles (the commensurate rank axis), including the previously-INVISIBLE Gygi-high/ProCan-low
direction, plus its verdict-inertness (the facet feeds no rule and touches no ladder).
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parent.parent, "tp_run")


def _fr(rule_id, card_id):
    return {"rule_id": rule_id, "card_id": card_id, "field": "x", "value": "y", "signals": {}}


def _cards(gygi_pct=None, procan_pct=None):
    """All declared cards with empty summaries, except the two cell-line protein platforms carry a raw
    `allgene_percentile` when supplied. `_headline` reads specific fields via get_card_field, which RAISES
    on a missing card_id but returns None for an absent key — so the full card list must be present."""
    out = []
    for cid in tp.CARDS:
        summary = {}
        if cid == "cellline-protein-abundance" and gygi_pct is not None:
            summary = {"allgene_percentile": gygi_pct}
        elif cid == "cellline-protein-abundance-procan" and procan_pct is not None:
            summary = {"allgene_percentile": procan_pct}
        out.append({"card_id": cid, "summary": summary})
    return out


# ── the helper, both directions + the neighbour/edge cases ──────────────────────────────────────────
def test_gygi_high_procan_low_is_the_previously_invisible_discordance():
    """THE GAP F1 CLOSES: a Gygi over-read (HIGH) the 2nd platform contradicts DOWNWARD (LOW) now yields
    an explicit token instead of nothing."""
    assert tp._protein_platform_concordance(_cards(gygi_pct=85.0, procan_pct=5.0)) == "discordant_gygi_high_procan_low"


def test_gygi_low_procan_high_is_the_surface_reanchor_direction_named():
    """The Gygi TMT surface-class under-read the #980 re-anchor already rescues upward (EPCAM: Gygi 8.6,
    ProCan 79.7) is now NAMED symmetrically."""
    assert tp._protein_platform_concordance(_cards(gygi_pct=8.6, procan_pct=79.7)) == "discordant_gygi_low_procan_high"


def test_genuinely_low_on_both_is_concordant_not_discordant():
    """FOLR1-shape: Gygi bottom-decile AND ProCan lower-mid (20.8) — the RAW percentile keeps this
    concordant-low, where the coarse `mid` class could not (both EPCAM and FOLR1 are `mid`)."""
    assert tp._protein_platform_concordance(_cards(gygi_pct=6.0, procan_pct=20.8)) == "concordant"


def test_both_high_is_concordant():
    assert tp._protein_platform_concordance(_cards(gygi_pct=88.0, procan_pct=72.0)) == "concordant"


def test_single_platform_when_only_one_reads_a_percentile():
    assert tp._protein_platform_concordance(_cards(gygi_pct=85.0, procan_pct=None)) == "single_platform"
    assert tp._protein_platform_concordance(_cards(gygi_pct=None, procan_pct=5.0)) == "single_platform"


def test_none_when_neither_platform_reads_a_percentile():
    assert tp._protein_platform_concordance(_cards(gygi_pct=None, procan_pct=None)) is None


def test_non_numeric_percentile_is_not_a_level():
    """A stringy/absent percentile (e.g. data_unavailable) must not be coerced to a level."""
    cards = _cards(gygi_pct=None, procan_pct=None)
    for c in cards:
        if c["card_id"] == "cellline-protein-abundance":
            c["summary"] = {"allgene_percentile": "data_unavailable"}
    assert tp._protein_platform_concordance(cards) is None


# ── emission through the real headline + verdict-inertness ───────────────────────────────────────────
def test_facet_is_emitted_into_the_headline_on_a_discordant_fixture():
    """End-to-end: a Gygi-high/ProCan-low discordance is now VISIBLE in the presence headline."""
    fired = [_fr("tumor-expression-broadly-high-supportive", "tumor-rna-distribution")]
    verdict_pair = tp._verdict(fired)
    hl = tp._headline(cards=_cards(gygi_pct=85.0, procan_pct=5.0), fired=fired, verdict_pair=verdict_pair)
    assert hl["protein_platform_concordance"] == "discordant_gygi_high_procan_low"
    # it also rides the synthesis facet the composed target-profile consumes
    assert "protein_platform_concordance" in tp._SYNTHESIS_FACET_KEYS


def test_facet_is_verdict_inert():
    """Surfacing the concordance must not move the spine: the collapsed verdict + driving rule are
    identical with a discordant, a concordant, and an absent protein-platform reading."""
    fired = [_fr("tumor-expression-broadly-high-supportive", "tumor-rna-distribution")]
    verdict_pair = tp._verdict(fired)
    verdicts = set()
    for gygi, procan in ((85.0, 5.0), (88.0, 72.0), (None, None)):
        hl = tp._headline(cards=_cards(gygi_pct=gygi, procan_pct=procan), fired=fired, verdict_pair=verdict_pair)
        verdicts.add((hl["presence_verdict"], hl["driving_rule_id"]))
    assert verdicts == {verdict_pair}, f"protein_platform_concordance moved the spine: {verdicts}"
