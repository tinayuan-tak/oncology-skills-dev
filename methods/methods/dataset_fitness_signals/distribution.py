"""Shape-conditioned re-anchoring for the contract's ``roster_relative`` threshold.

WHY THIS IS A METHOD AND NOT A ONE-LINER
----------------------------------------
``discordance_high`` is the one threshold in ``dataset_fitness_resolution.yaml`` declared
``basis: roster_relative``. Its rationale says so explicitly: it is not an absolute reliability
standard but a statement that "this product is in the top quartile of its own family", and it
"must be re-anchored when a second family lands". So re-anchoring is a DECLARED obligation, and
the obvious way to discharge it -- take the p75 of ``discordant_fraction`` over the roster --
is wrong in the exact way the whole axis exists to prevent.

THE MEASUREMENT (first roster, 2026-09-19, n=36)
------------------------------------------------
Discordance is the fraction of genes whose two comparator arms disagree in sign. A product that
lost a comparator has ONE live arm, and a single arm cannot disagree with itself, so its
discordance is not a low measurement -- it is an absence wearing a measured value. Seven of the
eight collapsed products report EXACTLY 0.0 for this reason. (The eighth, ``hnsc``, reports
0.0035: it is ``degraded_to_adjacent_only`` yet kept two adjacent-derived arms, so one
COMPARATOR but two live ARMS, and its discordance is genuinely measured.)

Pooling those zeros into the reference distribution therefore drags it down:

    conditioned on both_comparators (n=21):  p50 0.1210   p75 0.1502   p90 0.1662
    pooled over the whole roster   (n=32):  p50 0.0763   p75 0.1432   p90 0.1626

The p50 is understated by 37%. The consequence is not cosmetic: a cut re-anchored at the pooled
p75 (0.1432) fires on 7 of 21 both-arm products instead of 6, so a healthy product is labelled
high-discordance because the reference class was diluted by products that had nothing to
disagree with. The confound reaches the threshold CALIBRATION, not merely a ranking.

HOW THAT IS PREVENTED HERE
--------------------------
``reanchor`` reads the signal's own ``reads`` entry and REFUSES to compute a cut for a signal
declared ``use: within_shape_only`` unless a conditioning predicate is supplied. The discipline
is structural rather than a caller's obligation to remember, because the whole finding is that
the naive read looks perfectly reasonable. It also returns the pooled value alongside the
conditioned one, so the size of the confound is reported rather than merely avoided.

KNOWN PROVENANCE GAP
--------------------
The contract records the quantile in prose ("Cut at the p75.") but not as a machine-readable
field, so ``percentile`` cannot be recovered from the contract and must be passed explicitly.
Worth closing on the contract side with a ``percentile: 75`` key; until then, an explicit
argument is better than a default that silently re-anchors at the wrong quantile.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from .resolve import ContractInvalid


def _matches(row: Mapping[str, Any], where: Mapping[str, Any] | None) -> bool:
    """True when ``row`` satisfies every field constraint in ``where``.

    A constraint value may be a scalar (equality) or a list/tuple/set (membership).
    """
    if not where:
        return True
    for field, wanted in where.items():
        actual = row.get(field)
        if isinstance(wanted, (list, tuple, set)):
            if actual not in wanted:
                return False
        elif actual != wanted:
            return False
    return True


def conditioned_values(
    rows: Iterable[Mapping[str, Any]],
    signal: str,
    where: Mapping[str, Any] | None = None,
) -> list[float]:
    """Finite numeric values of ``signal`` over the rows satisfying ``where``.

    Non-finite values are dropped rather than coerced, for the reason recorded in
    ``resolve._finite``: an inf would dominate any quantile and a NaN would poison a sort.
    """
    out = []
    for row in rows:
        if not _matches(row, where):
            continue
        value = row.get(signal)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if math.isfinite(float(value)):
            out.append(float(value))
    return out


def percentile_cut(values: Sequence[float], percentile: float) -> float | None:
    """The requested percentile of ``values``, or ``None`` when there is nothing to measure.

    ``None`` rather than 0.0 on an empty input: a cut derived from no data is not a cut, and a
    zero would be the most permissive possible threshold -- failing open exactly where the
    reference class turned out to be empty.
    """
    if not 0 <= percentile <= 100:
        raise ValueError(f"percentile must be in [0, 100], got {percentile}")
    if not values:
        return None
    return float(np.percentile(np.asarray(values, dtype=float), percentile))


def roster_relative_cut(
    rows: Iterable[Mapping[str, Any]],
    signal: str,
    percentile: float,
    where: Mapping[str, Any] | None = None,
) -> float | None:
    """Percentile cut for ``signal`` over the rows satisfying ``where``.

    The low-level primitive: it does not know which signals require conditioning. Prefer
    ``reanchor``, which enforces that from the contract.
    """
    return percentile_cut(conditioned_values(rows, signal, where), percentile)


def reanchor(
    contract: Mapping[str, Any],
    threshold_id: str,
    rows: Iterable[Mapping[str, Any]],
    percentile: float,
    where: Mapping[str, Any] | None = None,
    tolerance: float = 1e-9,
) -> dict:
    """Re-measure a ``roster_relative`` threshold against a roster, conditioning enforced.

    Raises ``ContractInvalid`` if the threshold is not declared, if it is not
    ``roster_relative`` (re-anchoring an absolute standard is a category error -- an absolute
    floor is not supposed to move when the corpus does), or if the threshold's signal is
    declared ``use: within_shape_only`` / ``shape_confounded: true`` and no conditioning
    predicate was supplied.

    Returns a dict with ``declared``, ``remeasured``, ``pooled``, the two sample sizes, and
    ``drifted`` -- whether the re-measured cut differs from the declared one beyond
    ``tolerance``. ``pooled`` is included so the magnitude of the confound the conditioning
    avoided is reported rather than merely avoided.

    ``tolerance`` defaults to exact, which reports the deliberate rounding as drift: the first
    roster's declared cut is 0.15 against a measured p75 of 0.1502. That is the honest default
    -- a caller asking "has the corpus moved?" should pass the rounding they accepted (e.g.
    ``tolerance=0.01``) rather than have a re-anchoring silently absorb it.
    """
    rows = list(rows)
    spec = next((t for t in contract.get("thresholds", []) if t.get("id") == threshold_id), None)
    if spec is None:
        declared_ids = sorted(t.get("id") for t in contract.get("thresholds", []))
        raise ContractInvalid(f"threshold {threshold_id!r} is not declared. Declared: {declared_ids}")
    if spec.get("basis") != "roster_relative":
        raise ContractInvalid(
            f"threshold {threshold_id!r} has basis {spec.get('basis')!r}; only roster_relative "
            "thresholds are re-anchored. An absolute floor is not supposed to move when the "
            "corpus does -- that is what makes it a forward guard."
        )

    signal = spec["signal"]
    read = next((r for r in contract.get("reads", []) if r.get("signal") == signal), None)
    needs_conditioning = bool(read) and (read.get("use") == "within_shape_only" or read.get("shape_confounded") is True)
    if needs_conditioning and not where:
        raise ContractInvalid(
            f"signal {signal!r} is declared "
            f"use={read.get('use')!r} shape_confounded={read.get('shape_confounded')!r}, so a "
            f"roster-relative cut for {threshold_id!r} requires a conditioning predicate. "
            "Pooling the whole roster mixes in products whose value is structurally absent "
            f"rather than low (see this module's docstring); pass where={{...}} naming the "
            "partition the cut is relative to."
        )

    conditioned = conditioned_values(rows, signal, where)
    pooled = conditioned_values(rows, signal, None)
    remeasured = percentile_cut(conditioned, percentile)
    declared = spec.get("value")
    drifted = remeasured is not None and declared is not None and abs(remeasured - declared) > tolerance

    return {
        "threshold_id": threshold_id,
        "signal": signal,
        "percentile": percentile,
        "where": dict(where) if where else None,
        "declared": declared,
        "remeasured": remeasured,
        "n_conditioned": len(conditioned),
        "pooled": percentile_cut(pooled, percentile),
        "n_pooled": len(pooled),
        "tolerance": tolerance,
        "drifted": drifted,
    }
