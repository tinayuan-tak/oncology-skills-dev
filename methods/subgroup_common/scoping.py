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

from pathlib import Path

import pandas as pd

from methods.subgroup_common.loaders import load_assignments


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
    """
    assignments = load_assignments(assignments_manifest_id, data_catalog_repo=data_catalog_repo)
    members = assignments.loc[
        (assignments["stratum_id"] == subgroup_id) & (assignments["is_member"] == True),
        "sample_id",
    ]
    member_set = set(members)
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
