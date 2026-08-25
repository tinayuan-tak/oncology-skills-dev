"""Per-gene reader over the ICI-response expression-association product.

Reads ici-response-expression-per-gene-v1 (one row per gene_symbol x cohort, from open-GEO melanoma
anti-PD-1 cohorts — see data-catalog scripts/derive_ici_response_expression.py). Per-cohort rows carry
log2fc_resp_vs_nonresp / mannwhitney_p / higher_in; the `pan-melanoma-rollup` row additionally carries
a direction-aware Stouffer combine (stouffer_z / stouffer_p / n_cohorts_concordant). The product is
gene-SORTED (sort key == read filter key == gene_symbol), so a per-gene read uses pyarrow S3FileSystem
+ predicate-pushdown to touch a few row-groups — the gene-keyed-product invariant.

Dependencies are pyarrow/pandas/boto3 ONLY. Credential discipline: pyarrow's default cred chain honours
AWS_PROFILE=cbg. Mirrors the sibling gene-keyed bulk readers.

SCOPE: the product covers MELANOMA (SKCM) only (open-GEO anti-PD-1 cohorts). A non-melanoma query
resolves data_unavailable (honest scope ceiling), never a silent cross-indication read.

VERDICT-INERT: an ICI-biomarker display/context reader (immune-context). It emits an
`ici_response_class` PRIMARY categorical for provenance/availability accounting, but NO interpretation
rule consumes it — it moves no gate verdict.
"""
from __future__ import annotations

from typing import Optional

from methods.catalog_query.read import bucket_key_for

MANIFEST_ID = "ici-response-expression-per-gene-v1"
S3_BUCKET = "onc-compbio"
ROLLUP_COHORT = "pan-melanoma-rollup"

# Framework indication codes the product covers (melanoma). A query outside this set is out of scope.
_MELANOMA_INDICATIONS = frozenset({"SKCM", "MELANOMA", "SKIN"})

_PARQUET_COLS = ["gene_symbol", "cohort", "indication", "ici_agent",
                 "log2fc_resp_vs_nonresp", "mannwhitney_p", "higher_in",
                 "stouffer_z", "stouffer_p", "n_cohorts_concordant"]

_SIG_P = 0.05   # per-cohort Mann-Whitney significance threshold (uncorrected; display flag only)


def _summarize(rows) -> dict:
    """Roll the per-cohort + rollup rows for one gene up to a per-gene ICI-association summary.
    `rows` is a non-empty pandas DataFrame with _PARQUET_COLS."""
    import math
    df = rows
    per_cohort = df[df["cohort"].astype(str) != ROLLUP_COHORT]
    rollup = df[df["cohort"].astype(str) == ROLLUP_COHORT]

    cohorts = sorted(per_cohort["cohort"].astype(str).unique().tolist())
    ici_agents = sorted(per_cohort["ici_agent"].astype(str).dropna().unique().tolist())

    # Direction + effect: prefer the cross-cohort rollup row when present; else the single per-cohort row.
    if not rollup.empty:
        r = rollup.iloc[0]
        direction = str(r["higher_in"])
        log2fc = r["log2fc_resp_vs_nonresp"]
        stouffer_z = r["stouffer_z"]
        stouffer_p = r["stouffer_p"]
        n_concordant = r["n_cohorts_concordant"]
    else:
        r = per_cohort.iloc[0] if not per_cohort.empty else df.iloc[0]
        direction = str(r["higher_in"])
        log2fc = r["log2fc_resp_vs_nonresp"]
        stouffer_z = None
        stouffer_p = None
        n_concordant = None

    def _f(v):
        if v is None:
            return None
        try:
            fv = float(v)
        except (TypeError, ValueError):
            return None
        return None if math.isnan(fv) else round(fv, 4)

    # Any per-cohort Mann-Whitney below the (uncorrected) threshold — a display flag, not a claim.
    mw = per_cohort["mannwhitney_p"].astype(float) if not per_cohort.empty else df["mannwhitney_p"].astype(float)
    mw_valid = mw.dropna()
    any_sig = bool((mw_valid < _SIG_P).any()) if len(mw_valid) else False
    min_p = _f(mw_valid.min()) if len(mw_valid) else None

    if direction == "responder":
        cls = "higher_in_responders"
    elif direction == "non_responder":
        cls = "higher_in_nonresponders"
    else:
        cls = "no_ici_association"

    return {
        "ici_response_class": cls,
        "direction_higher_in": direction,
        "median_log2fc_resp_vs_nonresp": _f(log2fc),
        "rollup_stouffer_z": _f(stouffer_z),
        "rollup_stouffer_p": _f(stouffer_p),
        "n_cohorts_concordant": (int(n_concordant) if n_concordant is not None
                                 and not (isinstance(n_concordant, float) and math.isnan(n_concordant))
                                 else None),
        "n_cohorts": int(len(cohorts)),
        "any_cohort_significant": any_sig,
        "min_mannwhitney_p": min_p,
        "cohorts": cohorts,
        "ici_agents": ici_agents,
    }


