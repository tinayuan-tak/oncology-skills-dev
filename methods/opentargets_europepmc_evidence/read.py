"""opentargets_europepmc_evidence.read — cited gene×indication literature EVIDENCE (not just PMID pointers).

Answers "what does the literature actually SAY about {target} in {indication}, with citations?" — the
FULL cited-evidence layer that complements the thin literature FLOOR (opentargets_literature_floor,
which keeps only per-gene top-100 PMID pointers and discards disease grounding). Draws from the
derived product `opentargets-europepmc-evidence-per-target-v1` (OT 26.06 evidence_europepmc distilled
to gene×disease grain: literature VOLUME + RECENCY + the top-15 cited statements per (gene, disease)).

## Composition (one pinned catalogued product + the indication crosswalk)

  1. opentargets-europepmc-evidence-per-target-v1 : per-(ensembl_gene_id, disease_id) — n_papers,
     cooccur_sum, first/latest_year, n_papers_recent, nested top_papers[]{pmid,pmc,year,cooccur,
     section,sentence}. Derived over the pinned opentargets-26-06 mirror; disease_id is OT-native EFO/MONDO.
  2. indication_crosswalk.yaml (target-contracts) efo_ids lane : canonical OncoTree indication ->
     Open-Targets-native EFO/MONDO ids, used to scope the gene's disease rows to the indication.

  target -> symbol_to_ensembl -> pushdown-read (1) for that gene;
  indication -> (2) -> efo_ids; scope disease rows (disease_id in efo_ids) with an over-filter
  target-level fallback (mirrors opentargets_literature_floor).

## Honest coverage (measured-vs-null discipline)

- ZERO finding/severity/polarity inference — returns the co-occurrence cited statements OT itself
  text-mined; extraction/interpretation stays in the consuming skill's LLM layer. Relation DIRECTION
  is a separate product (pubtator3_gene_disease_relations).
- A gene with NO rows -> no_evidence (coverage gap or un-text-mined). Absence reported, never faked.
- No efo_ids lane for the indication -> disease rows NOT scoped; reported at target level.

data_unavailable-safe. Absence = coverage gap, never a silent fake-negative.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml

EVIDENCE_MANIFEST = "opentargets-europepmc-evidence-per-target-v1"
METHOD_VERSION = "0.1.0"
DEFAULT_TOP_N = 12

TARGET_CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
)

# Finer OncoTree/panel subtype codes -> the indication_crosswalk `canonical_code` (see the identical
# map in opentargets_literature_floor). Only 1:1 subtype->canonical aliases belong here.
INDICATION_ALIAS = {
    "LUAD": "NSCLC",
    "LUSC": "NSCLC",
    "DLBCL": "DLBC",
    "LAML": "AML",
}


def _canonical_indication(indication: str) -> str:
    """Normalize a framework indication code to the crosswalk canonical_code (via INDICATION_ALIAS)."""
    ind = (indication or "").strip().upper()
    return INDICATION_ALIAS.get(ind, ind)


def _indication_efo_ids(indication: str) -> list:
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
    """Pushdown-read the evidence product for one ENSG. Empty on genuine absence; re-raise env faults."""
    try:
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from methods.catalog_query.read import bucket_key_for
        import pyarrow.parquet as pq
        import pyarrow.fs as fs

        bucket, key = bucket_key_for(EVIDENCE_MANIFEST)
        return pq.read_table(
            f"{bucket}/{key}", filesystem=fs.S3FileSystem(), filters=[("ensembl_gene_id", "=", ensembl_gene_id)]
        ).to_pylist()
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent

        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return []
        raise


def _as_paper_dicts(top_papers, disease_id) -> list:
    """Normalize a row's nested top_papers (list of struct/dict) to plain dicts tagged with disease_id."""
    out = []
    for p in top_papers or []:
        d = dict(p) if not isinstance(p, dict) else p
        out.append(
            {
                "pmid": str(d.get("pmid")),
                "pmc": d.get("pmc"),
                "year": d.get("year"),
                "cooccur": d.get("cooccur"),
                "section": d.get("section"),
                "sentence": d.get("sentence"),
                "disease_id": disease_id,
            }
        )
    return out


