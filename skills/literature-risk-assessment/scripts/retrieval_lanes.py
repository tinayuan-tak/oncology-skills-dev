#!/usr/bin/env python3
"""retrieval_lanes — the SHARED multi-lane PubMed retriever for literature-risk-assessment.

Extracted (PR-2, 2026-09-08) from ground_axis.py so BOTH entrypoints — the per-axis grounded substrate
(`ground_axis.py`) AND the 6-dimension risk agent (`run.py`) — retrieve literature through ONE
collision-immune, starvation-resistant path instead of two divergent ones. `run.py` previously used the
weak single-lane keyword search (`pubmed_search.search_pubmed`), which suffers exactly the gene-symbol
collision (ME3 → trimethylation papers) and starvation (STAG1) failure modes this retriever fixes.

The retriever is a round-robin UNION of three lanes, each submitting two engine-aware query ANGLES:
  - entity lane (PubTator3): entity-normalized (@GENE_<entrez>), tight + broad angles — collision-immune.
  - OT reproducible-floor lane: the pinned, offline, entity-normalized literature floor (never-empty,
    axis-re-ranked) — a reproducible anchor where the live lanes starve/mis-retrieve.
  - keyword lane (E-utilities): tight + a COMPLEMENTARY MeSH-anchored (else broad) angle.
All lanes best-effort: a source outage / missing analysis-methods contributes nothing (others stand).
Query/dedup/interleave logic is PURE and unit-tested (test_retrieval_lanes.py).

Disease vocabulary is unified on Stack A's `_skills_common/literature_retrieval._INDICATION_PHRASE`
(40-code OncoTree/TCGA crosswalk) via `resolve_disease_terms`, replacing the crc/nsclc-only DISEASE_TERMS.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
_SKILLS = _HERE.parents[1]  # .../skills (so `import _skills_common` resolves)
if str(_SKILLS) not in sys.path:
    sys.path.insert(0, str(_SKILLS))

# Retrieval widening (entity-collision + starvation fix). Union an ENTITY-normalized PubTator lane with
# the keyword E-utilities lane, and soft-broaden EITHER lane when its tight axis-scoped query starves.
RETRIEVAL_FLOOR = 3  # below this a lane is "starved" -> retry with the broad query
MAX_RETRIEVED = 18  # cap the unioned abstract set fed to the model (lanes interleaved)

# TARGETED per-axis PubMed term clauses. `disease_scoped=False` for target-LEVEL axes (safety /
# tractability_sm / surface_modality / druggability — constraint/structure/surface biology are
# indication-independent), else the disease is AND-ed in.
#
# The first block is the grounded-substrate axis set (ground_axis). The second block adds the three
# 6-dimension risk-agent dims that are not already present as axis names (safety/clinical/commercial are
# shared 1:1); biological/druggability/translational port the intent of the retired
# pubmed_search.SEARCH_PATTERNS_BY_CATEGORY so run.py retrieves through the same lanes.
AXIS_PUBMED_TERMS = {
    "safety": ("toxicity OR adverse event OR normal tissue OR knockout mouse OR on-target", False),
    "dependency": ("genetic dependency OR essentiality OR CRISPR knockout OR knockdown OR RNAi", True),
    "selectivity": ("normal tissue expression OR tumor-specific OR on-target toxicity OR therapeutic window", True),
    "surface_modality": (
        "cell surface OR internalization OR shed ectodomain OR antibody-drug conjugate OR surface antigen",
        False,
    ),
    "tractability_sm": ("small molecule OR inhibitor OR druggable OR binding pocket OR crystal structure", False),
    "mechanism": ("signaling OR pathway OR mechanism OR phosphorylation OR downstream effector", True),
    "genomic_alteration": ("mutation OR amplification OR deletion OR fusion OR oncogenic driver", True),
    "differentiation": (
        "co-mutation OR mutual exclusivity OR prognosis OR molecular subtype OR patient stratification",
        True,
    ),
    "expression": ("expression OR overexpression OR RNA-seq OR protein abundance OR immunohistochemistry", True),
    "clinical": ("clinical trial OR patient OR phase I OR phase II OR discontinued", True),
    "commercial": ("therapeutic OR drug development OR competitive landscape OR approved", True),
    # --- 6-dimension risk-agent dims (run.py) not already covered by an axis name above ---
    "biological": (
        "validation OR knockdown OR knockout OR CRISPR OR genetic association OR oncogene addiction",
        True,
    ),
    "druggability": (
        "drug target OR inhibitor OR antibody OR small molecule OR crystal structure OR druggable",
        False,
    ),
    "translational": ("biomarker OR PDX OR organoid OR patient-derived model OR animal model", True),
}

# OncoTree/panel subtype code -> crosswalk canonical_code (for the MeSH lookup); mirrors the
# analysis-methods reader's INDICATION_ALIAS.
_INDICATION_ALIAS = {"LUAD": "NSCLC", "LUSC": "NSCLC", "DLBCL": "DLBC", "LAML": "AML"}


def resolve_disease_terms(indication: str) -> str:
    """Disease free-text expansion for retrieval. Prefers Stack A's shared `_INDICATION_PHRASE` (the
    40-code OncoTree/TCGA crosswalk used across the fan-out skills), keyed by the UPPER-cased indication
    code; falls back to the raw indication string (so a free-text indication like "ovarian cancer" passes
    through unchanged). Replaces the crc/nsclc-only DISEASE_TERMS special-case. Best-effort import."""
    code = (indication or "").strip()
    try:
        from _skills_common.literature_retrieval import _INDICATION_PHRASE

        return _INDICATION_PHRASE.get(code.upper(), code)
    except Exception:  # noqa: BLE001 — Stack A always present, but never let a vocab lookup break retrieval
        return code


# ── pure query construction / merge helpers (unit-tested) ────────────────────────────────────────────
def _axis_query(target: str, disease_terms: str, axis: str, *, broad: bool = False) -> str:
    """PURE: build the TARGETED PubMed query for an axis — (gene) [AND (disease)] AND (axis terms).
    Disease is AND-ed only for indication-conditioned axes (AXIS_PUBMED_TERMS[axis][1]). `broad=True`
    drops the axis-term conjunction (the soft-fallback used when the tight query starves), keeping only
    (gene) [AND (disease)]."""
    terms, disease_scoped = AXIS_PUBMED_TERMS.get(axis, ("", True))
    if disease_scoped and disease_terms:
        return f"({target}) AND ({disease_terms})" + ("" if broad else f" AND ({terms})")
    return f"({target})" + ("" if broad else f" AND ({terms})")


def _dedup(pmids) -> list:
    """PURE: order-preserving de-duplication (entity-lane hits kept ahead of keyword-lane)."""
    seen, out = set(), []
    for p in pmids:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _interleave(*lanes) -> list:
    """PURE: round-robin merge of ranked lane lists, then de-dup. Round-robin (not concat) so every lane
    is represented within MAX_RETRIEVED even when an earlier lane is long."""
    out = []
    for i in range(max((len(lane) for lane in lanes), default=0)):
        for lane in lanes:
            if i < len(lane):
                out.append(lane[i])
    return _dedup(out)


def _mesh_disease_clause(indication: str) -> str | None:
    """Best-effort: framework indication code -> a PubMed MeSH-anchored disease clause
    ('"colorectal neoplasms"[MeSH Terms]') from the indication_crosswalk `mesh_terms` lane. Used as the
    keyword lane's precision ANGLE (MeSH helps E-utilities; it BREAKS PubTator, so the entity lane never
    gets it). None when no crosswalk/lane/term."""
    import os
    from pathlib import Path as _P

    try:
        import yaml

        root = os.environ.get(
            "TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"
        )
        path = _P(root) / "vocabularies" / "indication_crosswalk.yaml"
        doc = yaml.safe_load(path.read_text()) or {}
        code = (indication or "").strip().upper()
        code = _INDICATION_ALIAS.get(code, code)
        for e in doc.get("indications", []):
            if str(e.get("canonical_code", "")).upper() == code:
                mesh = (e.get("mesh_terms") or [None])[0]
                return f'"{mesh}"[MeSH Terms]' if mesh else None
    except Exception:  # noqa: BLE001
        return None
    return None


def _keyword_angles(target: str, disease_terms: str, axis: str, mesh_clause, *, disease_scoped: bool) -> list:
    """PURE: the keyword lane's TWO complementary query angles — tight (axis terms) + either a
    MeSH-anchored disease angle (precision; disease-scoped axes with a MeSH term) or a broad angle
    (recall; drops axis terms). Distinct from the entity lane's tight+broad so the two live lanes ask
    complementary questions."""
    angles = [_axis_query(target, disease_terms, axis)]
    if disease_scoped and mesh_clause:
        angles.append(_axis_query(target, mesh_clause, axis))
    else:
        angles.append(_axis_query(target, disease_terms, axis, broad=True))
    return angles


# ── live lanes ────────────────────────────────────────────────────────────────────────────────────
def _ot_floor_pmids(target: str, indication: str, per_cat: int, axis_terms: str = "") -> list:
    """OT reproducible-floor lane (best-effort): the pinned, offline, entity-normalized literature floor
    (analysis-methods opentargets_literature_floor over opentargets-literature-per-target-v2). Never-empty
    and collision-free where the live keyword lane starves/mis-retrieves; if analysis-methods is
    unavailable it contributes nothing. `axis_terms` re-ranks the floor's rows by axis relevance."""
    try:
        from methods.opentargets_literature_floor.read import read_literature_floor

        return list(
            read_literature_floor(target, indication, top_n=per_cat, axis_terms=axis_terms or None).get("pmids", [])
            or []
        )
    except TypeError:  # older reader without axis_terms — degrade gracefully
        try:
            from methods.opentargets_literature_floor.read import read_literature_floor

            return list(read_literature_floor(target, indication, top_n=per_cat).get("pmids", []) or [])
        except Exception:  # noqa: BLE001
            return []
    except Exception:  # noqa: BLE001 — best-effort; missing method/product must not break grounding
        return []


