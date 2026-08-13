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

import importlib.util
import sys
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"
SKILLS = Path(__file__).resolve().parents[2]  # .../skills
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.compose_core import CompositionResult, GateVerdict  # noqa: E402


def _load_run_module():
    spec = importlib.util.spec_from_file_location("tp_run_composition", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tp = _load_run_module()

# A deliberately UNSORTED, DUPLICATED fired list — so we can tell the raw emission convention
# (list order, dups kept) apart from compose_core's sorted-set fired_rule_ids.
_FAKE_FIRED = [{"rule_id": "r-b"}, {"rule_id": "r-a"}, {"rule_id": "r-b"}]
_FAKE_CARDS = [{"card_id": "c-present"}, {"card_id": "c-missing", "_missing": True}]


def _install_fakes(monkeypatch):
    monkeypatch.setattr(tp, "_prewarm_sub_skill_imports", lambda: None)
    monkeypatch.setattr(tp, "resolve_cards",
                        lambda cards, target, indication, **kw: list(_FAKE_CARDS))
    monkeypatch.setattr(tp, "fired_rules",
                        lambda cards, axis, card_id_filter, **kw: list(_FAKE_FIRED))
    # every sub-skill "resolves" to a fixed pair whose verdict encodes its short, so we can
    # assert the pair rode through untouched (a value no real resolver would emit).
    def _fake_loader(short_dir):
        return lambda fired: (f"verdict::{short_dir}", "drv-01")
    monkeypatch.setattr(tp, "_load_sub_skill_verdict_fn", _fake_loader)


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

    r = results["dependency"]                       # a GATED short (_SHORT_TO_GATE -> "dependency")
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

    r = results["expression"]                       # tumor-presence — NOT in _SHORT_TO_GATE
    assert r["composition"].primary_gate_verdict is None
    # its presence verdict is untouched in the legacy field the nomination still emits
    assert r["verdict"] == ("verdict::tumor-presence", "drv-01")


def test_attach_is_byte_additive_raw_fired_untouched(monkeypatch):
    """The nomination emits fired_rule_ids as [f["rule_id"] for f in r["fired"]] — RAW order,
    dups kept — NOT the sorted set on the carrier. Prove the attach did not disturb r["fired"]
    (2 axes × the fake list) and that the two conventions genuinely differ."""
    _install_fakes(monkeypatch)
    results = tp._run_sub_skills("KRAS", "COADREAD")

    r = results["selectivity"]
    raw_emitted = [f["rule_id"] for f in r["fired"]]          # what nomination.json writes
    assert raw_emitted == ["r-b", "r-a", "r-b", "r-b", "r-a", "r-b"]  # 2 axes, order + dups kept
    assert raw_emitted != r["composition"].fired_rule_ids     # sorted-set convention differs
    assert r["composition"].fired_rule_ids == ["r-a", "r-b"]
