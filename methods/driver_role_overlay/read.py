"""alteration_role assembler — join OncoKB gene-role + IntOGen mode-of-action → typed driver role.

For a (target, indication): OncoKB geneType (curated gene-role backbone) × IntOGen Compendium
mode-of-action (patient-scale, indication-scoped via CANCER_TYPE) → alteration_role +
functional_direction + a driver-tier/q-value confidence. data_unavailable-safe. No new ingestion.
"""
from __future__ import annotations

import io
import json
import zipfile
from functools import lru_cache
from typing import Optional

from methods.catalog_query.read import bucket_prefix_for

ONCOKB_MANIFEST_ID = "oncokb-gene-roles-public-snapshot-2026-07-01"
INTOGEN_MANIFEST_ID = "intogen-v2024-09-20"
# bucket + keys resolved from the data-catalog manifests (single source of truth).
S3_BUCKET, _ONCOKB_PREFIX = bucket_prefix_for(ONCOKB_MANIFEST_ID)
ONCOKB_KEY = f"{_ONCOKB_PREFIX}oncokb_cancer_gene_list.json"
INTOGEN_ZIP_KEY = f"{bucket_prefix_for(INTOGEN_MANIFEST_ID)[1]}IntOGen-Drivers-20240920.zip"
INTOGEN_COMPENDIUM = "2024-06-18_IntOGen-Drivers/Compendium_Cancer_Genes.tsv"

# framework indication → IntOGen CANCER_TYPE code(s). IntOGen uses its own cohort cancer-type
# vocabulary; map the framework indication to the matching code(s). An indication absent here →
# the IntOGen arm is pan-cancer-only (OncoKB still classifies the gene).
#
# Invariant: every code below must be present in the IntOGen v2024-09-20 Compendium's CANCER_TYPE
# set. A code absent from IntOGen silently matches nothing, so an indication mapped to a wrong code
# gets ZERO indication-scoped driver evidence while APPEARING mapped. Do NOT add a guessed variant;
# if a new indication has no real IntOGen code, leave it OUT (the pan-cancer fallback is correct).
# test_intogen_cancer_map_codes_are_real enforces this.
INDICATION_TO_INTOGEN_CANCER = {
    # colorectal — IntOGen has the merged COADREAD code AND the parts (the merged code was MISSED before)
    "COADREAD": ("COADREAD", "COAD", "READ"), "COAD": ("COAD", "COADREAD"), "READ": ("READ", "COADREAD"),
    "LUAD": ("LUAD",), "LUSC": ("LUSC",), "NSCLC": ("LUAD", "LUSC", "NSCLC"),
    "SCLC": ("SCLC",),                                     # was MISSING; IntOGen has SCLC
    "BRCA": ("BRCA",), "PAAD": ("PAAD",),
    "SKCM": ("SKCM", "MEL"), "STAD": ("STAD",),
    "PRAD": ("PRAD",), "OV": ("OVT",),                     # OV maps to IntOGen code OVT
    "KIRC": ("CCRCC",),                                    # KIRC maps to IntOGen code CCRCC
    "GBM": ("GBM",), "HNSC": ("HNSC",),
    "BLCA": ("BLCA",), "LIHC": ("HCC",),                   # LIHC maps to IntOGen code HCC
    "ESCA": ("ESCA", "ESCC"), "UCEC": ("UCEC",),
    # newly-mapped framework indications (each code verified present in IntOGen 2024-09-20):
    "CESC": ("CESC",), "LGG": ("LGGNOS",), "UCS": ("UCS",), "ACC": ("ACC",),
    "CHOL": ("CHOL",), "DLBC": ("DLBCLNOS",), "LAML": ("AML",), "MESO": ("PLMESO",),
}

_DRIVER_TIER_QVALUE = 0.05     # IntOGen q-value below which a per-cohort driver call is confident


def _boto3():
    import boto3
    return boto3.Session().client("s3")


# Module-level breadcrumb: set to a short token when a loader hit a NON-absent (transient/creds/
# broken-env) error, so read_alteration_role can surface it. A genuine 404/NoSuchKey leaves it None
# (honest data_unavailable — the object simply isn't there).
_live_read_error: Optional[str] = None


