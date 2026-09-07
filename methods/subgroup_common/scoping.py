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

from methods.subgroup_common.loaders import load_assignments


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
        (tri-value insufficient → downstream synthesis handles this;
        method-level filter conservatively excludes)

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
