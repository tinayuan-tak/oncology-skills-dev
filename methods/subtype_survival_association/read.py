"""read_subtype_survival_association — omnibus OS log-rank ACROSS an indication's molecular subtypes.

The SUBTYPE arm of the prognostic question (differentiation Q2): does overall survival differ across
{indication}'s molecular subtypes? INDICATION-level (target-independent) — a HYPOTHESIS-GENERATING
prognostic association for the biomarker/patient-selection facet, NOT a clinical claim.

  - subtype_stratifies_survival        → survival differs significantly across subtypes (omnibus
      k-group log-rank p <= alpha, with >= 2 admissible strata).
  - no_subtype_survival_association     → no significant cross-subtype survival difference.
  - insufficient_survival_data          → < 2 strata clear the per-arm floor, or too few events.
  - data_unavailable                    → no assignment shard or no survival substrate.

ZERO new ingestion — reuses:
  - a TCGA-side subgroup-assignment shard (patient-barcode-keyed, e.g. tcga-maf-subgroup-assignments-
    coadread-v1) via subgroup_common.load_assignments → per-stratum member patients.
  - PanCanAtlas TCGA-CDR (Liu 2018) OS/OS.time + the self-contained log-rank engine from
    expression_clinical_association (extended here to the k-group omnibus form).

Scope caveats (mirrored in the card): univariate, unadjusted for stage/age; strata below the per-arm
floor are dropped from the omnibus test (reported); a subtype that is intrinsically small stays
insufficient rather than forcing a claim.
"""
from __future__ import annotations

# Reuse the survival substrate + thresholds + barcode canonicalizer (single source of truth).
from methods.expression_clinical_association import read as _eca
from methods.subgroup_common.loaders import load_assignments
from methods.target_id_sidecar import ensure_aws_profile

MIN_EVENTS = _eca.MIN_EVENTS          # minimum total deaths for a meaningful omnibus test
MIN_PER_ARM = _eca.MIN_PER_ARM        # minimum patients per subtype arm to be admissible
SIGNIFICANCE_ALPHA = _eca.SIGNIFICANCE_ALPHA

# Indication → the TCGA-side SUBTYPE subgroup-assignment shard (patient-barcode-keyed) carrying the
# molecular-subtype strata (CMS/MSI/sidedness/etc.). When the caller passes no explicit manifest,
# resolve it here so a card can invoke this reader with just {indication} — mirroring the way the
# other subtype cards resolve a shard from subgroup_spec rather than a literal manifest id.
INDICATION_TO_TCGA_SUBTYPE_SHARD = {
    "COADREAD": "tcga-subgroup-assignments-coadread-v1",
    "COAD": "tcga-subgroup-assignments-coadread-v1",
    "READ": "tcga-subgroup-assignments-coadread-v1",
    "NSCLC": "tcga-subgroup-assignments-nsclc-v1",
    "ESCA": "tcga-subgroup-assignments-esca-v1",
    "HNSC": "tcga-subgroup-assignments-hnsc-v1",
    "PAAD": "tcga-subgroup-assignments-paad-v1",
    "PDAC": "tcga-subgroup-assignments-paad-v1",
}


def multivariate_logrank(arms: list[tuple]) -> tuple:
    """Omnibus (k-group) log-rank test from primitives — no lifelines.

    arms: list of (times, events) per group (events ∈ {0,1}; censored = 0). Returns
    (chi2, p, df). Uses the standard Mantel-Haenszel observed-minus-expected vector O-E with the
    multivariate hypergeometric covariance V; chi2 = z' V+ z over k-1 groups (drop one for full
    rank), df = k-1. Reduces to the 2-group log-rank for k=2.
    """
    import numpy as np
    from scipy import stats

    arms = [(np.asarray(t, float), np.asarray(e, int)) for t, e in arms if len(t)]
    k = len(arms)
    if k < 2:
        return 0.0, 1.0, 0
    t_all = np.concatenate([t for t, _e in arms])
    e_all = np.concatenate([e for _t, e in arms])
    grp = np.concatenate([np.full(len(t), g) for g, (t, _e) in enumerate(arms)])

    event_times = np.unique(t_all[e_all == 1])
    O = np.zeros(k)
    E = np.zeros(k)
    V = np.zeros((k, k))
    for tj in event_times:
        at_risk = t_all >= tj
        n = at_risk.sum()
        if n <= 1:
            continue
        d = int(((t_all == tj) & (e_all == 1)).sum())          # total deaths at tj
        n_g = np.array([((grp == g) & at_risk).sum() for g in range(k)], float)
        d_g = np.array([((grp == g) & (t_all == tj) & (e_all == 1)).sum() for g in range(k)], float)
        O += d_g
        E += d * (n_g / n)
        # multivariate hypergeometric covariance
        factor = d * (n - d) / (n - 1)
        for g in range(k):
            for h in range(k):
                delta = 1.0 if g == h else 0.0
                V[g, h] += factor * (n_g[g] / n) * (delta - n_g[h] / n)

    z = (O - E)[:-1]                # drop the last group for a full-rank system
    Vr = V[:-1, :-1]
    try:
        chi2 = float(z @ np.linalg.pinv(Vr) @ z)
    except Exception:  # noqa: BLE001 — singular (e.g. one arm carries all events) → no test
        return 0.0, 1.0, k - 1
    df = k - 1
    p = float(stats.chi2.sf(chi2, df=df))
    return chi2, p, df


