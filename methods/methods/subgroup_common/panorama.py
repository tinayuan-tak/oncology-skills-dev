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
  - SUBGROUP_EXPLORATORY_FLOOR: the lower, hypothesis-grade band beneath it.
  - evidence_state(): the positive/negative/UNKNOWN grade — a measured
    value on a floor-clearing cohort is trustworthy (a real negative is as
    valuable as a positive), distinct from an underpowered/absent unknown, and
    distinct again from an UNEVALUABLE stratum nobody ever classified.
  - axis_quality(): the same distinctions rolled up to one grade for the axis.

Both grading primitives are ADDITIVE: called the historical way they return the
historical values, so a reader opts into the finer grades only once its card
declares them. See each docstring's byte-identity note.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

# Subgroup-n floor. Mirrors the target-contracts subtype-rule `min_n_required`
# default (30). SINGLE SOURCE OF TRUTH — readers import this, never re-hardcode.
SUBGROUP_N_FLOOR = 30

# Exploratory floor. A stratum at or above this but BELOW SUBGROUP_N_FLOOR is too thin
# for a scoped call yet large enough that discarding it loses real information. It is a
# SECOND, LOWER band — NOT a relaxation of SUBGROUP_N_FLOOR, which keeps its one meaning
# ("powered enough for a comparative claim") across every substrate. An `exploratory`
# stratum reports its distribution stats with a NULL signal and is excluded from every
# cross-stratum reducer exactly as `underpowered` is; the only thing that changes is
# that a consumer can now see it and say so. Opt-in per reader: pass
# `exploratory_floor=SUBGROUP_EXPLORATORY_FLOOR` to evidence_state().
#
# Why 10: the cell-line substrates are an order of magnitude smaller than the patient
# cohorts the floor of 30 was calibrated on (DepMap n≈20-130 per indication BEFORE the
# stratum split), so on that arm a floor of 30 rejects nearly every stratum. Measured
# 2026-09-18 on the landed DepMap shards, the 10-29 band is where the real information
# sits: coadread-cms CMS3 19 / CMS1 17, hnsc larynx 10, sclc SCLC_N 15. Those are
# hypothesis-grade, not claim-grade — which is precisely what a distinct grade says.
SUBGROUP_EXPLORATORY_FLOOR = 10


def evidence_state(
    subgroup_n: int,
    floor_met: bool,
    *,
    evaluated: bool | None = None,
    exploratory_floor: int | None = None,
) -> str:
    """Positive/negative/UNKNOWN grade for a stratum row.

    Called with the two positional arguments alone this is EXACTLY the historical
    trichotomy — same three return values for every input. The two keyword arguments are
    opt-in refinements; a reader that does not pass them is byte-identical, which is why
    the eight existing call sites and the nine cards that declare
    `evidence_state: {enum: [measured, underpowered, absent]}` need no coordinated change.
    A reader opts in only after its card declares the wider enum.

    Args:
      subgroup_n: members of this stratum ∩ the method cohort.
      floor_met: whether `subgroup_n` clears SUBGROUP_N_FLOOR. Passed in rather than
        recomputed because some readers apply an additional substrate-specific floor.
      evaluated: whether the assigner CLASSIFIED any sample for this stratum, from
        `scoping.stratum_evaluability(...).evaluated`. Consulted ONLY when
        `subgroup_n == 0`, where it separates the two facts that a 0 count conflates.
        Leave None to keep the historical behaviour (a 0 count reads as `absent`).
      exploratory_floor: enables the `exploratory` band. None disables it.

    Returns:
      "measured"     — subgroup_n clears the floor; the metric is trustworthy
                       (whether the finding is positive OR a real negative)
      "exploratory"  — `exploratory_floor` <= subgroup_n < floor: real samples, too few
                       for a scoped call. Hypothesis-grade; null signal, excluded from
                       cross-stratum reducers. Only emitted when `exploratory_floor` is set.
      "underpowered" — evaluated but below the exploratory band; treat as unknown
      "absent"       — the stratum was EVALUATED and has no members in this cohort.
                       A real measured negative: "we looked; nobody here qualifies."
      "unevaluable"  — no member and `evaluated=False`: nobody was ever classified, so
                       there is no absence to assert. Distinct from `absent` because
                       `absent` is a claim and this is an abstention. Only emitted when
                       `evaluated` is passed as False.
    """
    if subgroup_n == 0:
        # `evaluated is False` — not falsy — so the historical None default keeps
        # returning "absent" and only an explicit measurement of non-evaluation abstains.
        return "unevaluable" if evaluated is False else "absent"
    if floor_met:
        return "measured"
    if exploratory_floor is not None and subgroup_n >= exploratory_floor:
        return "exploratory"
    return "underpowered"


