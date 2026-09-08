"""pubtator3_gene_disease_relations.read — TYPED gene×indication literature relations (DIRECTION).

Answers "what does the literature ASSERT about {target} in {indication} — associate / cause /
positive_correlate / negative_correlate / stimulate / inhibit — with citations?" This is the relation
DIRECTION/polarity layer that OT's co-occurrence-only europepmc evidence
(opentargets_europepmc_evidence) lacks. Draws from the derived product
`pubtator3-gene-disease-relations-per-gene-v1` (PubTator3 BioREx relations distilled to
gene × disease × relation_type with PMID support).

## Composition (pinned product + two crosswalks)

  1. pubtator3-gene-disease-relations-per-gene-v1 : per-(ensembl_gene_id, disease_mesh, relation_type)
     n_publications + top-20 PMIDs. Keyed on ensembl_gene_id (joins the OT europepmc evidence product).
  2. indication_crosswalk.yaml efo_ids lane : indication -> EFO/MONDO ids.
  3. opentargets_disease_xref.mesh_ids_for_efo : EFO/MONDO -> MESH ids (PubTator's disease key), from
     the OT disease entity dbXRefs. So the indication's disease family scopes disease_mesh.

  target -> symbol_to_ensembl -> pushdown-read (1); indication -> efo_ids -> MESH set -> scope disease_mesh.

## Honest coverage

- ZERO further inference — relation_type labels are PubTator's own BioREx output.
- gene×disease PubTator relations are dominated by `associate`; directional types are sparser.
- No rows -> no_relations. No MESH mapping for the indication -> target-level (not disease-scoped).

data_unavailable-safe. Absence = coverage gap, never a silent fake-negative.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml

RELATIONS_MANIFEST = "pubtator3-gene-disease-relations-per-gene-v1"
METHOD_VERSION = "0.1.0"
DEFAULT_TOP_N = 20

TARGET_CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
)

INDICATION_ALIAS = {"LUAD": "NSCLC", "LUSC": "NSCLC", "DLBCL": "DLBC", "LAML": "AML"}


def _canonical_indication(indication: str) -> str:
    ind = (indication or "").strip().upper()
    return INDICATION_ALIAS.get(ind, ind)


def _crosswalk_lane(indication: str, lane: str) -> list:
    path = TARGET_CONTRACTS / "vocabularies" / "indication_crosswalk.yaml"
    if not path.exists():
        return []
    doc = yaml.safe_load(path.read_text()) or {}
    ind = _canonical_indication(indication)
    for e in doc.get("indications", []):
        if str(e.get("canonical_code", "")).upper() == ind:
            return [str(t).strip() for t in (e.get(lane) or [])]
    return []


def _indication_efo_ids(indication: str) -> list:
    return _crosswalk_lane(indication, "efo_ids")


def _indication_mesh_ids(indication: str) -> list:
    """Curated indication -> MeSH descriptor ids (the disease_mesh scope), from the
    indication_crosswalk `mesh_ids` lane. This is the RELIABLE scope; the OT-disease dbXRefs
    bridge (mesh_ids_for_efo) is the fallback when the lane is absent."""
    return _crosswalk_lane(indication, "mesh_ids")


def _read_target_rows(ensembl_gene_id: str) -> list:
    """Pushdown-read the relations product for one ENSG. Empty on genuine absence; re-raise env faults."""
    try:
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import pyarrow.fs as fs
        import pyarrow.parquet as pq

        from methods.catalog_query.read import bucket_key_for

        bucket, key = bucket_key_for(RELATIONS_MANIFEST)
        return pq.read_table(
            f"{bucket}/{key}", filesystem=fs.S3FileSystem(), filters=[("ensembl_gene_id", "=", ensembl_gene_id)]
        ).to_pylist()
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent

        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return []
        raise


def aggregate_relations(rows: list, mesh_ids, *, top_n: int = DEFAULT_TOP_N) -> dict:
    """PURE aggregator (offline-testable): gene×disease×relation_type rows for ONE gene -> a
    per-relation-type DIRECTION summary. Disease rows are scoped to the indication when mesh_ids is
    non-empty (disease_mesh in mesh_ids), with an OVER-FILTER target-level fallback (if none match,
    keep all rows flagged relation_scope='target_level_fallback'). Groups by relation_type:
    n_publications (summed across the scoped diseases) + up to top_n merged PMIDs. Relations are
    returned ordered by n_publications desc."""
    mset = {str(x) for x in (mesh_ids or [])}
    scope = "indication" if mset else "target_level"

    relation_scope = scope
    if mset:
        scoped = [r for r in rows if str(r.get("disease_mesh")) in mset]
        if scoped:
            used = scoped
        elif rows:
            used, relation_scope = rows, "target_level_fallback"
        else:
            used = []
    else:
        used = rows

    by_type: dict = {}
    for r in used:
        rt = r.get("relation_type")
        d = by_type.setdefault(rt, {"n_publications": 0, "pmids": []})
        d["n_publications"] += int(r.get("n_publications") or 0)
        for p in r.get("pmids") or []:
            ps = str(p)
            if ps not in d["pmids"]:
                d["pmids"].append(ps)
    for d in by_type.values():
        d["pmids"] = d["pmids"][:top_n]

    relations = sorted([{"relation_type": rt, **d} for rt, d in by_type.items()], key=lambda x: -x["n_publications"])

    return {
        "indication_scope": scope,
        "relation_scope": relation_scope,  # 'indication' | 'target_level' | 'target_level_fallback'
        "n_relation_types": len(relations),
        "total_publications": sum(x["n_publications"] for x in relations),
        "relations": relations,
        "disease_mesh_ids": sorted({str(r.get("disease_mesh")) for r in used if r.get("disease_mesh") is not None}),
    }


def read_gene_disease_relations(
    target: str,
    indication: str,
    modality: Optional[str] = None,
    release_pin: Optional[str] = None,
    *,
    top_n: int = DEFAULT_TOP_N,
) -> dict:
    """Typed gene×indication literature relations (direction/polarity) for a (target, indication)."""
    from methods.opentargets_common import symbol_to_ensembl
    from methods.opentargets_disease_xref.read import mesh_ids_for_efo

    base = {
        "target": target,
        "indication": indication,
        "method_version": METHOD_VERSION,
        "source": RELATIONS_MANIFEST,
        "as_of_pubtator_snapshot": "2026-08-17",
    }

    ensg = symbol_to_ensembl(target)
    if not ensg:
        return {
            **base,
            "status": "insufficient",
            "total_publications": 0,
            "relations": [],
            "_note": f"{target}: could not resolve to an Ensembl gene id (OT resolver)",
        }

    rows = _read_target_rows(ensg)
    if not rows:
        return {
            **base,
            "ensembl_gene_id": ensg,
            "status": "no_relations",
            "indication_scope": "target_level",
            "total_publications": 0,
            "relations": [],
            "_note": f"{target} ({ensg}): no rows in {RELATIONS_MANIFEST} (no typed relations or coverage gap)",
        }

    efo_ids = _indication_efo_ids(indication)
    # PRIMARY: the curated indication_crosswalk mesh_ids lane (reliable). FALLBACK: the OT-disease
    # dbXRefs bridge (lossy — OT MONDO cancer terms often lack a MESH xref).
    mesh_ids = _indication_mesh_ids(indication)
    mesh_source = "crosswalk_mesh_ids" if mesh_ids else None
    if not mesh_ids:
        mesh_ids = sorted(mesh_ids_for_efo(efo_ids))
        mesh_source = "ot_dbxref_bridge" if mesh_ids else None
    agg = aggregate_relations(rows, mesh_ids, top_n=top_n)
    out = {
        **base,
        "ensembl_gene_id": ensg,
        "efo_ids": efo_ids,
        "mesh_ids": sorted(mesh_ids),
        "mesh_id_source": mesh_source,
        "status": "ok",
        **agg,
    }
    if not mesh_ids:
        out["_note"] = (
            f"no MESH mapping for indication {indication!r} (no crosswalk mesh_ids lane "
            f"and no dbXRef bridge; efo_ids={efo_ids or 'none'}) — reporting TARGET-LEVEL "
            f"relations (not disease-scoped)"
        )
    return out


def _main(argv=None):
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Typed gene×indication literature relations from PubTator3.")
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    args = ap.parse_args(argv)
    print(
        json.dumps(read_gene_disease_relations(args.target, args.indication, top_n=args.top_n), indent=2, default=str)
    )


if __name__ == "__main__":
    _main()
