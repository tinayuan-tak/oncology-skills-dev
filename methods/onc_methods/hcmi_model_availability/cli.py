"""hcmi_model_availability.cli — materialize the per-indication HCMI model-availability product.

Scientific-gap #1 (2026-08-14), lighter-v1: the TRANSLATIONAL-BRIDGE axis the framework lacked —
"for indication Y, how many patient-derived (HCMI organoid / next-gen cancer) models exist to
preclinically validate a nominated target?" This v1 is model-AVAILABILITY-by-indication
(target-independent cohort context); the genotype-MATCHED v2 (does a model carry target X's alteration?)
joins the HCMI WXS MAFs on top of this crosswalk and is the follow-up.

SOURCE (pre-existing ingestion — ZERO new pulls): HCMI-CMDC DR45 (hcmi-cmdc-dr45-0), the 805 per-case
ClinicalData JSONs under s3://onc-compbio/data-catalog/sources/hcmi/cmdc-dr45-0/HCMI-CMDC/.

METHOD (aggregate_model_availability): walk the 805 case JSONs, read each
ClinicalData."GDC Clinical Data Entities"[0].{primary_site, disease_type} (GDC vocabulary) + the
SubjectData.submitter_id model id, apply a (primary_site, disease_type) -> framework-indication
crosswalk, and count distinct models per indication. model_availability_class thresholds:
deep_model_coverage (>=50) / moderate_model_coverage (15-49) / sparse_model_coverage (<15).

CROSSWALK (crosswalk_indication) — BROADENED 2026-08-24. The original v1 mapped only the 4 GI/lung core
indications (COADREAD / PAAD / NSCLC / GC — 376/805 models). It now additionally maps 8 unambiguous
single-histology categories from HCMI's 22 disease types, using the DGE pan-tissue framework indication
vocabulary: ESCA (esophageal adeno), BRCA (breast carcinoma), SKCM (cutaneous melanoma), OV (epithelial
ovarian), BLCA (urothelial), UCEC (uterine-corpus carcinoma), HNSC (head & neck squamous), THCA (thyroid
adeno). The conservative discipline is preserved — a rule fires ONLY when (primary_site, disease_type)
is unambiguous for one indication. Categories DELIBERATELY LEFT UNMAPPED: Brain/Gliomas (grade-
indeterminate GBM-vs-LGG), Liver 'Adenomas and Adenocarcinomas' (intrahepatic cholangiocarcinoma, not
hepatocellular/LIHC), Kidney 'Adenomas and Adenocarcinomas' (RCC subtype KIRC/KIRP/KICH unresolvable from
disease_type), biliary tract / gallbladder (no CHOL code), small intestine (no SBA code), uterus-NOS
(corpus-vs-cervix ambiguous), adrenal neuroepitheliomatous, and all sarcomas / lymphomas / leukemias.

VALIDATION (2026-08-24 re-run): 631 / 805 models map to 12 indications — COADREAD 209 (deep),
PAAD 115 (deep), ESCA 96 (deep), BRCA 69 (deep), SKCM 44 (moderate), NSCLC 27 (moderate), GC 25
(moderate), OV 16 (moderate), BLCA 11 (sparse), UCEC 10 (sparse), HNSC 8 (sparse), THCA 1 (sparse).
COADREAD remains deepest, consistent with HCMI's documented GI/colorectal-heavy composition.

ROLE: VERDICT-INERT translational facet on first wiring; drives NO resolver rung.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import gzip
import io
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

from onc_methods.roots import data_catalog_root

_BUCKET = "onc-compbio"
_HCMI_PREFIX = "data-catalog/sources/hcmi/cmdc-dr45-0/HCMI-CMDC/"

# Genotype-matched (R2.10 v2) constants ─────────────────────────────────────────────────────────────
# Canonical S3 home for the per-(gene, indication) genotype-matched-model product.
_GENOTYPE_DERIVED_PREFIX = "data-catalog/derived/hcmi-genotype-matched-model-per-gene-v1/"
_GENOTYPE_PARQUET_BASENAME = "hcmi_genotype_matched_model.parquet"
DATA_CATALOG_ROOT = data_catalog_root()
DEFAULT_RESOLVER_RELEASE = "resolver_v1.0.0"

# FUNCTIONAL coding Variant_Classification values kept for a COARSE alteration match (any one of these
# in a gene = the model "carries an alteration in X"). Deliberately excludes Silent, RNA, intronic,
# UTR, IGR, flanking — those are not a nomination-validating coding hit. HGVSp is CARRIED (not
# filtered on) so a hotspot-specific v2 refinement stays a later step.
_FUNCTIONAL_CODING_CLASSES = frozenset(
    {
        "Missense_Mutation",
        "Nonsense_Mutation",
        "Frame_Shift_Ins",
        "Frame_Shift_Del",
        "In_Frame_Ins",
        "In_Frame_Del",
        "Splice_Site",
        "Nonstop_Mutation",
        "Translation_Start_Site",
    }
)

# Genotype-matched-model coverage thresholds (distinct models carrying a functional alteration in the
# gene, within the indication). matched_deep (>=5) / matched_sparse (1-4) / none (0 — reader-side only,
# the product stores only altered (gene, indication) pairs).
_GENOTYPE_MATCHED_THRESHOLDS = {"deep": 5}  # >=5 deep; 1-4 sparse; 0 none


def _rollup_indication() -> str:
    return "ALL"


def genotype_matched_class(n: int) -> str:
    """n distinct models carrying a functional alteration -> matched_deep / matched_sparse / none."""
    if n >= _GENOTYPE_MATCHED_THRESHOLDS["deep"]:
        return "matched_deep"
    if n >= 1:
        return "matched_sparse"
    return "none"


def _model_id_from_barcode(barcode: "Optional[str]") -> "Optional[str]":
    """Derive the HCMI model submitter_id (== case JSON SubjectData.submitter_id) from a MAF
    Tumor_Sample_Barcode. The barcode is HCM-<TSS>-<Patient>-<Sample>-<portion...>; the model id is
    the first four hyphen-delimited fields (e.g. 'HCM-STAN-0846-C20-01D-04D-A937-36' -> 'HCM-STAN-0846-C20').
    Validated 2026-08-24: this prefix matches the source manifest's per-MAF case_id and the case-JSON
    SubjectData.submitter_id verbatim, so no cross-repo manifest read is needed to join MAF -> model."""
    if not barcode:
        return None
    parts = barcode.split("-")
    if len(parts) < 4:
        return None
    return "-".join(parts[:4])


# (primary_site, disease_type) -> framework indication crosswalk.
# Keyed on lowercased substring matches against the GDC clinical vocabulary; deliberately conservative —
# a rule fires ONLY when (primary_site, disease_type) is UNAMBIGUOUS for one framework indication, so a
# mis-histology / grade-indeterminate / subtype-unresolvable model is left UNMAPPED (return None) rather
# than mis-assigned. Framework indication codes are the DGE pan-tissue vocabulary (same codes as
# methods/dge_deseq2), EXCEPT the pre-existing 'GC' (gastric) tag kept verbatim for byte-stability.
#
# BROADENED 2026-08-24 (crosswalk-broaden): the original v1 mapped only the 4 GI/lung core indications
# (COADREAD / PAAD / NSCLC / GC — 376/805 models). It now additionally maps 8 well-defined single-histology
# categories from HCMI's 22 disease types (ESCA/BRCA/SKCM/OV/BLCA/UCEC/HNSC/THCA), lifting coverage while
# preserving the conservative discipline. See the per-rule comments + the module docstring for the
# categories DELIBERATELY LEFT UNMAPPED (Brain/Gliomas grade-indeterminate; Liver adeno = intrahepatic
# cholangio not HCC; Kidney adeno = RCC-subtype-unresolvable; biliary/gallbladder = no CHOL code; small
# intestine; uterus-NOS; sarcomas/lymphomas/leukemias; colon non-adenocarcinoma).
_MODEL_AVAILABILITY_CLASS_THRESHOLDS = {"deep": 50, "moderate": 15}  # else sparse


def crosswalk_indication(primary_site: "Optional[str]", disease_type: "Optional[str]") -> "Optional[str]":
    """(primary_site, disease_type) -> framework indication code, or None if unmapped.

    Conservative: each rule requires an UNAMBIGUOUS (site, histology) pair for exactly one indication;
    genuinely ambiguous / mixed / grade-indeterminate / subtype-unresolvable histologies return None.
    """
    ps = (primary_site or "").lower()
    dt = (disease_type or "").lower()
    # ── core set (pre-existing v1, unchanged) ───────────────────────────────────────────────────────
    if any(x in ps for x in ("colon", "rectum", "rectosigmoid")) and "adenom" in dt:
        return "COADREAD"  # colon/rectum adenocarcinoma (non-adenocarcinoma colon histologies left unmapped)
    if "pancreas" in ps and ("ductal" in dt or "adenom" in dt):
        return "PAAD"  # pancreatic ductal / adenocarcinoma (PDAC)
    if ("bronchus" in ps or "lung" in ps) and any(x in dt for x in ("adenom", "squamous", "epithelial")):
        return "NSCLC"  # lung adeno / squamous / epithelial-NOS carcinoma (non-small-cell)
    if "stomach" in ps and "adenom" in dt:
        return "GC"  # gastric adenocarcinoma (pre-existing 'GC' tag kept verbatim, not 'STAD')
    # ── broadened set (2026-08-24): each an unambiguous single-histology category ────────────────────
    if "esophagus" in ps and "adenom" in dt:
        return "ESCA"  # esophageal adenocarcinoma (epithelial-NOS esophagus left unmapped)
    if "breast" in ps and ("ductal" in dt or "lobular" in dt or "epithelial" in dt):
        return "BRCA"  # invasive ductal/lobular + metaplastic/epithelial breast carcinoma (site is
        #   unambiguous for BRCA across epithelial subtypes)
    if "skin" in ps and "melanom" in dt:
        return "SKCM"  # cutaneous melanoma ONLY (skin SCC / lymphoma / sarcoma and uveal 'Eye and
        #   adnexa' melanoma are NOT skin-cutaneous-melanoma -> left unmapped)
    if "ovary" in ps and "stromal" not in dt and any(x in dt for x in ("serous", "cystic", "mucinous", "adenom")):
        return "OV"  # epithelial ovarian carcinoma (serous/cystic/mucinous/adeno); sex-cord
        #   'Complex Mixed and Stromal Neoplasms' excluded (distinct non-epithelial biology)
    if "bladder" in ps and ("transitional" in dt or "urothelial" in dt):
        return "BLCA"  # urothelial / transitional-cell carcinoma (bladder adeno-variant + NOS left unmapped)
    if "corpus uteri" in ps and any(x in dt for x in ("adenom", "serous", "cystic", "mucinous")):
        return "UCEC"  # endometrioid + serous uterine-corpus carcinoma; 'Uterus, NOS' site (ambiguous
        #   corpus-vs-cervix) and myomatous/stromal (leiomyo/carcinosarcoma) left unmapped
    if (
        any(s in ps for s in ("mouth", "tongue", "larynx", "pharynx", "lip", "tonsil", "palate", "gum"))
        and "squamous" in dt
    ):
        return "HNSC"  # head & neck squamous cell carcinoma (oral cavity / tongue / larynx / pharynx);
        #   sinonasal 'Nasal cavity and middle ear' + ill-defined sites left unmapped
    if "thyroid" in ps and "adenom" in dt:
        return "THCA"  # thyroid papillary/follicular adenocarcinoma (thyroid SCC left unmapped)
    return None


def _availability_class(n: int) -> str:
    if n >= _MODEL_AVAILABILITY_CLASS_THRESHOLDS["deep"]:
        return "deep_model_coverage"
    if n >= _MODEL_AVAILABILITY_CLASS_THRESHOLDS["moderate"]:
        return "moderate_model_coverage"
    return "sparse_model_coverage"


def _list_case_jsons(s3) -> list:
    keys = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=_BUCKET, Prefix=_HCMI_PREFIX):
        for obj in page.get("Contents", []):
            k = obj["Key"]
            base = k.rsplit("/", 1)[-1]
            if base.startswith("HCM-") and base.endswith(".json"):
                keys.append(k)
    return keys


def _read_one(key: str):
    """Return (model_id, primary_site, disease_type) for one case JSON, or None on any read/parse error."""
    import boto3

    try:
        d = json.loads(boto3.client("s3").get_object(Bucket=_BUCKET, Key=key)["Body"].read())["ClinicalData"]
        mid = (d.get("SubjectData") or {}).get("submitter_id")
        ent = (d.get("GDC Clinical Data Entities") or [{}])[0]
        return (mid, ent.get("primary_site"), ent.get("disease_type"))
    except Exception:  # absence-discipline: exempt -- build-time batch; a single unreadable case is skipped (COUNTED + WARNed by aggregate_model_availability so throttling can't silently undercount)
        return None


def aggregate_model_availability(max_workers: int = 24) -> list:
    """Walk the HCMI case JSONs and aggregate patient-derived model counts per framework indication."""
    import boto3

    os.environ.setdefault("AWS_PROFILE", "cbg")
    s3 = boto3.client("s3")
    keys = _list_case_jsons(s3)
    rows = []
    n_unreadable = 0  # _read_one returned None = a read/parse FAILURE (not a genuine no-model-id case)
    with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
        for r in ex.map(_read_one, keys):
            if r is None:
                n_unreadable += 1
                continue
            if r[0]:
                rows.append(r)
    if n_unreadable:
        import sys as _sys

        print(
            f"WARNING: {n_unreadable}/{len(keys)} HCMI case JSONs were unreadable/unparseable and "
            f"were SKIPPED — if this is S3 throttling (not genuine gaps) the per-indication model "
            f"counts UNDERCOUNT. Re-run to confirm stability.",
            file=_sys.stderr,
        )
    per = defaultdict(lambda: {"models": set(), "sites": Counter()})
    for mid, ps, dt in rows:
        ind = crosswalk_indication(ps, dt)
        if ind:
            per[ind]["models"].add(mid)
            per[ind]["sites"][f"{ps}|{dt}"] += 1
    out = []
    for ind in sorted(per):
        n = len(per[ind]["models"])
        out.append(
            {
                "indication": ind,
                "n_patient_derived_models": n,
                "model_availability_class": _availability_class(n),
                "source": "HCMI-CMDC-DR45",
                "primary_site_breakdown": "; ".join(f"{k}={c}" for k, c in per[ind]["sites"].most_common()),
            }
        )
    return out


# ── genotype-matched aggregation (R2.10 v2) ──────────────────────────────────────────────────────────
def build_model_indication_map(max_workers: int = 24) -> tuple:
    """Walk the HCMI case JSONs and return the per-MODEL crosswalk the genotype-matched join needs.

    Returns (model_to_indication, indication_denom, n_cases_walked, n_unreadable):
      model_to_indication : {model_submitter_id -> framework indication} for models mapped to a core
                            indication (reuses crosswalk_indication verbatim — identical mapping to v1).
      indication_denom    : {indication -> distinct-model count} == v1's n_patient_derived_models (the
                            genotype-matched n_models_in_indication DENOMINATOR).
    """
    import boto3

    os.environ.setdefault("AWS_PROFILE", "cbg")
    s3 = boto3.client("s3")
    keys = _list_case_jsons(s3)
    model_to_indication: dict = {}
    denom: Counter = Counter()
    n_unreadable = 0
    with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
        for r in ex.map(_read_one, keys):
            if r is None:
                n_unreadable += 1
                continue
            mid, ps, dt = r
            if not mid:
                continue
            ind = crosswalk_indication(ps, dt)
            if ind and mid not in model_to_indication:
                model_to_indication[mid] = ind
                denom[ind] += 1
    if n_unreadable:
        print(
            f"WARNING: {n_unreadable}/{len(keys)} HCMI case JSONs unreadable/unparseable and SKIPPED "
            f"— per-indication DENOMINATORS may undercount. Re-run to confirm stability.",
            file=sys.stderr,
        )
    return model_to_indication, denom, len(keys), n_unreadable


def _list_maf_keys(s3) -> list:
    """List the 923 per-model masked-somatic-mutation MAF object keys (wxs aliquot ensemble masked)."""
    keys = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=_BUCKET, Prefix=_HCMI_PREFIX):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".wxs.aliquot_ensemble_masked.maf.gz"):
                keys.append(obj["Key"])
    return keys


def _parse_maf(key: str):
    """Parse one gzipped MAF; return list of (model_id, gene_symbol, variant_class, hgvsp_short) for
    FUNCTIONAL coding variants only, or None on any read/parse error (COUNTED + WARNed by the caller)."""
    import boto3

    try:
        raw = boto3.client("s3").get_object(Bucket=_BUCKET, Key=key)["Body"].read()
        out = []
        with gzip.open(io.BytesIO(raw), "rt") as fh:
            header = None
            i_gene = i_vc = i_bc = i_hgvsp = None
            for line in fh:
                if line.startswith("#"):
                    continue
                cols = line.rstrip("\n").split("\t")
                if header is None:
                    header = cols
                    i_gene = header.index("Hugo_Symbol")
                    i_vc = header.index("Variant_Classification")
                    i_bc = header.index("Tumor_Sample_Barcode")
                    i_hgvsp = header.index("HGVSp_Short") if "HGVSp_Short" in header else None
                    continue
                if len(cols) <= i_bc:
                    continue
                vc = cols[i_vc]
                if vc not in _FUNCTIONAL_CODING_CLASSES:
                    continue
                gene = cols[i_gene]
                if not gene or gene == ".":
                    continue
                mid = _model_id_from_barcode(cols[i_bc])
                if not mid:
                    continue
                hgvsp = cols[i_hgvsp] if (i_hgvsp is not None and len(cols) > i_hgvsp) else ""
                out.append((mid, gene, vc, hgvsp))
        return out
    except Exception:  # absence-discipline: exempt -- build-time batch; a single unreadable MAF is COUNTED + WARNed so throttling can't silently undercount alteration hits
        return None


def aggregate_genotype_matched(max_workers: int = 24) -> tuple:
    """Build the per-(gene_symbol, indication) genotype-matched-model table.

    Answers "for target X in indication Y, do HCMI patient-derived models carry a (COARSE, any functional
    coding) alteration in X?". Returns (rows, meta). rows are sorted by (gene_symbol, indication) and
    carry an indication='ALL' rollup per gene. meta captures cohort + join provenance for the manifest.

    RECURRENT-HOTSPOT COLUMN (#2, 2026-08-24): n_models_with_recurrent_hotspot = distinct models (within
    the gene x indication cell) whose alteration in the gene shares an HGVSp_Short protein change seen in
    >=2 DISTINCT models for that gene across the FULL HCMI cohort (all MAF-bearing models, mapped or not).
    This is a SELF-CONTAINED recurrence signal (no external hotspot source) that lets a consumer tell an
    "any-functional-coding" match from a match at a cohort-recurrent position (a weak driver-hotspot cue).

    CROSSWALK: reuses crosswalk_indication verbatim, which was BROADENED 2026-08-24 from the 4 GI/lung core
    indications to 12 (adds ESCA/BRCA/SKCM/OV/BLCA/UCEC/HNSC/THCA), so the per-indication denominators and
    the set of covered indications grow correspondingly.
    """
    import boto3

    os.environ.setdefault("AWS_PROFILE", "cbg")
    model_to_indication, denom, n_cases, n_unreadable_cases = build_model_indication_map(max_workers)
    s3 = boto3.client("s3")
    maf_keys = _list_maf_keys(s3)

    # (gene, indication) -> {"models": set(model_id), "classes": Counter, "hgvsp": set(sample),
    #                         "model_hgvsps": {model_id -> set(HGVSp_Short)} for the recurrent-hotspot column}
    agg: dict = defaultdict(
        lambda: {"models": set(), "classes": Counter(), "hgvsp": set(), "model_hgvsps": defaultdict(set)}
    )
    # Self-contained hotspot recurrence (#2): (gene, HGVSp_Short) -> set(model_id) tallied over the FULL
    # HCMI cohort (ALL MAF-bearing models, mapped OR unmapped), so recurrence has a robust cohort-wide
    # denominator and does NOT depend on the indication crosswalk. An HGVSp is "recurrent" for a gene iff
    # it is seen in >=2 DISTINCT models cohort-wide (no external hotspot source).
    gene_hgvsp_models: dict = defaultdict(set)
    n_unreadable_mafs = 0
    mafs_mapped = set()  # distinct model ids (with a MAF) that map to a core indication
    mafs_unmapped_models = set()
    ROLL = _rollup_indication()
    with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
        for res in ex.map(_parse_maf, maf_keys):
            if res is None:
                n_unreadable_mafs += 1
                continue
            for mid, gene, vc, hgvsp in res:
                if hgvsp:
                    gene_hgvsp_models[(gene, hgvsp)].add(mid)  # cohort-wide recurrence tally (all models)
                ind = model_to_indication.get(mid)
                if ind is None:
                    mafs_unmapped_models.add(mid)
                    continue
                mafs_mapped.add(mid)
                for scope in (ind, ROLL):
                    cell = agg[(gene, scope)]
                    cell["models"].add(mid)
                    cell["classes"][vc] += 1
                    if hgvsp:
                        cell["model_hgvsps"][mid].add(hgvsp)
                        if len(cell["hgvsp"]) < 5:
                            cell["hgvsp"].add(hgvsp)
    if n_unreadable_mafs:
        print(
            f"WARNING: {n_unreadable_mafs}/{len(maf_keys)} HCMI MAFs unreadable/unparseable and SKIPPED "
            f"— n_models_with_alteration may undercount. Re-run to confirm stability.",
            file=sys.stderr,
        )

    # recurrent HGVSp set per gene (>=2 distinct models cohort-wide)
    recurrent_by_gene: dict = defaultdict(set)
    for (gene, hgvsp), mids in gene_hgvsp_models.items():
        if len(mids) >= 2:
            recurrent_by_gene[gene].add(hgvsp)

    denom_all = sum(denom.values())
    rows = []
    for (gene, scope), cell in agg.items():
        n_alt = len(cell["models"])
        n_denom = denom_all if scope == ROLL else denom.get(scope, 0)
        rec = recurrent_by_gene.get(gene, frozenset())
        # distinct models (in this gene x indication cell) carrying >=1 recurrent-hotspot HGVSp
        n_recurrent = sum(1 for _mid, hgs in cell["model_hgvsps"].items() if hgs & rec)
        rows.append(
            {
                "gene_symbol": gene,
                "indication": scope,
                "n_models_in_indication": int(n_denom),
                "n_models_with_alteration": int(n_alt),
                "n_models_with_recurrent_hotspot": int(n_recurrent),
                "variant_classes_present": "; ".join(sorted(cell["classes"])),
                "hgvsp_examples": "; ".join(sorted(x for x in cell["hgvsp"] if x)),
                "genotype_matched_class": genotype_matched_class(n_alt),
                "source": "HCMI-CMDC-DR45",
            }
        )
    rows.sort(key=lambda r: (r["gene_symbol"], r["indication"]))
    meta = {
        "n_cases_walked": n_cases,
        "n_unreadable_cases": n_unreadable_cases,
        "n_maf_files": len(maf_keys),
        "n_unreadable_mafs": n_unreadable_mafs,
        "indication_denom": dict(denom),
        "n_models_total_mapped": denom_all,
        "n_maf_models_mapped_to_core": len(mafs_mapped),
        "n_maf_models_unmapped": len(mafs_unmapped_models),
        "n_gene_indication_rows": len(rows),
        "n_distinct_genes": len({r["gene_symbol"] for r in rows}),
    }
    return rows, meta


def _emit_genotype_sidecar(payload_path: Path, resolver_release: str):
    """Emit the target-resolution sidecar next to the genotype payload (gene_symbol native key).
    Mirrors uniprot_gpi_anchor.derive._emit_sidecar; the emit_resolver_sidecar CLI only works on SOURCE
    manifests, so the sidecar is emitted inside the producer for this DERIVED parquet."""
    lib = DATA_CATALOG_ROOT / "libs" / "target_id_resolver"
    if str(lib) not in sys.path:
        sys.path.insert(0, str(lib))
    from target_id_resolver.sidecar import emit_sidecar

    sidecar_path = Path(str(payload_path).replace(".parquet", ".target_resolution.parquet"))
    stats = emit_sidecar(
        payload_parquet_path=payload_path,
        native_key_column="gene_symbol",
        native_key_type="gene_symbol",
        gencode_version_source="n/a",  # GDC MAF Hugo_Symbol column; not gencode-versioned here
        out_path=sidecar_path,
        resolver_release=resolver_release,
    )
    return sidecar_path, stats


def _run_availability(args) -> int:
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = aggregate_model_availability(max_workers=args.max_workers)
    pq.write_table(pa.Table.from_pylist(rows), args.out)
    total = sum(r["n_patient_derived_models"] for r in rows)
    print(f"wrote {len(rows)} indications ({total} mapped models) -> {args.out}")
    for r in rows:
        print(f"  {r['indication']:9} n={r['n_patient_derived_models']:4}  {r['model_availability_class']}")
    return 0


def _run_genotype_matched(args) -> int:
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows, meta = aggregate_genotype_matched(max_workers=args.max_workers)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), str(out))
    print(f"wrote {len(rows)} (gene, indication) rows ({meta['n_distinct_genes']} genes) -> {out}", file=sys.stderr)
    print(f"  meta: {json.dumps(meta)}", file=sys.stderr)
    if not args.no_sidecar:
        sidecar_path, stats = _emit_genotype_sidecar(out, args.resolver_release)
        print(f"  sidecar -> {sidecar_path}", file=sys.stderr)
        print(f"  resolver stats: {stats}", file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Materialize an HCMI model product (availability or genotype-matched).")
    ap.add_argument(
        "--mode",
        choices=["availability", "genotype-matched"],
        default="availability",
        help="availability = v1 per-indication counts; genotype-matched = R2.10 v2 per-(gene, indication).",
    )
    ap.add_argument("--out", required=True, help="output parquet path")
    ap.add_argument("--max-workers", type=int, default=24)
    ap.add_argument(
        "--resolver-release",
        default=DEFAULT_RESOLVER_RELEASE,
        help="resolver release pin for the genotype-matched sidecar",
    )
    ap.add_argument("--no-sidecar", action="store_true", help="genotype-matched: skip sidecar emission")
    args = ap.parse_args()
    if args.mode == "genotype-matched":
        return _run_genotype_matched(args)
    return _run_availability(args)


if __name__ == "__main__":
    raise SystemExit(main())
