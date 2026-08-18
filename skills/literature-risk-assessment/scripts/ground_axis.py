#!/usr/bin/env python3
"""ground_axis — per-subskill GROUNDED SUBSTRATE reader (design: grounded-substrate two-projection).

Augments ONE subskill/axis's deterministic cards with literature evidence, as ESCALATE-ONLY LIABILITY
FINDINGS — specific, PMID-traceable liabilities the narrow deterministic verdict may miss. It does NOT
emit a LOW/MED/HIGH score: a re-scored bin anchored to a narrow verdict propagates that verdict's
blindness (the FOLR1 safety false-LOW: on-target gnomAD read = "tolerant" while the ADC's real ocular /
normal-tissue liability lives elsewhere). Emitting liability FINDINGS instead is escalate-only by
construction — the grounded read can RAISE a concern, never lower a deterministic one. Downstream
consumers (risk roll-up, hypothesis) weigh the findings; this layer only SURFACES them.

Output = the `grounded` block of a substrate record:
  { axis, deterministic:{verdict, driving_rule_id, cards:{id:call}},
    grounded:{ liability_findings:[{liability, organ_or_class, cited_pmids}], corroborations,
               contradicts_deterministic, anchor_verdict, confabulated_dropped, corpus_pin,
               escalate_only:true, n_retrieved } }

Retrieval + confab-containment reuse this skill's pubmed_search + the _skills_common LLM layer.
Scope note: the escalate-only LIABILITY contract is validated on the SAFETY axis; other axes reuse the
same machinery with an axis-appropriate finding contract (follow-on).
"""
from __future__ import annotations
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
_SKILLS = _HERE.parents[2]
if str(_SKILLS) not in sys.path:
    sys.path.insert(0, str(_SKILLS))

# Per-axis card sets whose deterministic calls the grounded read contextualizes. Safety spans the
# on-target-safety cards PLUS the cross-axis normal-tissue signals (surface/selectivity) — because
# safety is a modality-conditioned conjunction, not the on-target axis alone.
AXIS_CARDS = {
    "safety": ["gnomad-lof-constraint", "normal-tissue-liability-gtex", "clingen-dosage",
               "mouse-ko-phenotype", "clinvar-pathogenicity-safety", "gene-burden-safety",
               "target-safety-prioritisation", "sc-normal-celltype-expression",
               "modality-therapeutic-window", "shed-ectodomain-liability"],
}
_PUBMED_CATEGORY = {"safety": "safety"}

SYSTEM = ("You are a retrieval-grounded safety analyst. Use ONLY the provided abstracts. Cite ONLY "
          "PMIDs that appear in them. NEVER cite from memory. If the abstracts do not support a "
          "liability, do not invent one.")

TOOL_SCHEMA = {"type": "object", "properties": {
    "liability_findings": {"type": "array", "items": {"type": "object", "properties": {
        "liability": {"type": "string"}, "organ_or_class": {"type": "string"},
        "cited_pmids": {"type": "array", "items": {"type": "string"}}},
        "required": ["liability", "organ_or_class", "cited_pmids"]}},
    "corroborations_of_deterministic": {"type": "array", "items": {"type": "string"}},
    "contradicts_deterministic": {"type": "boolean"}, "notes": {"type": "string"}},
    "required": ["liability_findings", "corroborations_of_deterministic",
                 "contradicts_deterministic", "notes"]}


def _uv(x):
    """Unwrap the structured-output field wrapper {"value":..., "_source":..., "_model_id":...}."""
    return x["value"] if isinstance(x, dict) and "value" in x else x


def build_grounded_block(det: dict, llm_out: dict, retrieved_pmids: set, *,
                         corpus_pin: dict, n_retrieved: int) -> dict:
    """PURE (offline-testable): parse the LLM output into the escalate-only grounded block, dropping
    any cited PMID NOT in the retrieved set (confabulation containment)."""
    kept, dropped = [], []
    for f in (_uv(llm_out.get("liability_findings")) or []):
        if isinstance(f, str):
            f = {"liability": f, "organ_or_class": "", "cited_pmids": []}
        cites = _uv(f.get("cited_pmids")) or []
        good = [str(p) for p in cites if str(p) in retrieved_pmids]
        dropped += [str(p) for p in cites if str(p) not in retrieved_pmids]
        kept.append({"liability": _uv(f.get("liability")),
                     "organ_or_class": _uv(f.get("organ_or_class")), "cited_pmids": good})
    return {"liability_findings": kept,
            "corroborations": _uv(llm_out.get("corroborations_of_deterministic")) or [],
            "contradicts_deterministic": _uv(llm_out.get("contradicts_deterministic")),
            "anchor_verdict": det.get("verdict"), "confabulated_dropped": dropped,
            "corpus_pin": corpus_pin, "escalate_only": True, "n_retrieved": n_retrieved}


