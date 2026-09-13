"""alteration_role assembler — join OncoKB gene-role + IntOGen mode-of-action → typed driver role.

For a (target, indication): OncoKB geneType (curated gene-role backbone) × IntOGen Compendium
mode-of-action (patient-scale, indication-scoped via CANCER_TYPE) → alteration_role +
functional_direction + a driver-tier/q-value confidence. data_unavailable-safe. No new ingestion.

The two sources are DIFFERENT KINDS of evidence and the join keeps them apart (2026-09-12):
curation says a gene is a cancer gene somewhere, statistical inference says an alteration drives a
cohort. Membership without measurement is `curated_cancer_gene`, not a driver call
(_classify_alteration_role); a split per-cohort vote is not a direction (_majority_role); and
inference that contradicts curation yields `ambiguous` rather than silently outranking it
(_resolve_direction). Each of those three docstrings records the measured defect it closes.
"""

from __future__ import annotations

import io
import json
import zipfile
from functools import lru_cache

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
    "COADREAD": ("COADREAD", "COAD", "READ"),
    "COAD": ("COAD", "COADREAD"),
    "READ": ("READ", "COADREAD"),
    "LUAD": ("LUAD",),
    "LUSC": ("LUSC",),
    "NSCLC": ("LUAD", "LUSC", "NSCLC"),
    "SCLC": ("SCLC",),  # was MISSING; IntOGen has SCLC
    "BRCA": ("BRCA",),
    "PAAD": ("PAAD",),
    "SKCM": ("SKCM", "MEL"),
    "STAD": ("STAD",),
    "PRAD": ("PRAD",),
    "OV": ("OVT",),  # OV maps to IntOGen code OVT
    "KIRC": ("CCRCC",),  # KIRC maps to IntOGen code CCRCC
    "GBM": ("GBM",),
    "HNSC": ("HNSC",),
    "BLCA": ("BLCA",),
    "LIHC": ("HCC",),  # LIHC maps to IntOGen code HCC
    "ESCA": ("ESCA", "ESCC"),
    "UCEC": ("UCEC",),
    # newly-mapped framework indications (each code verified present in IntOGen 2024-09-20):
    "CESC": ("CESC",),
    "LGG": ("LGGNOS",),
    "UCS": ("UCS",),
    "ACC": ("ACC",),
    "CHOL": ("CHOL",),
    "DLBC": ("DLBCLNOS",),
    "LAML": ("AML",),
    "MESO": ("PLMESO",),
}

_DRIVER_TIER_QVALUE = 0.05  # IntOGen q-value below which a per-cohort driver call is confident


def _boto3():
    import boto3

    return boto3.Session().client("s3")


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
        # as an empty role map (would silently strip driver-role evidence for every target) —
        # re-raise (lru_cache never memoizes the raise, so it is retried).
        from methods.target_id_sidecar import is_definitively_absent

        if not is_definitively_absent(e):
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
        # as an empty compendium (would silently strip indication-scoped driver evidence) —
        # re-raise (lru_cache never memoizes the raise, so it is retried).
        from methods.target_id_sidecar import is_definitively_absent

        if not is_definitively_absent(e):
            raise
        return pd.DataFrame(
            columns=["SYMBOL", "CANCER_TYPE", "ROLE", "QVALUE_COMBINATION", "%_SAMPLES_COHORT", "IS_DRIVER"]
        )


# IntOGen ROLE → functional_direction.
_ROLE_TO_DIRECTION = {"Act": "activating", "LoF": "loss_of_function", "ambiguous": "ambiguous"}
# OncoKB geneType → the direction it implies (backbone when IntOGen is silent).
_ONCOKB_TO_DIRECTION = {"ONCOGENE": "activating", "TSG": "loss_of_function", "ONCOGENE_AND_TSG": "ambiguous"}

# Minimum dominance for a per-cohort ROLE vote to establish a DIRECTION (winner >= this x loser).
# IntOGen infers ROLE per (gene, cohort); 274 of 633 driver genes (43%) carry BOTH Act and LoF rows,
# so a bare majority manufactures a direction out of a near-tie — ROS1 {LoF: 3, Act: 2} read
# loss_of_function, for a canonical FUSION-driven oncogene whose SNV spectrum is uninformative.
# Chosen for CONSISTENCY with the recurrent_event_dominant_ratio convention, NOT tuned: measured
# directional precision against OncoKB's independent curated direction is flat across thresholds
# (0.744 at 1:1, 0.762 at 2:1, 0.766 at 3:1) and unanimity is WORST (0.690), because the residual
# conflicts concentrate in single-cohort genes where a lone row is unanimous by construction.
# Contradiction is handled by _resolve_direction below, not by this threshold.
_ROLE_DOMINANCE_RATIO = 2.0


