"""Paralog-buffering veto-suppressor: a pooled negative CONTRADICTED by a strong
paralog buffer must NOT veto.

When a target's single-gene CRISPR KO is rescued by a paralog (MARK2/3, SMARCA2/4-
class), the pooled pan-cancer read is `non_dependent` — but that is a BUFFERING
ARTIFACT, not a trusted negative (the target may be a genuine dependency once the
paralog is co-inhibited/lost). When the pooled non-dependent killer fires AND the
`strong-paralog-buffering-degrader-preferred` rule fires, _verdict must return a
distinct `non_dependent_paralog_buffered` verdict — NEVER `non_dependent` — so the
nomination gate (which vetoes only on the exact `non_dependent` tuple) treats it as a
coverage gap, not a false negative. Sibling of test_verdict_underpowered_not_veto.py.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

RUN = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("fr_run", RUN)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


fr = _load()


def test_strong_paralog_buffer_suppresses_non_dependent_veto():
    """MARK2/3-class: pooled non-dependent-killer fires BUT strong paralog buffering
    also fires → distinct non_dependent_paralog_buffered, NOT the veto verdict."""
    v, drv = fr._verdict([
        {"rule_id": "non-dependent-killer"},
        {"rule_id": "strong-paralog-buffering-degrader-preferred"},
    ])
    assert v != "non_dependent", "a strong-buffered pooled negative must not reach the veto verdict"
    assert v == "non_dependent_paralog_buffered"
    assert drv == "strong-paralog-buffering-degrader-preferred", "driving rule recorded for provenance"


def test_genuine_non_dependent_no_buffer_still_vetoes_control():
    """CONTROL: pooled non-dependent WITHOUT a strong paralog buffer must still veto —
    the suppressor only spares the buffered case. (A genuinely expendable gene with no
    paralog rescue is a real trusted negative.)"""
    assert fr._verdict([{"rule_id": "non-dependent-killer"}]) == (
        "non_dependent", "non-dependent-killer")


def test_paralog_buffer_alone_does_not_fabricate_a_dependency():
    """A strong paralog buffer WITHOUT a pooled non-dependent read must NOT emit the
    buffered verdict — the suppressor only fires to SPARE a would-be veto, it never
    invents a dependency call. (Here only the paralog rule fired; no dependency rule →
    falls through to insufficient.)"""
    v, drv = fr._verdict([{"rule_id": "strong-paralog-buffering-degrader-preferred"}])
    assert v == "insufficient"
    assert drv is None


def test_pan_essential_precedence_over_paralog_buffer():
    """A pan-essential killer still wins over a co-firing paralog buffer — a
    common-essential target is not rescued by buffering (different failure mode; the
    suppressor targets the non_dependent arm only, never pan_essential)."""
    v, _ = fr._verdict([
        {"rule_id": "pan-essential-killer"},
        {"rule_id": "non-dependent-killer"},
        {"rule_id": "strong-paralog-buffering-degrader-preferred"},
    ])
    assert v == "pan_essential_killer"


def test_positive_dependency_precedence_over_buffer():
    """If the target reads as a real dependency (concordant/selective) that wins — the
    paralog-buffered rung is only reached when the pooled read was non-dependent."""
    v, _ = fr._verdict([
        {"rule_id": "concordant-dependent-supportive-dominant"},
        {"rule_id": "strong-paralog-buffering-degrader-preferred"},
    ])
    assert v == "concordant_dependent"
