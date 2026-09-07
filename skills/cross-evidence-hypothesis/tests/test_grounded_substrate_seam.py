"""SEAM test: the grounded-substrate PRODUCE -> CONSUME contract across skills.

The grounded-substrate two-projection design rests on ONE invariant: the per-subskill grounded
substrate produced by literature-risk-assessment (`ground_axis.build_grounded_block`) is consumed
UNCHANGED by BOTH downstream projections, so they "cannot silently disagree." The hypothesis
consumer's ingest is `hypothesis_core.parse_grounded_substrate`. Nothing pinned that the PRODUCER's
output shape actually matches what the CONSUMER expects — each skill only tests its own half.

This test drives real producer output through the real consumer (offline, no Bedrock, no network)
and asserts the shape holds end-to-end: findings, cited PMIDs (which become CITABLE), the
anchor_verdict, and the engine<->literature discordance flag all survive the hand-off. It also
guards that the `severity` field added to findings is TOLERATED by the consumer (the
hypothesis ignores it; it is a risk_rollup concern) rather than breaking the parse.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SKILLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_SKILLS / "cross-evidence-hypothesis" / "scripts"))
sys.path.insert(0, str(_SKILLS / "literature-risk-assessment" / "scripts"))

import ground_axis as ga  # noqa: E402  (PRODUCER)
import hypothesis_core as hc  # noqa: E402  (CONSUMER)


def _produce(axis_verdict: str, llm_out: dict, retrieved: set) -> dict:
    """Build a real ground_axis record {axis, deterministic, grounded} the way ground_axis() does."""
    det = {"verdict": axis_verdict, "driving_rule_id": "r", "cards": {}}
    grounded = ga.build_grounded_block(
        det, llm_out, retrieved, corpus_pin={"mindate": "2015", "maxdate": "2026"}, n_retrieved=len(retrieved)
    )
    return {"axis": "safety", "deterministic": det, "grounded": grounded}


def test_producer_output_parses_through_consumer_full_record():
    # a producer record with a severity-graded finding + a confabulated PMID (dropped by the producer)
    llm_out = {
        "findings": [
            {
                "finding": "on-target ocular toxicity in normal retina",
                "kind": "tox",
                "severity": "high",
                "cited_pmids": ["111", "999"],
            }
        ],
        "corroborations": ["consistent with GTEx retinal expression"],
        "contradicts_deterministic": True,
        "notes": "",
    }
    rec = _produce("wt_constraint_mechanism_mismatch", llm_out, retrieved={"111"})

    # the producer already contained confabulation: 999 was not retrieved -> dropped
    assert rec["grounded"]["confabulated_dropped"] == ["999"]
    assert rec["grounded"]["findings"][0]["severity"] == "high"  # severity field present on the producer side

    parsed = hc.parse_grounded_substrate({"safety": rec})
    assert parsed["present"] is True and parsed["n_findings"] == 1
    ax = parsed["per_axis"][0]
    assert ax["axis"] == "safety"
    assert ax["anchor_verdict"] == "wt_constraint_mechanism_mismatch"
    # the CITABLE set: only the retrieved-and-cited PMID survives the seam (confab already stripped)
    assert parsed["pmids"] == {"111"}
    assert ax["findings"][0]["cited_pmids"] == ["111"]
    # engine<->literature discordance survives the hand-off
    assert parsed["discordant_axes"] == ["safety"]
    assert ax["contradicts_deterministic"] is True
    # escalate-only is carried through (the consumer defaults it True even if absent)
    assert ax["escalate_only"] is True


def test_consumer_tolerates_severity_field_and_bare_record():
    # bare grounded block (no {axis, deterministic} wrapper) must also parse (tolerant shape)
    bare = ga.build_grounded_block(
        {"verdict": "human_genetics_safety_concern"},
        {
            "findings": [
                {
                    "finding": "germline LoF intolerance",
                    "kind": "genetics",
                    "severity": "moderate",
                    "cited_pmids": ["222"],
                }
            ],
            "corroborations": [],
            "contradicts_deterministic": False,
            "notes": "",
        },
        {"222"},
        corpus_pin={},
        n_retrieved=1,
    )
    parsed = hc.parse_grounded_substrate({"safety": bare})
    assert parsed["present"] is True and parsed["pmids"] == {"222"}
    # the consumer does not choke on the severity key it doesn't use
    assert parsed["per_axis"][0]["findings"][0]["kind"] == "genetics"
    assert parsed["discordant_axes"] == []


def test_empty_and_absent_substrate_are_safe():
    assert hc.parse_grounded_substrate(None)["present"] is False
    assert hc.parse_grounded_substrate({})["present"] is False
    # a producer record with zero findings parses to present-but-empty
    empty = _produce(
        "tolerant_reduced_safety_risk",
        {"findings": [], "corroborations": [], "contradicts_deterministic": False, "notes": ""},
        retrieved=set(),
    )
    parsed = hc.parse_grounded_substrate({"safety": empty})
    assert parsed["present"] is True and parsed["n_findings"] == 0 and parsed["pmids"] == set()
