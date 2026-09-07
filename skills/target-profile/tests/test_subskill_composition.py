"""Stage 1b golden — target-profile attaches a shared CompositionResult per sub-skill.

target-profile has NO full-run byte-golden (its resolve_cards needs live S3), so this
OFFLINE test monkeypatches the fan-out's data/verdict boundary (resolve_cards, fired_rules,
_load_sub_skill_verdict_fn) and drives the real `_run_sub_skills` to prove:

  1. every sub-skill result now carries a well-formed `composition` CompositionResult;
  2. for a GATED sub-skill it wraps the sub-skill's already-decided (verdict, driving_rule_id)
     — NOT a fresh resolver call — so post-resolver logic is preserved;
  3. for the GATELESS `expression` (tumor-presence) sub-skill the primary is None but the
     presence verdict is retained in `verdict`;
  4. BYTE-SAFETY: the attach is purely additive — `verdict`, `fired`, and the raw-ordered
     fired-rule-id list the nomination emits from `r["fired"]` are untouched (and differ from
     compose_core's sorted-set convention, which is exactly why the emission must not read it
     from `composition`).
"""

from __future__ import annotations

from pathlib import Path

from _skills_common.compose_core import CompositionResult, GateVerdict
from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parents[1], "tp_run_composition")
# The fan-out (_run_sub_skills + its resolve_cards/fired_rules/_load_sub_skill_verdict_fn boundary)
# lives in tp_fanout after the 2026-08-16 god-module split; monkeypatch it there so the patch is
# resolved in the same namespace _run_sub_skills looks the names up in (run.py only re-exports them).
import tp_fanout  # noqa: E402

# A deliberately UNSORTED, DUPLICATED fired list — so we can tell the raw emission convention
# (list order, dups kept) apart from compose_core's sorted-set fired_rule_ids.
_FAKE_FIRED = [{"rule_id": "r-b"}, {"rule_id": "r-a"}, {"rule_id": "r-b"}]
_FAKE_CARDS = [{"card_id": "c-present"}, {"card_id": "c-missing", "_missing": True}]


def _install_fakes(monkeypatch):
    monkeypatch.setattr(tp_fanout, "_prewarm_sub_skill_imports", lambda: None)
    monkeypatch.setattr(tp_fanout, "resolve_cards", lambda cards, target, indication, **kw: list(_FAKE_CARDS))
    monkeypatch.setattr(tp_fanout, "fired_rules", lambda cards, axis, card_id_filter, **kw: list(_FAKE_FIRED))

    # every sub-skill "resolves" to a fixed pair whose verdict encodes its short, so we can
    # assert the pair rode through untouched (a value no real resolver would emit).
    def _fake_loader(short_dir):
        return lambda fired: (f"verdict::{short_dir}", "drv-01")

    monkeypatch.setattr(tp_fanout, "_load_sub_skill_verdict_fn", _fake_loader)


def test_every_sub_skill_carries_a_composition(monkeypatch):
    _install_fakes(monkeypatch)
    results = tp._run_sub_skills("KRAS", "COADREAD")

    assert set(results) == {short for _, short in tp.SUB_SKILLS}
    for short, r in results.items():
        comp = r["composition"]
        assert isinstance(comp, CompositionResult), short
        # fired_rule_ids on the carrier is the sorted, deduped set (compose_core convention)
        assert comp.fired_rule_ids == ["r-a", "r-b"], short


def test_gated_sub_skill_wraps_decided_verdict(monkeypatch):
    _install_fakes(monkeypatch)
    results = tp._run_sub_skills("KRAS", "COADREAD")

    r = results["dependency"]  # a GATED short (_SHORT_TO_GATE -> "dependency")
    comp = r["composition"]
    # _fake_loader keys the dir; functional-requirement is the dependency sub-skill dir
    assert comp.primary_gate_verdict == GateVerdict(
        gate="dependency",
        verdict="verdict::functional-requirement",
        driving_rule_id="drv-01",
        fired_rule_ids=["r-a", "r-b"],
    )
    # the carrier's primary agrees with the legacy tuple the emission reads
    assert comp.primary_dict()["verdict"] == r["verdict"][0]
    assert comp.primary_dict()["driving_rule_id"] == r["verdict"][1]


