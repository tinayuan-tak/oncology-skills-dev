#!/usr/bin/env python3
"""adversarial_survival — intrinsic defensibility metric, PRODUCTION post-check for the
cross-evidence hypothesis integrator.

Clause-traceability (pointer-COMPLETENESS) is computed inside the integrator. This is the ORTHOGONAL
intrinsic metric: does each clause SURVIVE a skeptic who tries to REFUTE it FROM THE SAME EVIDENCE
ONLY? (retrieve-don't-recall.)

  - For each assertive clause (causal_rationale, therapeutic_hypothesis, population,
    therapeutic_window) a SKEPTIC LLM pass tries to refute it using ONLY the citation surface the
    integrator was allowed to cite (the same package). No outside knowledge.
  - CONTAINMENT: the skeptic's own cited tokens are validated with the integrator's own
    `hypothesis_core.check_traceability`. A refutation whose citations do not resolve to the package
    is recall (confabulation), NOT retrieval — discarded (the clause survives that skeptic).
  - N=3 skeptics; a clause refuted by a MAJORITY (>=2) of *valid* (contained) refutations is not
    survived. Score = fraction of clauses surviving.

This is the in-repo evolution of framework-runs/ws6-measurement/adversarial_survival.py: it imports
the PRODUCTION skill's `hypothesis_core` (assemble + check_traceability), so it runs against
hypotheses this skill emits. It is an OPTIONAL post-check (needs Bedrock) — the always-on, offline
sibling is the deterministic intra-package COHERENCE guard in the skill's defensibility block, which
removes the internally-contradicted clauses this skeptic would otherwise refute.

Run:
  BEDROCK_AWS_PROFILE=cmp-dev python3 adversarial_survival.py \
      --evidence-package <evidence_package.json> --hypothesis <hypothesis.json> \
      [--risk r.json] [--target-dossier d.json] [--threshold 0.75] [--out survival.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))   # skills/ (for _skills_common)

import hypothesis_core as hc  # noqa: E402
import run as R  # noqa: E402

CLAUSE_KEYS = ("causal_rationale", "therapeutic_hypothesis", "population", "therapeutic_window")
N_SKEPTICS = 3
DEFAULT_THRESHOLD = 0.75   # a hypothesis below this is FLAGGED, not shipped clean on traceability alone

SKEPTIC_SYSTEM = (
    "You are a SKEPTICAL oncology target reviewer. You are given a drug-target hypothesis broken into "
    "clauses (each: a statement + the evidence tokens it cites) AND the FULL evidence package those "
    "clauses were built from (per-line deterministic verdicts, per-card interpretation calls, grounded "
    "literature risk reads, and indication-independent target-biology dossier fields).\n\n"
    "Your job: for EACH clause, try HARD to REFUTE it. A refutation is a specific, evidence-grounded "
    "reason the clause is NOT supported — an internal contradiction, an over-reach beyond what the "
    "cited line actually shows, a competing line in the SAME package that undercuts it, or reliance on "
    "a line whose verdict is insufficient / data_unavailable / not_informative (absence is not "
    "evidence).\n\n"
    "HARD CONTAINMENT RULE (retrieve-don't-recall): you may cite ONLY fields, card_ids, sub-verdict "
    "names, fired rule_ids, PMIDs, or target-biology dossier field names that are ALREADY PRESENT in "
    "the evidence package shown to you. You may NOT introduce ANY fact, frequency, dependency, "
    "compound, or claim from prior knowledge of the named gene — even if you recognise the target. If "
    "you cannot refute a clause from the package's OWN fields, you MUST mark it refuted=false and say "
    "the clause survives. A refutation citing anything not in the package is invalid.\n\n"
    "IMPORTANT: if a clause ITSELF already surfaces the tension you would raise (it lists the "
    "contradicting line in contradicting_citations or states the tension), it is NOT refuted — an "
    "acknowledged tension is honest reasoning, not an over-reach.\n\n"
    "For each clause return: refuted (bool), refutation (the specific evidence-grounded reason, or '' "
    "if it survives), and cited (the EXACT package tokens your refutation rests on — card_ids / "
    "sub-verdict names / rule_ids / PMIDs / dossier field names)."
)


def _skeptic_schema(clause_names: list) -> dict:
    return {
        "type": "object",
        "properties": {
            "clauses": {"type": "array", "items": {"type": "object", "properties": {
                "clause": {"type": "string", "enum": clause_names},
                "refuted": {"type": "boolean"},
                "refutation": {"type": "string"},
                "cited": {"type": "array", "items": {"type": "string"}}},
                "required": ["clause", "refuted", "refutation", "cited"]}},
        },
        "required": ["clauses"],
    }


def _clause_block(hyp: dict):
    """Extract the assertive clauses {name: {statement, citations}} from a hypothesis result."""
    clauses = {}
    h = hyp.get("hypothesis", hyp)   # accept the full result OR the inner hypothesis dict
    for k in CLAUSE_KEYS:
        c = hc._uv(h.get(k)) or {}
        c = c if isinstance(c, dict) else {}
        stmt = hc._scalar(c.get("statement"))
        if stmt is None:
            continue
        cites = list(c.get("citations") or []) + list(c.get("contradicting_citations") or [])
        clauses[k] = {"statement": stmt, "citations": cites}
    return list(clauses.keys()), clauses


def _evidence_block(panel: dict) -> str:
    """The SAME evidence surface the integrator saw — the only thing the skeptic may cite."""
    parts = [
        "EVIDENCE PACKAGE (refute ONLY from these fields; cite the exact token):",
        f"PANEL — deterministic verdict per line:\n{json.dumps(panel['conviction'], indent=1, default=str)}",
        f"PANEL — per-card interpretation (card_id -> call):\n{json.dumps(panel['cards_brief'], indent=1, default=str)}",
    ]
    if panel.get("dossier"):
        parts.append(f"TARGET-BIOLOGY dossier fields:\n{json.dumps(panel['dossier'], indent=1, default=str)}")
    if panel.get("risk"):
        parts.append(f"GROUNDED literature risk reads:\n{json.dumps(panel['risk'], indent=1, default=str)}")
    return "\n\n".join(parts)


def adversarial_survival(hypothesis_result: dict, pkg_path: str, risk_path=None,
                         dossier_path=None, n_skeptics: int = N_SKEPTICS,
                         synthesize_fn=None) -> dict:
    """Run n_skeptics refutation passes over the hypothesis clauses; return per-clause survival + score.
    `synthesize_fn` is injectable for offline testing (mirrors run.run)."""
    synth = synthesize_fn or R._default_synthesize()
    panel = hc.assemble(pkg_path, risk_path, dossier_path, "modality_agnostic")
    surface = panel["citation_surface"]
    clause_names, clauses = _clause_block(hypothesis_result)
    if not clause_names:
        return {"score": None, "n_clauses": 0, "clauses": {}, "note": "no assertive clauses found"}

    clause_prompt = "\n\n".join(
        f"CLAUSE `{k}`:\n  statement: {c['statement']}\n  cites: {json.dumps(c['citations'], default=str)}"
        for k, c in clauses.items())
    user = (f"{_evidence_block(panel)}\n\n"
            f"HYPOTHESIS CLAUSES TO ATTACK:\n{clause_prompt}\n\n"
            "For every clause, attempt refutation from the evidence package ONLY. "
            "Return one entry per clause.")
    schema = _skeptic_schema(clause_names)

    tally = {k: [] for k in clause_names}
    for i in range(n_skeptics):
        out = synth(SKEPTIC_SYSTEM, user, "skeptic_refutation", schema, max_tokens=6000)
        for entry in R._objs(out.get("clauses")):
            name = hc._scalar(entry.get("clause"))
            if name not in tally:
                continue
            refuted = bool(hc._scalar(entry.get("refuted")))
            cited = [str(x) for x in (entry.get("cited") or [])]
            untraceable = hc.check_traceability(cited, surface)   # CONTAINMENT: recall is discarded
            contained = refuted and bool(cited) and not untraceable
            tally[name].append({
                "skeptic": i, "refuted": refuted,
                "refutation": hc._scalar(entry.get("refutation")) or "",
                "cited": cited, "containment_valid": bool(contained),
                "untraceable_citations": untraceable,
            })

    clause_results, n_survive = {}, 0
    for k in clause_names:
        votes = tally[k]
        valid_refutations = sum(1 for v in votes if v["containment_valid"])
        survives = valid_refutations < 2   # refuted by a MAJORITY of 3 => not survived
        if survives:
            n_survive += 1
        clause_results[k] = {"survives": survives, "valid_refutations": valid_refutations,
                             "n_skeptics": len(votes), "skeptics": votes}
    score = round(n_survive / len(clause_names), 3)
    return {"score": score, "n_clauses": len(clause_names),
            "n_surviving": n_survive, "clauses": clause_results}


def adversarial_survival_gate(result: dict, threshold: float = DEFAULT_THRESHOLD) -> dict:
    """Turn a survival result into a pass/flag GATE decision. A hypothesis whose survival is below
    threshold is FLAGGED (not clean-shipped on traceability alone)."""
    score = result.get("score")
    below = sorted(k for k, c in (result.get("clauses") or {}).items() if not c.get("survives"))
    passed = score is not None and score >= threshold
    return {"passed": bool(passed), "score": score, "threshold": threshold,
            "below_threshold": (score is not None and score < threshold),
            "non_surviving_clauses": below}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-package", required=True)
    ap.add_argument("--hypothesis", required=True, help="cross-evidence-hypothesis hypothesis.json")
    ap.add_argument("--risk", default=None)
    ap.add_argument("--target-dossier", default=None)
    ap.add_argument("--n-skeptics", type=int, default=N_SKEPTICS)
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    hyp = json.loads(Path(args.hypothesis).read_text())
    r = adversarial_survival(hyp, args.evidence_package, args.risk, args.target_dossier,
                             args.n_skeptics)
    gate = adversarial_survival_gate(r, args.threshold)
    r["gate"] = gate
    print(f"\n=== adversarial-survival: {hyp.get('target')} / {hyp.get('indication')} ===")
    print(f"SCORE {r['score']}  ({r.get('n_surviving')}/{r['n_clauses']} clauses survive "
          f"{args.n_skeptics} skeptics)  GATE={'PASS' if gate['passed'] else 'FLAG'} "
          f"(threshold {args.threshold})")
    for k, c in r["clauses"].items():
        flag = "SURVIVES" if c["survives"] else "REFUTED"
        print(f"  [{flag}] {k}: {c['valid_refutations']}/{c['n_skeptics']} valid refutations")
        for s in c["skeptics"]:
            if s["refuted"]:
                mark = "valid" if s["containment_valid"] else "DISCARDED (uncontained)"
                print(f"       - skeptic{s['skeptic']} ({mark}): {s['refutation'][:160]}")
    if args.out:
        Path(args.out).write_text(json.dumps(r, indent=2, default=str))
        print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
