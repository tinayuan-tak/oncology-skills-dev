"""pair_selectivity_gate.read — S3 boundary + orchestration for the AND/OR/NOT pair scan.

Computes per-group (TCGA study / GTEx tissue) gate-positive FRACTIONS for an antigen pair {A, B}
directly in DuckDB — a SINGLE scan of each long product per pair, pulling both genes together and
self-joining on sample_id server-side, so we never materialize per-sample rows in Python:
  - tcga-tumor-tpm-recount3-long-v1  (gene_symbol, sample_id, study, log2_tpm)
  - gtex-tpm-recount3-long-v1        (gene_symbol, sample_id, tissue, log2_tpm)

PERFORMANCE (measured): the GTEx long product is 790M rows; a per-pair scan is ~60-75s (the read
dominates — the product's row-group layout is not single-gene-pushdown-optimal). This matches the
biologics-target-discovery guidance (pair scans are >120s/pair → a BATCH path, not an interactive
per-target lookup). The bispecific-pair-scan skill runs this as a bounded background scan over a
partner set and states the cost; it is NOT wired into the per-target profile.

Credential discipline: AWS_PROFILE=cbg. Manifest IDs → S3 URIs via catalog_query.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from methods.catalog_query.read import s3_uri_for
from . import gates as _gates

DEFAULT_AWS_PROFILE = "cbg"
TUMOR_MANIFEST_ID = "tcga-tumor-tpm-recount3-long-v1"
GTEX_MANIFEST_ID = "gtex-tpm-recount3-long-v1"

try:
    from methods.dge_deseq2.read import INDICATION_TO_TCGA_STUDIES
except Exception:  # noqa: BLE001
    # Fallback only if the SoR import fails — keep in step with dge_deseq2.read.INDICATION_TO_TCGA_STUDIES.
    # LUSC is a first-class indication there (own single-study cohort), so the same-cell/pseudobulk
    # LUSC cubes are reachable; mirror that here so a degraded import doesn't silently drop LUSC.
    INDICATION_TO_TCGA_STUDIES = {
        "COADREAD": ["COAD", "READ"], "NSCLC": ["LUAD", "LUSC"],
        "LUAD": ["LUAD"], "LUSC": ["LUSC"],
    }

_POS = _gates.GATE_POSITIVE_THRESHOLD_TPM
_VETO = _gates.NOT_GATE_VETO_ABSENT_TPM


def _con():
    import duckdb
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-east-1';")
    try:
        con.execute("CREATE SECRET s (TYPE S3, PROVIDER credential_chain);")
    except Exception:  # noqa: BLE001 — secret may already exist / creds via env
        pass
    return con


def _gate_expr(gate: str) -> str:
    """SQL boolean (per joined sample) for the gate, over linear-TPM columns a_tpm / b_tpm."""
    if gate == "AND":
        return f"(a_tpm >= {_POS} AND b_tpm >= {_POS})"
    if gate == "OR":
        return f"(a_tpm >= {_POS} OR b_tpm >= {_POS})"
    return f"(a_tpm >= {_POS} AND b_tpm < {_VETO})"   # NOT: A present, veto B truly absent


@lru_cache(maxsize=128)
def _frac_by_group(gene_a: str, gene_b: str, gate: str, source: str) -> Optional[dict]:
    """{group: gate_positive_fraction} for a pair from one long product, computed server-side.

    source='tumor' → grouped by `study`; 'normal' → by `tissue`. None if the product is unreadable;
    empty dict if neither gene is present. Cached on (a, b, gate, source)."""
    manifest = TUMOR_MANIFEST_ID if source == "tumor" else GTEX_MANIFEST_ID
    group_col = "study" if source == "tumor" else "tissue"
    try:
        uri = s3_uri_for(manifest)
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent
        # Genuine NoSuchKey/404 (or FileNotFoundError) resolving the product URI -> None (caller emits
        # data_unavailable, unchanged). A transient/creds/broken-env/config-resolution failure is NOT
        # absence -> re-raise so the live-read seam surfaces an honest _live_read_error.
        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return None
        raise
    a, b = gene_a.upper().strip(), gene_b.upper().strip()
    sql = f"""
      WITH g AS (
        SELECT sample_id, {group_col} AS grp, gene_symbol, pow(2, log2_tpm) - 1 AS tpm
        FROM read_parquet('{uri}') WHERE gene_symbol IN ('{a}', '{b}')
      )
      SELECT x.grp AS grp,
             avg(CASE WHEN {_gate_expr(gate)} THEN 1.0 ELSE 0.0 END) AS pos_frac
      FROM (SELECT sample_id, grp, tpm AS a_tpm FROM g WHERE gene_symbol = '{a}') x
      JOIN (SELECT sample_id, grp, tpm AS b_tpm FROM g WHERE gene_symbol = '{b}') y
        USING (sample_id, grp)
      GROUP BY x.grp
    """
    try:
        df = _con().execute(sql).df()
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent
        # DuckDB httpfs surfaces a GENUINELY missing S3 parquet as an IO error whose message carries
        # "NoSuchKey"/"404" (not a botocore ClientError) — treat that as genuine absence -> None
        # (data_unavailable, unchanged). A creds error (403/AccessDenied), throttle, broken-env, or a
        # SQL fault is NOT absence -> re-raise so the seam records an honest _live_read_error.
        msg = str(e)
        if (is_definitively_absent(e) or isinstance(e, FileNotFoundError)
                or "NoSuchKey" in msg or "404" in msg):
            return None
        raise
    return {str(r.grp): float(r.pos_frac) for r in df.itertuples()}


def scan_pair(target: str, partner: str, indication: str, gate: str = "AND") -> dict:
    """Score one antigen pair for one gate in one indication (NOT: partner is the veto antigen).
    Reports the indication's most-selective TCGA study. Carries the avidity caveat."""
    studies = INDICATION_TO_TCGA_STUDIES.get(str(indication).upper().strip())
    if not studies:
        return _unavailable(target, partner, indication, gate,
                            f"indication {indication} has no TCGA study mapping (scan is TCGA-cohort-based)")
    tumor_frac = _frac_by_group(target, partner, gate, "tumor")
    normal_frac = _frac_by_group(target, partner, gate, "normal")
    if tumor_frac is None or normal_frac is None:
        return _unavailable(target, partner, indication, gate, "per-sample TPM product unreadable")
    if not tumor_frac:
        return _unavailable(target, partner, indication, gate,
                            f"{target}/{partner} pair absent from the tumor TPM product")
    best = None
    for study in studies:
        r = _gates.reduce_gate(gate, tumor_frac, normal_frac, study)
        if r["tumor_fraction"] is None:
            continue
        if best is None or (r["selectivity"] or -1) > (best["selectivity"] or -1):
            best = r
    if best is None:
        return _unavailable(target, partner, indication, gate,
                            f"no tumor samples for {indication} studies {studies}")
    best.update({"target": target, "partner": partner, "indication": str(indication).upper().strip(),
                 "_avidity_caveat": _gates.AVIDITY_CAVEAT})
    return best