def aggregate_evidence(rows: list, efo_ids: list, *, top_n: int = DEFAULT_TOP_N) -> dict:
    """PURE aggregator (offline-testable): gene×disease evidence rows for ONE gene -> an
    indication-scoped cited-evidence summary. Disease rows are scoped to the indication when efo_ids
    is non-empty (disease_id in efo_ids), with an OVER-FILTER target-level fallback: if none of the
    gene's disease rows match the family, fall back to ALL the gene's rows (flagged
    europepmc_scope='target_level_fallback') rather than emptying the lane.

    Returns literature VOLUME (total_papers = sum of per-disease distinct-PMID counts across the
    scoped diseases; NOTE: a paper spanning multiple diseases is counted once per disease), RECENCY
    (earliest/latest_year, n_papers_recent), and top_papers[] — the scoped diseases' cited statements
    merged, deduped by PMID (keeping the highest-co-occurrence mention), and cut to top_n by cooccur."""
    efo_set = {str(x) for x in (efo_ids or [])}
    scope = "indication" if efo_set else "target_level"

    europepmc_scope = scope
    if efo_set:
        scoped = [r for r in rows if str(r.get("disease_id")) in efo_set]
        if scoped:
            used = scoped
        elif rows:
            used, europepmc_scope = rows, "target_level_fallback"
        else:
            used = []
    else:
        used = rows

    if not used:
        return {
            "indication_scope": scope,
            "europepmc_scope": europepmc_scope,
            "n_diseases": 0,
            "disease_ids": [],
            "total_papers": 0,
            "n_papers_recent": 0,
            "earliest_year": None,
            "latest_year": None,
            "top_papers": [],
        }

    total_papers = sum(int(r.get("n_papers") or 0) for r in used)
    n_recent = sum(int(r.get("n_papers_recent") or 0) for r in used)
    years = [r.get("first_year") for r in used if r.get("first_year") is not None] + [
        r.get("latest_year") for r in used if r.get("latest_year") is not None
    ]
    disease_ids = sorted({str(r.get("disease_id")) for r in used if r.get("disease_id") is not None})

    # merge all scoped diseases' cited statements, dedup by pmid keeping the highest-cooccur mention
    best_by_pmid: dict = {}
    for r in used:
        for p in _as_paper_dicts(r.get("top_papers"), r.get("disease_id")):
            cur = best_by_pmid.get(p["pmid"])
            if cur is None or (p.get("cooccur") or 0) > (cur.get("cooccur") or 0):
                best_by_pmid[p["pmid"]] = p
    top_papers = sorted(best_by_pmid.values(), key=lambda p: (-(p.get("cooccur") or 0), -(p.get("year") or 0)))[:top_n]

    return {
        "indication_scope": scope,
        "europepmc_scope": europepmc_scope,  # 'indication' | 'target_level' | 'target_level_fallback'
        "n_diseases": len(disease_ids),
        "disease_ids": disease_ids,
        "total_papers": total_papers,
        "n_papers_recent": n_recent,
        "earliest_year": min(years) if years else None,
        "latest_year": max(years) if years else None,
        "top_papers": top_papers,
    }


def read_europepmc_evidence(
    target: str,
    indication: str,
    modality: Optional[str] = None,
    release_pin: Optional[str] = None,
    *,
    top_n: int = DEFAULT_TOP_N,
) -> dict:
    """Cited gene×indication literature evidence for a (target, indication). `modality`/`release_pin`
    accepted for dispatch-signature parity; the product is pinned to its OT release."""
    from methods.opentargets_common import symbol_to_ensembl

    base = {
        "target": target,
        "indication": indication,
        "method_version": METHOD_VERSION,
        "source": EVIDENCE_MANIFEST,
        "as_of_opentargets_release": "26.06",
    }

    ensg = symbol_to_ensembl(target)
    if not ensg:
        return {
            **base,
            "status": "insufficient",
            "total_papers": 0,
            "top_papers": [],
            "_note": f"{target}: could not resolve to an Ensembl gene id (OT resolver)",
        }

    rows = _read_target_rows(ensg)
    if not rows:
        return {
            **base,
            "ensembl_gene_id": ensg,
            "status": "no_evidence",
            "indication_scope": "target_level",
            "total_papers": 0,
            "top_papers": [],
            "_note": f"{target} ({ensg}): no rows in {EVIDENCE_MANIFEST} (un-text-mined or coverage gap)",
        }

    efo_ids = _indication_efo_ids(indication)
    agg = aggregate_evidence(rows, efo_ids, top_n=top_n)
    out = {**base, "ensembl_gene_id": ensg, "efo_ids": efo_ids, "status": "ok", **agg}
    if not efo_ids:
        out["_note"] = (
            f"no efo_ids lane for indication {indication!r} in indication_crosswalk.yaml — "
            f"reporting the TARGET-LEVEL evidence (disease rows not indication-scoped)"
        )
    return out


def _main(argv=None):
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Cited gene×indication literature evidence from Open Targets 26.06.")
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    args = ap.parse_args(argv)
    print(json.dumps(read_europepmc_evidence(args.target, args.indication, top_n=args.top_n), indent=2, default=str))


if __name__ == "__main__":
    _main()
