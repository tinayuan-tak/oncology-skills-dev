"""Deterministic bucket-key ordering — the one shared kernel behind the framework's grouped views.

Several places group a flat collection into named buckets and then must emit those buckets in a
STABLE, reproducible order (golden-stable output, deterministic queries). Two such consumers exist
today and they had independently open-coded the same fiddly ordering policy:

  * report_render `ReportIR.lenses()` — buckets sections/blocks by lens, emits ``vocab.LENS_ORDER``
    first then any future lens "stably last".
  * l2_substrate `group_records_by_context` — buckets records by context key, emits keys sorted with
    the residual ``UNKEYED`` bucket last.

The ordering step is exactly where determinism bugs hide (a forgotten sort, a residual bucket that
drifts to the front because its sentinel sorts low). ``ordered_bucket_keys`` captures it ONCE, with
tests, so both consumers share the same guarantee.

It is deliberately NOT a declarative "ViewDef" config object: with only two ordered consumers, each
building its buckets differently and carrying a different value shape, a config language would be
over-engineering. The genuinely shared, genuinely error-prone piece is *key order* — so that, and
only that, is what this extracts. (`by_role` in target-profile also buckets by a key, but its
consumer reads it BY NAME — `by_role.get("gating")` — so its order is inert and it is intentionally
not a consumer of this kernel.)
"""

from __future__ import annotations

from typing import Any, Iterable, Optional


def ordered_bucket_keys(
    buckets: dict,
    *,
    known_order: Optional[Iterable[Any]] = None,
    residual_key: Any = None,
) -> list:
    """Return the keys of ``buckets`` in a deterministic visit order, each exactly once.

    - ``known_order`` — an optional sequence of keys emitted FIRST, in that order, skipping any not
      present in ``buckets``. When it is None, the non-residual keys are emitted SORTED.
    - the remaining keys (present in ``buckets``, not named in ``known_order``, not the residual) then
      follow: in ``buckets`` insertion order (stable) when ``known_order`` was given, or SORTED when it
      was None (the residual is never sorted into this run).
    - ``residual_key`` — when it is not None and present in ``buckets``, it is always emitted LAST
      (never in the known/remaining runs), so a sentinel bucket can't drift to the front just because
      its key sorts low.

    Every returned key is present in ``buckets``; no key appears twice.
    """
    has_residual = residual_key is not None and residual_key in buckets

    def _is_body(k: Any) -> bool:
        # a "body" (non-residual) key — eligible for the known/remaining runs
        return not (has_residual and k == residual_key)

    out: list = []
    seen: set = set()

    if known_order is not None:
        for k in known_order:
            if k in buckets and _is_body(k) and k not in seen:
                out.append(k)
                seen.add(k)
        # remaining body keys in insertion order (stable), those not already placed
        for k in buckets:
            if _is_body(k) and k not in seen:
                out.append(k)
                seen.add(k)
    else:
        body = [k for k in buckets if _is_body(k)]
        for k in sorted(body):
            out.append(k)
            seen.add(k)

    if has_residual:
        out.append(residual_key)

    return out
