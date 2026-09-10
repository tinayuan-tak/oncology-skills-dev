"""Fan-out reorder — the per-sub-skill LITERATURE lane now runs BEFORE narration and its result is
threaded onto the decision the narrator reads (narrator_engine._render_literature keys off
decision['literature_synthesis']), so the per-sub-skill exec_bullets can WEAVE + CITE the literature.

OFFLINE (no Bedrock): monkeypatch the fan-out's data/verdict/facet/literature boundary + the shared
narrator seam (narrator_engine.narrate) and drive the real `_run_sub_skills`, then capture the decision
each narrator was handed. Verdict-inert: the literature is display-only, byte-identical to today when
absent (--subskill-literature off → threaded literature is None).
"""

from __future__ import annotations

from pathlib import Path

from _skills_common import narrator_engine as NE
from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parents[1], "tp_run_litweave")
import tp_fanout  # noqa: E402

_FAKE_FIRED = [{"rule_id": "r-a"}]
_FAKE_CARDS = [{"card_id": "c-1", "summary": {}}]
_LIT = {
    "axes": [
        {
            "axis_key": "A",
            "literature_read": "supports",
            "agreement_vs_omics": "agree",
            "confidence": "high",
            "assertion": "published corroboration",
            "citations": [{"citation_id": "lit-1", "pmid": "16404434", "label": "Went 2006", "verified": True}],
        }
    ],
    "overall_consistency": "concordant",
}


def _install(monkeypatch, captured, *, literature: bool):
    monkeypatch.setattr(tp_fanout, "_prewarm_sub_skill_imports", lambda: None)
    monkeypatch.setattr(tp_fanout, "resolve_cards", lambda cards, target, indication, **kw: list(_FAKE_CARDS))
    monkeypatch.setattr(tp_fanout, "fired_rules", lambda cards, axis, card_id_filter, **kw: list(_FAKE_FIRED))
    monkeypatch.setattr(tp_fanout, "_load_sub_skill_verdict_fn", lambda sd: lambda fired: ("v", "d"))
    # every sub-skill exposes a (dict) synthesis_facet so the literature block's isinstance guard passes
    monkeypatch.setattr(tp_fanout, "_load_sub_skill_facet_fn", lambda sd: lambda cards, fired, vp, **kw: {})

    # the literature lane returns a fixed non-empty literature dict (no Bedrock / network)
    def _fake_make_lit(lens, retrieve_fn=None, verify_fn=None):
        return lambda decision, model=None: dict(_LIT)

    monkeypatch.setattr(tp_fanout, "make_literature_fn", _fake_make_lit)

    # capture the literature lane on every decision the narrator is handed. BOTH narration paths
    # (bespoke _llm_synthesis hooks AND the central-lens fallback) ultimately call narrator_engine.narrate.
    def _cap_narrate(decision, lens, model_id=None):
        captured.append({"lens": lens.name, "literature_synthesis": decision.get("literature_synthesis")})
        return {"exec_bullets": [], "_source": "fake"}

    monkeypatch.setattr(NE, "narrate", _cap_narrate)


def test_fanout_literature_lane_is_threaded_onto_narrator_decision(monkeypatch):
    """--subskill-literature: the literature lane runs FIRST and is threaded onto the decision the
    narrator reads, for every lensed sub-skill that narrates."""
    captured: list = []
    _install(monkeypatch, captured, literature=True)
    tp._run_sub_skills("KRAS", "COADREAD", synthesize_subskills=True, subskill_literature=True)

    assert captured, "expected the narrator to be invoked for lensed sub-skills"
    # every narrated decision carries the pre-computed literature lane (weave + cite is now possible)
    assert all(c["literature_synthesis"] == _LIT for c in captured), captured


def test_fanout_without_literature_flag_threads_none_byte_stable(monkeypatch):
    """Default (no --subskill-literature): the narrator decision carries literature_synthesis=None —
    byte-identical to the pre-reorder behaviour (the narrator prompt has no literature section)."""
    captured: list = []
    _install(monkeypatch, captured, literature=False)
    tp._run_sub_skills("KRAS", "COADREAD", synthesize_subskills=True, subskill_literature=False)

    assert captured
    assert all(c["literature_synthesis"] is None for c in captured), captured


def test_synthesize_with_retry_threads_literature_to_hook():
    """The bespoke-hook path: _synthesize_with_retry passes the pre-computed literature lane through to
    the sub-skill's _llm_synthesis hook as literature_synthesis=."""
    seen: dict = {}

    def _fake_hook(cards, fired, verdict_pair, target, indication, model, subtype, literature_synthesis=None):
        seen["lit"] = literature_synthesis
        return {"exec_bullets": [], "_source": "fake"}

    out = tp_fanout._synthesize_with_retry(
        _fake_hook, [], [], ("v", "d"), "KRAS", "COADREAD", "model-x", literature_synthesis=_LIT
    )
    assert out == {"exec_bullets": [], "_source": "fake"}
    assert seen["lit"] == _LIT


def test_bespoke_hook_attaches_literature_to_the_narrator_decision(monkeypatch):
    """A real sub-skill _llm_synthesis hook must set decision['literature_synthesis'] before narrating,
    so the exec_bullets weave + cite it. (functional-requirement narrates via make_synthesize_fn →
    narrator_engine.narrate.)"""
    fr = load_run_py(Path(__file__).resolve().parents[2] / "functional-requirement", "fr_run_litweave")
    monkeypatch.setattr(fr, "_headline", lambda *a, **k: {})  # decouple from card data
    captured: dict = {}
    monkeypatch.setattr(NE, "narrate", lambda decision, lens, model_id=None: captured.update(d=decision) or {"ok": 1})

    fr._llm_synthesis([], [], ("v", "d"), "KRAS", "COADREAD", literature_synthesis=_LIT)
    assert captured["d"].get("literature_synthesis") == _LIT
