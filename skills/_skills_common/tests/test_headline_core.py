"""Unit tests for the SHARED headline_core contract (skills/_skills_common/headline_core.py).

Pin the headline discipline independent of any one skill:
  * confidence is weakest-link over MEASURED corroboration, capped by conflict, floored by coverage;
  * a CERTAINTY_MODEL sidecar WINS over the derived confidence;
  * the top tension is the single highest-severity item (conflict on a strong claim > caveat);
  * the hero payload carries every declared axis (unmeasured axes included, as gaps);
  * headline_text is deterministic and mentions verdict + confidence + tension.
Pure — no S3, no card reads.
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]        # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.headline_core import (  # noqa: E402
    HeadlineSpec, build_headline, derive_confidence, rank_tension, headline_hero_plot_data)

SPEC = HeadlineSpec(
    gate="presence",
    axis_labels={"A": "abundance", "B": "tumor-elevation", "C": "malignant-intrinsic", "D": "generality"},
    axis_keys=("A", "B", "C", "D"),
    critical_axes=("A", "B", "C"),
    verdict_label=lambda v: {"present": "Present", "absent": "Absent"}.get(v, str(v)),
)


def _cv(a=("strong", "high", None), b=("moderate", "moderate", None),
        c=("strong", "high", None), d=("moderate", "moderate", None)):
    def cell(t):
        return {"signal": t[0], "corroboration": t[1], "conflict": t[2], "evidence": "x"}
    return {"A": cell(a), "B": cell(b), "C": cell(c), "D": cell(d)}


# ── confidence ────────────────────────────────────────────────────────────────────────────────────
def test_confidence_weakest_link():
    # weakest measured corroboration = low  → weak
    cv = _cv(a=("strong", "high", None), b=("moderate", "low", None), c=("strong", "high", None))
    conf = derive_confidence(cv, SPEC.axis_keys, SPEC.critical_axes)
    assert conf["level"] == "weak"
    assert conf["coverage"]["n_measured"] == 4


def test_confidence_conflict_caps_to_moderate():
    # all corroboration high (→ strong) BUT a conflict on B caps at moderate
    cv = _cv(a=("strong", "high", None), b=("moderate", "high", "RNA/protein disagree"),
             c=("strong", "high", None), d=("strong", "high", None))
    conf = derive_confidence(cv, SPEC.axis_keys, SPEC.critical_axes)
    assert conf["level"] == "moderate"
    assert "conflict" in conf["basis"]


def test_confidence_insufficient_when_no_critical_axis_measured():
    cv = _cv(a=("unmeasured", "unmeasured", None), b=("unmeasured", "unmeasured", None),
             c=("unmeasured", "unmeasured", None), d=("strong", "high", None))
    conf = derive_confidence(cv, SPEC.axis_keys, SPEC.critical_axes)
    assert conf["level"] == "insufficient"


def test_confidence_coverage_floor_caps_at_weak():
    # only 1 of 3 critical axes measured (< half) → capped at weak even with high corroboration
    cv = _cv(a=("strong", "high", None), b=("unmeasured", "unmeasured", None),
             c=("unmeasured", "unmeasured", None), d=("strong", "high", None))
    conf = derive_confidence(cv, SPEC.axis_keys, SPEC.critical_axes)
    assert conf["level"] == "weak"
    assert "coverage" in conf["basis"]


def test_certainty_sidecar_wins():
    cv = _cv(a=("strong", "low", None))  # would derive weak
    conf = derive_confidence(cv, SPEC.axis_keys, SPEC.critical_axes,
                             certainty={"certainty": {"level": "strong"}})
    assert conf["level"] == "strong"
    assert conf["basis"] == "certainty_model_sidecar"


# ── tension ─────────────────────────────────────────────────────────────────────────────────────
def test_tension_prefers_conflict_on_strong_claim_over_caveat():
    cv = _cv(a=("strong", "high", "abundance floor: bottom-decile"), b=("weak", "low", None))
    ks = {"caveat": "mid-tier abundance"}
    t = rank_tension(cv, ks, SPEC, {})
    assert t["source"] == "claim:A"          # severity from A's strong signal beats the caveat (sev 1)
    assert "bottom-decile" in t["text"]


def test_tension_extra_wins_at_high_severity():
    spec = HeadlineSpec(gate="presence", axis_labels=SPEC.axis_labels, axis_keys=SPEC.axis_keys,
                        critical_axes=SPEC.critical_axes,
                        tension_extra=lambda h: ({"text": h["note"], "source": "x", "severity": 3}
                                                 if h.get("flag") else None))
    cv = _cv(a=("weak", "low", "small conflict"))
    t = rank_tension(cv, {"caveat": "c"}, spec, {"flag": True, "note": "buried measured-negative"})
    assert t["text"] == "buried measured-negative"


def test_tension_none_when_clean():
    assert rank_tension(_cv(), {}, SPEC, {}) is None


# ── hero payload + full build ──────────────────────────────────────────────────────────────────
def test_hero_payload_includes_all_axes_and_gaps():
    cv = _cv(c=("unmeasured", "unmeasured", None))
    hero = headline_hero_plot_data(verdict={"call": "present", "phrase": "Present", "gate": "presence"},
                                   confidence={"level": "moderate", "coverage": {}}, tension=None,
                                   claim_vector=cv, spec=SPEC)
    assert [a["key"] for a in hero["axes"]] == ["A", "B", "C", "D"]
    c_axis = next(a for a in hero["axes"] if a["key"] == "C")
    assert c_axis["signal"] == "unmeasured"


def test_build_headline_text_deterministic_and_verdict_inert():
    cv = _cv(b=("moderate", "moderate", "RNA/protein disagree"))
    ks = {"caveat": "mid-tier abundance"}
    blk = build_headline({"presence_verdict": "present"}, cv, ks, spec=SPEC,
                         verdict_token="present", driving_rule_id="R1")
    assert blk["verdict"] == {"call": "present", "phrase": "Present", "gate": "presence",
                              "driving_rule_id": "R1", "polarity": None}
    assert blk["headline_text"].startswith("Present — ")
    assert "tension:" in blk["headline_text"]
    # idempotent / pure — a second build over the same inputs is byte-identical
    blk2 = build_headline({"presence_verdict": "present"}, cv, ks, spec=SPEC,
                          verdict_token="present", driving_rule_id="R1")
    assert blk == blk2
