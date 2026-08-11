"""pair_selectivity_gate.samecell — same-cell coexpression AVIDITY confirmation for nominated pairs.

Closes the bispecific-pair-scan avidity gap. The gate scan nominates pairs from BULK co-expression
(necessary but not sufficient — two antigens can be high in a tumor SAMPLE yet on DIFFERENT cells);
this reads the single-cell same-cell coexpression cube (sc-samecell-coexpr-{indication}-v1, emitted
from CELLxGENE Census by data-catalog/scripts/aggregate_sc_samecell_coexpr.py) and returns, for a
pair, the cross-donor fraction of MALIGNANT cells expressing BOTH antigens + enrichment_vs_independence:
  >1  coordinated (co-express on the same cells — avidity-supportive)
  ~1  independent (both highly expressed, co-occur by chance)
  <1  mutual exclusion (rarely the same cell — avidity-NEGATIVE despite bulk co-expression)

The DONOR is the replicate: the cube is per (donor, pair); we summarize ACROSS donors (cross-donor
median), never a cell-weighted pool. Pushdown-read by (gene_a, gene_b). data_unavailable when the
indication's same-cell cube is not landed (COADREAD/NSCLC/LUSC landed) — the pair-scan still returns
its bulk verdict + the honest 'avidity unconfirmed' caveat, never a fabricated confirmation.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from methods.catalog_query.read import s3_uri_for

# indication → same-cell cube manifest id (parallels the sc-pseudobulk products; COADREAD + NSCLC + LUSC).
# LUSC has a DEDICATED cube (squamous-only malignant denominators) — distinct from the LUAD+LUSC-mixed
# NSCLC umbrella. LUAD stays on the umbrella (no LUAD-specific cube). Adding an indication = emit its
# cube (data-catalog) + one line here (keep in step with sc_tumor_expression_celltype.INDICATION_TO_PRODUCT).
INDICATION_TO_SAMECELL_MANIFEST = {
    "COADREAD": "sc-samecell-coexpr-coadread-v1",
    "COAD": "sc-samecell-coexpr-coadread-v1",
    "READ": "sc-samecell-coexpr-coadread-v1",
    "NSCLC": "sc-samecell-coexpr-nsclc-v1",
    "LUAD": "sc-samecell-coexpr-nsclc-v1",
    "LUSC": "sc-samecell-coexpr-lusc-v1",   # dedicated squamous cube (was: nsclc umbrella)
}

# enrichment_vs_independence bands for the avidity call.
_COORDINATED_MIN = 1.2      # >= → coordinated (same-cell avidity supportive)
_EXCLUSION_MAX = 0.8        # <= → mutual exclusion (avidity negative)


@lru_cache(maxsize=64)
def _read_cube(manifest_id: str):
    """The full same-cell cube for an indication (small — per donor×pair). None if unreadable."""
    try:
        uri = s3_uri_for(manifest_id)
    except Exception:  # noqa: BLE001
        return None
    try:
        import pyarrow.parquet as pq
        import pyarrow.fs as fs
        s3fs = fs.S3FileSystem(region="us-east-1")
        # uri is s3://bucket/key → strip scheme for pyarrow fs
        path = uri.replace("s3://", "")
        return pq.read_table(path, filesystem=s3fs).to_pandas()
    except Exception:  # noqa: BLE001
        return None


def _avidity_call(enrichment: Optional[float], both_fraction: Optional[float]) -> str:
    if enrichment is None or both_fraction is None:
        return "avidity_unconfirmed"
    if enrichment >= _COORDINATED_MIN:
        return "same_cell_coordinated"       # co-express on the same malignant cells — avidity supportive
    if enrichment <= _EXCLUSION_MAX:
        return "same_cell_mutually_exclusive"  # rarely the same cell — avidity NEGATIVE (bulk was misleading)
    return "same_cell_independent"           # both present, co-occur ~by chance


def confirm_pair_samecell(target: str, partner: str, indication: str) -> dict:
    """Cross-donor same-cell coexpression for one pair in one indication. Order-insensitive on the
    pair (A:B == B:A). Returns the avidity call + cross-donor median both-fraction / enrichment, or a
    data_unavailable payload (cube not landed / pair absent) — never a fabricated confirmation."""
    manifest = INDICATION_TO_SAMECELL_MANIFEST.get(str(indication).upper().strip())
    if not manifest:
        return _unavailable("indication has no same-cell coexpr cube (COADREAD/NSCLC/LUSC landed)")
    df = _read_cube(manifest)
    if df is None:
        return _unavailable(f"same-cell cube {manifest} not landed / unreadable")
    a, b = target.upper().strip(), partner.upper().strip()
    # order-insensitive match
    m = df[((df["gene_a"] == a) & (df["gene_b"] == b)) | ((df["gene_a"] == b) & (df["gene_b"] == a))]
    if m.empty:
        return _unavailable(f"pair {a}:{b} not in the same-cell cube (not emitted for this indication)")
    import numpy as np
    both_med = float(np.median(m["both_fraction"]))
    enr = m["enrichment_vs_independence"].dropna()
    enr_med = float(np.median(enr)) if len(enr) else None
    return {
        "samecell_avidity_call": _avidity_call(enr_med, both_med),
        "samecell_both_fraction_median": round(both_med, 4),
        "samecell_enrichment_median": round(enr_med, 3) if enr_med is not None else None,
        "n_donors": int(len(m)),
        "_evidence_tier": "single_cell_measured",
    }


def _unavailable(note: str) -> dict:
    return {
        "samecell_avidity_call": "data_unavailable",
        "samecell_both_fraction_median": None,
        "samecell_enrichment_median": None,
        "n_donors": 0,
        "_data_note": note,
    }
