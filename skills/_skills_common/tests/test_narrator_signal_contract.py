"""Narrator-input CONTRACT (v1) — signals_first.render_narrator_signals.

The narrator's leading SIGNAL block is derived SOLELY from a declared slice of the deterministic
headline (subgroup_signals PRIMARY, question_table, claim_vector FALLBACK), so any skill that
populates those keys is narrated with no per-builder edit. Deterministic (prompt-string) assertions —
no Bedrock. Verdict-INERT: the renderer reads the headline, never writes it.
"""

from __future__ import annotations

from _skills_common.signals_first import render_narrator_signals, render_signal_summary  # noqa: E402


def _subgroup_headline():
    return {
        "subgroup_signals": {
            "abundance": {
                "signal": "strong",
                "confidence": "high",
                "n_sources": 3,
                "n_agree": 3,
                "power": "high",
                "conflict": False,
                "sources": [
                    {
                        "card": "cellline-rna-distribution",
                        "tier": "strong",
                        "n": 1400,
                        "label": "cell-line RNA",
                        "conflict": False,
                        "value": "broadly_high",
                    }
                ],
            },
            "tumor_elevation": {
                "signal": "weak",
                "confidence": "low",
                "n_sources": 2,
                "n_agree": 0,
                "power": "moderate",
                "conflict": True,
                "sources": [
                    {
                        "card": "tumor-rna-vs-adjacent",
                        "tier": "weak",
                        "n": 90,
                        "label": "tumor vs adjacent",
                        "conflict": True,
                        "value": "flat",
                    }
                ],
            },
        },
    }


def _claim_only_headline():
    return {
        "claim_vector": {
            "A": {"signal": "strong", "corroboration": "high", "evidence": "99.7th all-gene pct"},
            "B": {"signal": "absent", "corroboration": "moderate", "evidence": "DGE flat"},
        }
    }


# 1. subgroup_signals is the PRIMARY lead + structural directive
def test_subgroup_signals_lead_and_directive():
    p = render_narrator_signals(_subgroup_headline())
    assert "SUB-GROUP SIGNALS" in p
    assert "abundance: signal=strong confidence=high" in p
    assert "tumor_elevation: signal=weak confidence=low" in p
    assert "3/3 sources agree" in p and "0/2 sources agree" in p
    assert "CONFLICT" in p  # tumor_elevation conflict surfaced
    assert "cell-line RNA: strong" in p  # binding source rendered
    assert "LEAD with the sub-group signals" in p  # structural directive, not the fallback one


# 2. no subgroup_signals → the claim vector becomes the SIGNAL VECTOR fallback lead
def test_fallback_to_claim_vector_when_no_subgroups():
    p = render_narrator_signals(_claim_only_headline(), axis_labels={"A": "abundance", "B": "tumor-elevation"})
    assert "SUB-GROUP SIGNALS" not in p
    assert "SIGNAL VECTOR (per-axis claim vector" in p  # literal 'SIGNAL VECTOR' retained for the fallback lead
    assert "A abundance: signal=strong corroboration=high" in p
    assert "claim corroboration tiers" in p  # fallback directive


# 3. structural present → claim vector demoted to supporting PER-AXIS EVIDENCE (not the lead)
def test_claim_vector_demoted_when_structural_present():
    h = _subgroup_headline()
    h["claim_vector"] = _claim_only_headline()["claim_vector"]
    p = render_narrator_signals(h)
    assert "PER-AXIS EVIDENCE (claim vector" in p
    assert p.index("SUB-GROUP SIGNALS") < p.index("PER-AXIS EVIDENCE")


# 4. question_table decomposition rendered
def test_question_table_rendered():
    h = {
        "question_table": [
            {
                "id": "Q1",
                "question": "Expressed in cancers at all?",
                "primary": "99th pct",
                "signal": {"tier": "strong"},
                "confidence": {"tier": "high"},
            },
            {"id": "Q3", "question": "Elevated vs normals?", "primary": "flat", "signal": "weak", "confidence": "low"},
        ]
    }
    p = render_narrator_signals(h)
    assert "PER-QUESTION DECOMPOSITION" in p
    assert "Q1 Expressed in cancers at all?: signal=strong confidence=high" in p
    assert "Q3 Elevated vs normals?: signal=weak confidence=low" in p  # bare-tier cell shape tolerated


# 5. first-class subtype by_stratum surfaced under its sub-group
def test_by_stratum_rendered():
    h = _subgroup_headline()
    h["subgroup_signals"]["abundance"]["by_stratum"] = {
        "MSI_H": {"signal": "strong", "certainty": "high", "n": 60},
        "MSS": {"signal": "moderate", "certainty": "moderate", "n": 300},
    }
    h["subgroup_signals"]["abundance"]["subtype_axis"] = {
        "stratification_class": "concentrated",
        "epsilon_squared": 0.12,
    }
    p = render_narrator_signals(h)
    assert "by stratum" in p and "ORTHOGONAL conditioner" in p
    assert "MSI_H: signal=strong certainty=high (n=60)" in p
    assert "ε²=0.12" in p


# 6. degrade cleanly on empty / None headline — never raise
def test_empty_headline_degrades():
    assert "not present in this decision" in render_narrator_signals({})
    assert "not present in this decision" in render_narrator_signals(None)


# 7. extra_directive is appended
def test_extra_directive_appended():
    p = render_narrator_signals(_subgroup_headline(), extra_directive="PRESENCE RULE: foo bar.")
    assert "PRESENCE RULE: foo bar." in p


# 8. generic over ANY skill's sub_group names — the contract is not presence-specific
def test_generic_subgroup_names():
    h = {
        "subgroup_signals": {
            "dependency_strength": {
                "signal": "strong",
                "confidence": "high",
                "n_sources": 2,
                "n_agree": 2,
                "power": "high",
                "conflict": False,
                "sources": [],
            }
        }
    }
    p = render_narrator_signals(h)
    assert "dependency_strength: signal=strong confidence=high" in p


# render_signal_summary — SECTION-context content (no lead/directive framing) for the composed facet
def test_signal_summary_is_section_register_no_lead_no_directive():
    p = render_signal_summary(_subgroup_headline())
    assert "SUB-GROUP SIGNALS" in p
    assert "abundance: signal=strong confidence=high" in p
    assert "LEAD your narration" not in p  # section register, not the single-lens lead framing
    assert "DIRECTIVE" not in p  # no confidence directive in a facet section
    # question_table also rendered
    h = _subgroup_headline()
    h["question_table"] = [
        {"id": "Q1", "question": "Expressed?", "signal": {"tier": "strong"}, "confidence": {"tier": "high"}}
    ]
    assert "PER-QUESTION DECOMPOSITION" in render_signal_summary(h)


def test_signal_summary_empty_when_no_structural_signals():
    # a headline with only a claim_vector (no subgroup_signals/question_table) yields '' — the composed
    # facet renders nothing rather than duplicating the claim vector it already surfaces elsewhere.
    assert render_signal_summary(_claim_only_headline()) == ""
    assert render_signal_summary({}) == ""
    assert render_signal_summary(None) == ""
