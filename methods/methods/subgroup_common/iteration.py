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
import warnings
from pathlib import Path
from typing import Any, Callable

from methods.subgroup_common.scoping import resolve_subgroup_cohort, stratum_evaluability

# Mirror scoping._MATCH_RATE_FLOOR: below this matched-fraction (with a non-empty member set) we
# suspect an id-convention mismatch, not a legitimate empty stratum. Legitimate subsetting lands at
# 0.3-0.8; a true convention mismatch lands at ~0.0.
_FANOUT_MATCH_RATE_FLOOR = 0.05


def _emit_join_coverage_warning(wrapped, subgroup_id, member_ids, result) -> None:
    """Fan-out-path join-coverage guard: warn when a non-empty resolved member set matched
    NEAR-ZERO rows in the reader's data (the sample-id-convention-mismatch signature). Generic:
    reads the reader's reported matched count from its `subgroup_n` field (the count AFTER the
    reader intersected _sample_id_filter with its own data). A reader that does not report
    subgroup_n is skipped (no false alarm)."""
    n_members = len(member_ids) if member_ids else 0
    if not n_members:
        return  # empty member set is a legitimate absent stratum, not a join failure
    matched = None
    if isinstance(result, dict):
        matched = result.get("subgroup_n")
    if not isinstance(matched, int):
        return  # reader doesn't expose a matched count; nothing to compare
    match_rate = matched / n_members
    if match_rate < _FANOUT_MATCH_RATE_FLOOR:
        warnings.warn(
            f"{getattr(wrapped, '__name__', 'reader')} / subgroup '{subgroup_id}': only "
            f"{matched}/{n_members} resolved members ({match_rate:.1%}) matched the method's "
            f"data. This is the signature of a sample-id-convention mismatch (e.g. patient-barcode "
            f"assignments vs full-aliquot method data, or ModelID vs barcode), NOT necessarily an "
            f"empty stratum. Check id normalization before trusting per-stratum stats.",
            UserWarning,
            stacklevel=3,
        )


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

    A reader MAY additionally declare `_stratum_evaluated: bool | None = None` to receive
    `scoping.stratum_evaluability(...).evaluated` for the stratum being read — the flag that
    separates an EMPTY stratum from an UNEVALUABLE one. See the injection site for why this is
    probed rather than injected unconditionally.
    """
    # Decoration-time signature probe (once per decorated function, NOT per call). The
    # evaluability flag is OPT-IN because injecting it unconditionally would raise TypeError in
    # every reader that does not declare it — `_sample_id_filter` gets away with unconditional
    # injection only because declaring it is a hard precondition of the fan-out path, whereas
    # this flag is purely additive. Probing keeps the four readers whose cards still declare the
    # narrow `{measured, underpowered, absent}` enum byte-identical.
    try:
        _wants_evaluated = "_stratum_evaluated" in inspect.signature(wrapped).parameters
    except (TypeError, ValueError):  # C-implemented / signature-less callables
        _wants_evaluated = False

    @functools.wraps(wrapped)
    def _wrapper(*args, subgroups=None, subgroup_assignments_manifest=None, subgroup_catalog_repo=None, **kwargs):
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
                subgroup_assignments_manifest,
                subgroup_id,
                data_catalog_repo=subgroup_catalog_repo,
            )
            # Inject _sample_id_filter kwarg — methods opt in by declaring it
            call_kwargs = dict(kwargs)
            call_kwargs["_sample_id_filter"] = member_ids
            if _wants_evaluated:
                # `member_ids` cannot answer "was this stratum ever CLASSIFIED?" — an empty set
                # conflates "we looked, nobody qualifies" (absent) with "nobody was assessed"
                # (unevaluable). Only the assigner's is_member partition separates them, and only
                # this loop knows both the stratum id and the manifest, so the flag is computed
                # HERE and graded in the reader at its existing evidence_state() call.
                # No new failure mode: `load_assignments` is lru_cached and resolve_subgroup_cohort
                # above already loaded the same shard without swallowing errors, so an unloadable
                # shard raises there first. Deliberately NOT wrapped in try/except — that would
                # launder a mis-typed assignments column into a silent `absent`.
                call_kwargs["_stratum_evaluated"] = stratum_evaluability(
                    subgroup_assignments_manifest,
                    subgroup_id,
                    data_catalog_repo=subgroup_catalog_repo,
                ).evaluated
            result = wrapped(*args, **call_kwargs)
            # JOIN-COVERAGE GUARD (fan-out path). The reader has now intersected the resolved
            # member set with its OWN data-id column. Compare the resolved member count against the
            # reader's matched count (its `subgroup_n`): a non-empty member set that matches
            # NEAR-ZERO rows is the signature of a sample-id-convention mismatch (e.g. patient-
            # barcode assignments vs full-aliquot method data, or ModelID vs barcode), NOT a
            # legitimately empty stratum. Previously only the expression reader called
            # compute_join_coverage directly; the two @subgroup_iterable readers (depmap_chronos,
            # gdc_somatic_hotspot) bypassed it entirely — this closes that gap generically for ALL
            # decorated readers without each needing to know its own id column.
            _emit_join_coverage_warning(wrapped, subgroup_id, member_ids, result)
            results[subgroup_id] = result
        return results

    # Preserve introspection: expose that this is a subgroup-iterable method
    _wrapper._subgroup_iterable = True  # type: ignore[attr-defined]
    return _wrapper
