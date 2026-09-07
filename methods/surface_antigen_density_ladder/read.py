"""surface_antigen_density_ladder.read — reader + admissibility validator for the ABSOLUTE
surface-density calibration corpus (schema v3, superset).

The corpus is a committed, GOVERNED TSV of MEASURED surface-antigen density values — the only
evidence-grade A/B anchor in the tiered density model (feedback_surface_density_evidence_model).
Only directly-calibrated flow / single-molecule counting sets the absolute scale; CSPA, CCLE/CPTAC
whole-cell proteomics, and HPA IHC are priors (grades C/D), never absolute anchors.

SCHEMA v3 (2026-07-23) is the SUPERSET of the domain-expert's 32-column governed schema and this
module's validator guarantees. Every value is quoted from a primary table/supplement with a
resolvable DOI (no bar-graph digitization). Design invariants the reader/validator enforce:

  1. PARTITIONS are load-bearing (record_partition): native_patient / native_cell_line feed a tumor
     density anchor; normal_reference / calibration_reference (engineered) / method_control (fixed) /
     explicit_negative do NOT. read_absolute_density defaults to the two native partitions.
  2. DUAL ADMISSIBILITY booleans travel per row: admissible_for_absolute_scale (may set the copies
     scale) and admissible_for_native_biology (represents native tumor). BOTH the partition filter
     AND the row boolean must pass — belt and suspenders against a mis-tagged row.
  3. QUALIFIERS survive as data (value_qualifier): exact_reported / mean / median / patient_median /
     mean_with_reported_range / approximate / lower_bound / upper_bound / explicit_negative. A bound
     is never coerced to an exact count; a patient_median is ranked on the median, never on its SD.
  4. SEMANTICS are distinguished (measurement_semantics + reported_unit): ABC ≠ molecule count;
     monovalent-epitope ≈ epitopes; dSTORM = direct molecule count; PE-equivalent is a proxy. Never
     silently averaged; recorded so a consumer can choose comparable rows.
  5. GRADE sub-tiers (evidence_grade): A (patient direct) / A- (patient, proxy or median) / A-N
     (normal-reference patient-adjacent) / B (cell-line direct) / B- (cell-line, rounded/bounded) /
     CAL (engineered calibration) / QC (method control). Only A/A- and B/B- feed a native anchor.

No value is authored in code; the committed corpus is the governed artifact. validate_row is the
machine guard that keeps a malformed/quarantined row out of any calibration.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

from methods.catalog_query.read import bucket_prefix_for

METHOD_VERSION = "0.3.0"

# The governed corpus is the SOURCE-OF-TRUTH object on S3 (data-catalog manifest
# surface-antigen-absolute-density-curated-v1), NOT an in-repo copy — single source, no dual-home
# drift. Read from S3 with a local cache + the definitive-vs-transient latch pattern (mirrors
# cptac_protein_deg). Tests pass an explicit corpus_path to bypass S3.
DEFAULT_AWS_PROFILE = "cbg"
SOURCE_MANIFEST_ID = "surface-antigen-absolute-density-curated-v1"
# bucket + key resolved from the data-catalog manifest (single source of truth).
S3_BUCKET, _SOURCE_PREFIX = bucket_prefix_for(SOURCE_MANIFEST_ID)
CORPUS_S3_KEY = f"{_SOURCE_PREFIX}absolute_density_corpus.tsv"
CACHE_DIR = Path.home() / ".cache" / "framework-surface-density-ladder"
CACHE_CORPUS = CACHE_DIR / "absolute_density_corpus.tsv"

_CORPUS_STATUS: Optional[bool] = None


from methods.target_id_sidecar import s3_client as _boto3_client


def _ensure_corpus_cached() -> Optional[Path]:
    """Download + cache the governed corpus from S3. Definitive-vs-transient latch: only a real
    404/NoSuchKey latches _CORPUS_STATUS=False (product genuinely absent); a transient error
    (403/expired creds/network) leaves it None so a later call retries. Returns the cache path or None."""
    global _CORPUS_STATUS
    if _CORPUS_STATUS is False:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if CACHE_CORPUS.exists() and CACHE_CORPUS.stat().st_size > 0:
        _CORPUS_STATUS = True
        return CACHE_CORPUS
    if _CORPUS_STATUS is None:
        try:
            _boto3_client().download_file(S3_BUCKET, CORPUS_S3_KEY, str(CACHE_CORPUS))
            _CORPUS_STATUS = True
            return CACHE_CORPUS
        except Exception as e:
            resp = getattr(e, "response", None)
            code = resp.get("Error", {}).get("Code") if isinstance(resp, dict) else None
            definitive = code in ("404", "NoSuchKey") or e.__class__.__name__ in ("NoSuchKey", "404")
            if definitive:
                _CORPUS_STATUS = False
            return None
    return None


# --- schema v3 columns (superset; = the governed FINAL header) -------------------------------
SCHEMA_V3_COLUMNS = (
    "record_id",
    "target_gene",
    "target_symbol_reported",
    "sample_id",
    "model_or_sample",
    "sample_type",
    "disease_or_context",
    "species",
    "native_or_engineered",
    "measurement_method",
    "measurement_semantics",
    "reported_unit",
    "value_qualifier",
    "value_central",
    "value_lower",
    "value_upper",
    "uncertainty_type",
    "uncertainty_value",
    "replicate_count",
    "positive_cell_fraction",
    "cells_measured",
    "preanalytical_condition",
    "record_partition",
    "evidence_grade",
    "admissible_for_absolute_scale",
    "admissible_for_native_biology",
    "source_title",
    "source_year",
    "source_doi",
    "source_url",
    "source_locator",
    "extraction_note",
)

# For admission as a NUMERIC absolute-scale datum. A record missing any of these (or that is an
# explicit_negative / method_control) is not a numeric anchor — but may still be a valid status/QC row.
# NOTE `value_central` is NOT here: a bound-only row (lower_bound/upper_bound puts the value in
# value_lower/value_upper) is a legitimate anchor — the numeric-value check below requires an anchor
# value from central OR the matching bound, per the qualifier.
REQUIRED_FIELDS = (
    "target_gene",
    "value_qualifier",
    "reported_unit",
    "measurement_method",
    "record_partition",
    "evidence_grade",
    "source_doi",
)

# Absolute-scale reported units. A relative/normalized unit (log2/ppm/NPX/TPM) is NOT admissible.
ADMISSIBLE_UNITS = frozenset(
    {
        "ABC/cell",
        "sites_per_cell",
        "molecules/cell",
        "ABS/cell",
        "MESF",
        "PE-equivalent molecules/cell",
        "epitopes/cell",
    }
)

# Direct-measurement methods (calibrated flow / single-molecule). Non-calibrated → rejected.
ADMISSIBLE_METHODS = frozenset(
    {
        "QIFIKIT calibrated flow cytometry",
        "Quantibrite PE calibrated flow cytometry",
        "monovalent Quantibrite PE calibrated flow cytometry",
        "PE-calibrated quantitative flow cytometry",
        "calibrated bead flow cytometry",
        "dSTORM single-molecule localization microscopy",
        "quantitative IHC calibrated",
        # engineered calibration-ladder rows report study-characterized density; readable ONLY in the
        # calibration_reference partition (grade CAL) — never a native anchor (partition gate handles that).
        "quantitative antigen-density characterization reported by study",
    }
)

# record_partition vocabulary. NATIVE_PARTITIONS are the tumor-density default read.
NATIVE_PARTITIONS = frozenset({"native_patient", "native_cell_line"})
NONNATIVE_PARTITIONS = frozenset({"normal_reference", "calibration_reference", "method_control", "explicit_negative"})
ADMISSIBLE_PARTITIONS = NATIVE_PARTITIONS | NONNATIVE_PARTITIONS

# value_qualifier vocabulary. explicit_negative carries no numeric value (a status record).
NUMERIC_QUALIFIERS = frozenset(
    {
        "exact_reported",
        "mean",
        "median",
        "patient_median",
        "mean_with_reported_range",
        "approximate",
        "lower_bound",
        "upper_bound",
    }
)
VALUE_QUALIFIERS = NUMERIC_QUALIFIERS | frozenset({"explicit_negative"})

# evidence_grade sub-tiers. NATIVE_ANCHOR_GRADES may set a native tumor density; CAL/QC/A-N never do.
NATIVE_ANCHOR_GRADES = frozenset({"A", "A-", "B", "B-"})
ALL_GRADES = NATIVE_ANCHOR_GRADES | frozenset({"A-N", "CAL", "QC"})

# grade rank for "best measurement" selection (lower = preferred): patient direct > patient proxy >
# cell-line direct > cell-line rounded.
_GRADE_RANK = {"A": 0, "A-": 1, "B": 2, "B-": 3}


def _looks_like_doi(v: str) -> bool:
    s = str(v).strip().lower()
    if s.startswith("https://doi.org/"):
        s = s[len("https://doi.org/") :]
    if s.startswith("doi:"):
        s = s[4:].strip()
    return s.startswith("10.") and "/" in s and len(s) > 7


def validate_row(row: dict) -> tuple[bool, Optional[str]]:
    """Admissibility gate for one v3 corpus row as a NUMERIC absolute-scale datum → (ok, reason).

    A row is admissible ONLY if: required fields present; value_qualifier + reported_unit +
    measurement_method + record_partition + evidence_grade in their vocabularies; the row's
    `admissible_for_absolute_scale` is truthy ('yes'/'qualified'); a positive numeric value OR a
    numeric bound consistent with the qualifier; and a DOI-shaped source. explicit_negative /
    method_control rows are (correctly) NOT admissible numeric anchors — they return a specific reason
    so an audit can distinguish them from malformed rows."""
    for f in REQUIRED_FIELDS:
        if not str(row.get(f, "") or "").strip():
            return False, f"missing_required:{f}"

    qual = str(row["value_qualifier"]).strip()
    if qual not in VALUE_QUALIFIERS:
        return False, f"value_qualifier_not_admissible:{qual}"
    if qual == "explicit_negative":
        return False, "explicit_negative_not_a_numeric_anchor"

    unit = str(row["reported_unit"]).strip()
    if unit not in ADMISSIBLE_UNITS:
        return False, f"reported_unit_not_admissible:{unit}"

    method = str(row["measurement_method"]).strip()
    if method not in ADMISSIBLE_METHODS:
        return False, f"measurement_method_not_admissible:{method}"

    partition = str(row["record_partition"]).strip()
    if partition not in ADMISSIBLE_PARTITIONS:
        return False, f"record_partition_not_admissible:{partition}"

    grade = str(row["evidence_grade"]).strip()
    if grade not in ALL_GRADES:
        return False, f"evidence_grade_not_admissible:{grade}"

    # dual-admissibility per-row veto: a row the curator marked not-for-absolute-scale is held even if
    # otherwise well-formed (belt & suspenders with the partition filter).
    abs_ok = str(row.get("admissible_for_absolute_scale", "") or "").strip().lower()
    if abs_ok not in ("yes", "qualified"):
        return False, f"not_admissible_for_absolute_scale:{abs_ok or 'empty'}"

    # numeric value / bound consistent with the qualifier
    vc = str(row.get("value_central", "") or "").strip()
    lo = str(row.get("value_lower", "") or "").strip()
    hi = str(row.get("value_upper", "") or "").strip()
    if qual == "lower_bound":
        anchor = vc or lo
    elif qual == "upper_bound":
        anchor = vc or hi
    else:
        anchor = vc
    if not anchor:
        return False, "no_numeric_value_for_qualifier"
    try:
        val = float(anchor)
    except (TypeError, ValueError):
        return False, "value_not_numeric"
    if not (val > 0):
        return False, "value_not_positive"

    # if an explicit range is given, it must bracket the central value
    if vc and lo and hi:
        try:
            if not (float(lo) <= float(vc) <= float(hi)):
                return False, "bounds_do_not_bracket_value"
        except (TypeError, ValueError):
            return False, "bounds_not_numeric"

    if not _looks_like_doi(row["source_doi"]):
        return False, "source_doi_not_doi_shaped"

    return True, None


def _load_corpus(corpus_path: Optional[Path] = None) -> list[dict]:
    """Read the governed corpus TSV → row dicts. Skips `#` comment lines. Empty if absent.

    Source of truth is the S3 object (cached locally); an explicit `corpus_path` overrides for tests.
    Graceful-empty on S3-unavailable (data_unavailable, never a fabricated row) — matches every other
    derived reader in the module family."""
    if corpus_path is not None:
        path: Optional[Path] = Path(corpus_path)
    else:
        path = _ensure_corpus_cached()
    if path is None or not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        lines = [ln for ln in fh if not ln.startswith("#")]
    return list(csv.DictReader(lines, delimiter="\t"))


def _anchor_value(row: dict) -> Optional[float]:
    """The numeric value a row anchors on (central, or the stated bound). None if unparseable."""
    qual = str(row.get("value_qualifier", "")).strip()
    vc = str(row.get("value_central", "") or "").strip()
    lo = str(row.get("value_lower", "") or "").strip()
    hi = str(row.get("value_upper", "") or "").strip()
    anchor = (vc or lo) if qual == "lower_bound" else (vc or hi) if qual == "upper_bound" else vc
    try:
        return float(anchor) if anchor else None
    except (TypeError, ValueError):
        return None


def _empty(note: str) -> dict:
    """Grade-E: no admissible absolute measurement in the requested partition(s)."""
    return {
        "absolute_density_class": "no_absolute_measurement",
        "density_evidence_level": "E",
        "value_best": None,
        "value_qualifier_best": None,
        "reported_unit": None,
        "measurement_semantics_best": None,
        "record_partition_best": None,
        "n_admissible_measurements": 0,
        "n_patient": 0,
        "n_cell_line": 0,
        "measurements": [],
        "method_version": METHOD_VERSION,
        "_data_note": note,
    }


def _absolute_abundance_proxy(sym: str) -> dict:
    """ADDITIVE, verdict-INERT genome-wide absolute-abundance PROXY (B1 2026-09-02). The curated
    density corpus covers only ~181 antigens → grade-E `no_absolute_measurement` for the rest
    (FOLR1/TROP2/CD22 …). ProCan cell-line proteomics gives an absolute all-gene abundance percentile
    for ANY protein — a real MEASURED absolute signal (unlike the tumor-vs-normal RATIO the density
    class otherwise rests on), so it fills the gap as CONTEXT. Explicitly a CELL-LINE proxy (not tumor
    copies-per-cell) and NOT verdict-moving (no fit_class rung reads it) — promotion to deciding-axis
    capture is a deliberate second pass. Best-effort: any failure → data_unavailable, never raises."""
    out = {
        "absolute_abundance_proxy_class": "data_unavailable",
        "absolute_abundance_proxy_percentile": None,
        "absolute_abundance_proxy_source": "procan-cellline-protein-abundance-per-protein-v1",
        "absolute_abundance_proxy_note": "cell-line proteomics all-gene percentile; NOT tumor "
        "copies-per-cell; additive context, verdict-inert",
    }
    try:
        from methods.procan_protein_abundance.read import read_target_summary as _procan

        s = _procan(target=sym) or {}
        pct = s.get("allgene_percentile")
        if isinstance(pct, (int, float)):
            out["absolute_abundance_proxy_percentile"] = round(float(pct), 1)
            out["absolute_abundance_proxy_class"] = (
                "high" if pct >= 75 else "moderate" if pct >= 50 else "low" if pct >= 25 else "very_low"
            )
    except Exception:
        pass  # verdict-inert context — degrade silently to data_unavailable
    return out


def read_absolute_density(
    target: str,
    indication: str = None,
    partitions: tuple = ("native_patient", "native_cell_line"),
    corpus_path: Optional[Path] = None,
) -> dict:
    """Absolute surface-density for a target from the governed calibration corpus (schema v3).

    Defaults to the two NATIVE partitions (a tumor-density anchor). `best` prefers patient-direct (A)
    > patient-proxy (A-) > cell-line-direct (B) > cell-line-rounded (B-); within a grade, same-
    indication and higher replicate/positive-fraction win. Non-native partitions (normal_reference,
    calibration_reference, method_control, explicit_negative) are excluded by default — pass
    `partitions` to read them (e.g. ('normal_reference',) for the safety comparator). Empty /
    all-held / no-row-in-partition → grade E. NO value is fabricated.
    """
    sym = str(target or "").upper().strip()
    if not sym:
        return _empty("no_target")

    rows = _load_corpus(corpus_path)
    if not rows:
        return _empty("corpus_empty_or_absent")

    # Additive absolute-abundance PROXY (verdict-inert) — fills the grade-E gap for non-corpus antigens.
    proxy = _absolute_abundance_proxy(sym)

    want = frozenset(partitions)
    admissible = []
    for row in rows:
        if str(row.get("target_gene", "")).upper().strip() != sym:
            continue
        if str(row.get("record_partition", "")).strip() not in want:
            continue
        ok, _reason = validate_row(row)
        if ok:
            admissible.append(row)

    if not admissible:
        return {**_empty("no_admissible_measurement_for_target_in_partition"), **proxy}

    ind = str(indication or "").upper().strip()

    def _rank(r: dict) -> tuple:
        grade = str(r["evidence_grade"]).strip()
        same_ind = 1 if (ind and ind in str(r.get("disease_or_context", "")).upper()) else 0
        try:
            reps = float(r.get("replicate_count") or 0)
        except (TypeError, ValueError):
            reps = 0.0
        return (_GRADE_RANK.get(grade, 9), -same_ind, -reps)

    best = sorted(admissible, key=_rank)[0]
    n_patient = sum(1 for m in admissible if m.get("record_partition") == "native_patient")

    return {
        "absolute_density_class": _classify(_anchor_value(best)),
        "density_evidence_level": str(best["evidence_grade"]).strip(),
        "value_best": _anchor_value(best),
        "value_qualifier_best": str(best["value_qualifier"]).strip(),
        "reported_unit": str(best["reported_unit"]).strip(),
        "measurement_semantics_best": str(best.get("measurement_semantics") or "").strip(),
        "record_partition_best": str(best.get("record_partition") or "").strip(),
        "n_admissible_measurements": len(admissible),
        "n_patient": n_patient,
        "n_cell_line": len(admissible) - n_patient,
        "measurements": [
            {
                "record_id": m.get("record_id"),
                "value": _anchor_value(m),
                "value_qualifier": str(m["value_qualifier"]).strip(),
                "reported_unit": str(m["reported_unit"]).strip(),
                "measurement_semantics": m.get("measurement_semantics"),
                "model_or_sample": m.get("model_or_sample"),
                "disease_or_context": m.get("disease_or_context"),
                "record_partition": m.get("record_partition"),
                "evidence_grade": str(m["evidence_grade"]).strip(),
                "source_doi": m.get("source_doi"),
            }
            for m in admissible
        ],
        "method_version": METHOD_VERSION,
        **proxy,
    }


def read_explicit_negatives(target: str, corpus_path: Optional[Path] = None) -> list[dict]:
    """The explicit antigen-NEGATIVE status records for a target (stored, never numeric zeros).

    A separate accessor because negatives are not numeric anchors but ARE real biology (e.g. CD25-
    negative CLL patients, CD19-negative myeloma samples) — a consumer wants them as evidence of
    absence, not as value=0."""
    sym = str(target or "").upper().strip()
    return [
        {
            "record_id": r.get("record_id"),
            "model_or_sample": r.get("model_or_sample"),
            "disease_or_context": r.get("disease_or_context"),
            "source_doi": r.get("source_doi"),
        }
        for r in _load_corpus(corpus_path)
        if str(r.get("target_gene", "")).upper().strip() == sym
        and str(r.get("record_partition", "")).strip() == "explicit_negative"
    ]


# surface_density card class boundaries applied to a MEASURED value (NOT the modality-viability
# thresholds — those are configurable format parameters, per the tiered model, not biological gates).
def _classify(value: Optional[float]) -> str:
    if value is None:
        return "unmeasured"
    if value > 10000:
        return "high"
    if value >= 1000:
        return "moderate"
    if value >= 100:
        return "low"
    return "very_low"
