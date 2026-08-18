"""read_functional_gene_state — assemble per-(sample, gene) two-hit evidence, classify, summarize.

Two arms sharing ONE classifier (classify.py):
  PATIENT (TCGA): MC3 mutations ⋈ PanCanAtlas ABSOLUTE segments (point-in-interval LOH/homdel at the
                  mutation locus) + GISTIC per-gene discrete CN (homdel for the no-mutation case),
                  scoped to the indication via merged_sample_quality_annotations (barcode→cancer type).
  MODEL (DepMap 26q1): OmicsSomaticMutationsMatrixDamaging/Hotspot (model × gene boolean) +
                  OmicsCNGeneWGS relative per-gene CN (homdel / single-copy-loss thresholds).

READ-PATH DISCIPLINE: the raw inputs are large (ABSOLUTE 253 MB, MC3 MAF + DepMap matrices hundreds
of MB). We NEVER stream a full matrix on the render path. Each arm reads BOUNDED slices — one gene's
mutation rows, one gene's CN row, the indication's sample set — so a target-profile call touches only
kilobytes. A precomputed derived product (an accelerator) is preferred when present; absent it,
the bounded live read is cheap enough to ship.

data_unavailable-safe: any arm that cannot read returns a structured absence, never raises.
"""
from __future__ import annotations

import io
from functools import lru_cache
from typing import Optional

from .classify import SampleEvidence, classify_functional_state, summarize_states
from methods.catalog_query.read import bucket_key_for, bucket_prefix_for, s3_uri_for

# bucket + source-dir prefixes/keys resolved from the data-catalog manifests (single source of
# truth); rstrip('/') keeps the existing f"{PREFIX}/file" idioms byte-identical.
S3_BUCKET, PANCAN_PREFIX = bucket_prefix_for("gdc-pancanatlas-cnv-2018")
PANCAN_PREFIX = PANCAN_PREFIX.rstrip("/")
MC3_KEY = f"{bucket_prefix_for('tcga-mc3-public-v0-2-8')[1]}mc3.v0.2.8.PUBLIC.maf.gz"
ABS_SEGTABS_KEY = f"{PANCAN_PREFIX}/TCGA_mastercalls.abs_segtabs.fixed.txt"
GISTIC_KEY = f"{PANCAN_PREFIX}/all_thresholded.by_genes_whitelisted.tsv"
SAMPLE_ANNOT_KEY = f"{PANCAN_PREFIX}/merged_sample_quality_annotations.tsv"
DEPMAP_PREFIX = bucket_prefix_for("depmap-consortium-26q1")[1].rstrip("/")

# CCLE 2019 RRBS methylation (model side, epigenetic arm).
# Rows = TSS-1kb windows; locus_id = GENESYMBOL_CHR_START_END.
# Columns 0-2 are meta (locus_id, CpG_sites_hg19, avg_coverage); rest are CELLLINENAME_TISSUE.
# Values are fractional methylation beta ∈ [0,1]; NaN = not measured in that cell line.
CCLE_RRBS_KEY = f"{bucket_prefix_for('depmap-consortium-ccle-2019')[1]}CCLE_RRBS_TSS1kb_20181022.txt.gz"
DEPMAP_MODEL_KEY = f"{DEPMAP_PREFIX}/Model.csv"
# Standard PanCanAtlas threshold: beta > 0.3 = promoter hypermethylated (silenced).
_RRBS_METH_THRESHOLD = 0.30

# SeSAMe HM450 derived product (patient-side methylation).
# tcga-sesame-promoter-methylation-v1: 2,730 GDC per-sample SeSAMe TSVs → per-(gene,patient)
# island-anchored promoter methylation call. 31.8M rows, 13,844 genes, 2,422 patients, 373 MB,
# sorted by gene_symbol for pyarrow row-group predicate pushdown (reads ~14 kB per gene).
_, HM450_PROMOTER_KEY = bucket_key_for("tcga-sesame-promoter-methylation-v1")

# framework indication → TCGA project code(s) used in merged_sample_quality_annotations `cancer type`
# (mirrors gdc_somatic_hotspot's INDICATION_TO_PROJECTS, minus the "TCGA-" prefix which this table omits).
INDICATION_TO_TCGA = {
    "COADREAD": ("COAD", "READ"), "COAD": ("COAD",), "READ": ("READ",),
    "LUAD": ("LUAD",), "LUSC": ("LUSC",), "NSCLC": ("LUAD", "LUSC"),
    "BRCA": ("BRCA",), "PAAD": ("PAAD",), "PDAC": ("PAAD",),
    "SKCM": ("SKCM",), "STAD": ("STAD",), "GC": ("STAD",), "PRAD": ("PRAD",), "OV": ("OV",),
    "KIRC": ("KIRC",), "GBM": ("GBM",), "HNSC": ("HNSC",), "HNSCC": ("HNSC",),
    "BLCA": ("BLCA",), "LIHC": ("LIHC",), "ESCA": ("ESCA",), "UCEC": ("UCEC",),
}

