#!/usr/bin/env python3
"""ground_axis — per-subskill GROUNDED SUBSTRATE reader (grounded-substrate two-projection design).

Augments ONE subskill/axis's deterministic cards with literature as ESCALATE-ONLY FINDINGS —
specific, PMID-traceable evidence that RAISES that axis's risk (a liability, or evidence weakening the
axis's positive case), which the narrow deterministic verdict may miss. It does NOT emit a LOW/MED/HIGH
score: a re-scored bin anchored to a narrow verdict propagates that verdict's blindness (FOLR1 safety
false-LOW). Emitting escalate-only FINDINGS avoids that structurally — the read can RAISE a concern,
never lower a deterministic one. Downstream consumers (risk roll-up, hypothesis) weigh the findings;
this layer only SURFACES them.

The contract is AXIS-PARAMETERIZED (AXIS_CONFIG): the STRUCTURE is identical across axes (escalate-only
findings + corroborations + a contradicts flag + confab-containment); only the finding NOUN + the KINDS
to look for differ. Validated axes: safety (findings = liabilities: ocular/normal-tissue tox, off-target,
immunogenicity) and dependency (findings = dependency-weakening: resistance, context-dependence, paralog
buffering, feedback). Add an axis by extending AXIS_CONFIG.

Output = the `grounded` block of a substrate record consumed by both the risk roll-up and the hypothesis:
  { axis, deterministic:{verdict, driving_rule_id, cards:{id:call}},
    grounded:{ findings:[{finding, kind, cited_pmids}], corroborations, contradicts_deterministic,
               anchor_verdict, confabulated_dropped, corpus_pin, escalate_only:true, n_retrieved } }
"""
from __future__ import annotations
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
_SKILLS = _HERE.parents[1]        # .../skills (so `import _skills_common` resolves)
if str(_SKILLS) not in sys.path:
    sys.path.insert(0, str(_SKILLS))

# Per-axis config. cards = deterministic cards the grounded read contextualizes; pubmed_category = which
# of the retrieval categories to read; verdict_key = sub_verdicts key; noun/kinds shape the extraction.
AXIS_CONFIG = {
    "safety": {
        "verdict_key": "safety", "pubmed_category": "safety",
        "cards": ["gnomad-lof-constraint", "normal-tissue-liability-gtex", "clingen-dosage",
                  "mouse-ko-phenotype", "clinvar-pathogenicity-safety", "gene-burden-safety",
                  "target-safety-prioritisation", "sc-normal-celltype-expression",
                  "modality-therapeutic-window", "shed-ectodomain-liability"],
        "finding_noun": "SAFETY LIABILITY",
        "kinds": ("on-target normal-tissue tox (NAME the organ), off-target/secondary pharmacology, "
                  "immunogenicity, ADC payload/ocular/hepatic")},
    "dependency": {
        "verdict_key": "dependency", "pubmed_category": "biological",
        "cards": ["pan-cancer-crispr-dependency-distribution", "pan-cancer-rnai-dependency-distribution",
                  "crispr-rnai-dependency-concordance", "dependency-lineage-selectivity",
                  "paralog-buffering", "partner-conditional-dependency", "cross-consortium-dependency"],
        "finding_noun": "DEPENDENCY-WEAKENING finding",
        "kinds": ("acquired/adaptive RESISTANCE, CONTEXT-dependence (works only in a subset), "
                  "PARALOG/redundancy buffering, FEEDBACK reactivation, or failure of the dependency "
                  "IN VIVO vs in vitro")},
    "selectivity": {
        "verdict_key": "selectivity", "pubmed_category": "safety",
        "cards": ["tumor-vs-normal-selectivity", "modality-therapeutic-window",
                  "sc-normal-celltype-expression", "tumor-vs-normal-percentile-crossing"],
        "finding_noun": "TUMOR-SELECTIVITY-WEAKENING finding",
        "kinds": ("reported NORMAL-TISSUE expression of the target, on-target normal-tissue/BYSTANDER "
                  "toxicity, lack of a tumor-vs-normal therapeutic WINDOW, or antigen expression on "
                  "CRITICAL normal cells")},
    "surface_modality": {
        "verdict_key": "surface_modality", "pubmed_category": "druggability",
        "cards": ["adc-tce-modality-fit", "surfaceome-family-classification", "surface-topology-and-ptm",
                  "shed-ectodomain-liability", "surface-abundance-density", "protein-surface-evidence"],
        "finding_noun": "SURFACE-MODALITY-WEAKENING finding",
        "kinds": ("antigen SHEDDING (soluble antigen sink), poor/absent INTERNALIZATION, tumor "
                  "HETEROGENEITY of surface expression, LOW surface density, or lack of a validated "
                  "biologics format")},
    "tractability_sm": {
        "verdict_key": "tractability_sm", "pubmed_category": "druggability",
        "cards": ["known-drug-tractability", "structure-features-static", "measured-potency-tractability",
                  "prism-compound-activity", "degradation-feasibility"],
        "finding_noun": "SMALL-MOLECULE-TRACTABILITY-WEAKENING finding",
        "kinds": ("lack of a druggable POCKET / intrinsically-disordered / undruggable, poor PK or "
                  "cell/CNS permeability, or resistance to chemical inhibition")},
}

SYSTEM = ("You are a retrieval-grounded analyst. Use ONLY the provided abstracts. Cite ONLY PMIDs that "
          "appear in them. NEVER cite from memory. If the abstracts do not support a finding, do not "
          "invent one.")

