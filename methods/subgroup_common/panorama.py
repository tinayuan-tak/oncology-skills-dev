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

import re
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


def axis_quality(records: list[dict], *, min_powered_strata: int = 2) -> str:
    """Roll the per-stratum `evidence_state` trichotomy up to ONE axis-quality grade.

    `subtype_axis_available: True` alone is misleading — an axis can be defined for an
    indication yet be hollow (every stratum empty, e.g. DepMap STAD/PAAD) or too thin to
    contrast (only ONE stratum clears the n-floor, e.g. NSCLC where only KRAS_G12C is
    powered). This grade lets a downstream card/skill/agent distinguish an ACTIONABLE
    subtype axis from a present-but-unusable one, WITHOUT changing any verdict.

    Grades (most→least usable):
      "powered"      — >= `min_powered_strata` strata clear the n-floor
                       (evidence_state == "measured"); comparative subtype claims
                       ("enriched in A vs B") are supportable.
      "underpowered" — the axis has samples but < `min_powered_strata` measured strata;
                       per-stratum reads are context only, not a selection axis.
      "empty"        — the axis is defined but every stratum is `absent`
                       (0 members ∩ the method cohort).
      "unavailable"  — no records at all (no assignment shard / no subtype axis).

    Substrate-agnostic: reads only `evidence_state`, which every panorama record carries,
    so it works identically for the tumor (case-grain) and cell-line (ModelID-grain)
    expression readers. Purely descriptive — emits no signal, moves no verdict.
    """
    if not records:
        return "unavailable"
    states = [r.get("evidence_state") for r in records]
    if all(s == "absent" for s in states):
        return "empty"
    n_measured = sum(1 for s in states if s == "measured")
    return "powered" if n_measured >= min_powered_strata else "underpowered"


# ---- Orthogonal subtype AXES ----------------------------------------------
# A molecular-subtype assignment shard packs strata from SEVERAL ORTHOGONAL axes.
# For COADREAD the 14 strata span 5 axes (MSI, CMS, sidedness, CIMP, stage), and a
# single patient is a member of ~one arm PER axis (MSI_H AND CMS2 AND left_sided AND
# CIMP_Neg AND stage_II). So the per-stratum ROWS legitimately share samples, but any
# CROSS-stratum OMNIBUS (k-group log-rank, Kruskal-Wallis) MUST be run per-axis over
# that axis's DISJOINT arms: pooling arms from different axes replicates each sample
# ~n_axes times, inflating N and violating the test's independent-groups assumption
# (the whole test statistic becomes uninterpretable).
#
# `stratum_axis` maps a stratum_id → its axis. Strata we are not CONFIDENT share an
# axis fall back to a SINGLETON axis (the stratum_id itself): the safe direction is
# UNDER-pooling (a singleton axis is simply never tested) rather than a false pooled
# test across biologically unrelated partitions. `disjoint_arms` is the second safety
# net — it verifies actual membership disjointness WITHIN an axis (e.g. it drops the
# composite `stage_resectable`, which is a superset of stage_I ∪ stage_II).

_AXIS_RULES: list[tuple[str, "re.Pattern[str]"]] = [
    ("MSI",           re.compile(r"^(MSI([_-]?[HL])?|MSS)$", re.IGNORECASE)),
    ("CMS",           re.compile(r"^CMS[1-4](_depmap)?$", re.IGNORECASE)),
    ("sidedness",     re.compile(r"^(left|right)_sided$", re.IGNORECASE)),
    ("CIMP",          re.compile(r"^CIMP", re.IGNORECASE)),
    ("stage",         re.compile(r"^stage", re.IGNORECASE)),
    ("histology",     re.compile(r"^histology", re.IGNORECASE)),
    ("HPV",           re.compile(r"^HPV[_-]", re.IGNORECASE)),
    ("primary_site",  re.compile(r"^site_", re.IGNORECASE)),
    ("PAM50",         re.compile(r"^PAM50", re.IGNORECASE)),
    ("molecular_subtype", re.compile(r"^subtype_", re.IGNORECASE)),
]


def stratum_axis(stratum_id: str) -> str:
    """Map a stratum_id to its ORTHOGONAL subtype axis (single source of truth).

    Returns a canonical axis label for the known molecular-subtype partitions
    (MSI / CMS / sidedness / CIMP / stage / histology / HPV / primary_site / PAM50 /
    molecular_subtype). An unrecognised stratum returns its OWN id as a singleton axis
    — the deliberately conservative default, so it is never falsely pooled into a
    cross-axis omnibus (a singleton axis has <2 arms and is simply not tested).
    """
    s = str(stratum_id)
    for axis, rx in _AXIS_RULES:
        if rx.match(s):
            return axis
    return s


def partition_axes(strata) -> dict[str, list[str]]:
    """Group stratum_ids by axis → {axis: [stratum_id, ...]} (sorted, deterministic)."""
    out: dict[str, list[str]] = {}
    for sid in sorted(strata):
        out.setdefault(stratum_axis(sid), []).append(sid)
    return out


def disjoint_arms(axis_strata, member_sets: dict) -> tuple[list, list]:
    """Reduce one axis's arms to a mutually-DISJOINT subset by member overlap.

    Even within a single axis, arms can overlap (e.g. the composite `stage_resectable`
    is a superset of stage_I and stage_II). Greedily keep arms in sorted id order,
    dropping any arm that shares a member with an already-kept arm.

    Args:
      axis_strata: stratum_ids belonging to one axis.
      member_sets: {stratum_id: set(member id)} — the sample/patient ids in each arm.
    Returns:
      (kept, dropped) stratum-id lists. `kept` are pairwise-disjoint.
    """
    kept, dropped, seen = [], [], set()
    for sid in sorted(axis_strata):
        ms = member_sets.get(sid) or set()
        if ms & seen:
            dropped.append(sid)
        else:
            kept.append(sid)
            seen |= set(ms)
    return kept, dropped


# ---- Named cross-stratum reducers -----------------------------------------
# A card picks one. Each takes the list of projected records + the metric key
# and returns a dict of summary scalars merged into the panorama envelope.

def delta_reducer(records: list[dict], metric_key: str, label: str = "frequency") -> dict:
    """max/min/delta across strata for a single numeric metric (freq, dependency…).

    Only POWERED (`evidence_state == "measured"`) records with a non-null metric drive
    the cross-stratum spread. UNDERPOWERED strata (1 <= n < floor) are deliberately
    EXCLUDED: they are "inadmissible in comparative prose" per every panorama card's own
    caveat, so a single tiny-n stratum with an extreme value must not inflate
    cross_subgroup_delta_* nor trip a "subgroup-specific pattern" hint. Underpowered
    strata are still reported per-stratum (in per_subgroup_metrics) — they just do not
    drive the cross-stratum scalars. `n_subgroups_measured` counts the powered strata the
    spread is actually built from; `n_subgroups_with_data` is retained (all non-empty
    strata) for context.
    """
    measured = [r for r in records if r.get("evidence_state") == "measured"]
    vals = [r[metric_key] for r in measured if r.get(metric_key) is not None]
    return {
        "n_subgroups_with_data": sum(1 for r in records if r.get("subgroup_n")),
        "n_subgroups_measured": len(vals),
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