@lru_cache(maxsize=1)
def _load_oncokb_roles() -> dict:
    """{hugoSymbol: geneType} from the OncoKB cancer-gene-list JSON. Empty on GENUINE absence only."""
    try:
        obj = _boto3().get_object(Bucket=S3_BUCKET, Key=ONCOKB_KEY)
        data = json.loads(obj["Body"].read())
        rows = data if isinstance(data, list) else data.get("genes", data.get("data", []))
        out = {}
        for r in rows:
            sym = r.get("hugoSymbol")
            if sym:
                out[sym] = r.get("geneType") or "NEITHER"
        return out
    except Exception as e:  # noqa: BLE001
        # Genuine 404/NoSuchKey → honest empty. A transient/creds/broken-env error must NOT be masked
        # as an empty role map (would silently strip driver-role evidence for every target) — record a
        # breadcrumb + re-raise (lru_cache never memoizes the raise, so it is retried).
        from methods.target_id_sidecar import is_definitively_absent
        if not is_definitively_absent(e):
            global _live_read_error
            _live_read_error = f"oncokb_load_failed:{type(e).__name__}"
            raise
        return {}


@lru_cache(maxsize=1)
def _load_intogen_compendium():
    """IntOGen Compendium as a DataFrame [SYMBOL, CANCER_TYPE, ROLE, QVALUE_COMBINATION,
    PCT_SAMPLES, IS_DRIVER]. Empty on failure."""
    import pandas as pd
    try:
        obj = _boto3().get_object(Bucket=S3_BUCKET, Key=INTOGEN_ZIP_KEY)
        zf = zipfile.ZipFile(io.BytesIO(obj["Body"].read()))
        with zf.open(INTOGEN_COMPENDIUM) as fh:
            df = pd.read_csv(io.TextIOWrapper(fh, "utf-8"), sep="\t")
        keep = {"SYMBOL", "CANCER_TYPE", "ROLE", "QVALUE_COMBINATION", "%_SAMPLES_COHORT", "IS_DRIVER"}
        df = df[[c for c in df.columns if c in keep]].copy()
        df["QVALUE_COMBINATION"] = pd.to_numeric(df["QVALUE_COMBINATION"], errors="coerce")
        df["%_SAMPLES_COHORT"] = pd.to_numeric(df["%_SAMPLES_COHORT"], errors="coerce")
        return df
    except Exception as e:  # noqa: BLE001
        # Genuine 404/NoSuchKey → honest empty. A transient/creds/broken-env error must NOT be masked
        # as an empty compendium (would silently strip indication-scoped driver evidence) — record a
        # breadcrumb + re-raise (lru_cache never memoizes the raise, so it is retried).
        from methods.target_id_sidecar import is_definitively_absent
        if not is_definitively_absent(e):
            global _live_read_error
            _live_read_error = f"intogen_load_failed:{type(e).__name__}"
            raise
        return pd.DataFrame(columns=["SYMBOL", "CANCER_TYPE", "ROLE", "QVALUE_COMBINATION",
                                     "%_SAMPLES_COHORT", "IS_DRIVER"])


# IntOGen ROLE → functional_direction.
_ROLE_TO_DIRECTION = {"Act": "activating", "LoF": "loss_of_function", "ambiguous": "ambiguous"}
# OncoKB geneType → the direction it implies (backbone when IntOGen is silent).
_ONCOKB_TO_DIRECTION = {"ONCOGENE": "activating", "TSG": "loss_of_function",
                        "ONCOGENE_AND_TSG": "ambiguous"}


