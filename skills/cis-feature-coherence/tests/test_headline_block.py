"""The canonical HEADLINE block (verdict + confidence + top-tension) rides the cis-feature-coherence
decision — a verdict-INERT projection over the already-computed cis-coherence headline (mirrors the
tumor-presence exemplar). This skill has no frozen S3 fixture, so the test drives the REAL `_headline`
(the same headline surface the dispatcher calls) with synthetic per-card summaries and a resolved
verdict pair, then asserts the headline_block is present, non-degraded, and internally consistent with
the cis-coherence spine.

A coherent_cis_driver call (CN → expression → dependency) is the one clearly FAVORABLE coherence class,
so — this skill being VERDICT-INERT / coherence-classifying — that verdict must colour the badge polarity
`positive` while every other class stays `neutral`.
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILL_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SKILL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SKILL_SCRIPTS))

from run import _headline, _cis_coherence_verdict_polarity  # noqa: E402

_VALID_CONFIDENCE = {"strong", "moderate", "weak", "insufficient"}
_AXIS_KEYS = ["CIS_DOSAGE", "SILENCING", "EXPR_DEP", "CONJOINT"]


def _cards():
    """Synthetic per-card summaries exercising a COHERENT cis-driver: CN → expression (cis-dosage coupled),
    expression → dependency (strong correlation), amp∩overexpr conjoint addiction, silencing uncoupled,
    and a TCGA patient arm that AGREES with the cell-line cis-dosage call."""
    return [
        {"card_id": "cis-feature-expression-coherence",
         "summary": {"cis_dosage_class": "cn_dosage_coupled_strong", "cn_expr_spearman_r": 0.62,
                     "cn_expr_spearman_p": 1e-6, "n_amplified": 40, "n_cell_lines_evaluated": 120}},
        {"card_id": "cellline-methylation-expression-coherence",
         "summary": {"methylation_silencing_class": "methylation_uncoupled", "n_hypermethylated": 3}},
        {"card_id": "expression-dependency-correlation",
         "summary": {"correlation_class": "strong_negative", "pearson_r": -0.55,
                     "n_cell_lines_evaluated": 118}},
        {"card_id": "amp-expr-stratified-dependency",
         "summary": {"amp_expr_stratification_class": "amplified_overexpressed_strongly_dependent",
                     "delta_chronos_amp_expr_vs_rest": -0.6, "n_amplified_overexpressed": 22}},
        {"card_id": "patient-cis-coherence",
         "summary": {"patient_cis_dosage_class": "cn_dosage_coupled_strong", "n_cases_expression": 300}},
        {"card_id": "cellline-isoform-dominance", "summary": {}},
        {"card_id": "cellline-isoform-expression", "summary": {}},
    ]


def test_headline_block_present_and_consistent_for_coherent_cis_driver():
    verdict_pair = ("coherent_cis_driver", "cis-dosage-coupled-supportive")
    hl = _headline(_cards(), [], verdict_pair)

    # the spine the headline projects over is untouched (byte-additive: no degrade key on the happy path)
    assert hl.get("cis_coherence_verdict") == "coherent_cis_driver"
    assert "headline_block" not in (hl.get("_enrichment_errors") or {}), (
        f"headline_block DEGRADED: {(hl.get('_enrichment_errors') or {}).get('headline_block')}")

    block = hl.get("headline_block")
    assert isinstance(block, dict), "headline_block missing or not a dict (degraded projection)"

    # verdict.call == the skill's cis_coherence_verdict; the canonical spelling carries gate + polarity
    verdict = block.get("verdict") or {}
    assert verdict.get("call") == "coherent_cis_driver"
    assert verdict.get("gate") == "cis_coherence"

    # confidence.level valid
    assert (block.get("confidence") or {}).get("level") in _VALID_CONFIDENCE

    # hero lists the four coherence-leg axes, in order
    hero = block.get("hero") or {}
    assert [a.get("key") for a in (hero.get("axes") or [])] == _AXIS_KEYS

    # a coherent cis-driven addiction is the one clearly FAVORABLE coherence class → positive badge
    assert verdict.get("polarity") == "positive", (
        f"a coherent_cis_driver call must colour the badge positive; got {verdict.get('polarity')!r}")

    # deterministic headline text is always available
    assert isinstance(block.get("headline_text"), str) and block["headline_text"]


def test_verdict_inert_polarity_defaults_neutral():
    """Every coherence class OTHER than coherent_cis_driver is a verdict-inert classification with no
    directional drug call → neutral badge."""
    for v in ("expressed_cis_coupled_inert", "dependency_without_cis_dosage",
              "cis_uncoupled_no_dependency", "insufficient_cis_coherence"):
        assert _cis_coherence_verdict_polarity(v) == "neutral"
    assert _cis_coherence_verdict_polarity("coherent_cis_driver") == "positive"