def test_gateless_expression_has_no_primary_but_keeps_verdict(monkeypatch):
    _install_fakes(monkeypatch)
    results = tp._run_sub_skills("KRAS", "COADREAD")

    r = results["expression"]  # tumor-presence — NOT in _SHORT_TO_GATE
    assert r["composition"].primary_gate_verdict is None
    # its presence verdict is untouched in the legacy field the nomination still emits
    assert r["verdict"] == ("verdict::tumor-presence", "drv-01")


def test_attach_is_byte_additive_raw_fired_untouched(monkeypatch):
    """The nomination emits fired_rule_ids as [f["rule_id"] for f in r["fired"]] — RAW order,
    dups kept — NOT the sorted set on the carrier. Prove the attach did not disturb r["fired"]
    (fan-out axes × the fake list) and that the two conventions genuinely differ.
    2026-08-14: 3 axes (+combinatorial_dependency); 2026-08-20: 4 (+cis_coherence), then 6
    (+combination_opportunity +resistance_emergence) → 6× the per-axis fake list."""
    _install_fakes(monkeypatch)
    results = tp._run_sub_skills("KRAS", "COADREAD")

    r = results["selectivity"]
    raw_emitted = [f["rule_id"] for f in r["fired"]]  # what nomination.json writes
    assert raw_emitted == ["r-b", "r-a", "r-b"] * 6  # 6 fan-out axes, order + dups kept
    assert raw_emitted != r["composition"].fired_rule_ids  # sorted-set convention differs
    assert r["composition"].fired_rule_ids == ["r-a", "r-b"]


# ─────────────────────────────────────────────────────────────────────────────
# (2026-08-17): target-intrinsic composed as a GATELESS descriptive PEER.
# It is the framework's FIRST verdict=None gateless short (`expression` /
# `combinatorial_dependency` are gateless but DO emit a verdict). These guards pin
# BOTH the structural gateless guarantee AND that the None-verdict gateless short is
# tolerated by every downstream consumer (gate assembly, positive-tier, LLM synthesis
# prompt-builder) — and, critically, is NON-GATING (recommendation + confidence
# byte-identical whether or not it is present).
# ─────────────────────────────────────────────────────────────────────────────


def test_target_intrinsic_is_a_gateless_peer_in_the_roster():
    """Structural must-not-gate guarantee: target_intrinsic is in the fan-out roster but
    deliberately absent from _SHORT_TO_GATE (→ gate=None), and target-intrinsic's run.py exposes no
    _verdict/_snapshot (synthesis:none → verdict_fn None → verdict=None)."""
    shorts = {short for _, short in tp_fanout.SUB_SKILLS}
    assert "target_intrinsic" in shorts
    assert "target_intrinsic" not in tp_fanout._SHORT_TO_GATE
    # the real loader returns None for a descriptive skill (no verdict function) — this is what makes
    # the composed verdict None (not a faked None).
    assert tp_fanout._load_sub_skill_verdict_fn("target-intrinsic") is None


def _fake_loader_target_intrinsic_none(short_dir):
    """Like _install_fakes' loader but returns None for target-intrinsic (a descriptive skill has no
    verdict fn) — so the fan-out produces verdict=None for target_intrinsic exactly as in production."""
    if short_dir == "target-intrinsic":
        return None
    return lambda fired: (f"verdict::{short_dir}", "drv-01")


def test_gateless_none_verdict_short_has_no_primary_and_no_verdict(monkeypatch):
    _install_fakes(monkeypatch)
    monkeypatch.setattr(tp_fanout, "_load_sub_skill_verdict_fn", _fake_loader_target_intrinsic_none)
    results = tp._run_sub_skills("KRAS", "COADREAD")

    r = results["target_intrinsic"]
    assert r["verdict"] is None  # no verdict function → None
    assert r["composition"].primary_gate_verdict is None  # gateless → empty primary
    assert isinstance(r["composition"], CompositionResult)
    # its cards/fired audit trail is still carried (descriptive evidence reaches the integrator)
    assert r["composition"].fired_rule_ids == ["r-a", "r-b"]