def read_alteration_role(target: str, indication: str) -> dict:
    """alteration_role assembler for a (target, indication). Returns the typed role + direction +
    driver-tier evidence from OncoKB × IntOGen. data_unavailable-safe."""
    sym = target.upper().strip()
    oncokb = _load_oncokb_roles()
    comp = _load_intogen_compendium()
    gene_type = oncokb.get(sym)             # may be None (gene not in OncoKB list)

    base = {"target": target, "indication": indication,
            "oncokb_gene_type": gene_type, "sources": []}
    if oncokb:
        base["sources"].append("oncokb")
    if not comp.empty:
        base["sources"].append("intogen")

    # IntOGen: this gene's driver calls, restricted to the indication's cancer type(s) if mapped.
    cancer_codes = INDICATION_TO_INTOGEN_CANCER.get(indication.upper().strip())
    g = comp[comp["SYMBOL"] == sym] if not comp.empty else comp
    g_ind = g[g["CANCER_TYPE"].isin(cancer_codes)] if (cancer_codes and not g.empty) else g.iloc[0:0]
    # confident indication-scoped driver calls (q < cutoff), else fall back to any indication call.
    conf_ind = g_ind[g_ind["QVALUE_COMBINATION"] < _DRIVER_TIER_QVALUE] if not g_ind.empty else g_ind

    intogen_role = None            # Act / LoF / ambiguous (indication-scoped, confident-preferred)
    intogen_scope = None           # 'indication' | 'pan_cancer' | None
    intogen_min_q = None
    intogen_pct = None
    src_rows = conf_ind if not conf_ind.empty else g_ind
    if not src_rows.empty:
        intogen_role = _majority_role(src_rows)
        intogen_scope = "indication"
        intogen_min_q = float(src_rows["QVALUE_COMBINATION"].min())
        intogen_pct = float(src_rows["%_SAMPLES_COHORT"].max())
    elif not g.empty:
        # gene is an IntOGen driver, but not in THIS indication's cohorts → pan-cancer evidence only
        intogen_role = _majority_role(g)
        intogen_scope = "pan_cancer"
        intogen_min_q = float(g["QVALUE_COMBINATION"].min()) if g["QVALUE_COMBINATION"].notna().any() else None

    direction = (_ROLE_TO_DIRECTION.get(intogen_role)
                 or _ONCOKB_TO_DIRECTION.get(gene_type))
    role = _classify_alteration_role(gene_type, intogen_role, intogen_scope)

    base.update({
        "alteration_role": role,
        "functional_direction": direction,
        "intogen_role": intogen_role,
        "intogen_scope": intogen_scope,
        # keep full precision — q-values span many orders of magnitude (1e-30 etc.); decimal
        # rounding would collapse tiny significant q-values to 0.0.
        "intogen_min_qvalue": (float(f"{intogen_min_q:.3g}") if intogen_min_q is not None else None),
        "intogen_max_pct_samples": (round(intogen_pct, 4) if intogen_pct is not None else None),
        "intogen_cancer_types": (list(cancer_codes) if cancer_codes else None),
    })
    if role == "data_unavailable":
        base["_data_note"] = "target not in OncoKB gene-role list nor an IntOGen driver"
    return base


def _majority_role(df) -> str:
    """Majority ROLE across a gene's IntOGen rows (Act/LoF/ambiguous), weighting confident calls."""
    counts = df["ROLE"].value_counts()
    if counts.empty:
        return "ambiguous"
    # Act vs LoF majority; ties or ambiguous-dominant → ambiguous.
    act = int(counts.get("Act", 0)); lof = int(counts.get("LoF", 0))
    if act > lof:
        return "Act"
    if lof > act:
        return "LoF"
    return "ambiguous"


def _classify_alteration_role(gene_type, intogen_role, intogen_scope) -> str:
    """The typed 4-role primitive:
      direct_driver_gof — OncoKB ONCOGENE or IntOGen Act (activating driver)
      direct_driver_lof — OncoKB TSG or IntOGen LoF (loss-of-function driver)
      predictive_biomarker — a driver gene whose role is ambiguous / bidirectional (OncoKB
                             ONCOGENE_AND_TSG, or IntOGen ambiguous) — actionable as a marker,
                             direction not resolved
      passenger — in neither curated list as a driver (OncoKB NEITHER/INSUFFICIENT and not an
                  IntOGen driver): no driver evidence for this target
      data_unavailable — absent from both sources entirely."""
    is_oncogene = gene_type in ("ONCOGENE",)
    is_tsg = gene_type in ("TSG",)
    is_dual = gene_type in ("ONCOGENE_AND_TSG",)
    known_gene = gene_type is not None
    intogen_driver = intogen_role is not None

    if not known_gene and not intogen_driver:
        return "data_unavailable"
    # direction from either source; IntOGen (functional, patient-scale) leads, OncoKB backs.
    if intogen_role == "Act" or is_oncogene:
        if intogen_role == "LoF" or is_tsg:
            return "predictive_biomarker"   # conflicting directions → marker, not a clean driver call
        return "direct_driver_gof"
    if intogen_role == "LoF" or is_tsg:
        return "direct_driver_lof"
    if is_dual or intogen_role == "ambiguous":
        return "predictive_biomarker"
    # known to a source but with no driver role (OncoKB NEITHER/INSUFFICIENT, no IntOGen driver)
    return "passenger"