# MC3 Variant_Classification values that count as a somatic hit for the gene (non-synonymous).
_NONSYN = {
    "Missense_Mutation", "Nonsense_Mutation", "Frame_Shift_Del", "Frame_Shift_Ins",
    "In_Frame_Del", "In_Frame_Ins", "Splice_Site", "Nonstop_Mutation",
    "Translation_Start_Site",
}
# ...of which these are clear loss-of-function classes (used to break the copy-neutral tie).
_LOF_CLASSES = {
    "Nonsense_Mutation", "Frame_Shift_Del", "Frame_Shift_Ins", "Splice_Site",
    "Nonstop_Mutation", "Translation_Start_Site",
}

# GISTIC discrete thresholded value → cn_class.
_GISTIC_TO_CLASS = {-2: "homdel", -1: "loss", 0: "neutral", 1: "gain", 2: "gain"}

# DepMap relative per-gene CN thresholds (OmicsCNGeneWGS is a ratio, not integer). Conservative:
# near-zero → homozygous deletion; clearly-below-one → single-copy loss; else neutral/gain.
_DEPMAP_HOMDEL_MAX = 0.20     # relative CN <= 0.20 → both copies effectively lost
_DEPMAP_LOSS_MAX = 0.75       # 0.20 < CN <= 0.75 → single-copy loss (hemizygous)


def _boto3():
    import boto3
    return boto3.Session().client("s3")


def _s3_read_bytes(key: str) -> bytes:
    return _boto3().get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()


# ─────────────────────────────────────────────────────────────────────────────
# Sample → indication map (patient arm)
# ─────────────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _load_sample_cancer_types() -> dict:
    """{patient_barcode: cancer_type} from merged_sample_quality_annotations. Empty on failure."""
    import pandas as pd
    try:
        raw = _s3_read_bytes(SAMPLE_ANNOT_KEY)
        df = pd.read_csv(io.BytesIO(raw), sep="\t", usecols=["patient_barcode", "cancer type"],
                         dtype=str)
        df = df.dropna(subset=["patient_barcode", "cancer type"])
        # one cancer type per patient (they're consistent within patient); last wins is fine.
        return dict(zip(df["patient_barcode"], df["cancer type"]))
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent
        if not is_definitively_absent(e):
            raise
        return {}


def _patient_barcode(tumor_sample_barcode: str) -> str:
    """TCGA-XX-XXXX-01A-... → TCGA-XX-XXXX (first 3 hyphen fields = patient)."""
    parts = tumor_sample_barcode.split("-")
    return "-".join(parts[:3]) if len(parts) >= 3 else tumor_sample_barcode


# ─────────────────────────────────────────────────────────────────────────────
# Patient arm
# ─────────────────────────────────────────────────────────────────────────────
def _read_mc3_gene(target: str):
    """MC3 rows for ONE gene (bounded): [Tumor_Sample_Barcode, Variant_Classification]. DataFrame."""
    import pandas as pd
    try:
        raw = _s3_read_bytes(MC3_KEY)
        # gzip MAF; read only the columns we need, then filter to the gene + non-synonymous.
        cols = ["Hugo_Symbol", "Variant_Classification", "Tumor_Sample_Barcode",
                "Chromosome", "Start_Position"]
        df = pd.read_csv(io.BytesIO(raw), sep="\t", compression="gzip", usecols=cols,
                         dtype=str, low_memory=False, comment=None)
        g = df[(df["Hugo_Symbol"] == target) &
               (df["Variant_Classification"].isin(_NONSYN))].copy()
        g["Start_Position"] = pd.to_numeric(g["Start_Position"], errors="coerce")
        return g
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent
        if not is_definitively_absent(e):
            raise
        return None