TOOL_SCHEMA = {"type": "object", "properties": {
    "findings": {"type": "array", "items": {"type": "object", "properties": {
        "finding": {"type": "string"}, "kind": {"type": "string"},
        "cited_pmids": {"type": "array", "items": {"type": "string"}}},
        "required": ["finding", "kind", "cited_pmids"]}},
    "corroborations": {"type": "array", "items": {"type": "string"}},
    "contradicts_deterministic": {"type": "boolean"}, "notes": {"type": "string"}},
    "required": ["findings", "corroborations", "contradicts_deterministic", "notes"]}


def _uv(x):
    """Unwrap the structured-output field wrapper {"value":..., "_source":..., "_model_id":...}."""
    return x["value"] if isinstance(x, dict) and "value" in x else x


def build_grounded_block(det: dict, llm_out: dict, retrieved_pmids: set, *,
                         corpus_pin: dict, n_retrieved: int) -> dict:
    """PURE (offline-testable): parse the LLM output into the escalate-only grounded block, dropping
    any cited PMID NOT in the retrieved set (confabulation containment). Axis-agnostic."""
    kept, dropped = [], []
    for f in (_uv(llm_out.get("findings")) or []):
        if isinstance(f, str):
            f = {"finding": f, "kind": "", "cited_pmids": []}
        cites = _uv(f.get("cited_pmids")) or []
        good = [str(p) for p in cites if str(p) in retrieved_pmids]
        dropped += [str(p) for p in cites if str(p) not in retrieved_pmids]
        kept.append({"finding": _uv(f.get("finding")), "kind": _uv(f.get("kind")), "cited_pmids": good})
    return {"findings": kept, "corroborations": _uv(llm_out.get("corroborations")) or [],
            "contradicts_deterministic": _uv(llm_out.get("contradicts_deterministic")),
            "anchor_verdict": det.get("verdict"), "confabulated_dropped": dropped,
            "corpus_pin": corpus_pin, "escalate_only": True, "n_retrieved": n_retrieved}


def deterministic_block(pkg: dict, axis: str) -> dict:
    cfg = AXIS_CONFIG[axis]
    sv = pkg["synthesis"]["sub_verdicts"].get(cfg["verdict_key"], {})
    calls = {c["card_id"]: c.get("interpretation_call") for c in pkg.get("cards", []) if c.get("card_id")}
    return {"verdict": sv.get("verdict"), "driving_rule_id": sv.get("driving_rule_id"),
            "cards": {k: calls.get(k) for k in cfg["cards"] if k in calls}}


def _prompt(target, indication, axis, anchor, abstracts):
    cfg = AXIS_CONFIG[axis]
    lines = [f"{axis.upper()}-axis grounding for {target} in {indication}.",
             f"\nDETERMINISTIC {axis} verdict (ANCHOR, context only): {anchor}",
             "This is a NARROW deterministic read and may MISS what the literature reports.",
             f"\nTASK: from the abstracts ONLY, extract each specific {cfg['finding_noun']}. "
             f"Kinds to look for: {cfg['kinds']}.",
             "Each finding is ESCALATE-ONLY — it may RAISE this axis's risk; you may NOT use the "
             "literature to LOWER the deterministic concern or conclude the axis is fine. Report the "
             "finding + its kind + its PMIDs. Flag if the literature CONTRADICTS the deterministic "
             "verdict.\n\nABSTRACTS:"]
    for a in abstracts:
        lines.append(f"[PMID {a.pmid}] {a.title}\n{(a.abstract or '')[:900]}")
    return "\n".join(lines)


def ground_axis(target: str, indication: str, pkg_path: str, *, axis: str = "safety",
                mindate: str = "2015", maxdate: str = "2026", per_cat: int = 8) -> dict:
    """LIVE: load the axis's deterministic block, retrieve literature, produce the grounded block."""
    import json
    import pubmed_search as ps
    from _skills_common.llm import synthesize_structured
    if axis not in AXIS_CONFIG:
        raise ValueError(f"axis {axis!r} not configured; have {sorted(AXIS_CONFIG)}")
    cfg = AXIS_CONFIG[axis]
    pkg = json.loads(Path(pkg_path).read_text())
    det = deterministic_block(pkg, axis)
    key = indication.strip().lower()
    if key not in ps.DISEASE_TERMS:
        ps.DISEASE_TERMS[key] = indication      # passthrough term for arbitrary indications
    res = ps.search_pubmed(target, key, abstracts_per_category=per_cat, mindate=mindate, maxdate=maxdate)
    abstracts = res.abstracts_by_category.get(cfg["pubmed_category"], [])
    retrieved = {a.pmid for a in abstracts}
    out = synthesize_structured(SYSTEM, _prompt(target, indication, axis, det["verdict"], abstracts),
                                "axis_findings", TOOL_SCHEMA)
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
    ap.add_argument("--axis", default="safety", choices=sorted(AXIS_CONFIG))
    ap.add_argument("--mindate", default="2015"); ap.add_argument("--maxdate", default="2026")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    rec = ground_axis(a.target, a.indication, a.evidence_package, axis=a.axis,
                      mindate=a.mindate, maxdate=a.maxdate)
    if a.out:
        Path(a.out).write_text(json.dumps(rec, indent=2))
    print(json.dumps(rec, indent=2))
