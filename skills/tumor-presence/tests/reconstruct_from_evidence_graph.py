#!/usr/bin/env python3
"""§7 acceptance demo: reconstruct the tumor-presence dashboard for a target·indication FROM THE
evidence_graph ALONE — zero .card.yaml reads, zero free-text parsing, zero positional guessing.

Reads a decision.json and BUILDS the graph from it (build_evidence_graph + the skill's questions.yaml).
A committed `headline.evidence_graph` is never used in preference to that rebuild — it is a snapshot
nothing regenerates, so trusting it would demo a stale dashboard as current. Then prints: the verdict
header, the 7 questions
with signal+confidence + their cards + their literature (incl. axis B → elevated_vs_normal), and each
card's dataset→data→rule→verdict chain — touching only the graph's own id-keyed nodes/edges.

Usage:
    python reconstruct_from_evidence_graph.py [path/to/decision.json]
Defaults to the committed EPCAM·COADREAD fixture.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent

from _skills_common.evidence_graph import build_evidence_graph, load_questions  # noqa: E402


def reconstruct(graph: dict) -> str:
    by_card = {c["id"]: c for c in graph["cards"]}
    by_cit = {c["id"]: c for c in graph["citations"]}
    lit_axis = {ax["axis_id"]: ax for ax in graph.get("literature", {}).get("axes", [])}
    lines = []
    v = graph["verdict"]
    lines.append(f"{graph['skill']} · {graph['target']} · {graph['indication']}")
    lines.append(f"VERDICT [{v['polarity']}]: {v['call']}  (driving: {v['driving_rule_id']})")
    conf = v.get("confidence", {})
    lines.append(f"confidence: {conf.get('level')}  coverage={conf.get('coverage')}")
    if v.get("top_tension"):
        lines.append(f"tension: {v['top_tension']['text']}  (cards: {v['top_tension']['source_card_ids']})")
    lines.append("")
    for q in graph["questions"]:
        sig, cf = q["signal"], q["confidence"]
        lines.append(f"[{q['seq']}] {q['id']}  axis={q['axis_id']}  role={q['role']}")
        lines.append(f"    {q['text']}")
        lines.append(f"    signal={sig['tier']}/{sig['polarity']}  confidence={cf['level']} ({cf['dots']}●)")
        for aid in q["literature_axis_ids"]:
            ax = lit_axis.get(aid, {})
            cites = " ".join(
                f"[{by_cit[cid]['label']}"
                + (f" PMID:{by_cit[cid]['pmid']}" if by_cit[cid].get("pmid") else "")
                + (" ✓]" if by_cit[cid].get("verified") else "]")
                for cid in ax.get("citation_ids", [])
                if cid in by_cit
            )
            lines.append(f"    literature axis {aid}: {ax.get('read')} · {ax.get('agreement_vs_omics')}  {cites}")
        for cid in q["card_ids"]:
            c = by_card[cid]
            ch = c["chain"]
            data = " · ".join(f"{d['field']}={d['value']}" for d in ch["data"][:2])
            rule = ch["rule_id"] or "(no rule — display-only)"
            drv = " ⟵ DRIVING" if ch["is_driving"] else (" → contributes" if ch["contributes_to_verdict"] else "")
            lines.append(f"      · {cid} [{c['role']}] {c['class']['field']}={c['class']['value']}")
            lines.append(f"          {', '.join(c['dataset_ids'][:3]) or '—'}  →  {data}  →  {rule}{drv}")
        lines.append("")
    lines.append(f"literature overall_consistency: {graph.get('literature', {}).get('overall_consistency')}")
    return "\n".join(lines)


def main(argv):
    path = Path(argv[1]) if len(argv) > 1 else SKILL_DIR / "tests" / "fixtures" / "epcam_coadread_decision.json"
    decision = json.loads(Path(path).read_text())
    # Always REBUILD. This was `decision[...].get("evidence_graph") or build_evidence_graph(...)`, which
    # PREFERRED a committed block — a snapshot nothing regenerates when the builder changes, so the demo
    # would reconstruct a dashboard from stale bytes and present it as what the skill emits today. It was
    # correct only by the accident that this default fixture carries no block; 5 of the 6 fixtures that do
    # carry one had drifted by 16-72 leaves. Warn rather than silently discard, so an unexpected block is
    # visible here too and not only in the guard.
    committed = decision.get("headline", {}).get("evidence_graph")
    graph = build_evidence_graph(decision, questions=load_questions(SKILL_DIR))
    if committed is not None and committed != json.loads(json.dumps(graph)):
        print(
            f"WARNING: {path}'s committed headline.evidence_graph differs from a rebuild; reconstructing "
            "from the REBUILD. See skills/tests/test_committed_evidence_graph_not_stale.py",
            file=sys.stderr,
        )
    print(reconstruct(graph))


if __name__ == "__main__":
    main(sys.argv)
