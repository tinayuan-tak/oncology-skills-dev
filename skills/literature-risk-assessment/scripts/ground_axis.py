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
to look for differ. Every axis is ESCALATE-ONLY in the same sense — a finding WEAKENS that axis's
positive case (raises a concern the narrow deterministic verdict may miss), never lowers one.
Axes now cover ALL of target-profile's indication-conditioned subskills (verdict_key == the SUB_SKILLS
short): the 5 original engine axes (safety, dependency, selectivity, surface_modality, tractability_sm)
+ 6 rolled out 2026-08-18 (mechanism, genomic_alteration, differentiation, synthetic_lethal_partners,
combinatorial_dependency, expression[=tumor-presence]) + 2 engine-blind pseudo-cards (clinical,
commercial). Add an axis by extending AXIS_CONFIG. (target_intrinsic is intentionally NOT grounded here:
it is gateless + indication-INDEPENDENT, so the escalate-the-indication-case frame does not apply.)

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
    # --- ROLLOUT 2026-08-18: the remaining indication-conditioned subskills. Each is ESCALATE-ONLY in
    # the SAME sense as dependency/selectivity — the finding WEAKENS that axis's positive case (raises a
    # concern the narrow deterministic verdict may miss); it can never LOWER a concern. verdict_key ==
    # the target-profile SUB_SKILLS short (tp_fanout). Retrieval reuses an existing pubmed_category
    # (search_pubmed unchanged); the axis-specific extraction is carried by finding_noun + kinds.
    "mechanism": {
        "verdict_key": "mechanism", "pubmed_category": "biological",
        "cards": ["signaling-network-mechanism", "pathway-activity-context", "phospho-pathway-activity",
                  "tahoe-drug-perturbation"],
        "finding_noun": "MECHANISM-DISCORDANCE finding",
        "kinds": ("a CONTRADICTORY pathway role for the target in this context (e.g. reported "
                  "tumor-suppressive where an oncogenic driver role is assumed), CONTEXT-dependent "
                  "signaling, FEEDBACK/BYPASS reactivation that undercuts the proposed mechanism of "
                  "action, or absence of the assumed pathway dependency")},
    "genomic_alteration": {
        "verdict_key": "genomic_alteration", "pubmed_category": "biological",
        "cards": ["alteration-role", "copy-number-distribution", "mutation-hotspot-frequency",
                  "oncogenic-pathway-alteration", "variant-level-interpretation", "functional-gene-state",
                  "fusion-rearrangement-landscape"],
        "finding_noun": "ALTERATION-INTERPRETATION-WEAKENING finding",
        "kinds": ("evidence the recurrent alteration is a PASSENGER not a driver, that the "
                  "amplification/mutation is NOT functionally activating, SUBCLONAL/heterogeneous "
                  "alteration, or CO-OCCURRING alterations that confound attributing the phenotype to "
                  "this target")},
    "differentiation": {
        "verdict_key": "differentiation", "pubmed_category": "translational",
        "cards": ["co-mutation-and-mutual-exclusivity", "expression-clinical-association",
                  "precog-prognostic-association", "pathway-node-leverage", "stemness-context"],
        "finding_noun": "DIFFERENTIATION/PATIENT-SELECTION-WEAKENING finding",
        "kinds": ("a CO-MUTATION that predicts RESISTANCE or poor response, a mutual-exclusivity that "
                  "NARROWS the addressable population, a PROGNOSTIC association OPPOSITE to the "
                  "therapeutic hypothesis, or the lack of a differentiating patient-selection biomarker")},
    "synthetic_lethal_partners": {
        "verdict_key": "synthetic_lethal_partners", "pubmed_category": "biological",
        "cards": ["synthetic-lethal-partners", "partner-conditional-dependency"],
        "finding_noun": "SYNTHETIC-LETHAL-WEAKENING finding",
        "kinds": ("FAILURE of the synthetic-lethal interaction to validate IN VIVO or across models, "
                  "GENOTYPE/context-dependence of the SL, ADAPTIVE RESISTANCE that bypasses it, or the "
                  "SL partner not being pharmacologically ACTIONABLE")},
    "combinatorial_dependency": {
        "verdict_key": "combinatorial_dependency", "pubmed_category": "biological",
        "cards": ["combinatorial-dependency"],
        "finding_noun": "COMBINATION-WEAKENING finding",
        "kinds": ("a combination that is ADDITIVE-not-SYNERGISTIC, combination TOXICITY that closes the "
                  "window, RESISTANCE emerging to the combination, or the co-dependency NOT HOLDING "
                  "across genetic backgrounds")},
    "expression": {
        "verdict_key": "expression", "pubmed_category": "biological",
        "cards": ["tumor-rna-distribution", "tumor-protein-abundance-cptac", "cellline-rna-distribution",
                  "tumor-scrna-celltype-expression", "tumor-rna-vs-adjacent", "tumor-elevation-breadth"],
        "finding_noun": "TUMOR-PRESENCE-WEAKENING finding",
        "kinds": ("reported ABSENCE or LOW/heterogeneous expression of the target in this tumor type, "
                  "RNA-ONLY evidence with no protein confirmation, expression restricted to a MINOR "
                  "subpopulation, or DISCORDANCE across cohorts/assays")},
    # PSEUDO-CARDS: engine-BLIND dims (no deterministic verdict/cards — verdict_key=None). Literature-only
    # NOW; upgradeable later by adding real `cards` (then they gain a deterministic bin like any axis).
    "clinical": {
        "verdict_key": None, "pubmed_category": "clinical", "cards": [], "pseudo_card": True,
        "finding_noun": "CLINICAL-PRECEDENT risk finding",
        "kinds": ("FAILED/DISCONTINUED trials for this target or its antibody/ADC/modality class, clinical "
                  "toxicity signals, negative pivotal readouts, or lack of clinical validation")},
    "commercial": {
        "verdict_key": None, "pubmed_category": "commercial", "cards": [], "pseudo_card": True,
        "finding_noun": "COMMERCIAL risk finding",
        "kinds": ("a CROWDED competitive landscape, approved/late-stage COMPETITORS on the same target/"
                  "pathway, IP/freedom-to-operate concerns, or a small addressable population")},
}
# Controlled per-finding SEVERITY — the SINGLE SOURCE OF TRUTH for pseudo-card (clinical/commercial)
# escalation (decision 2: literature-only, uncalibrated bin for portfolio-sortability). This replaces
# the former free-text `kind` substring-grep, which was fragile-by-construction: it hoped the model's
# prose `kind` happened to contain a token like "toxic"/"crowded", and one escalator ("lack_of") could
# NEVER match natural prose ("lack of clinical validation"). Now the model classifies each finding into
# a fixed enum and risk_rollup bins on exact membership — no substring matching, no drift-prone list.
SEVERITY_LEVELS = ("high", "moderate")   # schema enum (order-stable)
SEVERITY_HIGH = "high"                    # a `severity == SEVERITY_HIGH` finding escalates a pseudo dim

