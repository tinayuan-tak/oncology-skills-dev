"""surface_antigen_density_ladder.read — reader + admissibility validator for the ABSOLUTE
surface-density calibration corpus.

The corpus is a committed TSV (absolute_density_corpus.tsv) of MEASURED copies-per-cell values —
the only evidence-grade A/B anchor in the tiered density model. This module:
  - defines the `absolute_density_measurement` row schema (REQUIRED_FIELDS + vocabularies);
  - `validate_row(row)` — admissibility gate that REJECTS fabrication-prone rows (any row missing a
    numeric value, a recognized unit, a calibration_method, a source DOI, or an evidence_grade is
    NOT admissible → it never contributes to a calibration);
  - `read_absolute_density(target, indication=None)` — returns the admissible measurements for a
    target as a grade-resolved summary. An empty / all-rejected corpus reads as grade 'E' (no absolute
    measurement) — NEVER a fabricated number.

Governance: no value is authored in code. The corpus ships header-only until a governance step
populates it (team-curated / web-sourced-then-approved). validate_row is the machine guard that keeps
an un-governed or malformed row out of the calibration.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

METHOD_VERSION = "0.1.0"

CORPUS_PATH = Path(__file__).resolve().parent / "absolute_density_corpus.tsv"

# --- absolute_density_measurement schema (the review's Phase-2 schema) -----------------------
# A row is ADMISSIBLE only if every REQUIRED_FIELD is present + non-empty + passes its type/vocab
# check. This is deliberately strict: the corpus is a calibration GROUND-TRUTH, so a row that cannot
# prove what it measured, in what unit, by what calibration, from what source, at what grade, is
# rejected rather than trusted. (Fabrication guard: no DOI / no unit / no value → not calibration.)
REQUIRED_FIELDS = (
    "target",
    "value",              # numeric copies-per-cell (or ABC/sites/MESF per `unit`)
    "unit",               # must be in ADMISSIBLE_UNITS
    "calibration_method",  # must be in ADMISSIBLE_CALIBRATION_METHODS
    "source_doi",         # per-row provenance — must look like a DOI
    "evidence_grade",     # must be in ADMISSIBLE_GRADES (A or B for a direct flow measurement)
)

# Optional-but-recorded provenance fields (absence widens uncertainty, does not reject the row).
OPTIONAL_FIELDS = (
    "uniprot_ac", "cell_model", "disease", "specimen_type",
    "lower_bound", "upper_bound", "antibody_clone", "valency", "fluorophore",
    "saturation_confirmed", "viable_cell_gating", "replicate_count", "notes",
)

# Absolute-scale units the corpus admits (calibrated surface-count units). A relative/normalized unit
# (log2, ppm, NPX, TPM) is NOT admissible here — those belong to the PRIOR tiers, not the anchor.
ADMISSIBLE_UNITS = frozenset({
    "ABC",                # antibodies bound per cell (QIFIKIT / calibrated bead)
    "sites_per_cell",
    "molecules_per_cell",
    "MESF",               # molecules of equivalent soluble fluorochrome
})

# Direct-calibration methods the corpus admits. Anything not calibrated (e.g. "estimated", "inferred")
# is rejected — that is the whole point of the absolute anchor.
ADMISSIBLE_CALIBRATION_METHODS = frozenset({
    "QIFIKIT",
    "QuantiBRITE",
    "calibrated_bead",
    "MESF_calibration",
    "quantitative_ihc",   # absolute (calibrated) quantitative IHC, not qualitative scoring
})

# Only A/B are DIRECT calibrated flow (A = patient cells, B = cell-line/model). C/D/E are NOT direct
# measurements and must not appear in the absolute corpus (they are computed elsewhere from priors).
ADMISSIBLE_GRADES = frozenset({"A", "B"})


def _looks_like_doi(v: str) -> bool:
    """Minimal DOI shape check (10.<registrant>/<suffix>). Guards against a blank/placeholder source."""
    s = str(v).strip().lower()
    if s.startswith("https://doi.org/"):
        s = s[len("https://doi.org/"):]
    if s.startswith("doi:"):
        s = s[4:].strip()
    return s.startswith("10.") and "/" in s and len(s) > 7


def validate_row(row: dict) -> tuple[bool, Optional[str]]:
    """Admissibility gate for one corpus row → (is_admissible, reason_if_not).

    A row is admissible ONLY if all REQUIRED_FIELDS are present + non-empty AND value is a positive
    number AND unit/calibration_method/evidence_grade are in their vocabularies AND source_doi looks
    like a DOI. The first failing check's reason is returned (so a populated corpus can be audited)."""
    for f in REQUIRED_FIELDS:
        if not str(row.get(f, "") or "").strip():
            return False, f"missing_required:{f}"

    try:
        val = float(row["value"])
    except (TypeError, ValueError):
        return False, "value_not_numeric"
    if not (val > 0):
        return False, "value_not_positive"

    unit = str(row["unit"]).strip()
    if unit not in ADMISSIBLE_UNITS:
        return False, f"unit_not_admissible:{unit}"

    method = str(row["calibration_method"]).strip()
    if method not in ADMISSIBLE_CALIBRATION_METHODS:
        return False, f"calibration_method_not_admissible:{method}"

    grade = str(row["evidence_grade"]).strip().upper()
    if grade not in ADMISSIBLE_GRADES:
        return False, f"evidence_grade_not_admissible:{grade}"

    if not _looks_like_doi(row["source_doi"]):
        return False, "source_doi_not_doi_shaped"

    # optional bounds sanity: if both present, lower <= value <= upper
    lo, hi = row.get("lower_bound"), row.get("upper_bound")
    try:
        if str(lo or "").strip() and str(hi or "").strip():
            lo_f, hi_f = float(lo), float(hi)
            if not (lo_f <= val <= hi_f):
                return False, "bounds_do_not_bracket_value"
    except (TypeError, ValueError):
        return False, "bounds_not_numeric"

    return True, None


