"""Pure roll-up + classifier for spatial region-RNA abundance (no S3).

Consumes per-(gene, donor, compartment) rows from spatial-region-rna-{indication}-v1 (GeoMx DSP WTA)
and rolls them up DONOR-is-replicate (cross-donor median) to a tumour-vs-TME compartment abundance
summary + a primary `spatial_rna_class`. abundance_lcpm is a normalized log-scale RNA signal (region-
level), so the decision-relevant readout is the COMPARTMENT DIFFERENTIAL (tumour vs microenvironment),
not an absolute cutoff.
"""

from __future__ import annotations

_TUMOUR = "TUMOUR"
_TME = "TME"
_ENRICHED_DELTA = 0.5  # log-scale margin: |tumour - TME| >= => compartment-enriched


def _median(xs):
    xs = sorted(v for v in xs if v is not None)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def summarize_rna(rows) -> dict:
    """rows: dicts with donor_id, compartment, abundance_lcpm, detected. Returns cross-donor median
    abundance per compartment + provenance. Empty dict if no rows."""
    rows = list(rows)
    if not rows:
        return {}
    by_comp: dict[str, list] = {}
    det = False
    donors = set()
    for r in rows:
        by_comp.setdefault(str(r["compartment"]), []).append(r.get("abundance_lcpm"))
        det = det or bool(r.get("detected"))
        donors.add(str(r["donor_id"]))
    return {
        "compartment_abundance": {c: _median(v) for c, v in by_comp.items()},
        "detected": det,
        "n_donors": len(donors),
    }


def classify_region_rna(summ: dict, rows) -> dict:
    """Primary spatial_rna_class from the tumour-vs-TME compartment differential."""
    rows = list(rows)
    if not summ:
        return {
            "spatial_rna_class": "data_unavailable",
            "tumour_abundance_lcpm": None,
            "tme_abundance_lcpm": None,
            "tumour_vs_tme_delta": None,
            "detected_tumour": None,
            "n_donors": 0,
            "n_datasets": 0,
        }
    ca = summ["compartment_abundance"]
    tum = ca.get(_TUMOUR)
    tme = ca.get(_TME)
    delta = round(tum - tme, 4) if (tum is not None and tme is not None) else None
    if tum is None:
        cls = "data_unavailable"
    elif delta is None:
        cls = "tumour_present_no_compartment_preference"
    elif delta >= _ENRICHED_DELTA:
        cls = "tumour_enriched_rna"  # RNA concentrated in the tumour compartment
    elif delta <= -_ENRICHED_DELTA:
        cls = "tme_enriched_rna"  # RNA concentrated in the microenvironment (specificity caveat)
    else:
        cls = "tumour_present_no_compartment_preference"
    return {
        "spatial_rna_class": cls,
        "tumour_abundance_lcpm": round(tum, 4) if tum is not None else None,
        "tme_abundance_lcpm": round(tme, 4) if tme is not None else None,
        "tumour_vs_tme_delta": delta,
        "detected_tumour": bool(summ.get("detected")),
        "n_donors": summ.get("n_donors", 0),
        "n_datasets": 1 if rows else 0,  # single GeoMx WTA dataset per indication (region-RNA)
    }