# Per-abstract character budget passed to the model. Raised from the original 900 (which cut most
# oncology abstracts mid-way, dropping the RESULTS/limitations text where escalating findings live) to
# 1500 — closer to a full structured abstract while staying well within the input budget for ~8 items.
ABSTRACT_CHARS = 1500

SYSTEM = ("You are a retrieval-grounded analyst. Use ONLY the provided abstracts. Cite ONLY PMIDs that "
          "appear in them. NEVER cite from memory. If the abstracts do not support a finding, do not "
          "invent one.")

TOOL_SCHEMA = {"type": "object", "properties": {
    "findings": {"type": "array", "items": {"type": "object", "properties": {
        "finding": {"type": "string"}, "kind": {"type": "string"},
        "severity": {"type": "string", "enum": list(SEVERITY_LEVELS)},
        "cited_pmids": {"type": "array", "items": {"type": "string"}}},
        "required": ["finding", "kind", "severity", "cited_pmids"]}},
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
        sev = str(_uv(f.get("severity")) or "moderate").lower()
        if sev not in SEVERITY_LEVELS:  # tolerate a missing/off-enum value from a legacy or bare finding
            sev = "moderate"
        kept.append({"finding": _uv(f.get("finding")), "kind": _uv(f.get("kind")),
                     "severity": sev, "cited_pmids": good})
    return {"findings": kept, "corroborations": _uv(llm_out.get("corroborations")) or [],
            "contradicts_deterministic": _uv(llm_out.get("contradicts_deterministic")),
            "anchor_verdict": det.get("verdict"), "confabulated_dropped": dropped,
            "corpus_pin": corpus_pin, "escalate_only": True, "n_retrieved": n_retrieved}


def deterministic_block(pkg: dict, axis: str) -> dict:
    cfg = AXIS_CONFIG[axis]
    if cfg.get("verdict_key") is None:      # pseudo-card: engine-blind, no deterministic verdict/cards
        return {"verdict": None, "driving_rule_id": None, "cards": {}, "engine_blind": True}
    sv = pkg["synthesis"]["sub_verdicts"].get(cfg["verdict_key"], {})
    calls = {c["card_id"]: c.get("interpretation_call") for c in pkg.get("cards", []) if c.get("card_id")}
    return {"verdict": sv.get("verdict"), "driving_rule_id": sv.get("driving_rule_id"),
            "cards": {k: calls.get(k) for k in cfg["cards"] if k in calls}}


def _prompt(target, indication, axis, anchor, abstracts, abstract_chars: int = ABSTRACT_CHARS):
    cfg = AXIS_CONFIG[axis]
    anchor_line = (f"\nDETERMINISTIC {axis} verdict (ANCHOR, context only): {anchor}"
                   if anchor is not None else
                   f"\nThis is an ENGINE-BLIND pseudo-card dim ({axis}) — NO deterministic engine verdict "
                   "exists; it is LITERATURE-ONLY.")
    lines = [f"{axis.upper()}-axis grounding for {target} in {indication}.",
             anchor_line,
             "The engine may MISS what the literature reports; surface it.",
             f"\nTASK: from the abstracts ONLY, extract each specific {cfg['finding_noun']}. "
             f"Kinds to look for: {cfg['kinds']}.",
             "Each finding is ESCALATE-ONLY — it may RAISE this axis's risk; you may NOT use the "
             "literature to LOWER the deterministic concern or conclude the axis is fine. Report the "
             "finding + its kind + its PMIDs, and rate its SEVERITY: 'high' for a DECISIVE risk (e.g. a "
             "FAILED/DISCONTINUED trial or program, clinical toxicity, a negative pivotal readout, a "
             "crowded landscape with approved/late-stage competitors, or blocking IP); 'moderate' "
             "otherwise. Flag if the literature CONTRADICTS the deterministic verdict.\n\nABSTRACTS:"]
    for a in abstracts:
        lines.append(f"[PMID {a.pmid}] {a.title}\n{(a.abstract or '')[:abstract_chars]}")
    return "\n".join(lines)


# TARGETED per-axis PubMed retrieval (follow-up #3). Previously ground_axis reused the shared
# `pubmed_category` query, so the six target-biology axes (dependency / mechanism / genomic_alteration /
# synthetic_lethal_partners / combinatorial_dependency / expression) all retrieved the SAME 'biological'
# abstracts and only the extraction PROMPT differed. Each axis now gets an axis-specific term clause so
# RETRIEVAL is on-axis too. `disease_scoped=False` for target-LEVEL axes (safety / tractability_sm /
# surface_modality — gnomAD constraint / structure / surface biology are indication-independent), else
# the disease is AND-ed in. (pubmed_category is retained for back-compat + the 6-dim risk agent.)
AXIS_PUBMED_TERMS = {
    "safety": ("toxicity OR adverse event OR normal tissue OR knockout mouse OR on-target", False),
    "dependency": ("genetic dependency OR essentiality OR CRISPR knockout OR knockdown OR RNAi", True),
    "selectivity": ("normal tissue expression OR tumor-specific OR on-target toxicity OR therapeutic window", True),
    "surface_modality": ("cell surface OR internalization OR shed ectodomain OR antibody-drug conjugate OR surface antigen", False),
    "tractability_sm": ("small molecule OR inhibitor OR druggable OR binding pocket OR crystal structure", False),
    "mechanism": ("signaling OR pathway OR mechanism OR phosphorylation OR downstream effector", True),
    "genomic_alteration": ("mutation OR amplification OR deletion OR fusion OR oncogenic driver", True),
    "differentiation": ("co-mutation OR mutual exclusivity OR prognosis OR molecular subtype OR patient stratification", True),
    "synthetic_lethal_partners": ("synthetic lethal OR synthetic lethality OR co-dependency OR paralog buffering", True),
    "combinatorial_dependency": ("combination therapy OR co-targeting OR dual inhibition OR combinatorial dependency", True),
    "expression": ("expression OR overexpression OR RNA-seq OR protein abundance OR immunohistochemistry", True),
    "clinical": ("clinical trial OR patient OR phase I OR phase II OR discontinued", True),
    "commercial": ("therapeutic OR drug development OR competitive landscape OR approved", True),
}


def _axis_query(target: str, disease_terms: str, axis: str) -> str:
    """PURE: build the TARGETED PubMed query for an axis — (gene) [AND (disease)] AND (axis terms).
    Disease is AND-ed only for indication-conditioned axes (AXIS_PUBMED_TERMS[axis][1])."""
    terms, disease_scoped = AXIS_PUBMED_TERMS.get(axis, ("", True))
    if disease_scoped and disease_terms:
        return f"({target}) AND ({disease_terms}) AND ({terms})"
    return f"({target}) AND ({terms})"


def ground_axis(target: str, indication: str, pkg_path: str, *, axis: str = "safety",
                mindate: str = "2015", maxdate: str = "2026", per_cat: int = 8,
                abstract_chars: int = ABSTRACT_CHARS) -> dict:
    """LIVE: load the axis's deterministic block, retrieve literature, produce the grounded block."""
    import json
    import pubmed_search as ps
    from _skills_common.llm import synthesize_structured
    if axis not in AXIS_CONFIG:
        raise ValueError(f"axis {axis!r} not configured; have {sorted(AXIS_CONFIG)}")
    cfg = AXIS_CONFIG[axis]
    pkg = json.loads(Path(pkg_path).read_text())
    det = deterministic_block(pkg, axis)
    # TARGETED single-query retrieval (follow-up #3): one axis-specific query instead of the
    # all-category sweep (no wasted queries, on-axis abstracts). disease_terms = the DISEASE_TERMS
    # expansion when known, else the raw indication (read-only — no global DISEASE_TERMS mutation).
    key = indication.strip().lower()
    disease_terms = ps.DISEASE_TERMS.get(key, indication)
    query = _axis_query(target, disease_terms, axis)
    pmids = ps._esearch(query, retmax=per_cat, timeout_s=30.0, mindate=mindate, maxdate=maxdate)
    abstracts = ps._efetch_abstracts(pmids, category=axis, timeout_s=30.0) if pmids else []
    retrieved = {a.pmid for a in abstracts}
    out = synthesize_structured(SYSTEM, _prompt(target, indication, axis, det["verdict"], abstracts,
                                                abstract_chars=abstract_chars),
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
    ap.add_argument("--per-cat", type=int, default=8,
                    help="abstracts retrieved for the axis query (relevance-ranked; default 8)")
    ap.add_argument("--abstract-chars", type=int, default=ABSTRACT_CHARS,
                    help=f"per-abstract character budget passed to the model (default {ABSTRACT_CHARS})")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    rec = ground_axis(a.target, a.indication, a.evidence_package, axis=a.axis,
                      mindate=a.mindate, maxdate=a.maxdate, per_cat=a.per_cat,
                      abstract_chars=a.abstract_chars)
    if a.out:
        Path(a.out).write_text(json.dumps(rec, indent=2))
    print(json.dumps(rec, indent=2))