def deterministic_block(pkg: dict, axis: str) -> dict:
    sv = pkg["synthesis"]["sub_verdicts"].get(axis, {})
    calls = {c["card_id"]: c.get("interpretation_call") for c in pkg.get("cards", []) if c.get("card_id")}
    return {"verdict": sv.get("verdict"), "driving_rule_id": sv.get("driving_rule_id"),
            "cards": {k: calls.get(k) for k in AXIS_CARDS.get(axis, []) if k in calls}}


def _prompt(target, indication, anchor, abstracts):
    lines = [f"{('SAFETY')}-axis grounding for {target} in {indication}.",
             f"\nDETERMINISTIC on-target verdict (ANCHOR, context only): {anchor}",
             "This is a NARROW human-genetics/gnomAD on-target read. It can MISS modality- and "
             "tissue-specific liabilities (on-target normal-tissue tox, off-target/secondary "
             "pharmacology, immunogenicity, ADC payload/ocular/hepatic).",
             "\nTASK: from the abstracts ONLY, extract specific SAFETY LIABILITIES. Each finding is "
             "ESCALATE-ONLY — it may RAISE safety concern; you may NOT use the literature to LOWER "
             "the concern or conclude 'manageable/low risk'. Report the liability + the organ/class "
             "+ its PMIDs. Name the organ for any on-target normal-tissue tox. Flag if the literature "
             "CONTRADICTS the deterministic verdict.\n\nABSTRACTS:"]
    for a in abstracts:
        lines.append(f"[PMID {a.pmid}] {a.title}\n{(a.abstract or '')[:900]}")
    return "\n".join(lines)


def ground_axis(target: str, indication: str, pkg_path: str, *, axis: str = "safety",
                mindate: str = "2015", maxdate: str = "2026", per_cat: int = 8) -> dict:
    """LIVE: load the axis's deterministic block, retrieve literature, and produce the grounded block."""
    import json
    import pubmed_search as ps
    from _skills_common.llm import synthesize_structured
    if axis not in AXIS_CARDS:
        raise ValueError(f"axis {axis!r} not yet supported; have {sorted(AXIS_CARDS)}")
    pkg = json.loads(Path(pkg_path).read_text())
    det = deterministic_block(pkg, axis)
    key = indication.strip().lower()
    if key not in ps.DISEASE_TERMS:
        ps.DISEASE_TERMS[key] = indication      # passthrough term for arbitrary indications
    res = ps.search_pubmed(target, key, abstracts_per_category=per_cat, mindate=mindate, maxdate=maxdate)
    abstracts = res.abstracts_by_category.get(_PUBMED_CATEGORY[axis], [])
    retrieved = {a.pmid for a in abstracts}
    out = synthesize_structured(SYSTEM, _prompt(target, indication, det["verdict"], abstracts),
                                "axis_liabilities", TOOL_SCHEMA)
    grounded = build_grounded_block(det, out, retrieved,
                                    corpus_pin={"mindate": mindate, "maxdate": maxdate},
                                    n_retrieved=len(abstracts))
    return {"axis": axis, "deterministic": det, "grounded": grounded}


if __name__ == "__main__":
    import argparse, json
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--evidence-package", required=True)
    ap.add_argument("--axis", default="safety")
    ap.add_argument("--mindate", default="2015"); ap.add_argument("--maxdate", default="2026")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    rec = ground_axis(a.target, a.indication, a.evidence_package, axis=a.axis,
                      mindate=a.mindate, maxdate=a.maxdate)
    if a.out:
        Path(a.out).write_text(json.dumps(rec, indent=2))
    print(json.dumps(rec, indent=2))