def _europepmc_pmids(query: str, *, retmax: int) -> list:
    """Europe PMC lane (best-effort): numeric PMIDs for a query. Reuses Stack A's shared `_search` REST
    wrapper (result_type='lite' → pmid+title). Complements PubMed abstract-only recall with EPMC's
    full-text + preprint index; only MED-sourced records carry a numeric PMID (NCBI-efetch-able), so
    preprint/PPR ids are dropped. HAS_ABSTRACT:Y keeps the hit graded on real abstract text."""
    try:
        from _skills_common.literature_retrieval import _search

        data = _search(f"{query} AND (HAS_ABSTRACT:Y)", page_size=retmax, result_type="lite", timeout=30.0)
        out = []
        for r in ((data or {}).get("resultList") or {}).get("result") or []:
            pmid = str(r.get("pmid") or "")
            if pmid.isdigit():
                out.append(pmid)
            if len(out) >= retmax:
                break
        return out
    except Exception:  # noqa: BLE001 — best-effort; EPMC outage / import failure contributes nothing
        return []


def _retrieve_pmids(
    target: str, disease_terms: str, axis: str, *, per_cat: int, mindate: str, maxdate: str, indication: str = ""
) -> list:
    """Round-robin union of FOUR lanes, each submitting engine-aware query ANGLES (union'd).

    - entity lane (PubTator): tight (axis terms) + broad (recall). Entity-normalized; never gets MeSH.
    - OT-floor lane: pinned/offline reproducible floor, axis-re-ranked.
    - keyword lane (E-utilities): tight + MeSH-anchored disease (else broad). Complementary to the entity lane.
    - Europe PMC lane: tight + broad (NO MeSH — [MeSH Terms] is PubMed syntax, breaks EPMC); full-text +
      preprint index complements PubMed abstract-only recall.
    All lanes best-effort. Query/dedup/interleave logic is pure and unit-tested."""
    import entity_search as es
    import pubmed_search as ps

    terms, disease_scoped = AXIS_PUBMED_TERMS.get(axis, ("", True))

    # -- entity lane (PubTator): tight + broad angles, unioned
    gene_clause = es.resolve_gene_entity(target) or f"({target})"
    pt = _dedup(
        es.pubtator_pmids(
            es.entity_axis_query(gene_clause, disease_terms, terms, disease_scoped=disease_scoped, broad=False),
            retmax=per_cat,
        )
        + es.pubtator_pmids(
            es.entity_axis_query(gene_clause, disease_terms, terms, disease_scoped=disease_scoped, broad=True),
            retmax=per_cat,
        )
    )

    # -- OT reproducible-floor lane (offline, entity-normalized, axis-re-ranked; pinned OT release)
    ot = _ot_floor_pmids(target, indication, per_cat, axis_terms=terms)

    # -- keyword lane (E-utilities): tight + a COMPLEMENTARY 2nd angle (MeSH-anchored, else broad)
    mesh = _mesh_disease_clause(indication) if disease_scoped else None
    kw = []
    for q in _keyword_angles(target, disease_terms, axis, mesh, disease_scoped=disease_scoped):
        kw = _dedup(kw + ps._esearch(q, retmax=per_cat, timeout_s=30.0, mindate=mindate, maxdate=maxdate))

    # -- Europe PMC lane: tight + broad angles (no MeSH clause — that is PubMed-only syntax)
    ep = []
    for q in (_axis_query(target, disease_terms, axis), _axis_query(target, disease_terms, axis, broad=True)):
        ep = _dedup(ep + _europepmc_pmids(q, retmax=per_cat))

    return _interleave(list(pt), list(ot), list(kw), list(ep))[:MAX_RETRIEVED]