def read_alteration_role(target: str, indication: str) -> dict:
    """alteration_role assembler for a (target, indication). Returns the typed role + direction +
    driver-tier evidence from OncoKB × IntOGen. data_unavailable-safe."""
    sym = target.upper().strip()
    oncokb = _load_oncokb_roles()
    comp = _load_intogen_compendium()
    gene_type = oncokb.get(sym)  # may be None (gene not in OncoKB list)

    base = {"target": target, "indication": indication, "oncokb_gene_type": gene_type, "sources": []}
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

    intogen_role = None  # Act / LoF / ambiguous (indication-scoped, confident-preferred)
    intogen_scope = None  # 'indication' | 'pan_cancer' | None
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

    direction = _resolve_direction(intogen_role, gene_type)
    role = _classify_alteration_role(gene_type, intogen_role, intogen_scope)

    base.update(
        {
            "alteration_role": role,
            "functional_direction": direction,
            "intogen_role": intogen_role,
            "intogen_scope": intogen_scope,
            # keep full precision — q-values span many orders of magnitude (1e-30 etc.); decimal
            # rounding would collapse tiny significant q-values to 0.0.
            "intogen_min_qvalue": (float(f"{intogen_min_q:.3g}") if intogen_min_q is not None else None),
            "intogen_max_pct_samples": (round(intogen_pct, 4) if intogen_pct is not None else None),
            "intogen_cancer_types": (list(cancer_codes) if cancer_codes else None),
        }
    )
    if role == "data_unavailable":
        base["_data_note"] = "target not in OncoKB gene-role list nor an IntOGen driver"
    elif role == "curated_cancer_gene":
        base["_data_note"] = (
            f"OncoKB curates {sym} as {gene_type}, but it has no statistically-significant IntOGen "
            "driver call in any cohort — curated cancer gene, no patient-scale driver evidence"
        )
    return base


def _majority_role(df) -> str:
    """DOMINANT ROLE across a gene's IntOGen rows → Act / LoF / ambiguous.

    Requires a _ROLE_DOMINANCE_RATIO majority, not a bare one: a split per-cohort vote is NOT a
    direction, it is an unresolved role. Do NOT relax this back to `act > lof` — that forced a
    direction for 228 of the 274 genes whose per-cohort ROLE rows disagree.

    Deliberately UNWEIGHTED by q-value or cohort size. That was measured and rejected: for MET/LUAD
    the LoF rows are the MORE significant ones (q=5.7e-6 and 1.1e-2 vs Act q=9.0e-3), so a
    significance-weighted vote flips a canonical activating oncogene HARDER than a plain count does.
    Per-cohort ROLE inference being confident is not the same as it being right about direction, so
    disagreement is resolved against curation in _resolve_direction, not by reweighting the vote.
    """
    counts = df["ROLE"].value_counts()
    if counts.empty:
        return "ambiguous"
    act = int(counts.get("Act", 0))
    lof = int(counts.get("LoF", 0))
    if act > lof and act >= lof * _ROLE_DOMINANCE_RATIO:
        return "Act"
    if lof > act and lof >= act * _ROLE_DOMINANCE_RATIO:
        return "LoF"
    return "ambiguous"  # tie, near-tie, or ambiguous-dominant


def _resolve_direction(intogen_role, gene_type) -> str | None:
    """functional_direction from the two sources, with the CONFLICT case made explicit.

    IntOGen leads where the sources agree or only one speaks (it is functional and per-indication).
    But where IntOGen's INFERRED direction contradicts OncoKB's CURATED direction, neither wins:
    the answer is `ambiguous`, which is what _classify_alteration_role already reports for the same
    input (`predictive_biomarker` = "direction not resolved").

    This is the fix for a record that asserted both at once. Before 2026-09-12, 80 genes published
    alteration_role=predictive_biomarker beside a fully definite functional_direction — 41 TSGs as
    `activating` (CHEK2, BARD1, CDKN2C, FANCA...) and 39 oncogenes as `loss_of_function` (CDK4,
    ABL1, CD274, ERBB4) — because the direction expression let IntOGen win unconditionally.

    That defect is the ROOT CAUSE two downstream contracts were written to contain: the
    role-agreement gate in intracellular-intrinsic.rules.yaml and
    allele_selective_required_role_rules in wt_loss_safety_conditioning.yaml, both citing "SMARCA2:
    oncokb_gene_type=TSG yet functional_direction=activating". SMARCA2 has exactly ONE IntOGen row
    (Act), so it is unanimous by construction and no dominance ratio reaches it — only this
    conflict rule does. Those co-gates stay in place as defence in depth.

    Precedence, in order:
      1. both sources definite and DISAGREEING  → ambiguous (neither wins)
      2. IntOGen definite                       → IntOGen (functional, per-indication, leads)
      3. otherwise                              → curation, if curation is definite

    Step 3 matters as much as step 1: an `ambiguous` IntOGen vote is the ABSENCE of a direction, not
    evidence against curation, so it must not erase a definite curated one. Letting it through
    produced its own incoherence — ROS1/LUAD read alteration_role=direct_driver_gof (a role that
    names a direction) beside functional_direction=ambiguous (a field that withholds one), and
    likewise CCND1 and MYC, whose per-cohort ROLE rows are exact ties.
    """
    ig = _ROLE_TO_DIRECTION.get(intogen_role)
    kb = _ONCOKB_TO_DIRECTION.get(gene_type)
    definite = {"activating", "loss_of_function"}
    if ig in definite and kb in definite and ig != kb:
        return "ambiguous"  # curated direction contradicted by inferred direction → unresolved
    if ig in definite:
        return ig
    return kb or ig


