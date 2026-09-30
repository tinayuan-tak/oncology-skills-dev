"""control_position_dependency — the dependency (Gate-C) control-benchmark axis.

Given a target, fetch its pan-panel MEDIAN Chronos AND the median Chronos of each
curated control gene (pan-essential positives + non-essential negatives, from
target-contracts/vocabularies/dependency_controls.yaml), then classify where the
target sits relative to the two control bands — on the SAME Chronos scale, same
DepMap release.

THE INVERSION (vs tumor_presence_controls): positives are pan-essential (an
essentiality CEILING → reading at this depth is a BROAD-TOX liability), negatives are
non-essential (a dependency FLOOR). The therapeutic sweet spot is BETWEEN the bands.
See vocabularies/dependency_controls.yaml header for the full rationale.

NO percentile product: Chronos is already control-normalized, so control genes are
read DIRECTLY from the CRISPR matrix (cheap lru-cached column reads).

data_unavailable-safe: vocab/Chronos read failure → dep_control_position_class of
data_unavailable, never a raise (so this can land before the vocab is merged). A
TRANSIENT read failure (S3/network/credentials) on the target OR any control gene is
distinguished from genuine gene-absence (#2184): absence degrades that one member to
None as before, but a transient failure aborts the whole computation to
data_unavailable rather than silently dropping the failed member out of its band —
the bands are data-driven from the control genes, so a silently-narrowed band would
bias the pan-essential/non-essential bounds the classifier reads.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from onc_methods.roots import contracts_root

METHOD_VERSION = "0.1.0"

# Portable sibling default; `or` so an empty env value falls back too (Path("") is the CWD).
DEFAULT_TARGET_CONTRACTS = Path(contracts_root())
CONTROLS_VOCAB_RELPATH = "vocabularies/dependency_controls.yaml"


@lru_cache(maxsize=4)
def _load_controls(contracts_dir: str) -> dict:
    import yaml

    path = Path(contracts_dir) / CONTROLS_VOCAB_RELPATH
    return yaml.safe_load(path.read_text())


class TransientReadFailure(RuntimeError):
    """A control/target Chronos read failed for a reason OTHER than genuine gene-absence
    from the DepMap panel (S3 throttle, credentials, network, malformed row, ...).

    Distinguishing this from absence matters (#2184): `get_chronos_column` returning
    None (or an empty/no-signal column) is the panel's own, reproducible verdict that
    the gene is not there — a legitimate `None`. A raised exception is NOT that; it is
    unknown-state, and treating it the same as absence let a transient failure quietly
    drop a control gene out of its pos/neg band with no marker, biasing the data-driven
    pan-essential/non-essential bounds that the classifier reads directly.
    """


def _median_chronos(symbol: str, release_pin: str) -> Optional[float]:
    """Pan-panel median Chronos for a gene, via the cheap column-projection read.

    Returns None ONLY for genuine gene-absence (not in the DepMap panel, or present with
    no non-null values across the panel) — that is a real, reproducible data condition.
    A read failure (S3/network/credentials/malformed data) raises TransientReadFailure
    instead of silently returning None, so callers can refuse to compute a control band
    that lost a member to an unknown-state failure rather than a true absence (#2184).
    """
    from onc_methods.depmap_common.parquet import get_chronos_column

    try:
        df = get_chronos_column(symbol, release_pin)
    except Exception as e:  # noqa: BLE001 — real failure, NOT absence: surface as a typed marker
        raise TransientReadFailure(f"{symbol}: {type(e).__name__}: {e}") from e
    if df is None:
        return None  # genuine absence: gene not present in the DepMap panel
    cols = [c for c in df.columns if c != "ModelID"]
    if not cols:
        return None  # genuine absence: column-projection returned no gene column
    try:
        series = df[cols[0]].dropna()
    except Exception as e:  # noqa: BLE001 — malformed data is a real failure, not absence
        raise TransientReadFailure(f"{symbol}: {type(e).__name__}: {e}") from e
    if len(series) == 0:
        return None  # genuine absence: gene present but every model value is null
    return float(series.median())


def _classify_dep_control_position(target_med: Optional[float], pos_meds: dict, neg_meds: dict) -> str:
    """Where does the target's median Chronos sit relative to the control bands?

    Bands are DATA-DRIVEN from the control genes themselves (not hardcoded thresholds):
      pan_essential_ceiling = max (LEAST negative) positive median — the shallow edge of
          the pan-essential band (≈ the common-essential -1 calibration line).
      non_essential_floor   = min (MOST negative) negative median — the deepest a truly
          non-essential gene reaches (≈ 0, small noise).

    Classes (INVERTED vs presence):
      as_essential_as_pan_essential      — target <= pan_essential_ceiling: reads as
          essential as the pan-essential controls → BROAD-TOXICITY liability, not a win.
      between_controls                    — non_essential_floor > target > ceiling: a real,
          SELECTIVE dependency that is not pan-essential (the therapeutic sweet spot).
      non_dependent_near_negatives        — target >= non_essential_floor: no dependency
          (as non-essential as the negative controls).
      data_unavailable                    — target or all controls unrankable.
    """
    if target_med is None:
        return "data_unavailable"
    pos = [m for m in pos_meds.values() if m is not None]
    neg = [m for m in neg_meds.values() if m is not None]
    if not pos and not neg:
        return "data_unavailable"
    # Pan-essential CEILING = the least-negative (shallowest) pan-essential median.
    ceiling = max(pos) if pos else None
    # Non-essential FLOOR = the most-negative non-essential median (deepest a non-essential reaches).
    floor = min(neg) if neg else None

    if ceiling is not None and target_med <= ceiling:
        return "as_essential_as_pan_essential"
    if floor is not None and target_med >= floor:
        return "non_dependent_near_negatives"
    # Below the non-essential floor but above the pan-essential ceiling → selective window.
    return "between_controls"


def control_position_dependency(
    target: str, release_pin: str = "26q3", contracts_dir: str = str(DEFAULT_TARGET_CONTRACTS)
) -> dict:
    """Control-benchmark position for the pan-cancer-crispr-dependency-distribution card.

    Reads the target's + each control gene's pan-panel median Chronos DIRECTLY (no
    percentile product) and classifies the target against the pan-essential ceiling +
    non-essential floor. Returns dep_control_* fields (display-only / verdict-inert).
    """
    try:
        controls = _load_controls(contracts_dir)
    except Exception as e:  # noqa: BLE001  # absence-discipline: exempt -- verdict-inert display-only control-benchmark facet (dep_control_* never flips the dependency verdict); the guarded read is the target-contracts controls VOCAB, whose deliberate contract is to degrade when the vocab is not yet merged (cross-repo staleness tolerance), not an S3 data product
        return {
            "dep_control_position_class": "data_unavailable",
            "_dep_control_note": f"controls vocab unavailable: {type(e).__name__}",
            "dep_control_method_version": METHOD_VERSION,
        }

    def _safe_median(sym: str):
        """(median, failure_note) — failure_note is None on success (incl. genuine absence)."""
        try:
            return _median_chronos(sym, release_pin), None
        except TransientReadFailure as e:
            return None, str(e)

    target_med, target_failure = _safe_median(target)
    pos_meds: dict = {}
    neg_meds: dict = {}
    failures: dict = {}
    if target_failure is not None:
        failures[target] = target_failure
    for sym in controls.get("positive_controls") or {}:
        med, failure = _safe_median(sym)
        pos_meds[sym] = med
        if failure is not None:
            failures[sym] = failure
    for sym in controls.get("negative_controls") or {}:
        med, failure = _safe_median(sym)
        neg_meds[sym] = med
        if failure is not None:
            failures[sym] = failure

    if failures:
        # A transient failure on ANY member (target or control) is unknown-state, not
        # absence — refuse to compute a band that would silently lose that member
        # (#2184), rather than quietly narrowing the pan-essential/non-essential bounds.
        return {
            "dep_control_position_class": "data_unavailable",
            "_dep_control_note": (
                "transient read failure (not genuine absence) on "
                f"{', '.join(sorted(failures))}; refusing to compute a control band that "
                "would silently drop a member: " + "; ".join(f"{k}: {v}" for k, v in failures.items())
            ),
            "dep_control_method_version": METHOD_VERSION,
        }

    klass = _classify_dep_control_position(target_med, pos_meds, neg_meds)

    # human-readable position: how the target ranks vs each band (essentiality direction:
    # a target is "more essential than" a control when its Chronos is MORE negative).
    pos_present = [m for m in pos_meds.values() if m is not None]
    neg_present = [m for m in neg_meds.values() if m is not None]
    n_pos = len(pos_present)
    n_neg = len(neg_present)
    n_pos_more_essential = (
        sum(1 for m in pos_present if target_med is not None and target_med <= m) if target_med is not None else 0
    )
    n_neg_more_essential = (
        sum(1 for m in neg_present if target_med is not None and target_med < m) if target_med is not None else 0
    )
    parts = []
    if n_pos:
        parts.append(f"as/more essential than {n_pos_more_essential}/{n_pos} pan-essential control(s)")
    if n_neg:
        parts.append(f"more dependent than {n_neg_more_essential}/{n_neg} non-essential control(s)")
    position = "; ".join(parts) if parts else "no control medians resolved"

    ceiling = max(pos_present) if pos_present else None
    floor = min(neg_present) if neg_present else None
    ctx = (
        f"DepMap {release_pin} pan-panel median Chronos vs curated dependency controls "
        f"(dependency_controls v{controls.get('version')}; "
        f"pan_essential_ceiling={_round(ceiling)}; non_essential_floor={_round(floor)}). "
        f"INVERTED: at/below the ceiling = pan-essential tox liability; between = selective "
        f"dependency window; at/above the floor = non-dependent."
    )

    return {
        "dep_control_position_class": klass,
        "dep_control_position": position,
        "dep_control_target_chronos": _round(target_med),
        "dep_control_positives": {k: _round(v) for k, v in pos_meds.items() if v is not None},
        "dep_control_negatives": {k: _round(v) for k, v in neg_meds.items() if v is not None},
        "dep_control_pan_essential_ceiling": _round(ceiling),
        "dep_control_non_essential_floor": _round(floor),
        "dep_control_position_context": ctx,
        "dep_control_method_version": METHOD_VERSION,
    }


def _round(v, nd=3):
    return round(v, nd) if isinstance(v, (int, float)) else v
