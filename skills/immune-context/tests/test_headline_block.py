"""The canonical HEADLINE block (verdict + confidence + top-tension) rides the immune-context decision —
a verdict-INERT projection over the already-computed effector-context headline (mirrors the tumor-presence
exemplar). immune-context is GATELESS + single-axis (IMMUNE), and its verdict is a direct read of the
CIBERSORT-derived immune_context_class, so this drives _headline directly with a synthetic immune-context
card (no S3 / no fixture needed) and asserts the headline_block is present, non-degraded, and internally
consistent with the effector-context spine.

An immune-HOT indication is a CD8 effector context PRESENT for a TCE to redirect → the badge polarity is
`positive`, the discriminating polarity check for this skill.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

RUN = Path(__file__).resolve().parent.parent / "scripts" / "run.py"
SKILLS_DIR = RUN.resolve().parent.parent.parent

_VALID_CONFIDENCE = {"strong", "moderate", "weak", "insufficient"}


def _load():
    if str(SKILLS_DIR) not in sys.path:
        sys.path.insert(0, str(SKILLS_DIR))
    spec = importlib.util.spec_from_file_location("ic_run_hl", RUN)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ic = _load()


def _immune_hot_cards():
    """A synthetic immune-context card summarising an immune-HOT indication (CIBERSORT LM22)."""
    return [{
        "card_id": "immune-context",
        "summary": {
            "immune_context_class": "immune_hot",
            "median_cd8_fraction": 0.21,
            "median_total_t_cell_fraction": 0.38,
            "n_samples": 512,
            "tumor_studies": ["TCGA-SKCM"],
        },
    }, {
        # Saltz H&E-DL TIL corroborator (verdict-inert; _headline reads it via strict get_card_field).
        "card_id": "tcga-til-fraction-saltz",
        "summary": {"til_fraction_class": "til_high", "median_til_percentage": 5.6, "n_samples": 384},
    }]


def test_headline_block_present_and_consistent_for_immune_hot():
    """An immune-HOT effector-context call: the headline_block is present, non-degraded, its canonical
    verdict.call equals the skill's immune_context_verdict, confidence.level is valid, the hero lists the
    single IMMUNE axis, and — a CD8 effector context present is TCE-favourable — the badge is `positive`."""
    cards = _immune_hot_cards()
    verdict_pair = ic._verdict([{"rule_id": "immune-context-hot-tce-supportive"}])
    assert verdict_pair == ("immune_hot", "immune-context-hot-tce-supportive")

    hl = ic._headline(cards, [], verdict_pair)

    # spine the headline projects over
    assert hl.get("immune_context_verdict") == "immune_hot"
    assert "headline_block" not in (hl.get("_enrichment_errors") or {}), (
        f"headline_block DEGRADED: {(hl.get('_enrichment_errors') or {}).get('headline_block')}")

    block = hl.get("headline_block")
    assert isinstance(block, dict), "headline_block missing or not a dict (degraded projection)"

    # verdict.call == the skill's verdict; the canonical spelling carries gate + polarity
    verdict = block.get("verdict") or {}
    assert verdict.get("call") == "immune_hot"
    assert verdict.get("gate") == "immune_context"

    # confidence.level valid
    assert (block.get("confidence") or {}).get("level") in _VALID_CONFIDENCE

    # hero lists the single IMMUNE effector axis
    hero = block.get("hero") or {}
    assert [a.get("key") for a in (hero.get("axes") or [])] == ["IMMUNE"]

    # a CD8 effector context PRESENT is TCE-favourable → positive badge
    assert verdict.get("polarity") == "positive", (
        f"an immune-hot effector context must colour the badge positive; got {verdict.get('polarity')!r}")

    # deterministic headline text is always available
    assert isinstance(block.get("headline_text"), str) and block["headline_text"]


def test_immune_cold_is_negative_with_efficacy_risk_tension():
    """An immune-COLD indication: the effector-absence call colours the badge `negative` and surfaces the
    TCE-efficacy-risk tension (a MEASURED CD8 effector-absence, NOT a target veto)."""
    cards = [{"card_id": "immune-context",
              "summary": {"immune_context_class": "immune_cold", "median_cd8_fraction": 0.01,
                          "median_total_t_cell_fraction": 0.04, "n_samples": 300}},
             {"card_id": "tcga-til-fraction-saltz",
              "summary": {"til_fraction_class": "til_low", "median_til_percentage": 1.1, "n_samples": 300}}]
    verdict_pair = ic._verdict([{"rule_id": "immune-context-cold-tce-opposing"}])
    hl = ic._headline(cards, [], verdict_pair)
    block = hl["headline_block"]
    assert block["verdict"]["call"] == "immune_cold"
    assert block["verdict"]["polarity"] == "negative"
    tension = block.get("top_tension") or {}
    assert "efficacy" in (tension.get("text") or "").lower()


def test_immune_hot_discordant_with_absolute_til_is_neutral_not_positive():
    """PRAD-like: CIBERSORT calls it immune_hot (CD8 SHARE >= pan-cancer Q3) but the orthogonal absolute
    H&E-DL TIL (Saltz) is til_low → til_cibersort_agreement is False. The confident 'TCE-favourable' badge
    over-reads (relatively CD8-rich but absolutely T-cell-sparse), so the badge is DEMOTED to neutral, a
    severity-3 discordance tension is surfaced, and the key_signals headline+caveat carry the disagreement.
    The immune_context_verdict TOKEN stays immune_hot (an honest RELATIVE call) — verdict-inert."""
    cards = [{"card_id": "immune-context",
              "summary": {"immune_context_class": "immune_hot", "median_cd8_fraction": 0.13,
                          "median_total_t_cell_fraction": 0.3, "n_samples": 558}},
             {"card_id": "tcga-til-fraction-saltz",
              "summary": {"til_fraction_class": "til_low", "median_til_percentage": 1.5, "n_samples": 332}}]
    hl = ic._headline(cards, [], ic._verdict([{"rule_id": "immune-context-hot-tce-supportive"}]))
    # the spine TOKEN is unchanged (honest relative call)
    assert hl["immune_context_verdict"] == "immune_hot"
    assert hl["til_cibersort_agreement"] is False
    block = hl["headline_block"]
    assert block["verdict"]["call"] == "immune_hot"          # token unchanged
    assert block["verdict"]["polarity"] == "neutral"          # badge demoted (was positive)
    tension = block.get("top_tension") or {}
    assert tension.get("source") == "til_cibersort_agreement"
    assert "disagree" in (tension.get("text") or "").lower()
    assert (hl["key_signals"].get("caveat") or "")             # discordance caveat present
    assert "disagree" in hl["key_signals"]["caveat"].lower()
