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
# 2026-08-12: PAAD + HNSC wired to 3CA cubes (paired with INDICATION_TO_PRODUCT extension above).
# 2026-08-12: KIRC wired to the 3CA kidney cube (data-catalog #345). Pan-renal pooled malignant
# compartment (see INDICATION_TO_PRODUCT note); KIRC only (not KIRP/KICH).
# 2026-08-12: OV wired to the 3CA ovarian cube (data-catalog #350). Pan-gynecologic pooled malignant
# compartment (see INDICATION_TO_PRODUCT note). 10 ovarian pairs anchored on FOLR1/MSLN/MUC16/EPCAM.
# 2026-08-13: COADREAD/COAD/READ repointed to the CRC core atlas cube (data-catalog #366) from the
# Census coadread-v1 (paired with the INDICATION_TO_PRODUCT repoint — explicit 'Cancer cell' malignant
# call). 12 CRC surface-target pairs (EPCAM/CEACAM5/GUCY2C/TACSTD2/CDH17/GPA33/EGFR/MET/CEACAM6);
# 370 donors / 509,919 malignant cells. EPCAM:CEACAM5 both_fraction 0.71 (strong same-cell avidity).
INDICATION_TO_SAMECELL_MANIFEST = {
    "COADREAD": "sc-samecell-coexpr-crc-coadread-v1",
    "COAD": "sc-samecell-coexpr-crc-coadread-v1",
    "READ": "sc-samecell-coexpr-crc-coadread-v1",
    "NSCLC": "sc-samecell-coexpr-luca-nsclc-v1",       # LuCA (Salcher 2022): 140 donors / 81,678 malignant
    "LUAD": "sc-samecell-coexpr-luca-nsclc-v1",        #   (was Census sc-samecell-coexpr-nsclc-v1; LuCA is
                                                       #    the richer NSCLC atlas — same 8 pairs, drop-in)
    "LUSC": "sc-samecell-coexpr-lusc-v1",              # dedicated squamous cube (was: nsclc umbrella)
    "PAAD": "sc-samecell-coexpr-3ca-pancreas-v1",      # 3CA PDAC — 8 antigen pairs (MSLN/MUC1/EPCAM/ERBB2...)
    "HNSC": "sc-samecell-coexpr-3ca-hnsc-v1",          # 3CA HNSCC — 10 squamous/H&N pairs (EGFR/TROP2/EPCAM/MET...)
    "KIRC": "sc-samecell-coexpr-3ca-kidney-v1",        # 3CA Kidney — 8 ccRCC pairs (CA9/CD70/ENPP3/CDH16/MET...)
    "OV": "sc-samecell-coexpr-3ca-ovarian-v1",         # 3CA Ovarian — 10 pairs (FOLR1/MSLN/MUC16/EPCAM/TACSTD2/VTCN1/CLDN6...)
    "STAD": "sc-samecell-coexpr-stad-golim-v1",        # Go/Lim gastric atlas (data-catalog #434) — 16 CLDN18.2-anchored pairs / 88 malignant donors. CLDN18 in ~56% malignant; CLDN18:MUC1 / CLDN18:EPCAM highest co-avidity (both~0.37). Fills the gastric gap (paired with the INDICATION_TO_PRODUCT STAD add).
    "BRCA": "sc-samecell-coexpr-brca-wu-v1",           # Wu/Swarbrick breast atlas (GSE176078) same-cell co-avidity — the malignant-denominator sibling of sc-pseudobulk-tumor-brca-wu-v1. Keeps the pseudobulk↔same-cell parity invariant (paired with the INDICATION_TO_PRODUCT BRCA add).
}

# enrichment_vs_independence bands for the avidity call.
_COORDINATED_MIN = 1.2      # >= → coordinated (same-cell avidity supportive)
_EXCLUSION_MAX = 0.8        # <= → mutual exclusion (avidity negative)


