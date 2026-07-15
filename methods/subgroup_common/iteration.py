"""subgroup_common.iteration — Path-B method-iteration wrapper.

Ships a single decorator, `subgroup_iterable`, that Phase 3 methods apply
to their entry-point functions. It converts a scalar-return method into
a subgroup-fanning-out method WITHOUT rewriting the method's compute
logic. The decorator:

1. Adds two optional kwargs to the wrapped function's signature:
   `subgroups: list[str] | None = None`
   `subgroup_assignments_manifest: str | None = None`

2. When `subgroups is None` (or empty), calls the wrapped function as-is
   and returns the scalar result. This is the backward-compat path.

3. When `subgroups` is a non-empty list, the wrapper needs the wrapped
   function to accept a `_sample_id_filter: set[str] | None` kwarg
   (methods opt in explicitly) — for each subgroup it computes the
   member sample_id set via subgroup_common.scoping.resolve_subgroup_cohort,
   passes the set as `_sample_id_filter`, and collects
   `{subgroup_id: result}` into a dict.

Trade-off note: this is a light wrapper, not a full auto-instrumentation.
Methods still need one small change: accept `_sample_id_filter` and
respect it when filtering their source data. That's the minimum-invasive
Phase-3 change (~5 LOC per method).
"""

from __future__ import annotations

import functools
import inspect
from pathlib import Path
from typing import Any, Callable

from methods.subgroup_common.scoping import resolve_subgroup_cohort


def subgroup_iterable(wrapped: Callable) -> Callable:
    """Decorator that adds Path-B subgroup-iteration to a method.

    The wrapped function must accept an optional `_sample_id_filter:
    set[str] | None = None` kwarg. When the wrapper is invoked with
    `subgroups=[...]`, it resolves each subgroup to a set of sample_ids
    and calls the wrapped function once per subgroup with that set.

    Wrapper adds these kwargs (invisible to wrapped function unless
    the wrapped function explicitly declares `_sample_id_filter`):
      - `subgroups: list[str] | None`
      - `subgroup_assignments_manifest: str | None`
      - `subgroup_catalog_repo: Path | str | None` (defaults to standard)
    """

    @functools.wraps(wrapped)
    def _wrapper(*args, subgroups=None, subgroup_assignments_manifest=None,
                 subgroup_catalog_repo=None, **kwargs):
        # Backward-compat path: no subgroup fan-out requested
        if not subgroups:
            return wrapped(*args, **kwargs)

        # Path-B fan-out required
        if subgroup_assignments_manifest is None:
            raise ValueError(
                f"{wrapped.__name__}: `subgroups=[...]` supplied but "
                f"`subgroup_assignments_manifest` is None. Pass the "
                f"derived-manifest id for the subgroup_assignments.parquet "
                f"(e.g. 'tcga-subgroup-assignments-coadread-v1')."
            )

        if subgroup_catalog_repo is not None:
            subgroup_catalog_repo = Path(subgroup_catalog_repo)

        # Fan out: one call per subgroup
        results: dict[str, Any] = {}
        for subgroup_id in subgroups:
            member_ids = resolve_subgroup_cohort(
                subgroup_assignments_manifest, subgroup_id,
                data_catalog_repo=subgroup_catalog_repo,
            )
            # Inject _sample_id_filter kwarg — methods opt in by declaring it
            call_kwargs = dict(kwargs)
            call_kwargs["_sample_id_filter"] = member_ids
            results[subgroup_id] = wrapped(*args, **call_kwargs)
        return results

    # Preserve introspection: expose that this is a subgroup-iterable method
    _wrapper._subgroup_iterable = True  # type: ignore[attr-defined]
    return _wrapper