def scan_partner_set(target: str, partners: list, indication: str, gate: str = "AND") -> list:
    """Batched: scan `target` against each partner for one gate, sorted by selectivity desc.

    NOTE: each partner is a fresh pair scan (~60-90s cold — the GTEx read dominates). This is a
    bounded BACKGROUND scan, not an interactive call; keep the partner set small (dozens, not
    thousands) or pre-filter to a surfaceome/clinical-seed subset upstream."""
    results = []
    for partner in partners:
        if partner.upper().strip() == target.upper().strip():
            continue
        results.append(scan_pair(target, partner, indication, gate))
    scored = [r for r in results if r.get("selectivity") is not None]
    unscored = [r for r in results if r.get("selectivity") is None]
    scored.sort(key=lambda r: r["selectivity"], reverse=True)
    return scored + unscored


def _unavailable(target, partner, indication, gate, note) -> dict:
    return {
        "gate": gate, "target": target, "partner": partner,
        "indication": str(indication).upper().strip(), "tumor_study": None,
        "tumor_fraction": None, "max_essential_normal_fraction": None,
        "max_essential_normal_tissue": None, "max_any_normal_fraction": None,
        "max_any_normal_tissue": None, "selectivity": None,
        "call": "data_unavailable", "_data_note": note,
        "_avidity_caveat": _gates.AVIDITY_CAVEAT,
    }