@lru_cache(maxsize=64)
def _read_cube(manifest_id: str):
    """The full same-cell cube for an indication (small — per donor×pair). None if unreadable."""
    try:
        uri = s3_uri_for(manifest_id)
    except Exception as e:  # noqa: BLE001
        # manifest not registered (FileNotFoundError from load_manifest) → cube not landed
        # (data_unavailable). Re-raise broken-env / transient so it isn't a silent dead axis.
        from methods.target_id_sidecar import is_definitively_absent
        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return None
        raise
    try:
        import pyarrow.parquet as pq
        import pyarrow.fs as fs
        s3fs = fs.S3FileSystem(region="us-east-1")
        # uri is s3://bucket/key → strip scheme for pyarrow fs
        path = uri.replace("s3://", "")
        return pq.read_table(path, filesystem=s3fs).to_pandas()
    except Exception as e:  # noqa: BLE001
        # absence discipline: swallow ONLY genuine absence (cube not landed) as data_unavailable;
        # re-raise broken-env / transient / creds so it surfaces as a live-read error, not a silent
        # avidity dead-axis (the RD bug class — see tests/test_reader_absence_discipline.py).
        from methods.target_id_sidecar import is_definitively_absent
        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return None
        raise


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


# --- TARGET-CENTRIC avidity (the card-facing read) -------------------------------------------------
# confirm_pair_samecell needs an explicit partner; a card is keyed on ONE target (target_pair grain,
# "each pair carried under both members"). This scans the indication's cube for EVERY pair involving
# the target and summarizes its same-cell avidity across candidate partners — the read a bispecific
# co-localization card consumes.

# same_cell_coordinated is the avidity-POSITIVE state (AND-gate bispecific viable); the class ranking
# below picks the target's BEST partner (most avidity-supportive) as the headline.
_AVIDITY_RANK = {"same_cell_coordinated": 3, "same_cell_independent": 2,
                 "same_cell_mutually_exclusive": 1, "avidity_unconfirmed": 0}


def _target_unavailable(target: str, indication: str, note: str) -> dict:
    return {"target": target, "indication": indication, "samecell_avidity_class": "data_unavailable",
            "n_partners_tested": 0, "n_coordinated_partners": 0, "best_partner": None,
            "best_enrichment_median": None, "best_both_fraction_median": None,
            "best_avidity_call": None, "partners": [], "_data_note": note}


def read_target_samecell_avidity(target: str, indication: str) -> dict:
    """Same-cell avidity for a target across ALL candidate partners in the indication's cube.

    Primary field `samecell_avidity_class` = the target's BEST partner call (same_cell_coordinated if
    ANY partner co-expresses on the same malignant cells → an AND-gate bispecific has a viable partner).
    data_unavailable-safe (no cube for the indication / target absent from every pair)."""
    manifest = INDICATION_TO_SAMECELL_MANIFEST.get(str(indication).upper().strip())
    if not manifest:
        return _target_unavailable(target, indication,
                                   "indication has no same-cell coexpr cube (COADREAD/NSCLC/LUSC/PAAD/HNSC/KIRC/OV landed)")
    df = _read_cube(manifest)
    if df is None:
        return _target_unavailable(target, indication, f"same-cell cube {manifest} not landed / unreadable")
    import numpy as np
    a = target.upper().strip()
    m = df[(df["gene_a"] == a) | (df["gene_b"] == a)]
    if m.empty:
        return _target_unavailable(target, indication,
                                   f"{a} not in any nominated pair in {manifest} (no avidity partner scanned)")
    partner = np.where(m["gene_a"].to_numpy() == a, m["gene_b"], m["gene_a"])
    m = m.assign(_partner=partner)
    partners = []
    for p, g in m.groupby("_partner"):
        both_med = float(np.median(g["both_fraction"]))
        enr = g["enrichment_vs_independence"].dropna()
        enr_med = float(np.median(enr)) if len(enr) else None
        partners.append({"partner": str(p), "avidity_call": _avidity_call(enr_med, both_med),
                         "enrichment_median": round(enr_med, 3) if enr_med is not None else None,
                         "both_fraction_median": round(both_med, 4), "n_donors": int(len(g))})
    # headline = the most avidity-supportive partner (rank, then enrichment)
    partners.sort(key=lambda d: (_AVIDITY_RANK.get(d["avidity_call"], 0),
                                 d["enrichment_median"] or -1.0), reverse=True)
    best = partners[0]
    return {
        "target": target,
        "indication": str(indication).upper().strip(),
        "samecell_avidity_class": best["avidity_call"],
        "n_partners_tested": len(partners),
        "n_coordinated_partners": sum(1 for d in partners if d["avidity_call"] == "same_cell_coordinated"),
        "best_partner": best["partner"],
        "best_enrichment_median": best["enrichment_median"],
        "best_both_fraction_median": best["both_fraction_median"],
        "best_avidity_call": best["avidity_call"],
        "partners": partners,
        "_evidence_tier": "single_cell_measured",
    }