# retrieval provenance label recorded in corpus_pin by both callers.
RETRIEVAL_LABEL = "entity_pubtator+ot_literature_floor+keyword_eutils+europepmc"

# ── Stage-2 relevance gate (PR-3): DETERMINISTIC on-axis / on-target precision filter ──────────────
# The lanes maximize RECALL (three sources, tight+broad angles); this gate is the PRECISION lever —
# it drops abstracts that are not substantively about the target on this axis/indication BEFORE they
# reach the model, so the grounded read is enriched with the RIGHT literature, not merely more of it
# (e.g. a KRAS nanoparticle-vaccine paper surfaced under the SAFETY query but discussing no toxicity, or
# a different gene's toxicity paper that only shares the generic axis word). On-signal now requires a
# CONJUNCTION anchored to the target — target ∧ (axis ∨ indication) — not a permissive OR of two weak
# legs (#1615). Verdict-inert CONTEXT + no embeddings in-framework → a deterministic token-match filter
# (mirrors analysis-methods opentargets_literature_floor `_axis_tokens`/`_axis_match`), never a learned
# reranker.
RELEVANCE_FLOOR = 3  # keep at least this many abstracts even if off-axis (never starve the model)


def _axis_tokens(axis_terms: str) -> list:
    """PURE: split an axis OR/AND-clause ('toxicity OR adverse event OR ...') into lowercased phrase
    tokens for substring matching. Mirrors opentargets_literature_floor._axis_tokens."""
    if not axis_terms:
        return []
    raw = re.split(r"\bOR\b|\bAND\b", str(axis_terms))
    return [t.strip().lower() for t in raw if t and t.strip()]