def _read_absolute_segments():
    """ABSOLUTE segtabs (all samples): [Sample, Chromosome, Start, End, LOH, Homozygous_deletion].
    Cached (one 253 MB read per process); the per-mutation lookup is an in-memory filter."""
    import pandas as pd
    try:
        raw = _s3_read_bytes(ABS_SEGTABS_KEY)
        df = pd.read_csv(io.BytesIO(raw), sep="\t",
                         usecols=["Sample", "Chromosome", "Start", "End", "LOH",
                                  "Homozygous_deletion"])
        for c in ("Chromosome", "Start", "End", "LOH", "Homozygous_deletion"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent
        if not is_definitively_absent(e):
            raise
        return None


@lru_cache(maxsize=1)
def _absolute_segments_cached():
    return _read_absolute_segments()


def _read_gistic_gene(target: str) -> dict:
    """GISTIC per-gene discrete CN for ONE gene: {aliquot_barcode: int_value}. Empty on failure."""
    import pandas as pd
    try:
        raw = _s3_read_bytes(GISTIC_KEY)
        df = pd.read_csv(io.BytesIO(raw), sep="\t", low_memory=False)
        row = df[df["Gene Symbol"] == target]
        if row.empty:
            return {}
        meta = {"Gene Symbol", "Locus ID", "Cytoband"}
        vals = row.iloc[0].drop(labels=[c for c in meta if c in row.columns])
        return {str(k): int(v) for k, v in vals.items()
                if str(v) not in ("nan", "") and str(v).lstrip("-").isdigit()}
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent
        if not is_definitively_absent(e):
            raise
        return {}


def _loh_homdel_at_locus(segs, sample: str, chrom: float, pos: float):
    """Point-in-interval lookup: for a mutation at (chrom, pos) in `sample`, return the covering
    ABSOLUTE segment's (loh_bool, homdel_bool). (None, None) if no covering segment."""
    import pandas as pd
    if segs is None or chrom is None or pos is None:
        return (None, None)
    m = segs[(segs["Sample"] == sample) & (segs["Chromosome"] == chrom) &
             (segs["Start"] <= pos) & (segs["End"] >= pos)]
    if m.empty:
        return (None, None)
    r = m.iloc[0]
    loh = None if pd.isna(r["LOH"]) else bool(r["LOH"] >= 0.5)
    homdel = None if pd.isna(r["Homozygous_deletion"]) else bool(r["Homozygous_deletion"] >= 0.5)
    return (loh, homdel)


# ── Accelerator: the precomputed gene-SORTED two-hit evidence product ──────────────────────────────
# Replaces the ~1.6 GB per-query full-object read (MC3 + ABSOLUTE + GISTIC) with a per-gene pushdown
# scan. The product stores only ALTERED (gene, patient) rows (has_mutation OR cn_class∈{homdel,loss});
# an absent row is provably wt (classify rule 6), reconstructed from the indication's patient set. The
# classifier + roll-up below are UNCHANGED, so the summary is byte-identical to the live path (verified:
# KRAS/TP53/APC/PTEN in COADREAD). Methylation stays a separate gene-pushdown read, applied identically.
TWO_HIT_PRODUCT_S3_URI = s3_uri_for("pancan-genomic-two-hit-per-gene-v1")


@lru_cache(maxsize=64)
def _read_two_hit_evidence(target: str):
    """Pushdown-read ONE gene's altered-patient evidence rows from the precomputed product (DGE-shape
    true remote pruning: pyarrow.fs.S3FileSystem reads only matching row-groups over the wire).
    Returns a tuple of row dicts (possibly empty = gene present but no altered patients) or None if the
    product is unreachable → caller falls back to the live MC3+ABSOLUTE+GISTIC read."""
    try:
        import pyarrow.fs as fs
        import pyarrow.parquet as pq
        path = TWO_HIT_PRODUCT_S3_URI.replace("s3://", "", 1)
        s3 = fs.S3FileSystem()
        table = pq.read_table(path, filesystem=s3,
                              filters=[("gene_symbol", "=", target.upper())])
        return tuple(table.to_pylist())
    except Exception as e:  # noqa: BLE001
        # Product GENUINELY absent (not built / NoSuchKey → FileNotFoundError or 404) → None so the
        # caller falls back to the live MC3+ABSOLUTE+GISTIC read (the intended redundancy). A
        # transient-S3 / creds / broken-env error must NOT masquerade as "product absent" — re-raise
        # it (the live fallback would likely hit the same infra issue, and its own readers now enforce
        # the same discipline, so an honest _live_read_error is correct).
        from methods.target_id_sidecar import is_definitively_absent
        if not (isinstance(e, FileNotFoundError) or is_definitively_absent(e)):
            raise
        return None


def _reconstruct_patient_arm(target: str, indication: str, cancer_types, ind_patients: set,
                             rows) -> dict:
    """Reconstruct the patient-arm summary from the product's altered rows + the indication's patient
    set (absent row → wt), applying the SAME classifier + methylation upgrade + roll-up as the live
    path. Byte-identical to _read_patient_arm_live for the genetic-state fields."""
    by_patient = {}
    for r in rows:
        if r.get("patient_barcode") in ind_patients:
            by_patient[r["patient_barcode"]] = r
    methylation = _read_patient_methylation(target, indication)

    states: list[str] = []
    for patient in sorted(ind_patients):
        row = by_patient.get(patient)
        if row is None:
            ev = SampleEvidence(has_mutation=False, cn_class=None, loh_at_locus=None,
                                mutation_is_lof=None)
        else:
            ev = SampleEvidence(
                has_mutation=bool(row["has_mutation"]),
                cn_class=row.get("cn_class"),                 # None or homdel/loss/neutral/gain
                loh_at_locus=row.get("loh_at_locus"),         # None / True / False
                mutation_is_lof=row.get("mutation_is_lof"))   # None / True / False
        genetic_state = classify_functional_state(ev)

        is_methylated: Optional[bool] = methylation.get(patient)
        if is_methylated is True:
            if genetic_state == "wt":
                state = "epigenetic"
            elif genetic_state == "monoallelic":
                state = "biallelic+epigenetic"
            else:
                state = genetic_state
        else:
            state = genetic_state
        states.append(state)

    summ = summarize_states(states)
    n_ind = len(ind_patients)
    n_mutated = sum(1 for r in by_patient.values() if r.get("has_mutation"))
    summ.update({"_arm": "patient", "indication": indication,
                 "n_mutated": n_mutated,
                 "fraction_mutated": (n_mutated / n_ind) if n_ind else None,
                 "tcga_projects": list(cancer_types),
                 "loh_source": "pancanatlas_absolute_point_in_interval",
                 "cn_source": "gistic_thresholded_per_gene",
                 "methylation_source": "pancanatlas_hm450_promoter_v1" if methylation else None,
                 "_read_path": "two_hit_product_v1"})
    return summ


def _read_patient_arm(target: str, indication: str) -> dict:
    """Patient (TCGA) functional-gene-state distribution. Prefers the precomputed two-hit product
    (per-gene pushdown); falls back to the live full-object read when the product is unreachable."""
    cancer_types = INDICATION_TO_TCGA.get(indication.upper().strip())
    sample_ct = _load_sample_cancer_types()
    if not sample_ct or not cancer_types:
        return {"_arm": "patient", "state": "data_unavailable",
                "_note": "no sample→cancer-type map or unmapped indication"}
    ind_patients = {pb for pb, ct in sample_ct.items() if ct in cancer_types}
    if not ind_patients:
        return {"_arm": "patient", "state": "data_unavailable",
                "_note": f"no TCGA samples for indication {indication}"}

    rows = _read_two_hit_evidence(target)
    if rows is not None:
        return _reconstruct_patient_arm(target, indication, cancer_types, ind_patients, rows)
    # product unreachable → live read.
    return _read_patient_arm_live(target, indication, cancer_types, sample_ct, ind_patients)


def _read_patient_arm_live(target: str, indication: str, cancer_types, sample_ct,
                           ind_patients: set) -> dict:
    """The original live full-object read (fallback). Reads one gene's MC3 rows, the cached ABSOLUTE
    segments, and one gene's GISTIC row, then classifies + rolls up."""
    mc3 = _read_mc3_gene(target)
    if mc3 is None:
        return {"_arm": "patient", "state": "data_unavailable", "_note": "MC3 read failed"}
    segs = _absolute_segments_cached()
    gistic = _read_gistic_gene(target)
    # HM450 promoter methylation per patient (empty dict = parquet not yet available).
    methylation = _read_patient_methylation(target, indication)

    # mutation set for this gene, restricted to the indication's patients.
    mc3 = mc3.copy()
    mc3["patient"] = mc3["Tumor_Sample_Barcode"].map(_patient_barcode)
    mc3 = mc3[mc3["patient"].isin(ind_patients)]
    mutated_patients = set(mc3["patient"].unique())

    # GISTIC per-gene homdel/loss keyed by aliquot barcode → collapse to patient.
    gistic_by_patient: dict = {}
    for aliquot, val in gistic.items():
        gistic_by_patient.setdefault(_patient_barcode(aliquot), []).append(val)

    def _gistic_class(patient: str):
        vals = gistic_by_patient.get(patient)
        if not vals:
            return None
        v = min(vals)  # most-deleted call wins (−2 dominates −1)
        return _GISTIC_TO_CLASS.get(v)

    states: list[str] = []
    # iterate the indication's patients; each contributes ONE per-gene state.
    for patient in sorted(ind_patients):
        has_mut = patient in mutated_patients
        cn_class = _gistic_class(patient)
        loh = None
        mut_is_lof = None

        if has_mut:
            rows = mc3[mc3["patient"] == patient]
            mut_is_lof = bool(rows["Variant_Classification"].isin(_LOF_CLASSES).any())
            # point-in-interval LOH/homdel at each mutation locus; take the strongest signal.
            # match the ABSOLUTE `Sample` (tumor sample barcode, 4-field) — use the mutation's own.
            loh_any = None
            homdel_any = False
            for _, mr in rows.iterrows():
                samp = mr["Tumor_Sample_Barcode"]
                chrom = _chrom_to_num(mr["Chromosome"])
                l, h = _loh_homdel_at_locus(segs, _abs_sample_key(samp, segs), chrom,
                                            mr["Start_Position"])
                if h:
                    homdel_any = True
                if l is True:
                    loh_any = True
                elif l is False and loh_any is None:
                    loh_any = False
            if homdel_any:
                cn_class = "homdel"
            loh = loh_any

        ev = SampleEvidence(has_mutation=has_mut, cn_class=cn_class,
                            loh_at_locus=loh, mutation_is_lof=mut_is_lof)
        genetic_state = classify_functional_state(ev)

        # Methylation upgrade: same rules as model side.
        is_methylated: Optional[bool] = methylation.get(patient)  # None = not in HM450 parquet
        if is_methylated is True:
            if genetic_state == "wt":
                state = "epigenetic"
            elif genetic_state == "monoallelic":
                state = "biallelic+epigenetic"
            else:
                state = genetic_state  # biallelic-genetic / uncertain: genetic wins
        else:
            state = genetic_state

        states.append(state)

    summ = summarize_states(states)
    # mutation-presence fraction (ADDITIVE — independent of the allele-count state_counts). Needed by
    # the model-match assembler for the ACTIVATING-oncogene case: an activating hotspot's characterizing event is "mutation
    # present", which the allele-count vocabulary scatters across monoallelic + uncertain. This exposes
    # the raw mutation prevalence so a consumer can match on mutation presence for GoF targets.
    n_ind = len(ind_patients)
    n_mutated = len(mutated_patients & ind_patients)
    summ.update({"_arm": "patient", "indication": indication,
                 "n_mutated": n_mutated,
                 "fraction_mutated": (n_mutated / n_ind) if n_ind else None,
                 "tcga_projects": list(cancer_types),
                 "loh_source": "pancanatlas_absolute_point_in_interval",
                 "cn_source": "gistic_thresholded_per_gene",
                 "methylation_source": "pancanatlas_hm450_promoter_v1" if methylation else None,
                 "_read_path": "live_full_object"})
    return summ


def _chrom_to_num(chrom) -> Optional[float]:
    """MC3 Chromosome ('1'..'22','X','Y') → ABSOLUTE numeric chrom (1.0..22.0; X/Y unmapped→None)."""
    try:
        return float(int(str(chrom).replace("chr", "")))
    except (ValueError, TypeError):
        return None


def _abs_sample_key(mc3_barcode: str, segs) -> str:
    """Match an MC3 tumor-sample barcode to the ABSOLUTE `Sample` key. ABSOLUTE uses the 4-field
    sample barcode (TCGA-XX-XXXX-01); MC3 barcodes carry more fields. Truncate MC3 to 4 fields."""
    parts = mc3_barcode.split("-")
    return "-".join(parts[:4]) if len(parts) >= 4 else mc3_barcode


# ─────────────────────────────────────────────────────────────────────────────
# Model arm (DepMap 26q1)
# ─────────────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _load_ccle_colname_to_model_id() -> dict:
    """{RRBS_column_key_upper: ModelID} from DepMap Model.csv.

    RRBS columns are CCLE-style CELLLINE_TISSUE names (e.g. 'DMS53_LUNG',
    'NCIH2126_LUNG', '1321N1_CENTRAL_NERVOUS_SYSTEM'). The correct Model.csv bridge
    key is therefore CCLEName (the CELLLINE_TISSUE form, e.g. 'DMS53_LUNG') matched
    against the FULL column — mirroring the validated depmap_demeter_distribution bridge
    (cli.py:208). This map keys on BOTH forms so _read_model_methylation resolves either:
      - CCLEName.upper()            → ModelID  (matches the FULL RRBS column; primary)
      - StrippedCellLineName.upper() → ModelID (matches col.split('_')[0]; fallback)

    The PRIOR implementation keyed on CellLineName (the PUNCTUATED display name, e.g.
    'NCI-H2126', 'DMS 53') and was looked up against col.split('_')[0] (the alnum
    fragment, e.g. 'NCIH2126') — these NEVER matched for punctuated names, so most cell
    lines were silently unmapped and methylation-silenced TSGs were under-called
    biallelic/epigenetic. Returns empty dict on GENUINE absence (data_unavailable-safe).
    """
    import pandas as pd
    try:
        raw = _s3_read_bytes(DEPMAP_MODEL_KEY)
        hdr = pd.read_csv(io.BytesIO(raw), nrows=0)
        want = [c for c in ("ModelID", "CCLEName", "StrippedCellLineName") if c in hdr.columns]
        df = pd.read_csv(io.BytesIO(raw), usecols=want)
        out: dict = {}
        for row in df.itertuples(index=False):
            model_id = getattr(row, "ModelID", None)
            if not (pd.notna(model_id)):
                continue
            model_id = str(model_id)
            # PRIMARY: full CELLLINE_TISSUE name (matches the full RRBS column verbatim).
            ccle = getattr(row, "CCLEName", None)
            if pd.notna(ccle) and str(ccle).strip():
                out[str(ccle).upper()] = model_id
            # FALLBACK: stripped alnum name (matches col.split('_')[0]).
            stripped = getattr(row, "StrippedCellLineName", None)
            if pd.notna(stripped) and str(stripped).strip():
                out.setdefault(str(stripped).upper(), model_id)
        return out
    except Exception as e:  # noqa: BLE001
        # Genuine 404/NoSuchKey → honest empty (methylation arm degrades to unavailable). A
        # transient/creds/broken-env error must NOT be masked as an empty bridge (would silently
        # unmap every cell line) — re-raise (lru_cache never memoizes the raise, so it is retried).
        from methods.target_id_sidecar import is_definitively_absent
        if not is_definitively_absent(e):
            raise
        return {}


def _read_model_methylation(target: str) -> dict:
    """{ModelID: is_methylated (bool)} for `target` from CCLE RRBS TSS-1kb file.

    Algorithm:
      1. Stream the gzipped TSS-1kb matrix, filter rows where locus_id starts
         with 'TARGET_' (gene prefix match — one gene may have multiple windows).
      2. For each matching row, read all cell-line columns as floats.
      3. Per cell line, take min beta across all matching windows (most-methylated
         wins — conservative: if ANY promoter window is hypermethylated, the gene
         is silenced). NaN-only → no data for that cell line.
      4. Threshold: beta > _RRBS_METH_THRESHOLD (0.30) → methylated = True.
      5. Map CELLLINENAME_TISSUE column names → ModelID via Model.csv CellLineName.

    Returns {ModelID: bool}. Empty dict when target has no RRBS loci or S3 fails.
    """
    import gzip
    import pandas as pd

    gene_prefix = target.upper() + "_"
    col_to_model = _load_ccle_colname_to_model_id()
    if not col_to_model:
        return {}

    try:
        raw_bytes = _s3_read_bytes(CCLE_RRBS_KEY)
        with gzip.GzipFile(fileobj=io.BytesIO(raw_bytes)) as gz:
            df = pd.read_csv(gz, sep="\t", dtype=str)
    except Exception as e:  # noqa: BLE001
        # Genuine 404/NoSuchKey → honest empty (no RRBS methylation for this target). A transient/
        # creds/broken-env error must NOT be masked as "no methylation" — re-raise it.
        from methods.target_id_sidecar import is_definitively_absent
        if not is_definitively_absent(e):
            raise
        return {}

    gene_rows = df[df["locus_id"].str.startswith(gene_prefix, na=False)]
    if gene_rows.empty:
        return {}

    meta_cols = {"locus_id", "CpG_sites_hg19", "avg_coverage"}
    sample_cols = [c for c in gene_rows.columns if c not in meta_cols]
    beta = gene_rows[sample_cols].apply(pd.to_numeric, errors="coerce")

    # min across windows per cell line (NaN if all windows are NaN for that line)
    min_beta = beta.min(axis=0)

    out: dict = {}
    for col, val in min_beta.items():
        if pd.isna(val):
            continue
        # col = 'CELLLINE_TISSUE' (CCLE-style). Resolve against CCLEName via the FULL column first
        # (the correct bridge — mirrors depmap_demeter_distribution), then fall back to the stripped
        # alnum name (col.split('_')[0]) against StrippedCellLineName. The prior code used ONLY the
        # split-fragment against the punctuated display name, which never matched punctuated lines.
        model_id = (col_to_model.get(col.upper())
                    or col_to_model.get(col.split("_")[0].upper()))
        if model_id:
            out[model_id] = bool(val > _RRBS_METH_THRESHOLD)
    return out


@lru_cache(maxsize=32)
def _read_patient_methylation(target: str, indication: str) -> dict:
    """{patient_barcode: is_methylated (bool)} for `target` from the HM450 derived parquet.

    Returns {} if the derived parquet is not yet available (gated on pull + aggregation).
    Graceful degradation: when the parquet is absent, _read_patient_arm falls back to
    genetic states only, with no silent failure or exception propagation.

    The `indication` parameter is NOT used for filtering here — the derived parquet spans all
    TCGA cancer types. Filtering to indication-specific patients is done at join time in
    _read_patient_arm via `ind_patients`. The parameter is included in the cache key for
    clarity and to reserve future per-indication scoping without cache invalidation.
    """
    import pandas as pd
    try:
        raw = _s3_read_bytes(HM450_PROMOTER_KEY)
        # filters= pushes the predicate into pyarrow row-group statistics, reading only the
        # matching row group (~14 kB) rather than the full 373 MB parquet.
        # Requires the parquet to be sorted by gene_symbol (aggregate_sesame_promoter.py does this).
        df = pd.read_parquet(io.BytesIO(raw),
                             filters=[("gene_symbol", "==", target.upper())])
        sub = df[df["is_promoter_methylated"].notna()]
        return {str(row.patient_barcode): bool(row.is_promoter_methylated)
                for row in sub.itertuples(index=False)}
    except Exception as e:  # noqa: BLE001
        # HM450 product genuinely absent (not yet landed → NoSuchKey/404) → honest {} so the
        # patient arm degrades to genetic-only. A transient/creds/broken-env error must NOT be masked
        # as "no methylation" (would silently drop epigenetic upgrades) — re-raise it.
        from methods.target_id_sidecar import is_definitively_absent
        if not is_definitively_absent(e):
            raise
        return {}


# DepMap matrix CSV → parquet product name (depmap-26q1-parquet-v1, column-projection reads).
_DEPMAP_MATRIX_PARQUET = {
    "OmicsSomaticMutationsMatrixDamaging.csv": "OmicsSomaticMutationsMatrixDamaging.parquet",
    "OmicsSomaticMutationsMatrixHotspot.csv": "OmicsSomaticMutationsMatrixHotspot.parquet",
    "OmicsCNGeneWGS.csv": "OmicsCNGeneWGS.parquet",
}


def _read_depmap_matrix_column(matrix_filename: str, target: str):
    """Prefer the gene-sorted parquet product (column projection, ~1-2 MB) over the raw ~500 MB
    CSV. Returns a {ModelID: value} DataFrame-derived dict source: a pandas DataFrame with
    ['ModelID', <gene_col>], or None if the product is unreachable → caller falls back to the raw
    CSV read. Byte-identical projection: the same two columns the CSV path read (['ModelID',
    gene_col], no default-entry filter)."""
    parquet_name = _DEPMAP_MATRIX_PARQUET.get(matrix_filename)
    if parquet_name is None:
        return None
    try:
        from methods.depmap_common import parquet as _dp
        df = _dp.get_matrix_column_by_model_id(parquet_name, target)
        return df  # None if the gene is absent from the matrix (a real "no data" answer)
    except Exception as e:  # noqa: BLE001
        # Parquet product GENUINELY absent (unregistered / NoSuchKey → FileNotFoundError or 404) →
        # None so the caller falls back to the raw-CSV read (the intended redundancy). A transient/
        # creds/broken-env error must NOT masquerade as "product unreachable" — re-raise it (the CSV
        # fallback reads the same backend and its own reader now enforces the same discipline).
        from methods.target_id_sidecar import is_definitively_absent
        if not (isinstance(e, FileNotFoundError) or is_definitively_absent(e)):
            raise
        return None  # product genuinely absent → live CSV fallback


def _read_depmap_mut_matrix(matrix_filename: str, target: str) -> dict:
    """{ModelID: bool} for `target` from a DepMap model×gene boolean matrix. Empty on failure.
    Prefers the parquet product (column projection); falls back to the raw CSV full-object read.
    Columns are 'SYMBOL (entrez)'; the raw CSV's first 5 cols are ID metadata."""
    import pandas as pd
    # fast path: parquet column projection
    pq_df = _read_depmap_matrix_column(matrix_filename, target)
    if pq_df is not None:
        gene_col = next((c for c in pq_df.columns if c != "ModelID"), None)
        if gene_col is None:
            return {}
        return {str(m): bool(v) for m, v in zip(pq_df["ModelID"], pq_df[gene_col]) if pd.notna(v)}
    # fallback: raw CSV full-object read (product unreachable)
    key = f"{DEPMAP_PREFIX}/{matrix_filename}"
    try:
        raw = _s3_read_bytes(key)
        hdr = pd.read_csv(io.BytesIO(raw), nrows=0)
        gene_col = next((c for c in hdr.columns
                         if c == target or c.split(" (")[0] == target), None)
        if gene_col is None:
            return {}
        df = pd.read_csv(io.BytesIO(raw), usecols=["ModelID", gene_col])
        return {str(m): bool(v) for m, v in zip(df["ModelID"], df[gene_col]) if pd.notna(v)}
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent
        if not is_definitively_absent(e):
            raise
        return {}


def _read_depmap_cn(target: str) -> dict:
    """{ModelID: relative_cn} for `target` from OmicsCNGeneWGS. Empty on failure.
    Prefers the parquet product (column projection); falls back to the raw CSV full-object read."""
    import pandas as pd
    pq_df = _read_depmap_matrix_column("OmicsCNGeneWGS.csv", target)
    if pq_df is not None:
        gene_col = next((c for c in pq_df.columns if c != "ModelID"), None)
        if gene_col is None:
            return {}
        return {str(m): float(v) for m, v in zip(pq_df["ModelID"], pq_df[gene_col]) if pd.notna(v)}
    key = f"{DEPMAP_PREFIX}/OmicsCNGeneWGS.csv"
    try:
        raw = _s3_read_bytes(key)
        hdr = pd.read_csv(io.BytesIO(raw), nrows=0)
        gene_col = next((c for c in hdr.columns
                         if c == target or c.split(" (")[0] == target), None)
        if gene_col is None:
            return {}
        df = pd.read_csv(io.BytesIO(raw), usecols=["ModelID", gene_col])
        return {str(m): float(v) for m, v in zip(df["ModelID"], df[gene_col]) if pd.notna(v)}
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent
        if not is_definitively_absent(e):
            raise
        return {}


def _depmap_cn_class(rel_cn: Optional[float]) -> Optional[str]:
    if rel_cn is None:
        return None
    if rel_cn <= _DEPMAP_HOMDEL_MAX:
        return "homdel"
    if rel_cn <= _DEPMAP_LOSS_MAX:
        return "loss"
    return "neutral"


def read_model_states_per_model(target: str) -> dict:
    """PUBLIC per-model accessor: the DepMap 26q1 functional gene state of `target` per cell line.

    Returns {ModelID: {state, cn_class, has_mutation, mutation_is_lof, is_methylated}} — the
    per-model rows the aggregate model arm rolls up. Empty dict when absent from all substrate.

    Methylation (CCLE RRBS TSS-1kb): when a cell line has no genetic hit (wt by genetic
    evidence alone) but is_methylated=True, state is upgraded to 'epigenetic'. When a cell line
    has a genetic hit AND is methylated, state is upgraded to 'biallelic+epigenetic'. Models not
    covered by RRBS receive is_methylated=None (data_unavailable for that modality).

    Model-side LOH is genome-wide only (loh_at_locus=None) → copy-neutral mutations resolve
    `uncertain` (documented model caveat). Downstream consumers (the model-match assembler) join against Chronos + lineage.
    """
    damaging = _read_depmap_mut_matrix("OmicsSomaticMutationsMatrixDamaging.csv", target)
    hotspot = _read_depmap_mut_matrix("OmicsSomaticMutationsMatrixHotspot.csv", target)
    cn = _read_depmap_cn(target)
    methylation = _read_model_methylation(target)  # {} if RRBS unavailable — safe
    if not damaging and not hotspot and not cn:
        return {}

    out: dict = {}
    for m in sorted(set(damaging) | set(hotspot) | set(cn)):
        has_mut = bool(damaging.get(m) or hotspot.get(m))
        mut_is_lof = bool(damaging.get(m)) if has_mut else None
        cn_class = _depmap_cn_class(cn.get(m))
        is_methylated: Optional[bool] = methylation.get(m)  # None if not in RRBS

        ev = SampleEvidence(has_mutation=has_mut, cn_class=cn_class,
                            loh_at_locus=None, mutation_is_lof=mut_is_lof)
        genetic_state = classify_functional_state(ev)

        # Methylation upgrade: epigenetic silencing as a second-hit modality.
        if is_methylated is True:
            if genetic_state in ("wt", "monoallelic"):
                state = "epigenetic" if genetic_state == "wt" else "biallelic+epigenetic"
            else:
                state = genetic_state  # already biallelic-genetic or uncertain; methylation redundant
        else:
            state = genetic_state

        out[m] = {"state": state, "cn_class": cn_class,
                  "has_mutation": has_mut, "mutation_is_lof": mut_is_lof,
                  "is_methylated": is_methylated}
    return out


def _read_model_arm(target: str) -> dict:
    """Model (DepMap 26q1) functional-gene-state DISTRIBUTION across all cell lines (pan-lineage) —
    a pure roll-up of read_model_states_per_model. Model-side LOH is genome-wide only (not per-gene)
    → copy-neutral mutations resolve `uncertain` rather than a false biallelic (documented caveat)."""
    per_model = read_model_states_per_model(target)
    if not per_model:
        return {"_arm": "model", "state": "data_unavailable",
                "_note": "target absent from DepMap mutation matrices + CN"}
    # sorted() preserves the former iteration order → byte-identical summary to the pre-refactor arm.
    states = [per_model[m]["state"] for m in sorted(per_model)]
    summ = summarize_states(states)
    summ.update({"_arm": "model", "cn_source": "depmap_omicscngenewgs_relative",
                 "loh_note": "genome_wide_only_not_per_gene"})
    return summ


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────
def read_functional_gene_state(target: str, indication: str) -> dict:
    """Harmonized two-hit / biallelic-inactivation profile for (target, indication).

    Returns {target, indication, patient: {...}, model: {...}, functional_state_class} where each
    arm is a state distribution (state_counts + fraction_biallelic) or a data_unavailable marker.
    `functional_state_class` is a compact target-level headline derived from the patient arm
    (falls back to model when patient is unavailable)."""
    sym = target.upper().strip()
    patient = _read_patient_arm(sym, indication)
    model = _read_model_arm(sym)

    # headline: prefer the patient distribution; describe the dominant / biallelic picture.
    headline = _headline_class(patient, model)
    return {
        "target": target,
        "indication": indication,
        "patient": patient,
        "model": model,
        "functional_state_class": headline,
        "vocabulary_phase": "genetic_epigenetic_full_phase2b",
    }


def _headline_class(patient: dict, model: dict) -> str:
    """Compact target-level class from an arm's distribution: describes whether biallelic
    inactivation is a RECURRENT pattern in the cohort."""
    arm = patient if patient.get("fraction_biallelic") is not None else model
    fb = arm.get("fraction_biallelic")
    fa = arm.get("fraction_any_alteration")
    if fb is None:
        return "data_unavailable"
    if fb >= 0.10:
        return "recurrent_biallelic_inactivation"
    if fb > 0:
        return "sporadic_biallelic_inactivation"
    if fa and fa >= 0.10:
        return "predominantly_monoallelic"
    return "rarely_altered"
