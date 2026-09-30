"""read_alteration_clinical_association — OS log-rank by target ALTERATION (mutation) status.

The alteration analog of expression_clinical_association (Q11 → the genomic-feature-vs-survival
gap): instead of median-splitting on expression, split the indication's TCGA patients by whether
they carry a somatic mutation in {target} (MC3 per-sample MAF) vs wild-type, and log-rank overall
survival. A HYPOTHESIS-GENERATING prognostic association for the biomarker-definability facet —
NOT a clinical claim.

  - alteration_mutated_worse_survival  → mutated patients have WORSE OS (candidate poor-prognosis
      alteration; supports a patient-selection biomarker).
  - alteration_mutated_better_survival → mutated patients have BETTER OS (a caution — the alteration
      may mark indolent disease).
  - no_survival_association             → alteration status does not stratify OS in this indication.
  - insufficient_survival_data          → too few mutated patients / events for a meaningful test.
  - data_unavailable                    → no per-sample MAF or no survival substrate.

ZERO new ingestion — reuses:
  - tcga-mc3-per-sample-maf-v1 : per-patient somatic mutations. The COHORT (WT denominator) is the
    set of MC3-profiled patients in the indication (the product's `indication` column); ALTERED are
    those carrying a {target} mutation; WT = cohort − altered.
  - PanCanAtlas TCGA-CDR (Liu 2018) OS/OS.time — the SAME survival substrate + self-contained
    log-rank engine as expression_clinical_association (imported, never duplicated).

Scope caveats (mirrored in the card): MUTATION status only (CN / fusion arms = follow-on); WT means
"MC3-profiled indication patient with no {target} mutation" (assumes MC3 coverage of the cohort);
univariate, unadjusted for stage/age, exploratory, multiple-testing-naive.
"""

from __future__ import annotations

# Single source of truth for the survival substrate + log-rank engine + thresholds. Referenced via
# the module (not `from ... import _CDR_LOAD_ERROR`) so the live post-call error value is read.
from onc_methods.expression_clinical_association import read as _eca
from onc_methods.gdc_somatic_hotspot.read import (
    _PER_SAMPLE_MAF_MANIFEST,
    _mc3_maf_path,
    _read_product_table,
)
from onc_methods.target_id_sidecar import ensure_aws_profile

MIN_EVENTS = _eca.MIN_EVENTS  # minimum deaths for a meaningful log-rank
MIN_PER_ARM = _eca.MIN_PER_ARM  # minimum patients per arm
SIGNIFICANCE_ALPHA = _eca.SIGNIFICANCE_ALPHA


def classify_alteration_survival_association(
    p, mutated_hazard_direction: int | None, n_events: int, n_mut: int, n_wt: int
) -> str:
    """Pure classifier — no I/O. mutated_hazard_direction: +1 = MUTATED arm has MORE hazard
    (worse survival), -1 = less, 0 = none."""
    if n_events < MIN_EVENTS or n_mut < MIN_PER_ARM or n_wt < MIN_PER_ARM:
        return "insufficient_survival_data"
    if p is None:
        return "data_unavailable"
    if p <= SIGNIFICANCE_ALPHA and mutated_hazard_direction == 1:
        return "alteration_mutated_worse_survival"
    if p <= SIGNIFICANCE_ALPHA and mutated_hazard_direction == -1:
        return "alteration_mutated_better_survival"
    return "no_survival_association"