def _load_corpus(corpus_path: Optional[Path] = None) -> list[dict]:
    """Read the committed TSV → list of raw row dicts (no validation). Empty list if absent/header-only."""
    path = Path(corpus_path) if corpus_path is not None else CORPUS_PATH
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def _empty(note: str) -> dict:
    """Grade-E: no admissible absolute measurement (never a fabricated number)."""
    return {
        "absolute_density_class": "no_absolute_measurement",
        "density_evidence_level": "E",
        "copies_per_cell_best": None,
        "copies_per_cell_lower": None,
        "copies_per_cell_upper": None,
        "unit": None,
        "n_admissible_measurements": 0,
        "measurements": [],
        "method_version": METHOD_VERSION,
        "_data_note": note,
    }


def read_absolute_density(target: str, indication: str = None,
                          corpus_path: Optional[Path] = None) -> dict:
    """Absolute surface-density measurements for a target from the governed calibration corpus.

    Returns the admissible (validate_row-passing) measurements for `target`, resolved to a summary:
        absolute_density_class  — surface_density vocab {high|moderate|low|very_low} from best value,
                                  or 'no_absolute_measurement' when none admissible;
        density_evidence_level  — 'A' if any admissible row is grade A (patient cells), else 'B' if any
                                  grade B, else 'E' (none) — the corpus is direct-flow only, so never C/D;
        copies_per_cell_best/lower/upper — best (grade-A-preferred, else B) measurement + its bounds;
        n_admissible_measurements, measurements[] (the passing rows, provenance-tagged).

    An empty / header-only / all-rejected corpus → grade E. No value is ever fabricated. `indication`,
    when given, prefers same-disease measurements for `best` but does not exclude others (small corpus).
    """
    sym = str(target or "").upper().strip()
    if not sym:
        return _empty("no_target")

    rows = _load_corpus(corpus_path)
    if not rows:
        return _empty("corpus_empty_or_absent")

    admissible = []
    for row in rows:
        if str(row.get("target", "")).upper().strip() != sym:
            continue
        ok, _reason = validate_row(row)
        if ok:
            admissible.append(row)

    if not admissible:
        return _empty("no_admissible_measurement_for_target")

    # Prefer grade A (patient) over B (model); within grade, prefer same-indication when given.
    ind = str(indication or "").upper().strip()

    def _rank(r: dict) -> tuple:
        grade = str(r["evidence_grade"]).strip().upper()
        same_ind = 1 if (ind and str(r.get("disease", "")).upper().strip() == ind) else 0
        return (0 if grade == "A" else 1, -same_ind, -float(r.get("replicate_count") or 0))

    best = sorted(admissible, key=_rank)[0]
    best_grade = str(best["evidence_grade"]).strip().upper()
    val = float(best["value"])
    lo = float(best["lower_bound"]) if str(best.get("lower_bound") or "").strip() else None
    hi = float(best["upper_bound"]) if str(best.get("upper_bound") or "").strip() else None

    return {
        "absolute_density_class": _classify_copies(val),
        "density_evidence_level": best_grade,          # A or B (direct flow); corpus is anchor-only
        "copies_per_cell_best": val,
        "copies_per_cell_lower": lo,
        "copies_per_cell_upper": hi,
        "unit": str(best["unit"]).strip(),
        "n_admissible_measurements": len(admissible),
        "measurements": [
            {
                "value": float(m["value"]),
                "unit": str(m["unit"]).strip(),
                "cell_model": m.get("cell_model"),
                "disease": m.get("disease"),
                "specimen_type": m.get("specimen_type"),
                "calibration_method": m.get("calibration_method"),
                "evidence_grade": str(m["evidence_grade"]).strip().upper(),
                "source_doi": m.get("source_doi"),
            }
            for m in admissible
        ],
        "method_version": METHOD_VERSION,
    }


# surface_density vocabulary boundaries (target-contracts surface-abundance-density card). These are
# the CARD's class boundaries applied to a MEASURED value — NOT the modality-viability thresholds
# (those are configurable format parameters, per the tiered model, not encoded as biological gates).
def _classify_copies(copies: float) -> str:
    if copies > 10000:
        return "high"
    if copies >= 1000:
        return "moderate"
    if copies >= 100:
        return "low"
    return "very_low"