def axis_quality(records: list[dict], *, min_powered_strata: int = 2) -> str:
    """Roll the per-stratum `evidence_state` grades up to ONE axis-quality grade.

    `subtype_axis_available: True` alone is misleading — an axis can be defined for an
    indication yet be hollow (no stratum has members) or too thin to contrast (only ONE
    stratum clears the n-floor, e.g. NSCLC where only KRAS_G12C is powered). This grade
    lets a downstream card/skill/agent distinguish an ACTIONABLE subtype axis from a
    present-but-unusable one, WITHOUT changing any verdict.

    Grades (most→least usable):
      "powered"      — >= `min_powered_strata` strata clear the n-floor
                       (evidence_state == "measured"); comparative subtype claims
                       ("enriched in A vs B") are supportable.
      "exploratory"  — < `min_powered_strata` measured, but >= `min_powered_strata`
                       strata are measured OR `exploratory`: the axis is contrastable
                       as a HYPOTHESIS only. Reachable only from readers that enabled
                       the exploratory band.
      "underpowered" — the axis has samples but is not contrastable even as a hypothesis;
                       per-stratum reads are context only, not a selection axis.
      "unevaluable"  — NOTHING on this axis was classified: no stratum is measured,
                       exploratory or underpowered, and at least one is `unevaluable`.
                       Ranked ABOVE `empty` deliberately — `empty` asserts a measured
                       absence ("we looked, nobody qualifies") and there is no such
                       measurement here. Reachable only from readers that pass
                       `evaluated=` into evidence_state().
      "empty"        — every stratum was EVALUATED and none has members
                       (0 members ∩ the method cohort). A real negative about the axis.
      "unavailable"  — no records at all (no assignment shard / no subtype axis).

    `min_powered_strata` is deliberately reused as the contrastability threshold for the
    exploratory grade: whatever number of arms an axis needs to support a claim is the
    number it needs to support a hypothesis. One knob, not two.

    Substrate-agnostic: reads only `evidence_state`, which every panorama record carries,
    so it works identically for the tumor (case-grain) and cell-line (ModelID-grain)
    expression readers. Purely descriptive — emits no signal, moves no verdict.

    Byte-identical for records produced without the opt-in kwargs: with no `exploratory`
    state present `n_contrastable == n_measured`, and with no `unevaluable` state present
    the unevaluable branch cannot fire, leaving the original powered/empty/underpowered
    decision untouched.
    """
    if not records:
        return "unavailable"
    states = [r.get("evidence_state") for r in records]
    n_measured = sum(1 for s in states if s == "measured")
    if n_measured >= min_powered_strata:
        return "powered"
    n_contrastable = n_measured + sum(1 for s in states if s == "exploratory")
    if n_contrastable >= min_powered_strata:
        return "exploratory"
    # An unclassified axis must never be laundered into a measured absence. A mixed
    # unevaluable+absent axis grades `unevaluable`: the absent half is a real negative,
    # but it cannot carry an absence claim for the strata never examined.
    #
    # ORDER IS NOT WHAT ENFORCES THAT — the two predicates are DISJOINT, so swapping
    # these blocks is an equivalent mutant (verified exhaustively over all 251 state
    # multisets for k<=5: `empty` needs every state to be `absent`, which leaves no
    # `unevaluable` for the branch below, and vice versa). Do not re-file the swap as a
    # coverage hole. Order WOULD become load-bearing if the second condition were ever
    # weakened to a bare `any(s == "unevaluable")`, which is exactly the weakening to
    # refuse: it would let a single unclassified stratum mask a genuinely powered axis.
    if any(s == "unevaluable" for s in states) and not any(
        s in ("measured", "exploratory", "underpowered") for s in states
    ):
        return "unevaluable"
    if all(s == "absent" for s in states):
        return "empty"
    return "underpowered"


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
    ("MSI", re.compile(r"^(MSI([_-]?[HL])?|MSS)$", re.IGNORECASE)),
    ("CMS", re.compile(r"^CMS[1-4](_depmap)?$", re.IGNORECASE)),
    ("sidedness", re.compile(r"^(left|right)_sided$", re.IGNORECASE)),
    ("CIMP", re.compile(r"^CIMP", re.IGNORECASE)),
    ("stage", re.compile(r"^stage", re.IGNORECASE)),
    ("histology", re.compile(r"^histology", re.IGNORECASE)),
    ("HPV", re.compile(r"^HPV[_-]", re.IGNORECASE)),
    ("primary_site", re.compile(r"^site_", re.IGNORECASE)),
    ("PAM50", re.compile(r"^PAM50", re.IGNORECASE)),
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
    the cross-stratum spread. Every other grade is deliberately EXCLUDED — UNDERPOWERED
    strata (1 <= n < floor) and EXPLORATORY ones (exploratory_floor <= n < floor) alike:
    they are "inadmissible in comparative prose" per every panorama card's own caveat, so
    a single tiny-n stratum with an extreme value must not inflate cross_subgroup_delta_*
    nor trip a "subgroup-specific pattern" hint. The `measured`-only test is what keeps
    that true as grades are added: a new grade is excluded by DEFAULT rather than needing
    to be named in a growing deny-list. Sub-floor strata are still reported per-stratum
    (in per_subgroup_metrics) — they just do not drive the cross-stratum scalars.
    `n_subgroups_measured` counts the powered strata the spread is actually built from;
    `n_subgroups_with_data` is retained (all strata with a non-zero n) for context, and so
    also excludes an `unevaluable` stratum, whose n is 0.
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
        target,
        indication,
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
