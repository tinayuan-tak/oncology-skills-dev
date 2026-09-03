"""Synthetic nomination fixtures matching the documented spine shapes (docs/UNIFIED_OUTPUT_CONTRACT.md).

Shipped in-package (rather than under tests/) so the CI-collected suite in _skills_common/tests/ can
import it. Two builders: a fully-populated nomination (exercises every block kind) and a null-heavy one
(the fail-soft stressor — empty/None slots, a gateless call=None skill). Pure data; no imports.
"""
from __future__ import annotations


def _skill(*, call, role, polarity, honest_phrase="phrase", with_evidence=False,
           confidence=None, tension=None):
    r = {
        "call": call,
        "role": role,
        "polarity": polarity,
        "honest_phrase": honest_phrase,
        "confidence": confidence,
        "top_tension": tension,
        "claim_chips": [],
        "question_table": [],
        "per_phase_metrics": [],
        "figures": [],
        "provenance": {"driving_rule_id": None, "fired_rule_ids": [],
                       "cards_used": [], "cards_missing": []},
        "_contract": "docs/UNIFIED_OUTPUT_CONTRACT.md",
    }
    if with_evidence:
        r["confidence"] = confidence or {"level": "moderate", "basis": "2 concordant assays",
                                         "coverage": "3/4 cards"}
        r["claim_chips"] = [
            {"key": "A", "label": "constraint", "signal": "supportive",
             "corroboration": "high", "conflict": None, "evidence": "pLI 0.99",
             "cites": [{"role": "signal", "card_id": "gnomad-constraint"}], "cite": {"card_id": "gnomad-constraint"}},
            {"key": "B", "label": "burden", "signal": "opposing", "corroboration": "weak",
             "conflict": None, "evidence": "no burden signal",
             "cites": [{"role": "signal", "card_id": "ot-burden"}], "cite": {"card_id": "ot-burden"}},
        ]
        r["question_table"] = [
            {"question": "LoF-constrained?", "signal": "yes", "confidence": "high"},
            {"question": "population burden?", "signal": "none", "confidence": "moderate"},
        ]
        r["per_phase_metrics"] = [
            {"metric": "pLI", "value": 0.99, "sample_context": "gnomAD v4 (n=807k)"},
        ]
        r["figures"] = [
            {"slot": "hero", "kind": "hero_svg", "path": "figures/safety_hero.svg",
             "caption": "gnomAD constraint vs tolerance percentile"},
        ]
        r["provenance"] = {"driving_rule_id": "SAF-LOF-01",
                           "fired_rule_ids": ["SAF-LOF-01", "SAF-DOSAGE-02"],
                           "cards_used": ["gnomad-constraint", "ot-burden"],
                           "cards_missing": ["clinvar-path"]}
    return r


def make_nomination() -> dict:
    """A populated nomination — one killer gating skill (full evidence), one supportive gating skill,
    one gateless descriptive skill (call=None)."""
    return {
        "target": "USP8",
        "indication": "COADREAD",
        "target_report": {
            "schema": "target_report.v1",
            "skill_reports": {
                # NOTE: emit order intentionally NOT role-first, so ordering logic is exercised.
                "dependency": _skill(call="genetic_dependency", role="gating", polarity="supportive",
                                     honest_phrase="Selective dependency in MSI-high lines",
                                     with_evidence=True),
                "safety": _skill(call="lof_constrained", role="gating", polarity="killer",
                                 honest_phrase="Highly LoF-constrained — full-KO risk",
                                 with_evidence=True,
                                 tension={"text": "constraint vs tumor selectivity",
                                          "source": "safety", "severity": "high"}),
                "target_intrinsic": _skill(call=None, role="descriptive", polarity="not_scored",
                                           honest_phrase="Deubiquitinase; druggable pocket present"),
            },
            "target_call": {
                "schema": "target_call.v1",
                "recommendation": "hold",
                "confidence": {"level": "moderate", "basis": "killer safety vs supportive dependency"},
                "deciding_axis": {"short": "safety", "basis": "gate_fired"},
                "dissent": [{"source": "dependency", "detail": "supportive signal overruled by safety",
                             "resolved_to": "hold"}],
                "gate": {"recommendation_gate": "hold"},
            },
            "skill_report_rollup": {
                "by_role": {"gating": [{"short": "safety", "call": "lof_constrained", "polarity": "killer"},
                                       {"short": "dependency", "call": "genetic_dependency",
                                        "polarity": "supportive"}]},
                "killer_axes": ["safety"], "recommendation": "hold",
            },
        },
    }


def make_decision_json(skill_name: str = "on-target-safety-liability", *, with_evidence: bool = True,
                       call: str = "lof_constrained", role: str = "gating",
                       polarity: str = "killer") -> dict:
    """A STANDALONE skill decision.json: skill_report lives at decision['headline']['skill_report']
    (the shared write_package path). Mirrors the real on-disk shape."""
    return {
        "skill": skill_name,
        "target": "USP8",
        "indication": "COADREAD",
        "headline": {
            "headline_text": "…",
            "skill_report": _skill(call=call, role=role, polarity=polarity,
                                   honest_phrase="Highly LoF-constrained — full-KO risk",
                                   with_evidence=with_evidence,
                                   tension=({"text": "constraint vs selectivity", "source": "safety",
                                             "severity": "high"} if with_evidence else None)),
        },
        "run_health": {"skill_name": skill_name, "status": "ok"},
    }


def make_null_heavy_nomination() -> dict:
    """The fail-soft stressor: gateless call=None, empty everything, a None honest_phrase."""
    return {
        "target": None,
        "indication": None,
        "target_report": {
            "schema": "target_report.v1",
            "skill_reports": {
                "combination_vulnerability": _skill(call=None, role="descriptive",
                                                    polarity="not_scored", honest_phrase=None),
                "cis_coherence": _skill(call=None, role="inert", polarity="not_scored",
                                        honest_phrase=None),
                # a gating skill with NOTHING — should surface unmeasured coverage at L2, never crash.
                "selectivity": _skill(call=None, role="gating", polarity=None, honest_phrase=None),
            },
            "target_call": {},  # no recommendation, no deciding axis, no dissent
        },
    }
