"""P2 of the composed-evidence-graph rollup (docs/COMPOSED_EVIDENCE_GRAPH_ROLLUP.md §1): the fan-out
carries a per-subskill `evidence_graph` onto `target_report.skill_reports[<short>].evidence_graph`, so the
composed embedded lens view renders from the SAME graph as the standalone dashboard.

Uses the OFFLINE frozen-fixture harness (same monkeypatch as test_fanout_replay): the live dispatcher is
replaced by a frozen KRAS/COADREAD card-summary map, so this runs the REAL `_run_sub_skills` with no S3.
Asserts: (a) skills that produce a skill_report also carry a referentially-intact evidence_graph;
(b) tumor-presence (the only skill with a questions.yaml) carries its full 7-question structure — the graph
is question-anchored in composition, not just standalone; (c) the verdict spine is byte-identical to the
replay expectations (the carry is additive / display-only). Verdict-INERT throughout.
"""

import copy
from pathlib import Path

import pytest
import yaml

import _skills_common as skc
import tp_fanout as TP

_FIX = Path(__file__).resolve().parent / "fixtures"


def _real_summary(s) -> bool:
    return isinstance(s, dict) and not s.get("_missing")


def _fan_out_full(pair_id: str, target: str, indication: str) -> dict:
    """Run the REAL fan-out with the live dispatcher replaced by the frozen fixture; return the FULL
    sub_results dict (unlike test_fanout_replay._fan_out, which keeps only the verdict map)."""
    frozen = yaml.safe_load((_FIX / f"{pair_id}.yaml").read_text())

    def _factory():
        def _read(card_id, target_, indication_, *a, **k):
            s = frozen.get(card_id)
            return copy.deepcopy(s) if _real_summary(s) else None

        return _read

    mp = pytest.MonkeyPatch()
    mp.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)
    mp.setattr(skc, "_import_dispatcher", _factory)
    try:
        return TP._run_sub_skills(target, indication)
    finally:
        mp.undo()


def _graph_of(sub_results: dict, short: str):
    r = sub_results.get(short) or {}
    sr = (r.get("synthesis_facet") or {}).get("skill_report")
    return sr.get("evidence_graph") if isinstance(sr, dict) else None


@pytest.fixture(scope="module")
def kras():
    return _fan_out_full("kras_coadread", "KRAS", "COADREAD")


# ── the carry is broad + referentially intact ───────────────────────────────────────────────────────
def test_carry_attaches_referentially_intact_graphs(kras):
    graphed = {s: _graph_of(kras, s) for s in kras if _graph_of(kras, s)}
    # the KRAS fixture produces a skill_report for ~all shorts; the carry should graph the vast majority
    assert len(graphed) >= 12, f"expected the carry on ≥12 shorts, got {sorted(graphed)}"
    for short, eg in graphed.items():
        assert eg.get("schema_version") == "1.0", short
        cids = {c["id"] for c in eg["cards"]}
        rids = {x["id"] for x in eg["rules"] if x["id"]}
        qids = {q["id"] for q in eg["questions"]}
        dids = {d["id"] for d in eg["datasets"]}
        for q in eg["questions"]:
            assert set(q["card_ids"]) <= cids, f"{short}: dangling question→card"
            assert set(q["rule_ids"]) <= rids, f"{short}: dangling question→rule"
        for c in eg["cards"]:
            assert set(c["question_ids"]) <= qids, f"{short}: dangling card→question"
            assert set(c["dataset_ids"]) <= dids, f"{short}: dangling card→dataset"
            assert set(c["rule_ids"]) <= rids, f"{short}: dangling card→rule"
            # P1 canonical vocabulary is preserved through the composed carry
            assert c["signal"]["polarity"] in {"supportive", "neutral", "opposing", "killer", "not_applicable", None}, (
                f"{short}: non-canonical polarity"
            )


# ── tumor-presence carries its full question-anchored structure in composition (FULL tier) ───────────
def test_expression_graph_is_question_anchored(kras):
    eg = _graph_of(kras, "expression")
    assert eg is not None, "tumor-presence (expression) must carry a graph"
    # 7 canonical questions from skills/tumor-presence/questions.yaml — proving load_questions runs in
    # the composed path, not only in the standalone dispatcher
    assert len(eg["questions"]) == 7
    assert {q["id"] for q in eg["questions"]} >= {"expressed_at_all", "elevated_vs_normal", "malignant_intrinsic"}


# ── the carry never moves the verdict spine (additive / display-only) ────────────────────────────────
def test_carry_is_verdict_inert(kras):
    v = {short: (r.get("verdict")[0] if r.get("verdict") else None) for short, r in kras.items()}
    # same expectations test_fanout_replay pins for KRAS/COADREAD — the carry must not perturb them
    assert v["genomic_alteration"] == "biomarker_stratified_dependency"
    assert v["safety"] == "highly_constrained_safety_concern"
    assert len(kras) == len(TP.SUB_SKILLS)


# ── the _headline loader hook (mirrors _load_sub_skill_facet_fn) ─────────────────────────────────────
def test_headline_loader_hook():
    assert callable(TP._load_sub_skill_headline_fn("tumor-presence"))
    # genomic-alteration-profile has a _synthesis_facet but no _headline → None (graceful: partial graph)
    assert TP._load_sub_skill_headline_fn("genomic-alteration-profile") is None
