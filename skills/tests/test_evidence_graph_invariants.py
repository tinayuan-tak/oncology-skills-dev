"""Shared evidence_graph STRUCTURAL invariants across every skill that ships an evidence_graph fixture.

These invariants — referential integrity, purely-additive / no-mutation, determinism, no orphaned
cards, fail-soft without optional inputs, and referential intactness without a questions registry —
were byte-identical across all ~14 per-skill test_evidence_graph.py files. They are consolidated here,
parametrized over the skills (discovered by the presence of a committed decision fixture). Each
per-skill test_evidence_graph.py keeps ONLY its bespoke DATA assertions (role partition, reconstructed
signal/confidence/card_ids, literature-axis crosswalk, driving-card chain, verdict-node).

build_evidence_graph is a PURE function of (decision, questions) — no run.py import — so exercising all
skills in this one process is collision-free (unlike the per-skill suites that load run.py).
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

SKILLS_DIR = Path(__file__).resolve().parents[1]
if str(SKILLS_DIR) not in sys.path:
    sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.evidence_graph import build_evidence_graph, load_questions  # noqa: E402

_SKILLS = sorted(
    p.parents[1].name  # …/skills/<skill>/tests/test_evidence_graph.py → <skill>
    for p in SKILLS_DIR.glob("*/tests/test_evidence_graph.py")
    if list((p.parent / "fixtures").glob("*decision*.json"))  # has a committed decision fixture
)


def _load(skill: str):
    """(decision, questions) for a skill — the single *decision*.json fixture (target/indication
    varies per skill) + its questions.yaml registry."""
    fx = sorted((SKILLS_DIR / skill / "tests" / "fixtures").glob("*decision*.json"))[0]
    return json.loads(fx.read_text()), load_questions(SKILLS_DIR / skill)


def test_at_least_the_known_skills_are_discovered():
    """Guard the discovery glob — a fixture move/rename that silently drops skills from the
    parametrization would make the invariants vacuously pass."""
    assert len(_SKILLS) >= 14, _SKILLS


@pytest.mark.parametrize("skill", _SKILLS)
def test_referential_integrity(skill):
    d, q = _load(skill)
    g = build_evidence_graph(d, questions=q)
    q_ids = {x["id"] for x in g["questions"]}
    c_ids = {x["id"] for x in g["cards"]}
    r_ids = {x["id"] for x in g["rules"]}
    d_ids = {x["id"] for x in g["datasets"]}
    axis_ids = {x["axis_id"] for x in g["questions"] if x.get("axis_id")}
    for qq in g["questions"]:
        assert set(qq["card_ids"]) <= c_ids, (skill, qq["id"])
        assert set(qq["rule_ids"]) <= r_ids, (skill, qq["id"])
        for er in qq["evidence_refs"]:
            assert er["card_id"] in c_ids, (skill, qq["id"])
    for c in g["cards"]:
        assert set(c["question_ids"]) <= q_ids, (skill, c["id"])
        assert set(c["rule_ids"]) <= r_ids, (skill, c["id"])
        assert set(c["dataset_ids"]) <= d_ids, (skill, c["id"])
        if c["chain"]["rule_id"] is not None:
            assert c["chain"]["rule_id"] in r_ids, (skill, c["id"])
        if c.get("axis_id"):
            assert c["axis_id"] in axis_ids, (skill, c["id"])
    for r in g["rules"]:
        assert r["card_id"] in c_ids, (skill, r["id"])


@pytest.mark.parametrize("skill", _SKILLS)
def test_builder_is_pure_and_additive(skill):
    d, q = _load(skill)
    before = copy.deepcopy(d)
    g = build_evidence_graph(d, questions=q)
    assert d == before, skill  # builder does not mutate the decision
    enriched = copy.deepcopy(d)
    enriched["headline"]["evidence_graph"] = g
    assert "evidence_graph" not in d["headline"], skill  # trimmed fixture predates the layer
    assert enriched["headline"].pop("evidence_graph") == g
    assert enriched == d, skill  # attaching the layer changes nothing else


@pytest.mark.parametrize("skill", _SKILLS)
def test_build_is_deterministic(skill):
    d, q = _load(skill)
    a = json.dumps(build_evidence_graph(d, questions=q), default=str)
    b = json.dumps(build_evidence_graph(d, questions=q), default=str)
    assert a == b, skill


# NOTE: "every card joins a question" (no orphan) is deliberately NOT a shared invariant — it is
# per-skill DATA. Most skills have zero orphans, but surface-modality-fit pins a KNOWN orphan
# (surfaceome-cohort-ranking, whose contract lacks a measurement_type — a target-contracts gap). Each
# per-skill test_evidence_graph.py keeps its own orphan assertion (empty, or the pinned exception).


@pytest.mark.parametrize("skill", _SKILLS)
def test_fail_soft_without_optional_inputs(skill):
    d, q = _load(skill)
    full = build_evidence_graph(d, questions=q)
    stripped = copy.deepcopy(d)
    stripped.pop("literature_synthesis", None)
    stripped.pop("llm_synthesis", None)
    g = build_evidence_graph(stripped, questions=q)
    assert g["literature"] == {} and g["citations"] == [] and g["narrative"] == {}, skill
    assert len(g["cards"]) == len(full["cards"]), skill
    for qq in g["questions"]:
        assert qq["literature_axis_ids"] == [], (skill, qq["id"])


@pytest.mark.parametrize("skill", _SKILLS)
def test_graph_without_registry_is_referentially_intact(skill):
    d, _ = _load(skill)
    g = build_evidence_graph(d, questions=[])
    assert g["questions"] == [], skill
    d_ids = {x["id"] for x in g["datasets"]}
    for c in g["cards"]:
        assert c["question_ids"] == [], (skill, c["id"])
        assert set(c["dataset_ids"]) <= d_ids, (skill, c["id"])