def _axis_match(text: str, tokens: list) -> int:
    """PURE: count how many axis phrase-tokens appear (case-insensitive substring) in the text."""
    if not text or not tokens:
        return 0
    s = text.lower()
    return sum(1 for tok in tokens if tok and tok in s)


def relevance_filter(abstracts: list, target: str, axis: str, *, disease_terms: str = "", floor: int = RELEVANCE_FLOOR):
    """PURE precision gate. Partition retrieved abstracts into (kept, dropped).

    An abstract is ON-SIGNAL only under a CONJUNCTION anchored to the target: its title+abstract must
    NAME the target (word-boundary, case-insensitive) AND additionally be on-axis (≥1 axis phrase-token)
    OR on-indication (≥1 disease phrase-token from `disease_terms`). The prior predicate was a permissive
    OR of two weak legs (any generic axis substring, OR a bare target mention) with no indication and no
    conjunction, so an off-target paper carrying a generic axis word (e.g. a *different* gene's
    `toxicity`) and an off-indication paper merely naming the target both passed as "relevant retrieved."
    Requiring target ∧ (axis ∨ indication) closes both leaks (issue #1615). On-signal abstracts are always
    kept, in incoming (lane-ranked) order.

    Off-signal abstracts are dropped EXCEPT the deliberate relaxed floor: keep from them, in order, until
    at least `floor` abstracts are kept (never starve the model to zero on a thin axis/indication). Each
    dropped record is {pmid, reason} for the corpus-pin audit trail. Order-preserving; never raises."""
    tokens = _axis_tokens(AXIS_PUBMED_TERMS.get(axis, ("", True))[0])
    ind_tokens = _axis_tokens(disease_terms)
    tgt = (target or "").strip().lower()
    tgt_re = re.compile(rf"\b{re.escape(tgt)}\b") if tgt else None

    on_signal, off = [], []
    for a in abstracts:
        text = f"{getattr(a, 'title', '') or ''} {getattr(a, 'abstract', '') or ''}"
        hit_axis = _axis_match(text, tokens) > 0
        hit_ind = _axis_match(text, ind_tokens) > 0
        hit_tgt = bool(tgt_re.search(text.lower())) if tgt_re else False
        on = hit_tgt and (hit_axis or hit_ind)
        (on_signal if on else off).append(a)

    kept = list(on_signal)
    dropped = []
    for a in off:
        if len(kept) < floor:
            kept.append(a)
        else:
            dropped.append(
                {"pmid": getattr(a, "pmid", None), "reason": "off_signal_needs_target_and_axis_or_indication"}
            )
    return kept, dropped