def classify_subtype_survival_association(p, n_admissible_strata: int, n_events: int) -> str:
    """Pure classifier — no I/O."""
    if n_admissible_strata < 2 or n_events < MIN_EVENTS:
        return "insufficient_survival_data"
    if p is None:
        return "data_unavailable"
    if p <= SIGNIFICANCE_ALPHA:
        return "subtype_stratifies_survival"
    return "no_subtype_survival_association"


def read_subtype_survival_association(indication: str, subgroup_assignments_manifest: str | None = None,
                                      data_catalog_repo=None) -> dict:
    """Omnibus OS log-rank across {indication}'s molecular subtypes (from a TCGA-side assignment
    shard). data_unavailable-safe. Univariate/unadjusted. target-independent (indication-level).

    subgroup_assignments_manifest: the TCGA-side subtype shard id. When None, resolved from
    INDICATION_TO_TCGA_SUBTYPE_SHARD (so a card passes only {indication}); an indication with no
    registered subtype shard returns data_unavailable rather than raising."""
    ensure_aws_profile()
    if subgroup_assignments_manifest is None:
        subgroup_assignments_manifest = INDICATION_TO_TCGA_SUBTYPE_SHARD.get(str(indication).upper())
    base = {"indication": indication, "endpoint": "OS", "survival_source": "pancanatlas_tcga_cdr",
            "subgroup_assignments_manifest": subgroup_assignments_manifest}
    if not subgroup_assignments_manifest:
        base.update({"subtype_survival_association_class": "data_unavailable",
                     "_data_note": f"no TCGA subtype subgroup-assignment shard registered for {indication}"})
        return base

    # 1) per-stratum member patients from the assignment shard
    try:
        asg = load_assignments(subgroup_assignments_manifest, data_catalog_repo=data_catalog_repo)
    except Exception as e:  # noqa: BLE001 — shard genuinely unresolvable → honest data_unavailable
        base.update({"subtype_survival_association_class": "data_unavailable",
                     "_data_note": f"assignment shard unresolvable: {type(e).__name__}"})
        return base
    if asg is None or len(asg) == 0:
        base.update({"subtype_survival_association_class": "data_unavailable",
                     "_data_note": f"no assignments in {subgroup_assignments_manifest}"})
        return base

    members = asg[asg["is_member"] == True]  # noqa: E712
    # patient barcode: prefer patient_id, fall back to sample_id (both 3-segment for TCGA shards)
    id_col = "patient_id" if members["patient_id"].notna().any() else "sample_id"
    strata = {sid: {_eca._tcga_case(x) for x in grp[id_col].dropna()}
              for sid, grp in members.groupby("stratum_id")}

    # 2) CDR OS (broken-env ImportError surfaces distinctly, not a data gap)
    try:
        cdr = _eca._load_cdr()
    except ImportError:
        base.update({"subtype_survival_association_class": "data_unavailable",
                     "_data_note": (_eca._CDR_LOAD_ERROR or "survival read dependency missing (openpyxl)")})
        return base
    if not cdr:
        base.update({"subtype_survival_association_class": "data_unavailable",
                     "_data_note": _eca._CDR_LOAD_ERROR or "TCGA-CDR survival table unavailable"})
        return base

    # 3) build per-stratum arms over patients-with-OS; keep only strata clearing the per-arm floor
    import numpy as np
    arms, per_stratum, dropped, n_events = [], [], [], 0
    for sid, ids in sorted(strata.items()):
        pairs = [cdr[c] for c in ids if c in cdr]
        if len(pairs) >= MIN_PER_ARM:
            times = np.array([t for _o, t in pairs], float)
            events = np.array([o for o, _t in pairs], int)
            arms.append((times, events))
            n_events += int(events.sum())
            per_stratum.append({"stratum": sid, "n": len(pairs), "n_events": int(events.sum()),
                                "median_ostime_days": round(float(np.median(times)), 1)})
        elif pairs:
            dropped.append({"stratum": sid, "n": len(pairs), "reason": "below_per_arm_floor"})

    n_admissible = len(arms)
    base["n_admissible_strata"] = n_admissible
    base["per_stratum"] = per_stratum
    if dropped:
        base["dropped_underpowered_strata"] = dropped
    if n_admissible < 2:
        base.update({"subtype_survival_association_class": "insufficient_survival_data",
                     "_data_note": f"only {n_admissible} strata clear the per-arm floor of {MIN_PER_ARM}"})
        return base

    chi2, p, df = multivariate_logrank(arms)
    cls = classify_subtype_survival_association(p, n_admissible, n_events)
    base.update({
        "subtype_survival_association_class": cls,
        "logrank_p": float(f"{p:.3g}"),
        "logrank_chi2": round(float(chi2), 3),
        "logrank_df": df,
        "n_events": n_events,
        "n_patients": sum(s["n"] for s in per_stratum),
    })
    return base
