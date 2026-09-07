"""impc_mouse_ko_phenotype.read — IMPC-DIRECT mouse-KO normal-physiology safety (corroboration leg).

The verdict-facing mouse-KO safety leg reads Open-Targets-PACKAGED MGI
(methods/opentargets_mouse_phenotype). This is its IMPC-DIRECT corroboration: it reads the per-human-
gene rollup of International Mouse Phenotyping Consortium release-24.0 (impc-ko-phenotype-per-gene-v1,
human-symbol keyed) and re-derives ko_phenotype_class through the SAME shared classifier
(opentargets_mouse_phenotype.classify_ko_phenotype) so the two legs speak one taxonomy.

WHY DIRECT IMPC (vs OT-packaged MGI): IMPC runs a systematic PREWEANING VIABILITY screen — a clean
developmental-lethality call for ~every phenotyped KO — plus systematic top-level MP organ hits.
OT-packaged MGI carries the ADULT-lethal literature IMPC's viability screen does not. So this leg is
CORROBORATION at finer developmental resolution, NOT a replacement:
  * IMPC lethal_preweaning maps to the shared classifier's DEVELOPMENTAL bucket (a preweaning screen
    cannot assert adult essentiality) -> developmental_only, the honest guardrail.
  * IMPC organ-system hits -> severe_organ_phenotype when no lethal call.
COVERAGE IS PARTIAL: IMPC has phenotyped ~9k genes; embryonic-lethals hard to KO (KRAS/BRAF/VHL) are
ABSENT -> impc_ko_phenotype_class = no_phenotype / insufficient (coverage gap, never a killer). The
OT-MGI leg owns those. EVIDENCE TIER = inferred (mouse is a MODEL).

data_unavailable-safe. Absence = coverage gap (measured-vs-null discipline), never evidence-against.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

PRODUCT_MANIFEST_ID = "impc-ko-phenotype-per-gene-v1"
METHOD_VERSION = "0.1.0"

# IMPC preweaning-lethal / subviable synthesize a DEVELOPMENTAL lethal label for the shared
# classifier (a preweaning screen reflects development, not adult essentiality -> developmental_only).
_VIABILITY_LETHAL_LABEL = {
    "lethal_preweaning": "preweaning lethality (IMPC homozygous viability screen)",
    "subviable": "preweaning subviability (IMPC homozygous viability screen)",
}


def _read_impc_row(target: str) -> Optional[dict]:
    """Pushdown-read the per-human-gene IMPC rollup for one symbol. None if unresolvable/absent."""
    try:
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from methods.catalog_query.read import bucket_key_for
        import pyarrow.parquet as pq
        import pyarrow.fs as fs

        bucket, key = bucket_key_for(PRODUCT_MANIFEST_ID)
        tbl = pq.read_table(
            f"{bucket}/{key}",
            filesystem=fs.S3FileSystem(),
            filters=[("human_gene_symbol", "=", (target or "").strip().upper())],
        )
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent

        # A GENUINELY absent object (NoSuchKey/404 / FileNotFoundError) means IMPC has no row for this
        # gene -> None -> no_phenotype (honest coverage gap: IMPC has not phenotyped it). A
        # transient/creds/env failure is NOT absence -> re-raise so the live-read seam surfaces an
        # honest error rather than a false negative for a gene IMPC actually covers.
        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return None
        raise
    if tbl.num_rows == 0:
        return None
    return tbl.to_pylist()[0]


def _rows_for_classifier(impc_row: dict) -> list:
    """Reconstruct classify_ko_phenotype input rows from the IMPC rollup:
    the MP hits (label + top-level classes) + a synthesized viability lethal row."""
    rows = []
    try:
        for r in json.loads(impc_row.get("phenotype_rows_json") or "[]"):
            # IMPC packs multiple top-level MP systems comma-joined in one top_level_mp_term_name
            # field (e.g. "immune system phenotype,hematopoietic system phenotype") — split so each
            # matches the shared classifier's exact _SEVERE_ORGAN_CLASSES membership set.
            classes = []
            for c in r.get("classes") or []:
                classes.extend(part.strip() for part in str(c).split(",") if part.strip())
            rows.append(
                {"modelPhenotypeLabel": r.get("label", ""), "modelPhenotypeClasses": [{"label": c} for c in classes]}
            )
    except (ValueError, TypeError):
        pass
    lbl = _VIABILITY_LETHAL_LABEL.get(impc_row.get("impc_viability_class"))
    if lbl:
        rows.append({"modelPhenotypeLabel": lbl, "modelPhenotypeClasses": []})
    return rows


def read_impc_mouse_ko_phenotype(target: str, indication: Optional[str] = None) -> dict:
    """IMPC-direct mouse-KO safety corroboration for `target` (human HGNC symbol).

    `indication` accepted for signature-uniformity but NOT used — mouse-KO phenotype is per-gene.
    Emits the SAME ko_phenotype_class taxonomy as opentargets_mouse_phenotype (shared classifier),
    plus IMPC-specific viability + provenance fields, so the safety skill can corroborate directly.
    """
    sym = (target or "").strip().upper()
    base = {
        "target": target,
        "method_version": METHOD_VERSION,
        "source": "impc-release-24-0 (impc-ko-phenotype-per-gene-v1)",
        "evidence_tier": "inferred",
    }
    row = _read_impc_row(sym)
    if row is None:
        # coverage gap: IMPC has not phenotyped this gene (embryonic-lethals + un-phenotyped genes)
        return {
            **base,
            "ko_phenotype_class": "no_phenotype",
            "impc_viability_class": "unmeasured",
            "n_phenotype_hits": 0,
            "n_rows": 0,
            "_note": f"{sym} absent from impc-ko-phenotype-per-gene-v1 (IMPC has not phenotyped it — "
            f"covered by the OT-MGI leg)",
        }

    # reuse the SHARED classifier (single taxonomy source of truth)
    from methods.opentargets_mouse_phenotype.read import classify_ko_phenotype

    classified = classify_ko_phenotype(_rows_for_classifier(row))
    return {
        **base,
        **classified,
        "impc_viability_class": row.get("impc_viability_class"),
        "impc_viability_call_raw": row.get("impc_viability_call_raw"),
        "n_phenotype_hits": row.get("n_phenotype_hits"),
        "top_level_systems": row.get("top_level_systems"),
        "mouse_marker_symbol": row.get("mouse_marker_symbol"),
        "mgi_accession_id": row.get("mgi_accession_id"),
        "orthology_type": row.get("orthology_type"),
        "orthology_confidence": row.get("orthology_confidence"),
    }


def _main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(description="IMPC-direct mouse-KO safety corroboration for a target.")
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", default=None)
    args = ap.parse_args(argv)
    print(json.dumps(read_impc_mouse_ko_phenotype(args.target, args.indication), indent=2, default=str))


if __name__ == "__main__":
    _main()
