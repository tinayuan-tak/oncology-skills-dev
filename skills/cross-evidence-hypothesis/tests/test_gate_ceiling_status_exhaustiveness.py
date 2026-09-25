"""Exhaustiveness guard for gate_ceiling's hard-gate STATUS switch.

`cross-evidence-hypothesis` composes no cards and fires no rules — its teeth live ENTIRELY in the
deterministic ceiling that clamps the LLM-proposed verdict. So the ceiling's fidelity to the spine's
status vocab IS the guarantee. `gate_ceiling` switches on `recommendation_gate.hard_gates[].status`;
the target-profile spine (`tp_gates._hard_gates_status`) is the SOURCE OF TRUTH for that token and emits
7 values. Historically the switch handled only 4 (fired, blind, opposing, excluded) and the other three
(suppressed, reconciled, latent) fell through with NO signal — correct-by-luck today, but nothing
asserted the consumer's handled set stays a superset of the spine's emitted set. The planned
`opposing → uncorroborated` lifecycle split would mint a token that falls through silently, dropping the
`advanceable_with_caveat` clamp from every uncorroborated target = fail-OPEN one surface out.

These tests are the STATUS-axis mirror of the VALUE-axis token-completeness cluster: they fail LOUD the
moment the spine's emitted status set (or its gated-axis set) grows past what gate_ceiling handles.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent  # skills/
sys.path.insert(0, str(_ROOT / "cross-evidence-hypothesis" / "scripts"))
sys.path.insert(0, str(_ROOT / "target-profile" / "scripts"))

import hypothesis_core as hc  # noqa: E402
import tp_gates  # noqa: E402


def _spine_emitted_statuses() -> set[str]:
    """Extract every `status = "<token>"` literal minted inside tp_gates._hard_gates_status — the
    authoritative source. If the spine adds/renames a token, this set moves and the coverage assertions
    below fail until gate_ceiling handles it."""
    src = (_ROOT / "target-profile" / "scripts" / "tp_gates.py").read_text()
    m = re.search(r"\ndef _hard_gates_status\(.*?\n(?=\ndef )", src, re.DOTALL)
    assert m, "could not locate tp_gates._hard_gates_status source"
    # Collect every string literal on a `status = ...` assignment line — this captures BOTH branches of
    # a ternary (e.g. `status = "excluded" if ... else "latent"`), which a single-literal regex misses.
    tokens: set[str] = set()
    for line in m.group(0).splitlines():
        if re.match(r"\s*status\s*=", line):
            tokens.update(re.findall(r'"([a-z_]+)"', line))
    return tokens


def _pkg_with_gate(status, short="dependency", verdict="non_dependent", disp="gated"):
    return {
        "synthesis": {
            "sub_verdicts": {"safety": {"verdict": None}},
            "recommendation_gate": {
                "hard_gates": [{"short": short, "verdict": verdict, "disposition": disp, "status": status}]
            },
        }
    }


def test_ceiling_status_vocab_mirrors_the_spine_source_of_truth():
    """gate_ceiling's declared vocab must equal the set the spine actually emits — no more, no less."""
    assert hc._SPINE_HARD_GATE_STATUSES == _spine_emitted_statuses()


def test_every_spine_status_token_is_handled_without_falling_through():
    """Each of the 7 spine tokens must produce a ceiling result (no ValueError from the guard)."""
    for status in sorted(hc._SPINE_HARD_GATE_STATUSES):
        g = hc.gate_ceiling(_pkg_with_gate(status))
        assert g["ceiling"] in hc.VERDICT_RANK, f"{status!r} → bad ceiling {g['ceiling']!r}"


def test_non_capping_tokens_carry_no_ceiling_signal():
    """suppressed / reconciled / latent are inert BY DESIGN — they must not clamp below `advanceable`."""
    for status in sorted(hc._NON_CAPPING_SPINE_STATUSES):
        g = hc.gate_ceiling(_pkg_with_gate(status))
        assert g["ceiling"] == "advanceable", f"{status!r} unexpectedly capped to {g['ceiling']!r}"


def test_unknown_status_token_fails_loud_not_open():
    """The whole point: a token the spine does NOT emit (e.g. a future `uncorroborated`) must RAISE, not
    silently fall through with no ceiling signal."""
    with pytest.raises(ValueError, match="unhandled hard-gate status"):
        hc.gate_ceiling(_pkg_with_gate("uncorroborated"))


def test_gate_axis_role_sets_cover_the_spines_gated_axes():
    """The AXIS-set mirror: a future gated axis added to the spine (_GATING_AXIS_FAILCLOSED_ACTION) that
    the consumer's veto/hold sets do not know about would hit the `fired` else and be mis-treated as
    hold-grade (cap, not veto) — fail-open if it should veto. Assert exact per-action coverage."""
    spine = tp_gates._GATING_AXIS_FAILCLOSED_ACTION
    spine_veto = {a for a, act in spine.items() if act == "veto"}
    spine_hold = {a for a, act in spine.items() if act == "hold"}
    assert set(hc._VETO_GATE_AXES) == spine_veto
    assert set(hc._HOLD_GRADE_GATE_AXES) == spine_hold
    # union covers every gated axis — no axis role the spine gates is unknown to the consumer
    assert (set(hc._VETO_GATE_AXES) | set(hc._HOLD_GRADE_GATE_AXES)) >= set(spine)