def _classify_alteration_role(gene_type, intogen_role, intogen_scope) -> str:
    """The typed role primitive:
    direct_driver_gof — an ACTIVATING driver with patient-scale evidence (IntOGen Act, or OncoKB
                        ONCOGENE backed by an IntOGen driver call in some cohort)
    direct_driver_lof — likewise for loss-of-function (tumour suppressor)
    curated_cancer_gene — OncoKB curates a directional role but the gene has ZERO rows in the
                        IntOGen compendium: a curated cancer gene with NO statistically-significant
                        driver call in ANY cohort. Real evidence, but not a "drives this indication"
                        claim — see the note below.
    predictive_biomarker — a driver gene whose role is ambiguous / bidirectional (OncoKB
                           ONCOGENE_AND_TSG, IntOGen ambiguous, or an OncoKB↔IntOGen conflict) —
                           actionable as a marker, direction not resolved
    passenger — known to a source but with no driver role (OncoKB NEITHER/INSUFFICIENT and not an
                IntOGen driver): no driver evidence for this target
    data_unavailable — absent from both sources entirely.

    CURATION IS NOT MEASUREMENT (2026-09-12). `or is_oncogene` / `or is_tsg` used to make OncoKB
    gene-list MEMBERSHIP by itself sufficient for a direct_driver_* call, so 440 of 1242 OncoKB
    genes (283 ONCOGENE + 157 TSG) with zero IntOGen rows were reported as in-indication drivers —
    with a rule rationale that says "in this indication". Measured examples: CD19, FOLR1 and
    TACSTD2 are all oncokb=ONCOGENE with 0 compendium rows; their therapeutic rationale is lineage
    EXPRESSION, not genomic driver status. Beyond the false claim, direct_driver_gof feeds
    wt_loss_safety_conditioning.yaml's allele_selective_eligibility_rules, so gene-list membership
    was buying an allele-selective WT-loss safety downgrade for targets with no measured selectable
    allele. Membership now lands in curated_cancer_gene. Do NOT re-add the bare `or is_oncogene`.
    """
    is_oncogene = gene_type in ("ONCOGENE",)
    is_tsg = gene_type in ("TSG",)
    is_dual = gene_type in ("ONCOGENE_AND_TSG",)
    known_gene = gene_type is not None
    intogen_driver = intogen_role is not None

    if not known_gene and not intogen_driver:
        return "data_unavailable"
    # CURATED-ONLY: a DIRECTIONAL OncoKB role with no patient-scale driver call anywhere. Checked
    # BEFORE the direction branches, which is what stops membership alone reading as a driver.
    # Scoped to the directional roles on purpose: ONCOGENE_AND_TSG already resolves to
    # predictive_biomarker, which makes no direction claim and carries a neutral signal, so it was
    # never part of this defect and is left alone.
    if not intogen_driver and (is_oncogene or is_tsg):
        return "curated_cancer_gene"
    # Direction from either source; IntOGen (functional, patient-scale) leads, OncoKB backs.
    if intogen_role == "Act" or is_oncogene:
        if intogen_role == "LoF" or is_tsg:
            return "predictive_biomarker"  # conflicting directions → marker, not a clean driver call
        return "direct_driver_gof"
    if intogen_role == "LoF" or is_tsg:
        return "direct_driver_lof"
    if is_dual or intogen_role == "ambiguous":
        return "predictive_biomarker"
    # known to a source but with no driver role (OncoKB NEITHER/INSUFFICIENT, no IntOGen driver)
    return "passenger"
