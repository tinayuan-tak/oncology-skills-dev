"""opentargets_literature_floor.read — the pinned, reproducible per-target literature FLOOR.

Answers "what is the top pinned literature for {target} [in {indication}] that a grounded read can
extract from OFFLINE, without a live query?" — the never-empty, entity-normalized floor under the
skills grounded layer's live PubTator+E-utilities lanes. A source-bakeoff (2026-08-24) showed live
keyword retrieval STARVES / mis-retrieves on less-studied and gene-symbol-colliding targets (e.g.
ME3 the gene vs "me3" trimethylation → 9/10 wrong-entity papers → zero findings); this reader draws
from Open Targets' entity-resolved text-mining instead, pinned to the release.

## Composition (one pinned catalogued product + the indication crosswalk)

  1. opentargets-literature-per-target-v1 : per-(ensembl_gene_id, source, pmid) top-50 PubMed PMIDs
     from OT 26.06 evidence_europepmc (resourceScore + text-mined sentence + OT-native disease_id)
     and literature_entity_lut (relevance + year). Derived over the pinned opentargets-26-06 mirror.
  2. indication_crosswalk.yaml (target-contracts) efo_ids lane : canonical OncoTree indication ->
     Open-Targets-native EFO/MONDO ids, used to scope the europepmc lane to the indication.

  target -> symbol_to_ensembl -> pushdown-read (1) for that gene;
  indication -> (2) -> efo_ids; scope the europepmc rows (disease_id in efo_ids) when a lane exists.

## Honest coverage (measured-vs-null discipline)

- ZERO finding/severity/relevance inference — this reader returns PMID POINTERS (+ the europepmc
  text-mined sentence as a hint); the escalate-only extraction stays in the consuming skill's LLM
  layer (mirrors the competitor product's `modality_class_inference: none`).
- A gene with NO rows -> no_literature_floor (coverage gap or genuinely un-text-mined). Absence is
  reported, never a silent fake.
- No efo_ids lane for the indication -> the europepmc lane is NOT disease-scoped; both lanes fall
  back to the TARGET-LEVEL floor with indication_scope: 'target_level' + a _note. (The crosswalk EFO
  lane is currently unpopulated, so target-level is the normal path today.)

data_unavailable-safe. Absence = coverage gap, never a silent fake-negative.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml

LITERATURE_MANIFEST = "opentargets-literature-per-target-v2"   # v2: top-100 + entity_lut sentences
METHOD_VERSION = "0.2.0"                                        # 0.2.0: axis-aware re-ranking
DEFAULT_TOP_N = 10


def _axis_tokens(axis_terms) -> list[str]:
    """PURE: split an axis OR-clause ('toxicity OR adverse event OR ...') into lowercased tokens for
    sentence matching. Boolean glue (OR/AND) and parens are stripped; multi-word phrases kept whole."""
    import re
    if not axis_terms:
        return []
    raw = re.split(r"\bOR\b|\bAND\b", str(axis_terms))
    return [t.strip(" ()").lower() for t in raw if t.strip(" ()")]


def _axis_match(sentence, tokens: list[str]) -> int:
    """PURE: count how many axis tokens appear in the row's text-mined sentence (case-insensitive
    substring). 0 when no sentence (entity_lut rows with no europepmc join) or no tokens."""
    if not sentence or not tokens:
        return 0
    s = str(sentence).lower()
    return sum(1 for tok in tokens if tok and tok in s)

TARGET_CONTRACTS = Path(os.environ.get(
    "TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"))

# Finer OncoTree/panel subtype codes -> the indication_crosswalk `canonical_code` that carries the
# efo_ids lane. The framework often passes a fine OncoTree code (e.g. LUAD) while the crosswalk keys
# on the parent grouping (NSCLC), so disease-scoping would silently fall back to target-level without
# this normalization. Only 1:1 subtype->canonical aliases belong here (codes with no crosswalk entry,
# e.g. MESO, correctly stay unaliased -> target-level).
INDICATION_ALIAS = {
    "LUAD": "NSCLC", "LUSC": "NSCLC",   # lung adeno / squamous -> NSCLC grouping
    "DLBCL": "DLBC",                     # diffuse large B-cell lymphoma code spelling
    "LAML": "AML",                       # acute myeloid leukemia code spelling
}


def _canonical_indication(indication: str) -> str:
    """Normalize a framework indication code to the crosswalk canonical_code (via INDICATION_ALIAS)."""
    ind = (indication or "").strip().upper()
    return INDICATION_ALIAS.get(ind, ind)


def _indication_efo_ids(indication: str) -> list[str]:
    """indication code -> EFO/MONDO ids via indication_crosswalk.yaml `efo_ids` lane (case-insensitive,
    alias-normalized). Empty list when no lane/entry exists."""
    path = TARGET_CONTRACTS / "vocabularies" / "indication_crosswalk.yaml"
    if not path.exists():
        return []
    doc = yaml.safe_load(path.read_text()) or {}
    ind = _canonical_indication(indication)
    for e in doc.get("indications", []):
        if str(e.get("canonical_code", "")).upper() == ind:
            return [str(t).strip() for t in (e.get("efo_ids") or [])]
    return []


def _read_target_rows(ensembl_gene_id: str) -> list:
    """Pushdown-read the literature floor for one ENSG. Empty on genuine absence; re-raise env faults."""
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from methods.catalog_query.read import bucket_key_for
        import pyarrow.parquet as pq
        import pyarrow.fs as fs
        bucket, key = bucket_key_for(LITERATURE_MANIFEST)
        return pq.read_table(f"{bucket}/{key}", filesystem=fs.S3FileSystem(),
                             filters=[("ensembl_gene_id", "=", ensembl_gene_id)]).to_pylist()
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent
        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return []
        raise


def aggregate_literature(rows: list, efo_ids: list, *, top_n: int = DEFAULT_TOP_N,
                         axis_terms=None) -> dict:
    """PURE aggregator (offline-testable): literature-floor rows for ONE gene -> per-source top-N
    PMID pointers + the unioned PMID set. europepmc rows are scoped to the indication when efo_ids
    is non-empty (disease_id in efo_ids); entity_lut is target-level by construction.

    AXIS RE-RANK: when `axis_terms` (the subskill/axis OR-clause) is given, rows are re-ranked WITHIN
    each source by how many axis tokens their text-mined `sentence` contains, BEFORE the top-N cut —
    so the floor surfaces axis-RELEVANT papers instead of the same generic top-by-association papers
    for every axis. Ties fall back to the association-score rank_in_source. Rows with no sentence
    (entity_lut with no europepmc join) get axis_match 0 and keep their association order."""
    efo_set = {str(x) for x in (efo_ids or [])}
    scope = "indication" if efo_set else "target_level"
    tokens = _axis_tokens(axis_terms)

    # europepmc is disease-scoped when we have efo_ids; entity_lut is target-level by construction.
    # OVER-FILTER FALLBACK: the derived product keeps only the top-N europepmc rows/gene BY SCORE, so
    # for some (gene, indication) pairs none of those top rows carry a matching disease_id and scoping
    # would empty the lane. Rather than lose the reproducible europepmc signal entirely, fall back to
    # the target-level europepmc rows (flagged europepmc_scope='target_level_fallback').
    europepmc_all = [r for r in rows if r.get("source") == "europepmc"]
    europepmc_scope = scope
    if efo_set:
        scoped = [r for r in europepmc_all if r.get("disease_id") in efo_set]
        if scoped:
            europepmc_rows = scoped
        elif europepmc_all:
            europepmc_rows, europepmc_scope = europepmc_all, "target_level_fallback"
        else:
            europepmc_rows = []
    else:
        europepmc_rows = europepmc_all

    by_source: dict = {}
    for r in europepmc_rows:
        by_source.setdefault("europepmc", []).append(r)
    for r in rows:
        if r.get("source") != "europepmc":
            by_source.setdefault(r.get("source"), []).append(r)

    out_by_source: dict = {}
    union: list = []
    seen: set = set()
    for src, srows in by_source.items():
        # axis re-rank (axis_match desc) BEFORE the top-N cut; association rank_in_source breaks ties
        srows = sorted(srows, key=lambda r: (-_axis_match(r.get("sentence"), tokens),
                                             int(r.get("rank_in_source") or 1_000_000)))[:top_n]
        recs = [{"pmid": str(r.get("pmid")), "score": r.get("score"), "year": r.get("year"),
                 "rank_in_source": r.get("rank_in_source"),
                 "axis_match": _axis_match(r.get("sentence"), tokens),
                 "disease_id": r.get("disease_id"), "sentence": r.get("sentence")} for r in srows]
        out_by_source[src] = recs
        for rec in recs:                              # entity-first union order is caller's concern; here
            if rec["pmid"] not in seen:               # we just dedup, preserving per-source rank order
                seen.add(rec["pmid"])
                union.append(rec["pmid"])

    return {
        "indication_scope": scope,
        "europepmc_scope": europepmc_scope,   # 'indication' | 'target_level' | 'target_level_fallback'
        "axis_reranked": bool(tokens),        # rows re-ranked by sentence↔axis-term match
        "n_pmids": len(union),
        "pmids": union,
        "sources_present": sorted(out_by_source.keys()),
        "by_source": out_by_source,
    }


def read_literature_floor(target: str, indication: str, modality: Optional[str] = None,
                          release_pin: Optional[str] = None, *, top_n: int = DEFAULT_TOP_N,
                          axis_terms: Optional[str] = None) -> dict:
    """Pinned literature floor for a (target, indication). `modality`/`release_pin` accepted for
    dispatch-signature parity; the product is pinned to its OT release. `axis_terms` (the calling
    subskill/axis OR-clause) re-ranks each source by sentence↔axis-term match so the floor surfaces
    axis-RELEVANT papers, not the same generic top-by-association papers for every axis."""
    from methods.opentargets_common import symbol_to_ensembl
    base = {"target": target, "indication": indication, "method_version": METHOD_VERSION,
            "source": LITERATURE_MANIFEST, "as_of_opentargets_release": "26.06"}

    ensg = symbol_to_ensembl(target)
    if not ensg:
        return {**base, "status": "insufficient", "n_pmids": 0, "pmids": [], "by_source": {},
                "_note": f"{target}: could not resolve to an Ensembl gene id (OT resolver)"}

    rows = _read_target_rows(ensg)
    if not rows:
        return {**base, "ensembl_gene_id": ensg, "status": "no_literature_floor",
                "indication_scope": "target_level", "n_pmids": 0, "pmids": [], "by_source": {},
                "_note": f"{target} ({ensg}): no rows in {LITERATURE_MANIFEST} (un-text-mined or coverage gap)"}

    efo_ids = _indication_efo_ids(indication)
    agg = aggregate_literature(rows, efo_ids, top_n=top_n, axis_terms=axis_terms)
    out = {**base, "ensembl_gene_id": ensg, "efo_ids": efo_ids, "status": "ok", **agg}
    if not efo_ids:
        out["_note"] = (f"no efo_ids lane for indication {indication!r} in indication_crosswalk.yaml — "
                        f"reporting the TARGET-LEVEL literature floor (europepmc lane not disease-scoped)")
    return out


def _main(argv=None):
    import argparse
    import json
    ap = argparse.ArgumentParser(description="Pinned per-target literature floor from Open Targets 26.06.")
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    ap.add_argument("--axis-terms", default=None,
                    help="axis OR-clause to re-rank by sentence match, e.g. 'toxicity OR normal tissue'")
    args = ap.parse_args(argv)
    print(json.dumps(read_literature_floor(args.target, args.indication, top_n=args.top_n,
                                           axis_terms=args.axis_terms), indent=2, default=str))


if __name__ == "__main__":
    _main()