def retrieve_axis(
    target: str,
    indication: str,
    axis: str,
    *,
    per_cat: int = 8,
    mindate: str = "2015",
    maxdate: str = "2026",
    relevance_floor: int = RELEVANCE_FLOOR,
) -> dict:
    """HIGH-LEVEL seam used by BOTH ground_axis.py and run.py: resolve the disease vocabulary, run the
    3-lane union, efetch, then apply the Stage-2 relevance gate. Returns
    {"kept": [PubMedAbstract...], "dropped": [{pmid, reason}...]} — `dropped` is the corpus-pin audit
    trail of off-topic abstracts the gate removed. One function to monkeypatch in offline tests."""
    import pubmed_search as ps

    disease_terms = resolve_disease_terms(indication)
    pmids = _retrieve_pmids(
        target, disease_terms, axis, per_cat=per_cat, mindate=mindate, maxdate=maxdate, indication=indication
    )
    abstracts = ps._efetch_abstracts(pmids, category=axis, timeout_s=30.0) if pmids else []
    kept, dropped = relevance_filter(abstracts, target, axis, disease_terms=disease_terms, floor=relevance_floor)
    return {"kept": kept, "dropped": dropped}


def retrieve_axis_abstracts(
    target: str,
    indication: str,
    axis: str,
    *,
    per_cat: int = 8,
    mindate: str = "2015",
    maxdate: str = "2026",
) -> list:
    """Back-compat thin wrapper over retrieve_axis: returns only the KEPT abstracts (post relevance gate).
    Callers that want the dropped audit trail (run.py / ground_axis corpus_pin) call retrieve_axis."""
    return retrieve_axis(target, indication, axis, per_cat=per_cat, mindate=mindate, maxdate=maxdate)["kept"]
