#!/usr/bin/env python3
"""
validate_evidence_graph.py — evidence_graph structural + referential validator.

Mirrors validate_cards.py's two-layer shape for the additive, DISPLAY-ONLY claim graph
emitted at decision.headline.evidence_graph (schemas/evidence_graph.schema.json):

  (1) Structural — the graph object must validate against evidence_graph.schema.json
      (Draft 2020-12). This now covers the additive `key_evidence` promotion on card nodes.
  (2) Referential integrity — the invariant JSON Schema CANNOT express: every id referenced
      by an EDGE must resolve to a node in the SAME package. A dangling card/rule/dataset/
      citation/axis/question id is a silent renderer break, so we check every edge direction:
        - question.card_ids ⊆ cards · question.rule_ids ⊆ rules · question.literature_axis_ids ⊆ axes
        - card.question_ids ⊆ questions · card.dataset_ids ⊆ datasets · card.rule_ids ⊆ rules
          · card.chain.{dataset_ids,rule_id} · card.key_evidence.conflict.other[].card ⊆ cards
        - rule.card_id ⊆ cards
        - literature.axes[].{question_ids ⊆ questions, citation_ids ⊆ citations}
          · blind_spots[].citation_ids ⊆ citations
        - verdict.driving_rule_id ⊆ rules · verdict.top_tension.source_card_ids ⊆ cards
        - narrative.cites.{question_ids,card_ids,rule_ids} ⊆ respective
          · narrative.exec_bullets[].cites.{question_ids ⊆ questions, card_ids ⊆ cards, citation_ids ⊆ citations}

Usage:
  python validators/validate_evidence_graph.py --self-check          # bundled example fixture
  python validators/validate_evidence_graph.py path/to/graph.json ... # explicit graph objects
  python validators/validate_evidence_graph.py --decision run/decision.json  # extract .headline.evidence_graph

  # As a library (the claude-oncology-skills assert_evidence_graph_valid helper mirrors
  # referential_integrity_errors so all 14 skills validate identically):
  from validate_evidence_graph import validate_graph, referential_integrity_errors
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from jsonschema import Draft202012Validator

EXAMPLE_PATH = Path(__file__).resolve().parent.parent / "schemas" / "examples" / "evidence_graph.example.json"


@dataclass
class ValidationReport:
    graph_path: str
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.ok = False
        self.errors.append(msg)


def _load_schema() -> dict:
    # N3-1 #2144: load via the packaged loader instead of a local SCHEMA_PATH file read.
    from oncology_target_contracts.loader import load_schema

    return load_schema("evidence_graph")


def _structural_check(graph: dict, report: ValidationReport, schema: dict) -> None:
    validator = Draft202012Validator(schema)
    for err in validator.iter_errors(graph):
        path = ".".join(str(p) for p in err.absolute_path) or "<root>"
        report.add_error(f"STRUCTURAL [{path}]: {err.message}")


def referential_integrity_errors(graph: dict) -> list[str]:
    """Return the list of dangling-id referential errors (empty == intact). Pure; no I/O.
    Mirrored verbatim by claude-oncology-skills _skills_common.evidence_graph.assert_evidence_graph_valid."""
    errs: list[str] = []
    g = graph or {}
    card_ids = {c.get("id") for c in (g.get("cards") or []) if isinstance(c, dict)}
    rule_ids = {r.get("id") for r in (g.get("rules") or []) if isinstance(r, dict)}
    q_ids = {q.get("id") for q in (g.get("questions") or []) if isinstance(q, dict)}
    ds_ids = {d.get("id") for d in (g.get("datasets") or []) if isinstance(d, dict)}
    cite_ids = {c.get("id") for c in (g.get("citations") or []) if isinstance(c, dict)}
    axis_ids = {a.get("axis_id") for a in ((g.get("literature") or {}).get("axes") or []) if isinstance(a, dict)}

    def _chk(ids, universe, where):
        for i in ids or []:
            if i is not None and i not in universe:
                errs.append(f"REFERENTIAL [{where}]: id '{i}' does not resolve to a node")

    for q in g.get("questions") or []:
        if not isinstance(q, dict):
            continue
        qid = q.get("id")
        _chk(q.get("card_ids"), card_ids, f"question[{qid}].card_ids")
        _chk(q.get("rule_ids"), rule_ids, f"question[{qid}].rule_ids")
        _chk(q.get("literature_axis_ids"), axis_ids, f"question[{qid}].literature_axis_ids")
        for ref in q.get("evidence_refs") or []:
            if isinstance(ref, dict):
                _chk([ref.get("card_id")], card_ids, f"question[{qid}].evidence_refs.card_id")

    for c in g.get("cards") or []:
        if not isinstance(c, dict):
            continue
        cid = c.get("id")
        _chk(c.get("question_ids"), q_ids, f"card[{cid}].question_ids")
        _chk(c.get("dataset_ids"), ds_ids, f"card[{cid}].dataset_ids")
        _chk(c.get("rule_ids"), rule_ids, f"card[{cid}].rule_ids")
        chain = c.get("chain") or {}
        _chk(chain.get("dataset_ids"), ds_ids, f"card[{cid}].chain.dataset_ids")
        if chain.get("rule_id") is not None:
            _chk([chain.get("rule_id")], rule_ids, f"card[{cid}].chain.rule_id")
        ke = c.get("key_evidence") or {}
        conflict = (ke or {}).get("conflict") or {}
        for o in conflict.get("other") or []:
            if isinstance(o, dict) and o.get("card") is not None:
                _chk([o.get("card")], card_ids, f"card[{cid}].key_evidence.conflict.other.card")

    for r in g.get("rules") or []:
        if isinstance(r, dict) and r.get("card_id") is not None:
            _chk([r.get("card_id")], card_ids, f"rule[{r.get('id')}].card_id")

    lit = g.get("literature") or {}
    for ax in lit.get("axes") or []:
        if not isinstance(ax, dict):
            continue
        _chk(ax.get("question_ids"), q_ids, f"literature.axes[{ax.get('axis_id')}].question_ids")
        _chk(ax.get("citation_ids"), cite_ids, f"literature.axes[{ax.get('axis_id')}].citation_ids")
    for bs in lit.get("blind_spots") or []:
        if isinstance(bs, dict):
            _chk(bs.get("citation_ids"), cite_ids, "literature.blind_spots.citation_ids")

    verdict = g.get("verdict") or {}
    if verdict.get("driving_rule_id") is not None:
        _chk([verdict.get("driving_rule_id")], rule_ids, "verdict.driving_rule_id")
    tension = verdict.get("top_tension") or {}
    if isinstance(tension, dict):
        _chk(tension.get("source_card_ids"), card_ids, "verdict.top_tension.source_card_ids")

    narrative = g.get("narrative") or {}
    cites = narrative.get("cites") or {}
    _chk(cites.get("question_ids"), q_ids, "narrative.cites.question_ids")
    _chk(cites.get("card_ids"), card_ids, "narrative.cites.card_ids")
    _chk(cites.get("rule_ids"), rule_ids, "narrative.cites.rule_ids")
    for i, b in enumerate(narrative.get("exec_bullets") or []):
        bc = (b or {}).get("cites") or {} if isinstance(b, dict) else {}
        _chk(bc.get("question_ids"), q_ids, f"narrative.exec_bullets[{i}].cites.question_ids")
        _chk(bc.get("card_ids"), card_ids, f"narrative.exec_bullets[{i}].cites.card_ids")
        _chk(bc.get("citation_ids"), cite_ids, f"narrative.exec_bullets[{i}].cites.citation_ids")
    return errs


def validate_graph(graph: dict, path: str = "<graph>", schema: dict | None = None) -> ValidationReport:
    report = ValidationReport(graph_path=path)
    if not isinstance(graph, dict):
        report.add_error("graph is not a JSON object")
        return report
    schema = schema if schema is not None else _load_schema()
    _structural_check(graph, report, schema)
    for e in referential_integrity_errors(graph):
        report.add_error(e)
    return report


def _format_report(report: ValidationReport) -> str:
    head = f"{'✓' if report.ok else '✗'} {report.graph_path}"
    lines = [head] + [f"    {e}" for e in report.errors]
    return "\n".join(lines)


def _load_graph(path: Path, from_decision: bool) -> dict:
    obj = json.loads(path.read_text())
    if from_decision:
        return ((obj.get("headline") or {}).get("evidence_graph")) or {}
    # a decision.json passed without --decision still works: auto-detect the nested graph
    if "headline" in obj and "cards" not in obj:
        return ((obj.get("headline") or {}).get("evidence_graph")) or {}
    return obj


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate evidence_graph objects (schema + referential integrity).")
    ap.add_argument("paths", nargs="*", help="graph JSON files (or decision.json — the nested graph is auto-detected)")
    ap.add_argument(
        "--decision", action="store_true", help="treat inputs as decision.json and extract .headline.evidence_graph"
    )
    ap.add_argument("--self-check", action="store_true", help="validate the bundled example fixture")
    args = ap.parse_args(argv)

    schema = _load_schema()
    Draft202012Validator.check_schema(schema)  # the schema itself must be well-formed

    targets: list[Path] = [Path(p) for p in args.paths]
    if args.self_check:
        if not EXAMPLE_PATH.exists():
            print(f"✗ --self-check: bundled example not found at {EXAMPLE_PATH}", file=sys.stderr)
            return 1
        targets.append(EXAMPLE_PATH)
    if not targets:
        print("nothing to validate (pass graph paths or --self-check)", file=sys.stderr)
        return 1

    ok = True
    for p in targets:
        if not p.exists():
            print(f"✗ {p}: not found", file=sys.stderr)
            ok = False
            continue
        report = validate_graph(_load_graph(p, args.decision), str(p), schema)
        print(_format_report(report))
        ok = ok and report.ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
