#!/usr/bin/env python3
"""feature_vectoriser — the richer atlas feature substrate (Phase 1 of the atlas rebuild).

The frozen target-archetype atlas is built ONLY from ordinal claim tiers (108 features = 54 claims ×
{signal,corrob}); everything a card computes as a NUMBER is invisible to the phenotype geometry, and
mean-imputation cannot tell a measured-zero from an unmeasured axis (the documented EGFR
amp-because-SNV-silently-0 failure). This module assembles the EXTENDED feature vector the rebuilt atlas
will freeze over, across three families:

  1. ORDINAL CLAIM  — the existing `{short}::claim::{CLAIM}::{signal,corrob}` keys (delegated verbatim to
     archetype_core.claim_features, so the encoding stays the single shared source).
  2. NUMERIC        — `{short}::num::{field}` for each SALIENCE_SPECS axis that carries a `reference_frame`
     (the meter value_fields — already the framework's validated bounded/standardized scalars). The value is
     POLARITY-SIGNED via the spec's `direction` so "higher = more supportive of the phenotype" is uniform
     before z-scoring, and each numeric carries an explicit `{short}::num::{field}::mask` ∈ {0,1}
     distinguishing measured (mask=1) from unmeasured (mask=0, value→None→corpus-mean at embed) — the fix
     for the measured-zero-vs-unmeasured collapse.
  3. VERDICT        — DECLARED but not yet emitted (see VERDICT_FEATURES_STATUS): encoding a per-gate
     resolver verdict as a signed ordinal needs a verdict→severity map that does not yet exist as a shared
     contract; deferred to a follow-on so this module ships the fully-grounded numeric substrate now.

DESIGN INVARIANTS (preserved): pure-stdlib + deterministic; ONE vectoriser for offline build == runtime
query (build_atlas and Atlas._embed will both call this); verdict-INERT (a projection, never a decision);
`None` (unmeasured) is kept DISTINCT from a measured 0.0. Reused by build_atlas (offline) and archetype_core
(runtime) once the re-freeze adopts it — until then it is additive and touches no frozen path.
"""

from __future__ import annotations

from typing import Optional

from _skills_common.archetype_core import claim_features
from _skills_common.evidence_salience import SALIENCE_SPECS

FEATURE_SCHEMA_VERSION = "1.0.0"
VERDICT_FEATURES_STATUS = "deferred"  # pending a shared verdict→severity contract (see module docstring)

# sign multiplier so a larger feature value always means "more supportive of the phenotype"
_DIR_SIGN = {"higher_is_stronger": 1.0, "lower_is_stronger": -1.0, "higher_is_worse": 1.0}
# (higher_is_worse keeps +1: the magnitude still encodes the axis; safety's overall sign is handled by the
#  scorecard's AX_SIGN, not here — this module only makes each numeric monotone with its own effect.)


def numeric_feature_specs() -> dict:
    """{measurement_type: (value_field, direction)} for every SALIENCE_SPECS axis that carries a
    reference_frame — i.e. the meter value_fields double as the atlas numeric features (one registry).
    reference_frame may be a dict OR a list of frames (multi-ruler); the atlas keeps ONE numeric feature
    per axis, keyed off the PRIMARY (first) frame's value_field — the headline metric the axis leads with."""
    out = {}
    for mt, spec in SALIENCE_SPECS.items():
        rf = spec.get("reference_frame")
        primary = rf[0] if isinstance(rf, list) and rf else (rf if isinstance(rf, dict) else None)
        if isinstance(primary, dict) and primary.get("value_field"):
            out[mt] = (primary["value_field"], spec.get("direction"))
    return out


def _num(v) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # drop NaN


def numeric_features(numeric_values: dict) -> dict:
    """Project harvested per-axis numerics into polarity-signed atlas features + explicit missingness masks.

    `numeric_values` = {measurement_type: {field: number}} (harvested from card summaries by the numeric
    harvester). For each reference_frame axis: emit `{mt}::num::{field}` = sign(direction) * value when the
    value is a real number (mask=1), else value None (mask=0). A numeric key is emitted for EVERY declared
    axis (present or not) so the frozen feature_order is stable and missingness is explicit, never silent."""
    specs = numeric_feature_specs()
    feats: dict = {}
    for mt, (field, direction) in specs.items():
        raw = _num((numeric_values.get(mt) or {}).get(field))
        key = f"{mt}::num::{field}"
        if raw is None:
            feats[key] = None
            feats[f"{key}::mask"] = 0.0
        else:
            feats[key] = _DIR_SIGN.get(direction, 1.0) * raw
            feats[f"{key}::mask"] = 1.0
    return feats


def build_feature_vector(claim_vectors: dict, numeric_values: Optional[dict] = None) -> dict:
    """The extended atlas feature vector for ONE target: ordinal claim features (delegated to
    archetype_core.claim_features) merged with the polarity-signed numeric features + masks. Verdict
    features are not yet included (VERDICT_FEATURES_STATUS='deferred'). Deterministic; `None` = unmeasured.

    Pure over its inputs — the caller (build_atlas offline / archetype_core runtime) supplies the SAME
    harvested data so offline==runtime holds by construction."""
    feats = dict(claim_features(claim_vectors or {}))
    feats.update(numeric_features(numeric_values or {}))
    return feats