def _read_gene_rows(target: str):
    """Per-(cohort) rows for one gene. Returns a pandas DataFrame (possibly empty when the gene is
    absent), or None when the landed product cannot be found (404). Transient S3 faults propagate."""
    try:
        _, key = bucket_key_for(MANIFEST_ID)
    except FileNotFoundError:
        return None
    import pyarrow.fs as fs
    import pyarrow.parquet as pq
    s3fs = fs.S3FileSystem(region="us-east-1")   # default cred chain honours AWS_PROFILE=cbg
    filters = [("gene_symbol", "==", str(target).upper().strip())]
    try:
        tbl = pq.read_table(f"{S3_BUCKET}/{key}", filesystem=s3fs,
                            filters=filters, columns=_PARQUET_COLS)
    except FileNotFoundError:
        return None
    return tbl.to_pandas()


def read_target_summary(target: str, indication: Optional[str] = None) -> dict:
    """Per-gene ICI (anti-PD-1) responder-vs-non-responder expression association (immune-context
    ICI-biomarker lens). VERDICT-INERT display facet. MELANOMA (SKCM) scope only — a non-melanoma
    indication resolves data_unavailable (honest scope ceiling)."""
    ind = str(indication).upper().strip() if indication else None
    if ind is not None and ind not in _MELANOMA_INDICATIONS:
        return _data_unavailable(ind,
                                 note=f"ICI-response product ({MANIFEST_ID}) covers melanoma (SKCM) "
                                      f"open-GEO anti-PD-1 cohorts only; indication {ind} out of scope.")
    rows = _read_gene_rows(target)
    if rows is None:
        return _data_unavailable(ind, note=f"No landed ICI-response product ({MANIFEST_ID}).")
    if rows.empty:
        return _data_unavailable(ind,
                                 note=f"{str(target).upper().strip()} absent from {MANIFEST_ID} "
                                      f"(not measured in the melanoma ICI cohorts).")
    out = _summarize(rows)
    out["indication"] = "SKCM"   # product scope (both cohorts are melanoma)
    out["product_id"] = MANIFEST_ID
    return out


def _data_unavailable(indication: Optional[str], note: str) -> dict:
    """Honest coverage-gap payload — primary `ici_response_class: data_unavailable` + a note."""
    return {
        "ici_response_class": "data_unavailable",
        "direction_higher_in": None,
        "median_log2fc_resp_vs_nonresp": None,
        "rollup_stouffer_z": None,
        "rollup_stouffer_p": None,
        "n_cohorts_concordant": None,
        "n_cohorts": 0,
        "any_cohort_significant": False,
        "min_mannwhitney_p": None,
        "cohorts": [],
        "ici_agents": [],
        "indication": indication,
        "product_id": MANIFEST_ID,
        "_data_note": note,
    }
