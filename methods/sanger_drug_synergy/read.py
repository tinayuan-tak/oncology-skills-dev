"""sanger_drug_synergy.read — per-target chemical drug×drug synergy (Sanger 2022 anchor-library screen).

read_target_summary(target, indication=None) → the combo-chemical-synergy card summary: a target-level
synergy_opportunity_class + ranked partner drugs. `indication` accepted for the dispatcher signature but
NOT consumed (target-grain, pan-cell-line). A target with NO row → no_synergy_screen (a COVERAGE GAP,
NOT "no synergy exists" — measured-vs-null discipline). Read failure → data_unavailable + breadcrumb.
"""

from __future__ import annotations

from typing import Optional

from methods.catalog_query.read import bucket_key_for
from methods.target_id_sidecar import ensure_aws_profile, is_definitively_absent

METHOD_VERSION = "1.0.0"
PRODUCT_MANIFEST_ID = "sanger-drug-combination-synergy-per-target-v1"
COL_GENE = "target_gene"

_CLASS_RANK = {"robust_synergy": 0, "supported_synergy": 1, "context_synergy": 2}

import threading

_S3FS = None
_S3FS_LOCK = threading.Lock()


def _get_s3fs():
    global _S3FS
    if _S3FS is None:
        with _S3FS_LOCK:
            if _S3FS is None:
                ensure_aws_profile()
                import pyarrow.fs as fs

                _S3FS = fs.S3FileSystem(region="us-east-1")
    return _S3FS


def _read_rows(target: str) -> Optional[list]:
    """Rows for the target (list[dict]) or None on a genuine 404. Pushdown on target_gene.
    Transient/creds → raise (caller degrades gracefully with a breadcrumb)."""
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    bucket, key = bucket_key_for(PRODUCT_MANIFEST_ID)
    try:
        tbl = pq.read_table(f"{bucket}/{key}", filesystem=_get_s3fs(), filters=[(COL_GENE, "=", target)])
    except Exception as e:  # noqa: BLE001
        if is_definitively_absent(e):
            return None
        raise
    return tbl.filter(pc.equal(pc.utf8_upper(tbl[COL_GENE]), target)).to_pylist()


def _classify(rows: Optional[list]) -> str:
    """Target-level synergy_opportunity_class (strongest partner wins).
    no_synergy_screen = target not in the screened 86-gene panel (coverage gap, not evidence-against)."""
    if rows is None:
        return "no_synergy_screen"
    if not rows:
        return "no_synergy_screen"
    classes = {r.get("synergy_class") for r in rows}
    if "robust_synergy" in classes:
        return "strong_synergy_opportunity"
    if "supported_synergy" in classes:
        return "synergy_opportunity"
    if "context_synergy" in classes:
        return "context_synergy_opportunity"
    return "no_synergy_signal"


def _rank(rows: list, top_n: int = 20) -> list:
    ordered = sorted(
        rows,
        key=lambda r: (
            _CLASS_RANK.get(r.get("synergy_class"), 9),
            # `is not None` guard, NOT `or`: a genuine mean_delta_emax == 0.0 is falsy and `or -1.0` would
            # mis-sort a true-zero-effect pair as if it held the sentinel worst value.
            -(r.get("mean_delta_emax") if r.get("mean_delta_emax") is not None else -1.0),
        ),
    )
    return [
        {
            "partner_drug": r.get("partner_drug"),
            "partner_target": r.get("partner_target"),
            "partner_pathway": r.get("partner_pathway"),
            "target_role": r.get("target_role"),
            "n_lines_tested": int(r.get("n_lines_tested") or 0),
            "n_lines_synergistic": int(r.get("n_lines_synergistic") or 0),
            "frac_lines_synergistic": r.get("frac_lines_synergistic"),
            "mean_delta_emax": r.get("mean_delta_emax"),
            "tissues": r.get("tissues"),
            "synergy_class": r.get("synergy_class"),
        }
        for r in ordered[:top_n]
    ]


def synergy_partners_for_gene(target: str, rows: Optional[list] = None) -> dict:
    """Per-target chemical-synergy summary. `rows` injectable for tests."""
    sym = (target or "").strip().upper()
    read_error = None
    if rows is None:
        try:
            rows = _read_rows(sym)
        except Exception as e:  # noqa: BLE001 — graceful boundary; breadcrumb names the cause, no cache
            rows = None
            read_error = f"sanger_drug_synergy transient/creds/broken-env read failure: {e}"
            klass = "data_unavailable"
            partners = []
            out = {
                "synergy_opportunity_class": klass,
                "n_synergy_partners": 0,
                "strongest_synergy_partner_drug": None,
                "strongest_synergy_partner_target": None,
                "strongest_synergy_delta_emax": None,
                "top_synergy_partners": [],
                "synergy_context": None,
                "method_version": METHOD_VERSION,
                "_data_source": PRODUCT_MANIFEST_ID,
                "_live_read_error": read_error,
            }
            return out
    klass = _classify(rows)
    partners = _rank(rows) if rows else []
    strongest = partners[0] if partners else None
    ctx = None
    if strongest:
        ctx = (
            f"chemical synergy ({klass}): {sym} + {strongest['partner_drug']} "
            f"(targets {strongest.get('partner_target')}) — Bliss ΔEmax "
            f"{strongest.get('mean_delta_emax')} in {strongest.get('n_lines_synergistic')}/"
            f"{strongest.get('n_lines_tested')} lines (Sanger 2022; cell-line, hypothesis-generating)"
        )
    return {
        "synergy_opportunity_class": klass,
        "n_synergy_partners": len(rows) if rows else 0,
        "strongest_synergy_partner_drug": (strongest or {}).get("partner_drug"),
        "strongest_synergy_partner_target": (strongest or {}).get("partner_target"),
        "strongest_synergy_delta_emax": (strongest or {}).get("mean_delta_emax"),
        "top_synergy_partners": partners,
        "synergy_context": ctx,
        "method_version": METHOD_VERSION,
        "_data_source": PRODUCT_MANIFEST_ID,
    }


def read_target_summary(target: str, indication: Optional[str] = None) -> dict:
    return synergy_partners_for_gene(target)
