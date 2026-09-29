#!/usr/bin/env python3
"""subgroup_assigner_directly_tagged CLI — generate per-sample subgroup assignments
from directly-tagged source fields.

Invocation:
    subgroup-assigner-directly-tagged \
      --subgroup-catalog /path/to/coadread-subgroups-2026-q2.yaml \
      --data-source tcga \
      --release-pin 2026-Q2 \
      --catalog-repo /path/to/data-catalog \
      --out /path/to/output-dir/

The CLI:
  1. Loads the subgroup_catalog YAML; filters to atomic_strata with
     derivation_source in {directly_tagged_clinical, directly_tagged_source_provided}.
  2. Resolves the catalog's input manifest per data-source (TCGA marker paper
     for tcga; DepMap OmicsInferredMolecularSubtypes.csv + Model.csv for depmap).
  3. Evaluates each stratum's CEL-subset rule to produce per-sample membership.
  4. Emits:
       <out>/assignments.parquet  (tall rows: sample_id, stratum_id, is_member, ...)
       <out>/manifest.yaml        (validates against subgroup_assignment.schema.json)

Iter-1b implementation — Phase 2a.1 of iDAS Subtype Pipeline. See
target-contracts docs/design/SAMPLE_ANNOTATION_PLAN.md for Modality A design.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import click
import pandas as pd
import yaml

from methods.subgroup_common import lineage as _lineage
from methods.subgroup_common.manifest import emit_assignment_manifest
from methods.subgroup_common.paths import cache_root

METHOD_DIR = Path(__file__).resolve().parent
METHOD_VERSION = "0.3.0"  # Phase 2a.1 → 0.3.0 adds fusion-consensus source path

SUPPORTED_DERIVATION_SOURCES = {
    "directly_tagged_clinical",
    "directly_tagged_source_provided",
}

# data_source.method values that route to the fusion-consensus evaluator instead
# of the scalar-column rule evaluator. Fusion is set-membership over a per-
# (sample, gene) table (a sample can carry several fusions), not a scalar-column
# `==`, so it needs its own path + its own source frame.
_FUSION_METHOD = "fusion_partner_match"

# data_source.method that routes to a per-sample DERIVED-product label frame
# (e.g. tcga-tmb-per-sample-v1's tmb_bucket). Like the fusion path it reads a
# derived product rather than the marker-paper frame, but it's per-SAMPLE (not
# per-sample-gene) so a plain scalar `field == 'value'` rule applies directly.
_SAMPLE_LABEL_METHOD = "sample_label_match"

# data_source.method for gene-level copy-number amplification calls. Reads a
# per-(patient, gene) GISTIC product (framework-cn-gistic/{ind}-cn.parquet);
# the rule `copy_number.CCND1 == 'amplified'` names the gene in the lhs suffix
# and the amp_call value on the rhs. Per-(patient, gene) → own evaluator.
_CN_AMP_METHOD = "gene_amp_call"


# ---------- CEL-subset rule parser -----------------------------------------

# iter-1 rules are all forms of:
#   `<lhs> == '<value>'`
#   `<lhs> in [<values>]`
# Where <lhs> is `namespace.field` (e.g. `clinical.MSI_status`,
# `copy_number.ERBB2`).

_EQ_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_.]*)\s*==\s*'([^']*)'$")
_IN_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_.]*)\s+in\s+\[([^\]]+)\]$")


def parse_rule(rule: str) -> tuple[str, str, list[str]]:
    """Parse a CEL-subset rule into (field_lhs, op, values).

    Returns:
        (lhs, 'eq', [single_value]) for `field == 'value'`
        (lhs, 'in', [val1, val2, ...]) for `field in ['v1', 'v2']`

    Raises ValueError on unsupported forms (e.g., MAF predicates, negations,
    numeric comparisons — those belong in maf_filter or classifier assigners).
    """
    rule = rule.strip()
    m = _EQ_RE.match(rule)
    if m:
        return m.group(1), "eq", [m.group(2)]
    m = _IN_RE.match(rule)
    if m:
        raw_values = m.group(2)
        # Split on commas; strip whitespace + single quotes
        values = [v.strip().strip("'\"") for v in raw_values.split(",")]
        return m.group(1), "in", values
    raise ValueError(
        f"Unsupported rule form for directly-tagged assigner: {rule!r}. "
        f"This method only supports `field == 'value'` and `field in [values]`. "
        f"Other forms (MAF predicates, thresholds, classifiers) belong in "
        f"subgroup_assigner_maf_filter or subgroup_assigner_classifier."
    )


# ---------- Source-data loaders --------------------------------------------


def _load_tcga_marker_paper_labels(catalog_repo: Path, indication: str) -> pd.DataFrame:
    """Load TCGA marker-paper subtype labels for the indication.

    Returns a DataFrame with columns: sample_id (TCGA aliquot), patient_id
    (TCGA barcode), source_native_id, and whatever subtype columns the
    marker paper ships for this indication.

    Iter-1b scaffold: this reads a local CSV fallback if the S3 fetch is
    unavailable. The canonical source is
    s3://onc-compbio/data-catalog/sources/tcga-marker-papers/subtypes-2018/,
    with per-cohort files tcga_subtype_{CRC,LUAD,LUSC,PAAD,STAD,HNSC}.csv +
    the pancan_atlas_subtypes_curated.csv.

    For iter-1 the caller passes indication codes; the mapping to
    marker-paper file is:
        COADREAD -> tcga_subtype_CRC.csv
        NSCLC    -> (composed from tcga_subtype_LUAD.csv + tcga_subtype_LUSC.csv)
        HNSC     -> tcga_subtype_HNSC.csv
        STAD     -> tcga_subtype_STAD.csv
        PAAD     -> tcga_subtype_PAAD.csv
        AML      -> tcga_subtype_LAML.csv (if present in marker paper)
        ESCA     -> pancan_atlas_subtypes_curated.csv (histology from clinical)

    Not implemented here as a full fetch — the actual S3-plus-local-cache
    fetcher lives in subgroup_common/loaders.py (Phase 2a.4). This method's
    Phase-2a.1 responsibility is the CLI + rule-application logic; the
    loader is stubbed with a fallback-file protocol.
    """
    # Delegate to a lightweight local resolver that reads a session-cached
    # copy if present, otherwise returns None + prints a fetch instruction.
    fallback = cache_root() / "framework-tcga-marker-paper" / indication.lower() / "subtypes.csv"
    if not fallback.exists():
        raise FileNotFoundError(
            f"TCGA marker-paper labels for {indication} not found at {fallback}. "
            f"Phase 2a.1 stubs the fetch; Phase 2a.4 (subgroup_common/loaders.py) "
            f"provides the canonical loader with S3-plus-local-cache resolution. "
            f"For immediate execution: pull the source file from "
            f"s3://onc-compbio/data-catalog/sources/tcga-marker-papers/subtypes-2018/ "
            f"into the fallback path."
        )

    df = pd.read_csv(fallback)

    # ---- Source-specific column normalization (Phase 2b/c real-data fix) ----
    # TCGA marker-paper CSVs (TCGAbiolinks::PanCancerAtlas_subtypes export) are
    # patient-level with column `patient` = TCGA barcode. Normalize to the
    # resolver-product convention: sample_id / patient_id / source_native_id
    # per docs/design/IDAS_SUBTYPE_PIPELINE.md.
    if "patient" in df.columns and "sample_id" not in df.columns:
        df = df.rename(columns={"patient": "patient_id"})
        # Marker-paper is patient-level; sample_id == patient_id for this source.
        df["sample_id"] = df["patient_id"]
        df["source_native_id"] = df["patient_id"]

    # ---- Source-specific value normalization ----
    # TCGA anatomic_organ_subdivision uses Title-Case-With-Spaces
    # (`Sigmoid Colon`, `Ascending Colon`). Catalog rules use lowercase-with-
    # underscores (`sigmoid_colon`). Normalize at load time so catalog rules
    # stay clean.
    if "anatomic_organ_subdivision" in df.columns:
        df["primary_site"] = df["anatomic_organ_subdivision"].str.lower().str.replace(" ", "_")

    # ---- Optional: Guinney 2015 CMS join (COADREAD only) --------------------
    # The TCGA marker-paper CRC file carries MSI/methylation/expression-3-class
    # subtypes but NOT the Guinney 2015 CMS1-4 framework. Land Guinney CMS as
    # an additive column via a left-join on TCGA patient barcode. Source cached
    # from s3://onc-compbio/data-catalog/sources/guinney-2015-crc-cms/
    # cms_labels_public_all.txt (573 TCGA samples with canonical CMS1-4 labels;
    # see manifests/sources/guinney-2015-crc-cms-consortium.yaml in data-catalog).
    if indication == "COADREAD":
        # --- Guinney 2015 CMS labels (cms_labels_public_all.txt) ---
        cms_fallback = cache_root() / "framework-guinney-2015-crc-cms" / "cms_labels_public_all.txt"
        if cms_fallback.exists():
            cms_df = pd.read_csv(cms_fallback, sep="\t")
            tcga_cms = cms_df[cms_df["dataset"] == "tcga"][
                ["sample", "CMS_final_network_plus_RFclassifier_in_nonconsensus_samples"]
            ].rename(
                columns={
                    "sample": "patient_id",
                    "CMS_final_network_plus_RFclassifier_in_nonconsensus_samples": "cms_label",
                }
            )
            df = df.merge(tcga_cms, on="patient_id", how="outer")
            # Backfill sample_id + source_native_id for Guinney-only rows
            df["sample_id"] = df["sample_id"].fillna(df["patient_id"])
            df["source_native_id"] = df["source_native_id"].fillna(df["patient_id"])

        # --- Guinney 2015 clinical/molecular (clinical_molecular_public_all.txt) ---
        # Same Guinney 2015 CCS Consortium source; separate file with richer
        # clinical + molecular metadata. Iter-1 uses cimp column for CIMP-High/
        # CIMP-Low/CIMP-Neg atomic strata (Weisenberger 2006 methylator
        # phenotype). Also carries msi/kras_mut/braf_mut for cross-validation
        # against marker-paper + MC3 (cross-validation opportunity — not yet
        # wired as strata since we already have those from the other sources).
        clinical_fallback = cache_root() / "framework-guinney-2015-crc-cms" / "clinical_molecular_public_all.txt"
        if clinical_fallback.exists():
            clin_df = pd.read_csv(clinical_fallback, sep="\t")
            tcga_clin = clin_df[clin_df["dataset"] == "tcga"][["sample", "cimp"]].rename(
                columns={"sample": "patient_id"}
            )
            df = df.merge(tcga_clin, on="patient_id", how="outer")
            # Backfill sample_id + source_native_id in case Guinney-clinical-
            # only rows exist that aren't in the marker-paper or Guinney-CMS files
            df["sample_id"] = df["sample_id"].fillna(df["patient_id"])
            df["source_native_id"] = df["source_native_id"].fillna(df["patient_id"])

    # --- BRCA PAM50 from the PanCanAtlas curated subtypes file --------------------------------
    # The BRCA catalog's PAM50 strata rule `clinical.pam50_subtype == 'LumA'|'LumB'|'Her2'|'Basal'|
    # 'Normal'`. The curated file ships them as Subtype_Selected = 'BRCA.LumA'/.LumB/.Her2/.Basal/
    # .Normal (VERIFIED 1,218 BRCA rows). Decode the BRCA.<PAM50> prefix → a bare `pam50_subtype`
    # column (mirrors the STAD GI.* decode). Ingest-free; unmappable rows stay NaN → tri-value null.
    if indication == "BRCA":
        pam = _load_brca_pam50_from_curated()
        if pam is not None and not pam.empty:
            df = df.merge(pam, on="patient_id", how="outer")
            df["sample_id"] = df["sample_id"].fillna(df["patient_id"])
            df["source_native_id"] = df["source_native_id"].fillna(df["patient_id"])

    # --- NSCLC histology from TCGA-CDR clinical (gdc-pancanatlas-clinical-2018) ------------------
    # The marker-paper LUAD/LUSC files carry no `histology` column (they ARE per-histology), and the
    # RNA-seq manifest the catalog previously (mis)pointed at has no clinical fields → histology_Adeno/
    # SCC were silently all-null. TCGA-CDR (TCGA-CDR-SupplementalTableS1.xlsx) has `histological_type`
    # + `type` (LUAD/LUSC); merge a normalized `histology` column so the scalar rule
    # `clinical.histology == 'adenocarcinoma'|'squamous_cell_carcinoma'` resolves. Left-merge on the
    # TCGA patient barcode (bcr_patient_barcode). Ingest-free (manifest already held).
    if indication == "NSCLC":
        cdr = _load_pancanatlas_clinical_histology()
        if cdr is not None and not cdr.empty:
            # ★ The NSCLC marker-paper frame ALREADY carries a complete `histology`
            # column. A bare merge on an overlapping column name makes pandas suffix
            # BOTH sides to histology_x/histology_y, leaving NO `histology` column at
            # all — so _extract_field_value() found nothing and every one of the 1026
            # rows emitted is_member=null while the run exited 0 and logged it as
            # "null (data-missing)". The merge added to FIX all-null histology was what
            # caused it. Keep the left name and coalesce: the curated marker-paper label
            # wins where present, CDR fills only what it does not cover.
            #
            # Measured 2026-09-13 on release-pin 2026-Q3: marker-paper = 1026 patients,
            # 100% labelled (522 adenocarcinoma / 504 squamous). The CDR carries the
            # SAME 1026 patients with the SAME labels — 0 disagreements, 0 rows added,
            # 0 labels added. So for this pin the CDR merge contributes nothing and was
            # the sole cause of the all-null defect. It is kept (coalescing, guarded)
            # rather than deleted so a future pin with a sparser marker-paper file still
            # gets the fallback; if it stays redundant across pins, drop it.
            # Emits 522 / 504 with a 1026 evaluable denominator and 0 null.
            df = _merge_coalescing(df, cdr, on="patient_id", coalesce=("histology",), tag="cdr")
            df["sample_id"] = df["sample_id"].fillna(df["patient_id"])
            df["source_native_id"] = df["source_native_id"].fillna(df["patient_id"])

    _assert_no_merge_collision(df, indication)
    return df


def _merge_coalescing(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    on: str,
    coalesce: tuple[str, ...],
    tag: str,
) -> pd.DataFrame:
    """Outer-merge `right` into `left`, coalescing overlapping columns into the BARE name.

    A bare `left.merge(right, on=...)` with an overlapping column name makes pandas
    suffix BOTH sides to <name>_x / <name>_y, leaving NO column under the bare name.
    Rule fields are read by bare name (`_extract_field_value`), so such a column is
    unreachable BY CONSTRUCTION and every stratum using it silently emits
    is_member=null with a zero exit code. Here the left value wins where present and
    `right` fills its gaps.
    """
    out = left.merge(right, on=on, how="outer", suffixes=("", f"_{tag}"))
    for col in coalesce:
        incoming = f"{col}_{tag}"
        if incoming not in out.columns:
            continue
        out[col] = out[col].fillna(out[incoming]) if col in out.columns else out[incoming]
        out = out.drop(columns=[incoming])
    return out


def _assert_no_merge_collision(df: pd.DataFrame, indication: str | None) -> None:
    """Raise if any column carries pandas' default merge suffix.

    Several loaders merge auxiliary frames on `patient_id`; a future overlapping
    column name would suffix a rule's field to <name>_x/<name>_y and turn the whole
    stratum all-null while the run exits 0 and logs it as "null (data-missing)" —
    the exact NSCLC histology defect this guard was written for. Fail loudly instead.
    """
    collided = [c for c in df.columns if c.endswith(("_x", "_y"))]
    if collided:
        raise RuntimeError(
            f"pandas merge-suffix collision in the {indication} source frame: {collided}. "
            f"A rule reads its field by bare name, so a suffixed column can never be "
            f"matched and every stratum using it would silently emit is_member=null. "
            f"Give the merge an explicit `suffixes=` and coalesce into the bare name "
            f"(see _merge_coalescing)."
        )


# TCGA-CDR histological_type → catalog histology vocabulary. The TCGA-CDR export uses the compact
# strings 'Lung Adenocarcinoma' / 'Lung Squamous Cell Carcinoma' (verified against the real file);
# a substring fallback tolerates any granular variant a future export might carry. Anything unmapped
# stays NaN → tri-value null (unassayed), never a false negative.
def _cdr_histology_label(hist_type: str, tcga_type: str) -> "str | None":
    s = str(hist_type or "").lower()
    if "adenocarcinoma" in s:
        return "adenocarcinoma"
    if "squamous" in s:
        return "squamous_cell_carcinoma"
    # fall back to the TCGA project code (LUAD=adeno, LUSC=squamous) when histological_type is blank
    if tcga_type == "LUAD":
        return "adenocarcinoma"
    if tcga_type == "LUSC":
        return "squamous_cell_carcinoma"
    return None


# PAM50 label decode: curated Subtype_Selected 'BRCA.<PAM50>' → the catalog's bare pam50_subtype token.
_BRCA_PAM50_DECODE = {
    "BRCA.LumA": "LumA",
    "BRCA.LumB": "LumB",
    "BRCA.Her2": "Her2",
    "BRCA.Basal": "Basal",
    "BRCA.Normal": "Normal",
}


def _load_brca_pam50_from_curated() -> "pd.DataFrame | None":
    """Load PanCanAtlas curated subtypes, filter to BRCA, decode Subtype_Selected 'BRCA.<PAM50>' →
    per-patient `pam50_subtype` ∈ {LumA, LumB, Her2, Basal, Normal}. Unmappable rows dropped →
    tri-value null. Session-cached fallback; None if unreachable (strata self-degrade to null)."""
    fallback = cache_root() / "framework-tcga-marker-paper" / "pancan_atlas_subtypes_curated.csv"
    if not fallback.exists():
        return None
    try:
        cur = pd.read_csv(fallback)
    except FileNotFoundError:
        return None  # race: file vanished after the exists() check → null-strata
    except Exception:  # noqa: BLE001
        # the curated CSV EXISTS (checked above) — a parse failure is corruption, not a data gap;
        # surface it rather than silently collapsing every BRCA patient to a null PAM50 stratum.
        raise
    id_col = "pan.samplesID" if "pan.samplesID" in cur.columns else cur.columns[0]
    brca = cur[cur["cancer.type"].astype(str).str.upper().str.contains("BRCA", na=False)].copy()
    brca["pam50_subtype"] = brca["Subtype_Selected"].map(_BRCA_PAM50_DECODE)
    brca = brca.dropna(subset=["pam50_subtype"])
    # PanCanAtlas sample ids are aliquot-level (TCGA-XX-XXXX-01A...); reduce to the 12-char patient barcode
    brca["patient_id"] = brca[id_col].astype(str).str.slice(0, 12)
    return brca[["patient_id", "pam50_subtype"]].drop_duplicates("patient_id")


def _load_pancanatlas_clinical_histology() -> "pd.DataFrame | None":
    """Load TCGA-CDR clinical, filter to LUAD/LUSC, return per-patient normalized `histology`.

    Columns out: patient_id (TCGA barcode), histology ∈ {adenocarcinoma, squamous_cell_carcinoma}
    (unmappable rows DROPPED → those patients get tri-value null, not a false negative). Session-cached
    fallback; returns None if unreachable (strata self-degrade to null)."""
    fallback = cache_root() / "framework-tcga-cdr" / "TCGA-CDR-SupplementalTableS1.xlsx"
    if not fallback.exists():
        return None
    try:
        cdr = pd.read_excel(fallback, sheet_name=0)
    except Exception:  # noqa: BLE001
        return None
    lung = cdr[cdr["type"].isin(["LUAD", "LUSC"])].copy()
    lung["histology"] = [_cdr_histology_label(ht, tp) for ht, tp in zip(lung["histological_type"], lung["type"])]
    lung = lung.dropna(subset=["histology"])
    return lung[["bcr_patient_barcode", "histology"]].rename(columns={"bcr_patient_barcode": "patient_id"})


# Per-indication cache-dir slug for the prefetched BPC LOT parquet — MUST match
# scripts/prefetch_source_maf.py::GENIE_BPC_CACHE_DIR (the producer). Each cohort's
# LOT parquet lives in its own framework-genie-bpc-<slug>/ dir so identically-named
# regimen/cpt CSVs don't collide across indications.
_GENIE_BPC_CACHE_DIR = {
    "COADREAD": "genie-bpc-crc-v2",
    "NSCLC": "genie-bpc-nsclc-v2",
}


def _load_genie_bpc_lot(catalog_repo: Path, indication: str) -> pd.DataFrame:
    """Load GENIE-BPC line-of-therapy (LOT) per-sample labels.

    Returns a DataFrame with columns: sample_id (GENIE cpt_genie_sample_id),
    patient_id (GENIE record_id), source_native_id, lot_category
    (LOT_1L_only / LOT_2L / LOT_3Lplus), max_lot.

    LOT is DERIVED (not a single source column): the prefetch step
    (scripts/prefetch_source_maf.py --source genie_bpc_lot) reads the
    GENIE-BPC regimen_cancer_level_dataset.csv, takes max(regimen_number_
    within_cancer) per patient index-cancer (ca_seq=0), maps to a LOT
    category, and joins to sample_id via cancer_panel_test_level_dataset.csv.
    This loader reads the prefetched per-indication parquet from that
    indication's cache dir (the producer's GENIE_BPC_CACHE_DIR slug).

    Real derivations: 1,176 CRC samples (205 1L / 203 2L / 768 3L+);
    1,093 NSCLC samples (298 1L / 243 2L / 552 3L+).
    """
    slug = _GENIE_BPC_CACHE_DIR.get(indication.upper())
    if slug is None:
        raise ValueError(
            f"No GENIE-BPC cache-dir slug for indication {indication!r}; add it to "
            f"_GENIE_BPC_CACHE_DIR (mirror prefetch_source_maf.py::GENIE_BPC_CACHE_DIR)."
        )
    fallback = cache_root() / f"framework-{slug}" / f"{indication.lower()}-bpc-lot.parquet"
    if fallback.exists():
        return pd.read_parquet(fallback)
    raise FileNotFoundError(
        f"GENIE-BPC LOT parquet for {indication} not found at {fallback}. "
        f"Run scripts/prefetch_source_maf.py --source genie_bpc_lot "
        f"--indication {indication} to derive it from the BPC regimen +"
        f"cancer-panel-test datasets."
    )


# ---------- Fusion-consensus source path (NSCLC ALK/ROS1/RET etc.) ----------
#
# Fusion strata (data_source.method == 'fusion_partner_match') read a DERIVED
# per-(sample_key, gene_symbol) consensus product (tcga-fusion-consensus-per-
# sample-v1), NOT the marker-paper frame. This is a separate loader + evaluator
# because (a) the source frame is keyed differently (sample_key / gene_symbol),
# and (b) fusion membership is set-membership — a sample can carry several
# fusions — which the scalar-column `field == value` evaluator cannot express.


def _fetch_derived_parquet(catalog_repo: Path, manifest_id: str, filename: str) -> Path:
    """Resolve a derived product's parquet to a local path.

    Resolution order mirrors subgroup_common.loaders.load_assignments:
      1. session cache: {cache_root}/framework-fusion-consensus/{manifest_id}/{filename}
      2. derived manifest's s3_uri → aws s3 cp → session cache

    `filename` selects the payload (fusion_consensus_per_sample_gene.parquet) or
    the companion (sample_coverage.parquet); both live under the same S3 prefix,
    so the coverage URI is the payload s3_uri with the basename swapped.
    """
    local = cache_root() / "framework-fusion-consensus" / manifest_id / filename
    if local.exists():
        return local

    manifest_path = catalog_repo / "manifests" / "derived" / f"{manifest_id}.yaml"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Fusion-consensus product {manifest_id} not in session cache ({local}) "
            f"and no derived manifest at {manifest_path}. Publish the product "
            f"(data-catalog manifests/derived/{manifest_id}.yaml) or stage the parquet "
            f"at the session-cache path."
        )
    manifest = yaml.safe_load(manifest_path.read_text())
    payload_uri = manifest.get("s3_uri")
    if not payload_uri:
        raise FileNotFoundError(f"Derived manifest {manifest_id} declares no s3_uri to fetch from.")
    # Companion files share the payload's prefix; swap the basename.
    s3_uri = payload_uri.rsplit("/", 1)[0] + "/" + filename
    local.parent.mkdir(parents=True, exist_ok=True)
    import subprocess

    r = subprocess.run(["aws", "s3", "cp", s3_uri, str(local), "--no-progress"], capture_output=True, text=True)
    if r.returncode != 0 or not local.exists():
        raise FileNotFoundError(
            f"S3 fetch of {manifest_id}/{filename} failed ({s3_uri}): "
            f"{r.stderr.strip()[:200]}. Check AWS_PROFILE (needs onc-compbio GetObject)."
        )
    return local


def _load_fusion_consensus(catalog_repo: Path, manifest_id: str) -> pd.DataFrame:
    """Load the per-(sample_key, gene_symbol) fusion-consensus payload parquet."""
    p = _fetch_derived_parquet(catalog_repo, manifest_id, "fusion_consensus_per_sample_gene.parquet")
    return pd.read_parquet(p)


def _load_fusion_coverage(catalog_repo: Path, manifest_id: str) -> pd.DataFrame | None:
    """Load the sample_coverage.parquet companion (per-(sample_key, caller) roster).

    Returns None if the companion is absent — the evaluator then degrades the
    non-member class from `false` to `null` (cannot distinguish assayed-negative
    from not-assayed without the coverage denominator)."""
    try:
        p = _fetch_derived_parquet(catalog_repo, manifest_id, "sample_coverage.parquet")
    except FileNotFoundError:
        return None
    return pd.read_parquet(p)


def _fusion_participant_id(sample_key: str) -> str | None:
    """Participant-level barcode from a TCGA sample_key (TCGA-tss-part-sampleNum
    → TCGA-tss-part). Used as patient_id so fusion assignments join to the same
    patient axis as the marker-paper strata."""
    if not isinstance(sample_key, str):
        return None
    parts = sample_key.split("-")
    return "-".join(parts[:3]) if len(parts) >= 3 else sample_key


def _evaluate_fusion_stratum(
    stratum: dict,
    fusion_df: pd.DataFrame,
    coverage_df: pd.DataFrame | None,
    tissue_filter: list[str] | None,
) -> pd.DataFrame:
    """Evaluate a fusion_partner_match stratum against the consensus product.

    Tri-value semantics (the payoff of the sample_coverage companion):
      is_member = True   sample has a (sample_key, target_gene) row with
                         caller_count >= min_caller_count
      is_member = False  sample was ASSAYED (in coverage_df) but has no such row
      is_member = null   sample not in coverage_df (not assayed) — or coverage
                         absent entirely (can't distinguish negative from unassayed)

    The rule names the target gene as `fusion_gene == 'ALK'` (parsed by the
    shared parse_rule). The caller-count threshold is a data_source knob
    (data_source.min_caller_count, default 1 = union / "any partner").
    """
    lhs, op, values = parse_rule(stratum["rule"])
    if op != "eq" or len(values) != 1:
        raise ValueError(
            f"Fusion stratum {stratum['id']} rule must be `fusion_gene == '<GENE>'`; got {stratum['rule']!r}."
        )
    target_gene = values[0]
    min_cc = int(stratum.get("data_source", {}).get("min_caller_count", 1))

    fdf = fusion_df
    if tissue_filter and "tissue" in fdf.columns:
        fdf = fdf[fdf["tissue"].isin(tissue_filter)]

    # Samples with a qualifying fusion in the target gene.
    hits = fdf[(fdf["gene_symbol"] == target_gene) & (fdf["caller_count"] >= min_cc)]
    member_keys = set(hits["sample_key"].dropna())

    # Denominator (assayed samples). Prefer coverage; else fall back to the
    # union of samples appearing anywhere in the consensus for this tissue set.
    if coverage_df is not None:
        cov = coverage_df
        if tissue_filter and "tissue" in cov.columns:
            cov = cov[cov["tissue"].isin(tissue_filter)]
        assayed_keys = set(cov["sample_key"].dropna())
        coverage_known = True
    else:
        assayed_keys = set(fdf["sample_key"].dropna())
        coverage_known = False

    # The row universe: every assayed sample (so non-members surface as False),
    # unioned with member samples (defensive — a member should always be assayed).
    all_keys = sorted(assayed_keys | member_keys)

    def _member(k: str):
        if k in member_keys:
            return True
        if coverage_known and k in assayed_keys:
            return False
        # Not assayed (or coverage unknown): insufficient evidence.
        return None

    rows = []
    for k in all_keys:
        is_mem = _member(k)
        rows.append(
            {
                "sample_id": k,
                "patient_id": _fusion_participant_id(k),
                "source_native_id": k,
                "stratum_id": stratum["id"],
                "is_member": is_mem,
                "derivation_source": stratum["derivation_source"],
                "derivation_value": target_gene if is_mem is True else "",
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "sample_id",
            "patient_id",
            "source_native_id",
            "stratum_id",
            "is_member",
            "derivation_source",
            "derivation_value",
        ],
    )


# ---------- Per-sample label product path (TMB etc.) ----------
#
# A per-sample derived product carrying a categorical label column (e.g.
# tcga-tmb-per-sample-v1 with tmb_bucket ∈ {high, low}). The stratum's scalar
# rule (`tmb_bucket == 'high'`) evaluates directly against the label frame; the
# frame is keyed on patient_key (TCGA participant barcode), aligned to the
# marker-paper join axis so the assignment product co-joins with other strata.


def _load_sample_label_product(catalog_repo: Path, manifest_id: str) -> pd.DataFrame:
    """Load a per-sample label derived product's parquet (single-file payload)."""
    p = _fetch_derived_parquet(catalog_repo, manifest_id, "tmb_per_sample.parquet")
    return pd.read_parquet(p)


def _evaluate_sample_label_stratum(
    stratum: dict,
    label_df: pd.DataFrame,
    tissue_filter_keys: set | None,
) -> pd.DataFrame:
    """Evaluate a scalar `field == 'value'` / `field in [...]` rule against a
    per-sample label frame (patient_key + label columns).

    Tri-value: member = label matches; false = sample present with a non-matching
    label; null = sample absent from the product (unassayed). tissue_filter_keys,
    when given, restricts the row universe to the indication's samples (the label
    product is pan-TCGA; a downstream NSCLC shard wants only LUAD+LUSC patients).
    """
    lhs, op, values = parse_rule(stratum["rule"])
    _, field = lhs.split(".", 1) if "." in lhs else (None, lhs)
    if field not in label_df.columns:
        raise ValueError(
            f"Sample-label stratum {stratum['id']} references field {field!r} "
            f"not in the product columns {list(label_df.columns)}."
        )

    df = label_df
    if tissue_filter_keys is not None:
        df = df[df["patient_key"].isin(tissue_filter_keys)]

    def _member(v):
        if pd.isna(v):
            return None
        return (v == values[0]) if op == "eq" else (v in values)

    rows = []
    for _, r in df.iterrows():
        is_mem = _member(r[field])
        rows.append(
            {
                "sample_id": r["patient_key"],
                "patient_id": r["patient_key"],
                "source_native_id": r["patient_key"],
                "stratum_id": stratum["id"],
                "is_member": is_mem,
                "derivation_source": stratum["derivation_source"],
                "derivation_value": str(r[field]) if is_mem is True else "",
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "sample_id",
            "patient_id",
            "source_native_id",
            "stratum_id",
            "is_member",
            "derivation_source",
            "derivation_value",
        ],
    )


# ---------- Copy-number amplification path (CCND1 etc.) ----------
#
# Per-(patient, gene) GISTIC amp calls from framework-cn-gistic/{ind}-cn.parquet
# (produced by scripts/prefetch_cn_gistic.py). The rule
# `copy_number.CCND1 == 'amplified'` names the gene in the lhs suffix (CCND1) and
# the amp_call on the rhs. Membership = the sample's row for that gene has
# amp_call == 'amplified'; false = present but not amplified; null = gene/sample
# absent from the CN product (unassayed).


def _load_cn_gistic(indication: str) -> pd.DataFrame | None:
    """Load the per-(patient, gene) GISTIC amp product for an indication.

    Cached at {cache_root}/framework-cn-gistic/{ind}-cn.parquet. Returns None if
    absent (the CN strata then emit null — cannot call amp without the product)."""
    p = cache_root() / "framework-cn-gistic" / f"{indication.lower()}-cn.parquet"
    if not p.exists():
        return None
    return pd.read_parquet(p)


def _evaluate_cn_amp_stratum(stratum: dict, cn_df: pd.DataFrame | None) -> pd.DataFrame:
    """Evaluate a `copy_number.<GENE> == '<amp_call>'` rule against the CN product.

    Tri-value: member = (patient, gene) row has the matching amp_call; false =
    present with a different amp_call; null = gene/patient absent (unassayed) or
    the CN product is missing entirely.
    """
    lhs, op, values = parse_rule(stratum["rule"])
    _, gene = lhs.split(".", 1) if "." in lhs else (None, lhs)
    if op != "eq" or len(values) != 1:
        raise ValueError(
            f"CN-amp stratum {stratum['id']} rule must be "
            f"`copy_number.<GENE> == '<amp_call>'`; got {stratum['rule']!r}."
        )
    target_call = values[0]

    if cn_df is None:
        return pd.DataFrame(
            columns=[
                "sample_id",
                "patient_id",
                "source_native_id",
                "stratum_id",
                "is_member",
                "derivation_source",
                "derivation_value",
            ]
        )

    sub = cn_df[cn_df["gene_symbol"] == gene]
    rows = []
    for _, r in sub.iterrows():
        is_mem = r["amp_call"] == target_call
        rows.append(
            {
                "sample_id": r["patient_key"],
                "patient_id": r["patient_key"],
                "source_native_id": r["patient_key"],
                "stratum_id": stratum["id"],
                "is_member": bool(is_mem),
                "derivation_source": stratum["derivation_source"],
                "derivation_value": str(r["amp_call"]) if is_mem else "",
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "sample_id",
            "patient_id",
            "source_native_id",
            "stratum_id",
            "is_member",
            "derivation_source",
            "derivation_value",
        ],
    )


# Indication → DepMap OncotreeLineage / organ. RE-EXPORTED from
# subgroup_common.lineage, which alias-imports the ONE canonical map
# (depmap_chronos.cli.INDICATION_LINEAGE, 42 codes) rather than forking it: this module and
# scripts/prefetch_source_maf.py both scope DepMap by lineage, and the prefetch
# script formerly kept its own ONE-entry copy, so every non-COADREAD DepMap
# prefetch died with "No DepMap lineage mapping". The names stay bound here for
# the existing importers (see tests/test_dry_run.py).
INDICATION_TO_DEPMAP_LINEAGE = _lineage.INDICATION_TO_DEPMAP_LINEAGE
INDICATION_TO_DEPMAP_ORGAN = _lineage.INDICATION_TO_DEPMAP_ORGAN

# Indication → TCGA disease codes for filtering the pan-TCGA fusion-consensus
# product to the indication's cohorts. NSCLC = LUAD + LUSC. Without this an
# NSCLC fusion stratum would draw its assayed-sample denominator from all 33
# TCGA tissues, mis-scaling the false/null classes.
INDICATION_TO_TCGA_TISSUES = {
    "COADREAD": ["COADREAD", "COAD", "READ"],
    "NSCLC": ["LUAD", "LUSC"],
    "HNSC": ["HNSC"],
    "STAD": ["STAD"],
    "ESCA": ["ESCA"],
    "PAAD": ["PAAD"],
    "AML": ["LAML"],
}


# DepMap OncotreeSubtype → catalog-rule categorical vocab. DepMap cell lines
# carry no direct histology/anatomic-site column, but OncotreeSubtype encodes
# both; these maps land the two NSCLC-histology + three HNSC-anatomic-site
# strata that would otherwise emit all-null on the DepMap source. A subtype
# absent from the map (small-cell, large-cell, adenosquamous, hypopharynx,
# NUT-midline, generic-HNSC) intentionally maps to NaN → tri-value null.
_DEPMAP_ONCOTREE_TO_HISTOLOGY = {
    "Lung Adenocarcinoma": "adenocarcinoma",  # NSCLC histology_Adeno
    "Lung Squamous Cell Carcinoma": "squamous_cell_carcinoma",  # histology_SCC
    "Esophageal Adenocarcinoma": "adenocarcinoma",  # ESCA histology_EAC
    "Esophageal Squamous Cell Carcinoma": "squamous_cell_carcinoma",  # ESCA histology_ESCC
}
_DEPMAP_ONCOTREE_TO_SITE = {
    "Oral Cavity Squamous Cell Carcinoma": "oral_cavity",  # HNSC site_oral_cavity
    "Larynx Squamous Cell Carcinoma": "larynx",  # site_larynx
    "Oropharynx Squamous Cell Carcinoma": "oropharyngeal",  # site_oropharyngeal
}


def _load_depmap_inferred_subtypes(catalog_repo: Path, indication: str | None = None) -> pd.DataFrame:
    """Load DepMap OmicsInferredMolecularSubtypes.csv + Model.csv join.

    Returns a DataFrame with columns: ModelID, OncotreeLineage,
    OncotreePrimaryDisease, OncotreeSubtype, and the OmicsInferredMolecularSubtypes
    flag columns (KRAS_G12C, MSI, EWSR1_FLI1, etc.).

    When `indication` is given, the frame is FILTERED to that indication's
    DepMap OncotreeLineage (INDICATION_TO_DEPMAP_LINEAGE) — without this the
    shard is pan-cancer and a COADREAD dependency panorama would compute KRAS
    dependency across every lineage's MSI-H lines, not Bowel's.

    Phase 2a.4 (subgroup_common/loaders.py) will provide the canonical
    S3-plus-local-cache resolver. Here we delegate to the existing
    depmap_common/loaders.py pattern where possible.
    """
    try:
        # Prefer the existing depmap_common loader if it has this
        from methods.depmap_common import loaders as depmap_loaders  # noqa
        # depmap_common may not have OmicsInferredMolecularSubtypes yet — that's
        # a Phase-2a.4 add. For now, try local-cache fallback.
    except ImportError:
        pass
    # Cache pin bumped 26q1→26q3 (data-catalog#681, Wave-2 of #810). The lineage crosswalk is
    # byte-stable 26q1→26q3 (#810 re-validation), so no mapping change; only per-lineage membership
    # counts shifted. dmc-26q3 carries OmicsInferredMolecularSubtypes.csv + Model.csv.
    fallback = cache_root() / "framework-depmap-26q3" / "OmicsInferredMolecularSubtypes.csv"
    model_fallback = cache_root() / "framework-depmap-26q3" / "Model.csv"
    if not (fallback.exists() and model_fallback.exists()):
        raise FileNotFoundError(
            f"DepMap OmicsInferredMolecularSubtypes.csv + Model.csv not found at "
            f"{fallback} + {model_fallback}. Phase 2a.4 provides the canonical "
            f"loader. For immediate execution: pull both CSVs from "
            f"s3://onc-compbio/data-catalog/sources/depmap-consortium/dmc-26q3/ "
            f"into the fallback path."
        )
    subtypes = pd.read_csv(fallback)
    model = pd.read_csv(model_fallback)
    df = model.merge(subtypes, on="ModelID", how="left")

    # Restrict to the indication's DepMap lineage (else the shard is pan-cancer).
    if indication is not None:
        lineage = INDICATION_TO_DEPMAP_LINEAGE.get(indication.upper())
        if lineage is None:
            raise ValueError(
                f"No DepMap lineage mapping for indication {indication!r}; add it "
                f"to INDICATION_TO_DEPMAP_LINEAGE (mirror indication_crosswalk.yaml)."
            )
        df = df[df["OncotreeLineage"] == lineage].copy()
        # Second filter for organ-collapsed lineages (Esophagus/Stomach): keep only
        # the indication's organ by OncotreeSubtype substring, else ESCA and STAD
        # would each draw the OTHER organ's cell lines into their shard.
        organ = INDICATION_TO_DEPMAP_ORGAN.get(indication.upper())
        if organ is not None:
            df = df[df["OncotreeSubtype"].fillna("").str.lower().str.contains(organ)].copy()

    # ---- Source-specific column normalization (Phase 2b/c real-data fix) ----
    # DepMap Model.csv uses `ModelID` as the cell-line identifier. Normalize to
    # resolver-product convention: sample_id / source_native_id. DepMap has NO
    # patient concept (cell lines have anonymous PatientID that isn't a
    # clinical patient), so patient_id is null.
    df["sample_id"] = df["ModelID"]
    df["source_native_id"] = df["ModelID"]
    df["patient_id"] = None  # cell lines have no clinical-patient concept

    # ---- Source-specific value normalization ----
    # DepMap OmicsInferredMolecularSubtypes uses `MSI` as a boolean flag column
    # (True = MSI-H, False = MSS-equivalent, NaN = insufficient). COADREAD
    # catalog rules use TCGA marker-paper's categorical form
    # (clinical.MSI_status == 'MSI-H' / 'MSS'). Normalize DepMap's flag →
    # marker-paper categorical so a single rule set fires on both sources.
    # Real-data validation (2026-07-15): 140 Colorectal cell lines →
    # 30 MSI-H, 106 MSS, 4 insufficient.
    if "MSI" in df.columns:

        def _msi_flag_to_status(v):
            if pd.isna(v):
                return None
            return "MSI-H" if v else "MSS"

        df["MSI_status"] = df["MSI"].apply(_msi_flag_to_status)

    # DepMap has no anatomic_organ_subdivision equivalent (cell lines don't
    # have anatomic site metadata beyond `OncotreePrimaryDisease` which is
    # tumor-type, not tumor location). `primary_site` rule will emit is_member=
    # null (insufficient) for all rows — this is CORRECT tri-value behavior:
    # sidedness cannot be evaluated for cell lines.

    # ---- Derive histology / anatomic_site from OncotreeSubtype ----
    # NSCLC histology and HNSC anatomic-site strata reference clinical.histology
    # and clinical.anatomic_site — fields DepMap does not name directly. But
    # DepMap's OncotreeSubtype encodes both (e.g. "Lung Adenocarcinoma",
    # "Larynx Squamous Cell Carcinoma"), so we map it onto the catalog rules'
    # expected categorical vocabulary. Without this the rule evaluator finds no
    # `histology`/`anatomic_site` column and emits is_member=null for EVERY
    # DepMap row (the all-null-stratum bug). A subtype that maps to nothing
    # stays NaN → tri-value null (correct: genuinely unclassifiable).
    if "OncotreeSubtype" in df.columns:
        df["histology"] = df["OncotreeSubtype"].map(_DEPMAP_ONCOTREE_TO_HISTOLOGY)
        df["anatomic_site"] = df["OncotreeSubtype"].map(_DEPMAP_ONCOTREE_TO_SITE)
    # NOTE: HPV status (hpv_status), HNSC Bass subtype (hnsc_bass_subtype), and
    # PAAD Moffitt subtype (paad_moffitt_subtype) are NOT derivable from DepMap
    # — cell lines carry no HPV typing, and Bass/Moffitt are expression-classifier
    # calls (the subgroup_assigner_classifier path), not Oncotree fields. Those
    # strata correctly stay is_member=null on the DepMap source (unmeasurable,
    # not broken); they resolve on the TCGA source where the labels exist.

    return df


# ---------- Rule evaluation ------------------------------------------------


def _extract_field_value(row: pd.Series, field_lhs: str) -> object:
    """Extract a namespaced field value from a row.

    `clinical.MSI_status` -> row['MSI_status'] (namespace is contextual,
    dropped when reading the DataFrame; assigner method is responsible for
    supplying the right DataFrame per data-source).

    `copy_number.ERBB2` -> row['ERBB2_copy_number'] (namespace prefix
    remapped to column suffix when reading DepMap or GDC copy-number tables).
    """
    if "." in field_lhs:
        namespace, field = field_lhs.split(".", 1)
        # For iter-1, all rules use `clinical.<field>` semantics; namespace is
        # informational, actual column is <field>. Namespace normalization is
        # per-source; the loader is responsible for landing the DataFrame in
        # a shape where `<field>` is the column name.
        return row.get(field)
    return row.get(field_lhs)


def _evaluate_stratum(
    stratum: dict,
    df: pd.DataFrame,
    sample_id_col: str,
    patient_id_col: str | None,
    native_id_col: str,
) -> pd.DataFrame:
    """Evaluate a single stratum's rule against the source DataFrame.

    Returns a DataFrame with the resolver-product columns for this stratum's rows:
        sample_id, patient_id, source_native_id, stratum_id, is_member,
        derivation_source, derivation_value, evaluated_at_release
    """
    lhs, op, values = parse_rule(stratum["rule"])
    _, field = lhs.split(".", 1) if "." in lhs else (None, lhs)

    df = df.copy()

    # Phase 2b/c real-data fix: if the rule's field doesn't exist on this
    # data source, emit is_member=null for every row (tri-value insufficient).
    # Do NOT crash the assigner. Example: DepMap has no `primary_site`
    # (sidedness) → all DepMap rows for that stratum emit `null`.
    if field not in df.columns:
        out = pd.DataFrame(
            {
                "sample_id": df[sample_id_col],
                "patient_id": df[patient_id_col] if patient_id_col else None,
                "source_native_id": df[native_id_col],
                "stratum_id": stratum["id"],
                "is_member": None,
                "derivation_source": stratum["derivation_source"],
                "derivation_value": "",
            }
        )
        return out

    def _predicate(row):
        v = row.get(field)
        if pd.isna(v):
            return None  # tri-value: evaluated but source-value missing → insufficient
        if op == "eq":
            return v == values[0]
        return v in values

    df["_is_member"] = df.apply(_predicate, axis=1)

    out = pd.DataFrame(
        {
            "sample_id": df[sample_id_col],
            "patient_id": df[patient_id_col] if patient_id_col else None,
            "source_native_id": df[native_id_col],
            "stratum_id": stratum["id"],
            "is_member": df["_is_member"],
            "derivation_source": stratum["derivation_source"],
            "derivation_value": df[field].astype(str).where(df["_is_member"] == True, ""),
        }
    )
    return out


# ---------- Output emission ------------------------------------------------
# The schema-valid subgroup_assignment_product manifest is emitted via the
# shared subgroup_common.manifest.emit_assignment_manifest (single source of
# truth across all three assigners).


# ---------- CLI ------------------------------------------------------------


@click.command()
@click.option(
    "--subgroup-catalog",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to the subgroup_catalog YAML.",
)
@click.option(
    "--data-source",
    required=True,
    type=click.Choice(["tcga", "depmap", "genie_bpc"]),
    help="Which data source to assign against.",
)
@click.option("--release-pin", required=True, help="Catalog release_pin identifier (e.g., 2026-Q2).")
# Portable sibling default; `or` so an empty env value falls back too (Path("") is the CWD).
@click.option(
    "--catalog-repo",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path(
        os.environ.get("DATA_CATALOG_ROOT")
        or Path(__file__).resolve().parents[2].parent / "rnd-computational-biology-oncology-data-catalog"
    ),
    help="Path to the data-catalog repo for input-manifest resolution.",
)
@click.option(
    "--out",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Output directory; assignments.parquet + manifest.yaml land here.",
)
@click.option("--dry-run", is_flag=True, help="Parse the catalog, print the plan, do not produce assignments.")
def main(
    subgroup_catalog: Path, data_source: str, release_pin: str, catalog_repo: Path, out: Path, dry_run: bool
) -> int:
    """Generate per-sample subgroup assignments from directly-tagged source fields."""
    with subgroup_catalog.open() as f:
        catalog = yaml.safe_load(f)

    indication = catalog.get("indication")
    catalog_id = catalog.get("id")
    atomic = catalog.get("atomic_strata", [])

    def _stratum_method(s: dict) -> str | None:
        return s.get("data_source", {}).get("method")

    applicable = []
    for s in atomic:
        if s.get("derivation_source") not in SUPPORTED_DERIVATION_SOURCES:
            continue
        applicable_sources = s.get("applicable_data_sources", [])
        if data_source not in applicable_sources:
            continue
        applicable.append(s)

    # Partition by data_source.method into evaluation paths:
    #   fusion       — per-(sample, gene) consensus product (set-membership)
    #   sample_label — per-sample derived label product (scalar rule, e.g. TMB)
    #   cn_amp       — per-(patient, gene) GISTIC amp product (CCND1 etc.)
    #   scalar       — the per-data-source marker-paper/depmap frame (existing path)
    _routed = (_FUSION_METHOD, _SAMPLE_LABEL_METHOD, _CN_AMP_METHOD)
    fusion_strata = [s for s in applicable if _stratum_method(s) == _FUSION_METHOD]
    label_strata = [s for s in applicable if _stratum_method(s) == _SAMPLE_LABEL_METHOD]
    cn_amp_strata = [s for s in applicable if _stratum_method(s) == _CN_AMP_METHOD]
    scalar_strata = [s for s in applicable if _stratum_method(s) not in _routed]

    click.echo(f"=== subgroup_assigner_directly_tagged v{METHOD_VERSION} ===")
    click.echo(f"  catalog:       {catalog_id} (indication={indication})")
    click.echo(f"  data_source:   {data_source}")
    click.echo(f"  release_pin:   {release_pin}")
    click.echo(f"  out:           {out}")
    click.echo(f"  applicable strata ({len(applicable)} of {len(atomic)}):")
    for s in applicable:
        click.echo(f"    - {s['id']:<20} rule={s['rule']!r}")

    skipped = [s["id"] for s in atomic if s.get("derivation_source") not in SUPPORTED_DERIVATION_SOURCES]
    if skipped:
        click.echo(f"  skipped strata (non-tagged derivation): {skipped}")
        click.echo("  → dispatch these to subgroup_assigner_maf_filter or subgroup_assigner_classifier")

    if not applicable:
        click.echo(f"WARNING: no applicable directly-tagged strata for data_source={data_source}", err=True)
        return 0

    if dry_run:
        click.echo("(--dry-run: skipping actual assignment generation)")
        return 0

    per_stratum_dfs = []

    # ============ Scalar strata: per-data-source frame (existing path) ========
    # Only load the marker-paper / depmap / genie frame when a scalar stratum
    # needs it — a fusion-only catalog must not require the marker-paper cache.
    if scalar_strata:
        if data_source == "tcga":
            source_df = _load_tcga_marker_paper_labels(catalog_repo, indication)
            sample_id_col = "sample_id"  # produced by loader normalization
            patient_id_col = "patient_id"
            native_id_col = "source_native_id"
        elif data_source == "genie_bpc":
            source_df = _load_genie_bpc_lot(catalog_repo, indication)
            sample_id_col = "sample_id"
            patient_id_col = "patient_id"
            native_id_col = "source_native_id"
        else:  # depmap
            source_df = _load_depmap_inferred_subtypes(catalog_repo, indication)
            sample_id_col = "ModelID"
            patient_id_col = None  # cell lines have no patient concept
            native_id_col = "ModelID"

        click.echo(f"  loaded {len(source_df):,} source rows")

        for stratum in scalar_strata:
            try:
                rows = _evaluate_stratum(stratum, source_df, sample_id_col, patient_id_col, native_id_col)
            except ValueError as e:
                click.echo(f"  SKIP {stratum['id']}: {e}", err=True)
                continue
            per_stratum_dfs.append(rows)
            n_hit = int((rows["is_member"] == True).sum())
            n_null = int(rows["is_member"].isna().sum())
            click.echo(f"    {stratum['id']:<20} is_member=true: {n_hit:>5}, null (data-missing): {n_null:>5}")

    # ============ Fusion strata: derived consensus product (new path) =========
    # Fusion consensus is TCGA-only; for depmap/genie the strata self-degrade to
    # null (no fusion product for that source) — correct tri-value behavior.
    if fusion_strata:
        if data_source != "tcga":
            click.echo(
                f"  fusion strata present but data_source={data_source} has no "
                f"fusion-consensus product → emitting null for "
                f"{[s['id'] for s in fusion_strata]}"
            )
        else:
            tissue_filter = INDICATION_TO_TCGA_TISSUES.get((indication or "").upper())
            # Group fusion strata by their manifest_id so each distinct consensus
            # product loads once.
            by_manifest: dict[str, list[dict]] = {}
            for s in fusion_strata:
                mid = s.get("data_source", {}).get("manifest_id")
                if not mid:
                    click.echo(f"  SKIP {s['id']}: fusion stratum has no data_source.manifest_id", err=True)
                    continue
                by_manifest.setdefault(mid, []).append(s)

            for manifest_id, strata in by_manifest.items():
                fusion_df = _load_fusion_consensus(catalog_repo, manifest_id)
                coverage_df = _load_fusion_coverage(catalog_repo, manifest_id)
                cov_note = (
                    "with coverage (true false/null split)"
                    if coverage_df is not None
                    else "NO coverage (non-members → null)"
                )
                click.echo(
                    f"  loaded fusion consensus {manifest_id}: {len(fusion_df):,} (sample,gene) rows, {cov_note}"
                )
                for stratum in strata:
                    try:
                        rows = _evaluate_fusion_stratum(stratum, fusion_df, coverage_df, tissue_filter)
                    except ValueError as e:
                        click.echo(f"  SKIP {stratum['id']}: {e}", err=True)
                        continue
                    per_stratum_dfs.append(rows)
                    n_hit = int((rows["is_member"] == True).sum())
                    n_false = int((rows["is_member"] == False).sum())
                    n_null = int(rows["is_member"].isna().sum())
                    click.echo(
                        f"    {stratum['id']:<20} is_member=true: {n_hit:>5}, false: {n_false:>5}, null: {n_null:>5}"
                    )

    # ============ Sample-label strata: per-sample derived product (TMB etc.) ==
    # Also TCGA-keyed; depmap/genie self-degrade (no product for that source).
    if label_strata:
        if data_source != "tcga":
            click.echo(
                f"  sample-label strata present but data_source={data_source} has "
                f"no per-sample label product → skipping {[s['id'] for s in label_strata]}"
            )
        else:
            # Restrict the pan-TCGA label product to the indication's patients via
            # the marker-paper cohort (patient_key = participant barcode).
            tissue_keys = None
            mp = cache_root() / "framework-tcga-marker-paper" / (indication or "").lower() / "subtypes.csv"
            if mp.exists():
                mp_df = pd.read_csv(mp)
                if "patient" in mp_df.columns:
                    tissue_keys = set(mp_df["patient"])
            by_manifest_lbl: dict[str, list[dict]] = {}
            for s in label_strata:
                mid = s.get("data_source", {}).get("manifest_id")
                if not mid:
                    click.echo(f"  SKIP {s['id']}: sample-label stratum has no data_source.manifest_id", err=True)
                    continue
                by_manifest_lbl.setdefault(mid, []).append(s)
            for manifest_id, strata in by_manifest_lbl.items():
                label_df = _load_sample_label_product(catalog_repo, manifest_id)
                click.echo(
                    f"  loaded sample-label product {manifest_id}: {len(label_df):,} samples"
                    + (f", filtered to {len(tissue_keys)} {indication} patients" if tissue_keys else "")
                )
                for stratum in strata:
                    try:
                        rows = _evaluate_sample_label_stratum(stratum, label_df, tissue_keys)
                    except ValueError as e:
                        click.echo(f"  SKIP {stratum['id']}: {e}", err=True)
                        continue
                    per_stratum_dfs.append(rows)
                    n_hit = int((rows["is_member"] == True).sum())
                    n_false = int((rows["is_member"] == False).sum())
                    n_null = int(rows["is_member"].isna().sum())
                    click.echo(
                        f"    {stratum['id']:<20} is_member=true: {n_hit:>5}, false: {n_false:>5}, null: {n_null:>5}"
                    )

    # ============ CN-amp strata: per-(patient, gene) GISTIC product ==========
    # TCGA-only (GISTIC is a TCGA product); depmap/genie self-degrade.
    if cn_amp_strata:
        if data_source != "tcga":
            click.echo(
                f"  CN-amp strata present but data_source={data_source} has no "
                f"GISTIC product → skipping {[s['id'] for s in cn_amp_strata]}"
            )
        else:
            cn_df = _load_cn_gistic(indication)
            if cn_df is None:
                click.echo(
                    f"  CN-amp product not cached for {indication} "
                    f"(run scripts/prefetch_cn_gistic.py) → strata emit null: "
                    f"{[s['id'] for s in cn_amp_strata]}"
                )
            else:
                click.echo(f"  loaded CN GISTIC product: {len(cn_df):,} (patient, gene) rows")
            for stratum in cn_amp_strata:
                try:
                    rows = _evaluate_cn_amp_stratum(stratum, cn_df)
                except ValueError as e:
                    click.echo(f"  SKIP {stratum['id']}: {e}", err=True)
                    continue
                if rows.empty:
                    click.echo(f"    {stratum['id']:<20} (no rows — CN product absent, null)")
                    continue
                per_stratum_dfs.append(rows)
                n_hit = int((rows["is_member"] == True).sum())
                n_false = int((rows["is_member"] == False).sum())
                click.echo(f"    {stratum['id']:<20} is_member=true: {n_hit:>5}, false: {n_false:>5}")

    if not per_stratum_dfs:
        click.echo("ERROR: no strata produced rows", err=True)
        return 1

    assignments = pd.concat(per_stratum_dfs, ignore_index=True)
    assignments["evaluated_at_release"] = release_pin

    # ============ Emit outputs ============
    out.mkdir(parents=True, exist_ok=True)
    parquet_path = out / "assignments.parquet"
    assignments.to_parquet(parquet_path, index=False)
    click.echo(f"  wrote {parquet_path} ({len(assignments):,} rows)")

    emit_assignment_manifest(
        out_dir=out,
        catalog=catalog,
        catalog_path=subgroup_catalog,
        data_source=data_source,
        release_pin=release_pin,
        assignments=assignments,
        assigner_method="subgroup_assigner_directly_tagged",
    )
    click.echo(f"  wrote {out / 'manifest.yaml'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
