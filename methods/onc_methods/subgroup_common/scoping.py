"""subgroup_common.scoping — sample-filtering primitives for Path-B iteration.

This module ships the small helper that Phase-3 methods use to filter their
source data down to samples belonging to a subgroup. It sits on top of
`subgroup_common.loaders.load_assignments()` (which is lru_cached) so
methods that iterate over N subgroups in a single invocation re-read the
resolver parquet ONCE, then call this filter N times with only in-memory ops.

This is the load-bearing Path-B primitive from the Phase-0d method-vs-
dispatcher verdict. See target-contracts/docs/design/IDAS_SUBTYPE_PIPELINE.md.

Typical use in a Phase-3 method:

    def read_dge_gene_row(
        target: str,
        manifest_id: str,
        subgroups: list[str] | None = None,
        subgroup_assignments_manifest: str | None = None,
    ) -> dict | dict[str, dict]:
        table = pq.read_table(path, filters=[("gene_symbol", "=", target)])
        if subgroups is None:
            return _row_to_card_fields(table, manifest_id)
        # Path-B iteration
        return {
            s: _row_to_card_fields(
                filter_samples_by_subgroup(
                    table.to_pandas(),
                    sample_id_col="Tumor_Sample_Barcode",
                    subgroup_id=s,
                    assignments_manifest_id=subgroup_assignments_manifest,
                ),
                manifest_id,
            )
            for s in subgroups
        }
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from onc_methods.subgroup_common.loaders import load_assignments


@dataclass(frozen=True)
class JoinCoverage:
    """Diagnostic for a subgroup member-set ↔ method-data join.

    The load-bearing guard against silent sample-id-convention mismatch
    (provenance-audit Finding 5): a bare `.isin()` that drops 100% of rows
    because the assignment's `sample_id` is patient-level (TCGA-XX-XXXX) while
    the method keys on full aliquot barcode (TCGA-XX-XXXX-01A-...) looks
    identical to "nobody is a member." This makes the difference observable.

    Fields:
      subgroup_id:        the stratum being joined
      n_members:          members with is_member==True in the assignments
      n_matched:          members present in the method's own data
      n_assignment_only:  members absent from the method data (expected if the
                          method cohort is a subset — e.g. MAF covers fewer
                          samples than the marker-paper — but a red flag at ~0)
      match_rate:         n_matched / n_members (None if n_members == 0)
      id_convention_warning: True when match_rate is suspiciously low given a
                          non-empty member set — the signature of an id mismatch
    """

    subgroup_id: str
    n_members: int
    n_matched: int
    n_assignment_only: int
    match_rate: float | None
    id_convention_warning: bool


# Below this match rate (with a non-empty member set) we suspect an id-convention
# mismatch rather than a legitimate cohort subset. Deliberately low: legitimate
# subsetting (MAF ⊂ marker-paper) commonly lands at 0.3-0.8; a true convention
# mismatch lands at ~0.0.
_MATCH_RATE_FLOOR = 0.05


@dataclass(frozen=True)
class StratumEvaluability:
    """The EVALUABILITY DENOMINATOR of a stratum — what `is_member == True` discards.

    Every filter in this module keeps `is_member == True` and drops the rest, which
    collapses the tri-valued assignment into a binary and makes two very different
    facts indistinguishable downstream:

      * "we classified these samples and NONE is a member"   → a measured absence
      * "we never classified these samples"                  → an ABSTENTION

    Both arrive at the panorama as `subgroup_n == 0`, and `panorama.evidence_state`
    then labels both `absent`, which `axis_quality` rolls up to `empty` — "the axis is
    defined but every stratum has 0 members". For an all-null shard that grade is a
    FALSE ABSENCE ASSERTION. Measured 2026-09-18: the DepMap paad and stad assignment
    shards are 100% `is_member = None`, i.e. no cell line was ever classified; they were
    being reported as empty axes. The assigner already emits the honest tri-value (the
    unevaluable-rule convention: a predicate whose source cannot answer must abstain,
    not answer False) — it was being thrown away two layers later.

    This dataclass carries the denominator forward so `evidence_state(..., evaluated=)`
    can separate the two. It is DESCRIPTIVE: it changes no filter and no member set.

    Fields:
      subgroup_id:      the stratum described
      n_member:         rows with is_member is True  (the member set; == len(cohort))
      n_non_member:     rows with is_member is False (EVALUATED, not a member)
      n_abstained:      rows with is_member null     (NOT evaluated — the abstentions)
      n_unrecognized:   rows whose is_member is neither a recognised boolean nor null
                        (e.g. the string "false" from a mis-typed parquet column).
                        Folded into the abstention side of `evaluated` — an
                        uninterpretable value is not evidence of evaluation — and
                        surfaced separately so the cause stays legible instead of
                        silently inflating n_abstained.
      n_rows:           total assignment rows for this stratum (the partition closes:
                        n_member + n_non_member + n_abstained + n_unrecognized)
    """

    subgroup_id: str
    n_member: int
    n_non_member: int
    n_abstained: int
    n_unrecognized: int
    n_rows: int

    @property
    def n_evaluated(self) -> int:
        """Rows the assigner actually reached a verdict on (member OR non-member)."""
        return self.n_member + self.n_non_member

    @property
    def evaluated(self) -> bool:
        """True when at least one sample was CLASSIFIED for this stratum.

        The load-bearing flag: `evaluated == False` with `n_member == 0` means the
        stratum is UNEVALUABLE, not empty. Pass it to
        `panorama.evidence_state(..., evaluated=...)`.
        """
        return self.n_evaluated > 0

    @property
    def abstention_rate(self) -> float | None:
        """Fraction of rows the assigner abstained on (None when no rows)."""
        if not self.n_rows:
            return None
        return (self.n_abstained + self.n_unrecognized) / self.n_rows


def compute_join_coverage(
    df: pd.DataFrame,
    sample_id_col: str,
    subgroup_id: str,
    assignments_manifest_id: str,
    data_catalog_repo: Path | None = None,
    warn: bool = True,
) -> JoinCoverage:
    """Report how well a subgroup member-set joins to a method's data.

    Call this (or use filter_samples_by_subgroup, which calls it internally)
    before computing a per-stratum statistic. Emits a JoinCoverage diagnostic
    and, when `warn`, raises a UserWarning on a near-zero match rate so an
    id-convention mismatch surfaces instead of masquerading as an empty stratum.
    """
    assignments = load_assignments(assignments_manifest_id, data_catalog_repo=data_catalog_repo)
    members = set(
        assignments.loc[
            (assignments["stratum_id"] == subgroup_id) & (assignments["is_member"] == True),
            "sample_id",
        ]
    )
    data_ids = set(df[sample_id_col].dropna())
    matched = members & data_ids
    n_members = len(members)
    match_rate = (len(matched) / n_members) if n_members else None
    id_warn = bool(n_members and match_rate is not None and match_rate < _MATCH_RATE_FLOOR)
    if id_warn and warn:
        warnings.warn(
            f"subgroup '{subgroup_id}': only {len(matched)}/{n_members} members "
            f"({match_rate:.1%}) matched column '{sample_id_col}'. This is the "
            f"signature of a sample-id-convention mismatch (e.g. patient-barcode "
            f"assignments vs full-aliquot method data), NOT necessarily an empty "
            f"stratum. Check id normalization before trusting per-stratum stats.",
            UserWarning,
            stacklevel=2,
        )
    return JoinCoverage(
        subgroup_id=subgroup_id,
        n_members=n_members,
        n_matched=len(matched),
        n_assignment_only=n_members - len(matched),
        match_rate=match_rate,
        id_convention_warning=id_warn,
    )


def filter_samples_by_subgroup(
    df: pd.DataFrame,
    sample_id_col: str,
    subgroup_id: str,
    assignments_manifest_id: str,
    data_catalog_repo: Path | None = None,
) -> pd.DataFrame:
    """Filter a DataFrame to samples with `is_member == True` for a given subgroup.

    Args:
      df: the source DataFrame to filter (any shape — MAF rows, expression
        rows, etc. — as long as it has a sample-id column).
      sample_id_col: name of the column in `df` that carries the canonical
        sample identifier (e.g. "Tumor_Sample_Barcode", "ModelID",
        "sample_id"). The resolver product always uses "sample_id"; this
        argument lets callers map between their own conventions.
      subgroup_id: the stratum id to filter on (e.g. "MSI_H", "KRAS_G12C").
      assignments_manifest_id: id of the derived subgroup-assignments
        manifest to consume (e.g. "tcga-subgroup-assignments-coadread-v1").
      data_catalog_repo: path to the data-catalog repo. If None, uses the
        canonical SageMaker path.

    Returns:
      Subset of `df` with only rows whose sample_id belongs to the subgroup.

    Semantics:
      - is_member=True → sample INCLUDED
      - is_member=False → sample EXCLUDED (evaluated, not a member)
      - is_member=null OR row-absent in assignments → sample EXCLUDED
        (method-level filter conservatively excludes)

    The False and null cases are indistinguishable in the RESULT, and that erasure is
    not recoverable downstream — an all-null stratum and a genuinely 0-member stratum
    both arrive as an empty frame, and the panorama then grades the whole axis `empty`,
    which asserts a measured absence that was never measured. Callers that report a
    per-stratum evidence grade must therefore ALSO read `stratum_evaluability()` and
    pass `.evaluated` into `panorama.evidence_state(..., evaluated=...)`. The filter
    stays binary on purpose; only the REPORTING needs the third value.

    Emits a JoinCoverage diagnostic (via compute_join_coverage) so a near-zero
    match rate from a sample-id-convention mismatch surfaces as a warning rather
    than a silently-empty result.
    """
    assignments = load_assignments(assignments_manifest_id, data_catalog_repo=data_catalog_repo)
    members = assignments.loc[
        (assignments["stratum_id"] == subgroup_id) & (assignments["is_member"] == True),
        "sample_id",
    ]
    member_set = set(members)
    # Guard the join: warns on the id-convention-mismatch signature (Finding 5).
    compute_join_coverage(df, sample_id_col, subgroup_id, assignments_manifest_id, data_catalog_repo=data_catalog_repo)
    return df[df[sample_id_col].isin(member_set)].copy()


def resolve_subgroup_cohort(
    assignments_manifest_id: str,
    subgroup_id: str,
    data_catalog_repo: Path | None = None,
) -> set[str]:
    """Return the set of sample_ids belonging to a subgroup.

    Alternative to filter_samples_by_subgroup() when the caller just needs
    the sample ID set (e.g., for cohort-size checks before running a method).
    """
    assignments = load_assignments(assignments_manifest_id, data_catalog_repo=data_catalog_repo)
    members = assignments.loc[
        (assignments["stratum_id"] == subgroup_id) & (assignments["is_member"] == True),
        "sample_id",
    ]
    return set(members)


def stratum_evaluability(
    assignments_manifest_id: str,
    subgroup_id: str,
    data_catalog_repo: Path | None = None,
    *,
    warn: bool = True,
) -> StratumEvaluability:
    """Partition a stratum's assignment rows into member / non-member / ABSTAINED.

    The companion to `resolve_subgroup_cohort`, which answers "who is a member" and
    cannot distinguish an empty stratum from an unclassified one. See
    `StratumEvaluability` for why that distinction is load-bearing.

    Read this ONCE per stratum alongside the cohort and pass `.evaluated` into
    `panorama.evidence_state(subgroup_n, floor_met, evaluated=...)`. `load_assignments`
    is lru_cached, so this adds no I/O to a reader that already resolved the cohort.

    The partition is EXHAUSTIVE by construction: rows are bucketed by
    `is_member is True` / `is_member is False` / null / everything-else, and the four
    counts are asserted to sum to the row count. The residual bucket exists because the
    column is object-dtype in the shipped parquet — a value stored as the STRING
    "false" satisfies neither `== False` nor `isna()`, so a three-way split would drop
    it silently and under-report the denominator. Verified 2026-09-18 against the live
    tcga / depmap / cptac COADREAD shards: all three close exactly with 0 unrecognized.

    Args:
      assignments_manifest_id: the derived subgroup-assignments manifest id.
      subgroup_id: the stratum id (e.g. "MSI_H", "CMS4").
      data_catalog_repo: path to the data-catalog repo (None → canonical path).
      warn: emit a UserWarning when unrecognised `is_member` values are present.

    Returns:
      StratumEvaluability for `subgroup_id` (all-zero when the stratum id is absent
      from the shard — which is itself `evaluated == False`, i.e. unevaluable).
    """
    assignments = load_assignments(assignments_manifest_id, data_catalog_repo=data_catalog_repo)
    rows = assignments.loc[assignments["stratum_id"] == subgroup_id, "is_member"]
    n_rows = len(rows)
    # `is` comparisons on the object column: identity-safe for Python True/False and
    # unaffected by pandas' `== True` coercion of truthy non-booleans (e.g. 1, "yes").
    n_member = int(sum(1 for v in rows if v is True))
    n_non_member = int(sum(1 for v in rows if v is False))
    n_abstained = int(rows.isna().sum())
    n_unrecognized = n_rows - n_member - n_non_member - n_abstained
    if n_unrecognized and warn:
        offenders = sorted({repr(v) for v in rows if v is not True and v is not False and not pd.isna(v)})[:5]
        warnings.warn(
            f"subgroup '{subgroup_id}' in '{assignments_manifest_id}': {n_unrecognized} of "
            f"{n_rows} `is_member` values are neither a boolean nor null (e.g. {', '.join(offenders)}). "
            f"They are counted as NOT evaluated (an uninterpretable value is not evidence of "
            f"evaluation), so the stratum may grade `unevaluable` rather than `absent`. This is the "
            f"signature of a mis-typed assignments column — fix the shard, do not widen the parser.",
            UserWarning,
            stacklevel=2,
        )
    return StratumEvaluability(
        subgroup_id=subgroup_id,
        n_member=n_member,
        n_non_member=n_non_member,
        n_abstained=n_abstained,
        n_unrecognized=n_unrecognized,
        n_rows=n_rows,
    )


def cohort_size(
    assignments_manifest_id: str,
    subgroup_id: str,
    data_catalog_repo: Path | None = None,
) -> int:
    """Return the number of sample_ids in a subgroup.

    Used by subgroup-n-floor discipline (target-contracts rules layer
    requires subgroup_n as a required field on subtype-tier rules).
    """
    return len(resolve_subgroup_cohort(assignments_manifest_id, subgroup_id, data_catalog_repo))