def read_alteration_clinical_association(target: str, indication: str) -> dict:
    """Q11-alteration — OS log-rank by {target} mutation status for a (target, indication).
    Returns the association class + log-rank stats. data_unavailable-safe. Univariate/unadjusted."""
    ensure_aws_profile()
    sym = target.upper().strip()
    base = {
        "target": target,
        "indication": indication,
        "endpoint": "OS",
        "survival_source": "pancanatlas_tcga_cdr",
        "alteration_type": "somatic_mutation",
    }

    # 1) per-sample MC3 MAF for the indication. LOCAL-CACHE-FIRST then the registered S3 product
    #    (mirrors gdc_somatic_hotspot). cohort = MC3-profiled indication patients; altered = {target} mut.
    import pandas as pd

    maf_path = _mc3_maf_path(indication)
    maf = None
    if maf_path.exists():
        maf = pd.read_parquet(maf_path, columns=["sample_id", "gene_symbol"])
    else:
        table = _read_product_table(
            maf_path,
            _PER_SAMPLE_MAF_MANIFEST,
            filters=[("indication", "=", indication)],
            columns=["sample_id", "gene_symbol"],
        )
        if table is not None:
            maf = table.to_pandas()
    if maf is None or len(maf) == 0:
        base.update(
            {
                "alteration_survival_association_class": "data_unavailable",
                "_data_note": (
                    f"no per-sample MC3 MAF for {indication} "
                    f"(neither local {maf_path} nor {_PER_SAMPLE_MAF_MANIFEST} manifest/S3)"
                ),
            }
        )
        return base

    cohort_ids = {_eca._tcga_case(s) for s in maf["sample_id"].dropna()}
    altered_ids = {_eca._tcga_case(s) for s in maf.loc[maf["gene_symbol"] == sym, "sample_id"].dropna()}

    # 2) CDR OS. A missing dependency (openpyxl) is a BROKEN ENV, not a data gap — _load_cdr raises
    #    ImportError; catch it + report a DISTINCT note (the 2026-08-05 silent-survival bug class).
    try:
        cdr = _eca._load_cdr()
    except ImportError:
        base.update(
            {
                "alteration_survival_association_class": "data_unavailable",
                "_data_note": (
                    _eca._CDR_LOAD_ERROR
                    or "survival read dependency missing (install openpyxl in the run runtime) — NOT a data gap"
                ),
            }
        )
        return base
    if not cdr:
        base.update(
            {
                "alteration_survival_association_class": "data_unavailable",
                "_data_note": _eca._CDR_LOAD_ERROR or "TCGA-CDR survival table unavailable",
            }
        )
        return base

    # 3) arms over cohort ∩ patients-with-OS; log-rank mutated vs WT
    import numpy as np

    rows = [(c, (c in altered_ids), cdr[c][0], cdr[c][1]) for c in cohort_ids if c in cdr]
    base["n_patients"] = len(rows)
    mut = [(o, t) for _c, a, o, t in rows if a]
    wt = [(o, t) for _c, a, o, t in rows if not a]
    n_mut, n_wt = len(mut), len(wt)
    n_events = int(sum(o for _c, _a, o, _t in rows))
    if n_mut == 0 or n_wt == 0:
        base.update(
            {
                "alteration_survival_association_class": "insufficient_survival_data",
                "n_mutated": n_mut,
                "n_wildtype": n_wt,
                "n_events": n_events,
                "_data_note": f"cohort with OS has n_mutated={n_mut}, n_wildtype={n_wt}",
            }
        )
        return base

    mut_e = np.array([o for o, _t in mut], int)
    mut_t = np.array([t for _o, t in mut], float)
    wt_e = np.array([o for o, _t in wt], int)
    wt_t = np.array([t for _o, t in wt], float)
    # _logrank returns the hazard direction for group A; pass MUTATED as A → direction is the
    # mutated arm's (+1 = mutated worse, -1 = mutated better).
    chi2, p, mut_dir = _eca._logrank(mut_t, mut_e, wt_t, wt_e)
    cls = classify_alteration_survival_association(p, mut_dir, n_events, n_mut, n_wt)

    def _median_surv(arm):
        return round(float(np.median([t for _o, t in arm])), 1) if arm else None

    base.update(
        {
            "alteration_survival_association_class": cls,
            "logrank_p": float(f"{p:.3g}"),
            "logrank_chi2": round(float(chi2), 3),
            "n_events": n_events,
            "n_mutated": n_mut,
            "n_wildtype": n_wt,
            "mutated_hazard_direction": mut_dir,  # +1 worse, -1 better, 0 none
            "mutated_frequency": round(n_mut / (n_mut + n_wt), 4),
            "median_ostime_mutated_days": _median_surv(mut),
            "median_ostime_wildtype_days": _median_surv(wt),
        }
    )
    return base
