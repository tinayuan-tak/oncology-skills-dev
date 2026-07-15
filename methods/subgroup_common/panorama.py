"""subgroup_common.panorama — substrate-agnostic panorama composer.

The "one shape" half of the "one shape, four layers" design. A subgroup
PANORAMA enumerates a target's evidence across the strata of one axis for
DESCRIPTIVE purposes: it shows the landscape (positive AND negative
stratifications), it does NOT emit signals or change a target verdict.

Every panorama has the SAME shape regardless of substrate (MAF frequency,
Chronos dependency, expression, prevalence):
  1. fan a per-sample reader out across `subgroups` (via @subgroup_iterable),
     collecting {stratum_id: per_stratum_record};
  2. project each per-stratum record → the card's flat `per_subgroup_metrics`
     record (the ONLY substrate-specific customization);
  3. reduce across strata to cross-stratum summary scalars.

This module owns steps 1 and 3 (identical for every card) plus the shared
statistical-rigor constants, so they are written and tested ONCE rather than
copy-pasted per (substrate × indication). A method keeps only its
substrate-specific reader + a small projection.

Shared rigor primitives (single source of truth — do NOT redefine per method):
  - SUBGROUP_N_FLOOR: the subgroup-n floor (mirrors the target-contracts
    rules-layer `min_n_required`); a stratum below it is rendered but flagged.
  - evidence_state(): the positive/negative/UNKNOWN trichotomy — a measured
    value on a floor-clearing cohort is trustworthy (a real negative is as
    valuable as a positive), distinct from an underpowered/absent unknown.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

# Subgroup-n floor. Mirrors the target-contracts subtype-rule `min_n_required`
# default (30). SINGLE SOURCE OF TRUTH — readers import this, never re-hardcode.
SUBGROUP_N_FLOOR = 30


def evidence_state(subgroup_n: int, floor_met: bool) -> str:
    """Positive/negative/UNKNOWN trichotomy for a stratum row.

    Returns:
      "measured"     — subgroup_n clears the floor; the metric is trustworthy
                       (whether the finding is positive OR a real negative)
      "underpowered" — evaluated but below the floor; treat as unknown
      "absent"       — no samples in this stratum ∩ the method cohort
    """
    if subgroup_n == 0:
        return "absent"
    return "measured" if floor_met else "underpowered"


# ---- Named cross-stratum reducers -----------------------------------------
# A card picks one. Each takes the list of projected records + the metric key
# and returns a dict of summary scalars merged into the panorama envelope.

def delta_reducer(records: list[dict], metric_key: str, label: str = "frequency") -> dict:
    """max/min/delta across strata for a single numeric metric (freq, dependency…).

    Only `measured`/`underpowered` records with a non-null metric contribute;
    `absent` strata are ignored in the spread but still counted in n_subgroups.
    """
    vals = [r[metric_key] for r in records
            if r.get(metric_key) is not None and r.get("evidence_state") != "absent"]
    return {
        f"n_subgroups_with_data": sum(1 for r in records if r.get("subgroup_n")),
        f"max_subgroup_{label}": (max(vals) if vals else None),
        f"min_subgroup_{label}": (min(vals) if vals else None),
        f"cross_subgroup_delta_{label}": (round(max(vals) - min(vals), 4) if vals else None),
    }


def build_panorama(
    reader: Callable,
    *,
    target: str,
    indication: str,
    subgroups: list[str],
    subgroup_assignments_manifest: str,
    record_projection: Callable[[str, dict], dict],
    reducer: Callable[[list[dict]], dict],
    subgroup_catalog_repo: Path | str | None = None,
    reader_kwargs: dict | None = None,
) -> dict:
    """Compose a descriptive per-subgroup panorama from a per-sample reader.

    Args:
      reader: a @subgroup_iterable-decorated per-sample reader with signature
        (target, indication, *, _sample_id_filter=None, **substrate_args). Fans
        out to {stratum_id: per_stratum_record} when called with subgroups=[...].
      record_projection: (stratum_id, per_stratum_record) → flat card record.
        The ONLY substrate-specific step. Must set at minimum
        {stratum, subgroup_n, subgroup_n_floor_met, evidence_state, source_cohort}.
      reducer: (list[projected_record]) → cross-stratum summary scalars dict.
        Use functools.partial(delta_reducer, metric_key=..., label=...).
      reader_kwargs: extra substrate args forwarded to the reader (e.g.
        {"maf_source": "genie_registry"}).

    Returns the card-shaped panorama envelope:
      {target, indication, per_subgroup_metrics: [record, ...], <summary scalars>}
    Purely descriptive — no signals.
    """
    per_stratum = reader(
        target, indication,
        subgroups=subgroups,
        subgroup_assignments_manifest=subgroup_assignments_manifest,
        subgroup_catalog_repo=subgroup_catalog_repo,
        **(reader_kwargs or {}),
    )
    records = [record_projection(stratum_id, rec) for stratum_id, rec in per_stratum.items()]
    envelope = {
        "target": target,
        "indication": indication,
        "per_subgroup_metrics": records,
    }
    envelope.update(reducer(records))
    return envelope