def _gateless_none_entry():
    """A minimal sub_result for the target_intrinsic gateless None-verdict short."""
    fired = [{"rule_id": "ti-01", "card_id": "protein-domains-class", "field": "class", "value": "kinase"}]
    cards = [{"card_id": "protein-domains-class", "summary": {"class": "kinase"}}]
    return {"skill_dir": "target-intrinsic", "cards": cards, "fired": fired, "verdict": None, "composition": None}


def test_none_verdict_gateless_short_is_non_gating(monkeypatch):
    """ACCEPTANCE: adding the verdict=None gateless short must NOT change the gate recommendation or
    the positive-tier confidence (recommendation + confidence byte-identical)."""
    import tp_gates

    base = {
        "dependency": {"cards": [], "fired": [], "verdict": ("selective_dependency", "dep-01")},
        "selectivity": {"cards": [], "fired": [], "verdict": ("tumor_selective", "sel-01")},
        "safety": {"cards": [], "fired": [], "verdict": ("tolerated", "saf-01")},
    }
    with_ti = dict(base)
    with_ti["target_intrinsic"] = _gateless_none_entry()

    assert tp_gates._gate_recommendation(base) == tp_gates._gate_recommendation(with_ti)
    assert tp_gates._positive_tier(base) == tp_gates._positive_tier(with_ti)


def test_synthesis_prompt_builder_tolerates_none_verdict_gateless_short():
    """LLM synthesis prompt-builder must render a verdict=None gateless short (no crash) and label it
    honestly as having no rule-fired verdict."""
    import tp_synthesis_prompt

    sub_results = {
        "dependency": {
            "skill_dir": "functional-requirement",
            "cards": [],
            "fired": [],
            "verdict": ("selective_dependency", "dep-01"),
        },
        "target_intrinsic": _gateless_none_entry(),
    }
    prompt = tp_synthesis_prompt._build_user_prompt("KRAS", "COADREAD", sub_results)
    assert "target_intrinsic" in prompt
    assert "no rule-fired verdict" in prompt  # the None-verdict rendering branch
    # descriptive card evidence still reaches the integrator prompt
    assert "protein-domains-class" in prompt


# ---------------------------------------------------------------------------
# Figure Stage 3 (offline-seam activation, 2026-08-21): the fan-out must FORWARD
# plot_data_root to resolve_cards so figure emitters render offline (from persisted
# plot_data) instead of re-executing a second live read.
# ---------------------------------------------------------------------------


def _install_capturing_fakes(monkeypatch, captured):
    monkeypatch.setattr(tp_fanout, "_prewarm_sub_skill_imports", lambda: None)

    def _cap_resolve(cards, target, indication, **kw):
        captured.append(kw.get("plot_data_root", "__absent__"))
        return list(_FAKE_CARDS)

    monkeypatch.setattr(tp_fanout, "resolve_cards", _cap_resolve)
    monkeypatch.setattr(tp_fanout, "fired_rules", lambda cards, axis, card_id_filter, **kw: [])
    monkeypatch.setattr(tp_fanout, "_load_sub_skill_verdict_fn", lambda sd: lambda fired: (f"v::{sd}", "drv"))


def test_fanout_forwards_plot_data_root_to_resolve_cards(monkeypatch):
    from pathlib import Path

    captured: list = []
    _install_capturing_fakes(monkeypatch, captured)
    root = Path("/tmp/tp-figs")
    tp._run_sub_skills("KRAS", "COADREAD", plot_data_root=root)
    # one resolve_cards call per sub-skill, each given the SAME plot_data_root (the offline-seam wiring)
    assert captured, "expected at least one resolve_cards call"
    assert all(pdr == root for pdr in captured), f"plot_data_root not forwarded uniformly: {set(map(str, captured))}"


def test_fanout_defaults_plot_data_root_none_byte_stable(monkeypatch):
    """Default (verdict-only / --no-figures) forwards plot_data_root=None → no persistence, byte-stable."""
    captured: list = []
    _install_capturing_fakes(monkeypatch, captured)
    tp._run_sub_skills("KRAS", "COADREAD")
    assert captured and all(pdr is None for pdr in captured)
