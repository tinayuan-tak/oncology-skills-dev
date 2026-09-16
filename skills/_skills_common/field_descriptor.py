#!/usr/bin/env python3
"""field_descriptor — one per-field descriptor, DERIVED by joining the two registries that already
know a measured field's structure and its semantics.

The framework already writes down, in two places, everything needed to read a measured datum as a
signal rather than a bare number — but each half is visible to only one consumer:

  * `evidence_salience.SALIENCE_SPECS` knows the STRUCTURE per measurement_type — which field is the
    effect, which is its significance (q/p), which is the cross-stratum omnibus, which is the n, which
    direction counts as stronger, and which categoricals are load-bearing.
  * `display_gloss.gloss(field)` + `direction_phrase(direction)` know the SEMANTICS — a plain-language
    label, a units/scale token, and a "lower = stronger" clause.

This module is the JOIN. For each measurement_type it walks the spec's declared field slots, assigns a
`role`, and attaches the label/units/direction from the gloss. The output per field is the tuple the
substrate needs — `(value, units, direction, its significance field, its reference frame, measured)` —
so `median_chronos = -1.18` can be read as "median CRISPR gene-effect (CHRONOS), lower = stronger, its q
in q_value, panel-median frame, measured" instead of a naked scalar.

DESIGN CONTRACT (mirrors both sources verbatim):
  * DERIVED — re-expresses SALIENCE_SPECS + METRIC_GLOSS and holds NO independent content, so it cannot
    drift from them (a third hand-authored copy is exactly what we are avoiding).
  * ADDITIVE · DETERMINISTIC · VERDICT-INERT · DISPLAY-ONLY — feeds no rule/resolver/gate; touches no
    frozen path. Pure stdlib.
  * `measured` reuses `field_disposition.is_measured` (the shared value-level helper: 0/0.0/False are
    MEASURED, None/sentinel/non-finite/empty are not) — it does NOT invent a second measuredness rule.
  * A `reference_frame` primary value_field is flagged `atlas_live=True`. It is NOT display-only: it
    mints frozen atlas columns (`feature_vectoriser.numeric_feature_specs`) and feeds claim-record
    magnitude. This module DESCRIBES those fields; it must never reshape one.

Coverage is reported, never gated (`coverage_report`): a measurement_type with no spec, or an emitted
field in no spec, degrades to role `unclassified` — the reviewable per-field work queue, which is the
answer to "the notable signal may be different for each field and card." A zero `unclassified` count
would mean the classifier is fabricating roles, not that coverage is complete.
"""

from __future__ import annotations

from collections import Counter
from typing import Optional

from _skills_common import display_gloss
from _skills_common.evidence_salience import SALIENCE_SPECS
from _skills_common.field_disposition import is_measured

# role vocabulary — what a field IS within its measurement_type's evidence shape.
ROLE_EFFECT = "effect"
ROLE_SIGNIFICANCE = "significance"
ROLE_OMNIBUS = "omnibus"
ROLE_N = "n"
ROLE_CATEGORICAL = "categorical"
ROLE_EXTRA_SCALAR = "extra_scalar"
ROLE_LABEL = "label"
ROLE_STRATA = "strata"
ROLE_FRAME_VALUE = "frame_value"  # atlas-live: a reference_frame value_field (NEVER reshape)
ROLE_ENVELOPE = "envelope"  # framework plumbing, not a measurement
ROLE_UNCLASSIFIED = "unclassified"  # emitted but in no spec — the work queue

ROLES: frozenset = frozenset(
    {
        ROLE_EFFECT,
        ROLE_SIGNIFICANCE,
        ROLE_OMNIBUS,
        ROLE_N,
        ROLE_CATEGORICAL,
        ROLE_EXTRA_SCALAR,
        ROLE_LABEL,
        ROLE_STRATA,
        ROLE_FRAME_VALUE,
        ROLE_ENVELOPE,
        ROLE_UNCLASSIFIED,
    }
)

# roles that carry a NUMBER and therefore want a curated (label, units) in METRIC_GLOSS. A categorical
# `*_class`, a `label` column, or a `strata` array container reads fine from the snake->space fallback
# (a class has no units; its VALUES are humanised at display), so those are NOT counted as a gloss gap.
_NUMERIC_ROLES: frozenset = frozenset(
    {ROLE_EFFECT, ROLE_SIGNIFICANCE, ROLE_OMNIBUS, ROLE_N, ROLE_EXTRA_SCALAR, ROLE_FRAME_VALUE}
)

# framework plumbing carried in every card summary alongside the measurements — classifying these as
# `envelope` is what lets a machine consumer read the export as a dataset (they currently sit in the
# same namespace as the data) and is the modelling gap behind most per-card schema conformance failures.
ENVELOPE_FIELDS: frozenset = frozenset(
    {
        "method_version",
        "target",
        "indication",
        "source",
        "question",
        "generated_at",
        "skill",
        "card_id",
        "as_of",
        "ensembl_gene_id",
        "modality",
    }
)


def _spec_frame_value_fields(spec: dict) -> list:
    """The `value_field`(s) a spec's reference_frame gauges. ONE dict or a LIST of dicts; each may carry
    `value_field`. These are atlas-live — enumerated so they can be DESCRIBED (and flagged), never reshaped."""
    rf = spec.get("reference_frame")
    if not rf:
        return []
    frames = rf if isinstance(rf, list) else [rf]
    out = []
    for fr in frames:
        if isinstance(fr, dict) and fr.get("value_field"):
            out.append(fr["value_field"])
    return out


def _descriptor(field: str, measurement_type: str, role: str, spec: dict) -> dict:
    """One field's descriptor: structure (role + where its q/omnibus/n live) joined to semantics
    (label/units/direction from the gloss). The effect field carries the pointers to its own
    significance/omnibus/n so a reader gets the whole tuple from the one record."""
    label, units = display_gloss.gloss(field)
    # direction is a property of the effect axis (and the frame it is gauged on), not of a q or a count.
    direction = spec.get("direction") if role in (ROLE_EFFECT, ROLE_FRAME_VALUE) else None
    d = {
        "field": field,
        "measurement_type": measurement_type,
        "role": role,
        "label": label,
        "units": units,
        "direction": direction,
        "direction_phrase": display_gloss.direction_phrase(direction) if direction else None,
        "atlas_live": role == ROLE_FRAME_VALUE,
    }
    if role == ROLE_EFFECT:
        # the pointers that turn a bare effect into a signal: where its significance/omnibus/n live.
        d["significance_field"] = spec.get("significance_field")
        d["omnibus_field"] = spec.get("omnibus_field")
        d["n_field"] = spec.get("n_field")
    return d


# slot key on the spec -> (role, is_list). label_field/strata_array are single; categorical/extra_scalars are lists.
_SCALAR_SLOTS = (
    ("effect_field", ROLE_EFFECT),
    ("significance_field", ROLE_SIGNIFICANCE),
    ("omnibus_field", ROLE_OMNIBUS),
    ("n_field", ROLE_N),
    ("label_field", ROLE_LABEL),
    ("strata_array", ROLE_STRATA),
)
_LIST_SLOTS = (
    ("categorical", ROLE_CATEGORICAL),
    ("extra_scalars", ROLE_EXTRA_SCALAR),
)


def descriptors_for(measurement_type: str) -> dict:
    """`{field: descriptor}` for one measurement_type. First-writer-wins if a field fills two slots (a
    field named as both effect and a frame value keeps its effect role — the stronger statement)."""
    spec = SALIENCE_SPECS.get(measurement_type)
    if not spec:
        return {}
    out: dict = {}

    def put(field, role):
        if field and field not in out:
            out[field] = _descriptor(field, measurement_type, role, spec)

    for key, role in _SCALAR_SLOTS:
        put(spec.get(key), role)
    for key, role in _LIST_SLOTS:
        for field in spec.get(key) or ():
            put(field, role)
    for field in _spec_frame_value_fields(spec):
        put(field, ROLE_FRAME_VALUE)
    return out


def descriptor_catalog() -> dict:
    """`{measurement_type: {field: descriptor}}` over every SALIENCE_SPECS entry. Deterministic (dict
    insertion order follows SALIENCE_SPECS + the fixed slot order above)."""
    return {mt: descriptors_for(mt) for mt in SALIENCE_SPECS}


def _flat_index() -> dict:
    """`{field: descriptor}` folded across all measurement_types (first spec wins on a name collision).
    Backing store for `describe_field`/`classify_field` when the measurement_type is not known at the read."""
    flat: dict = {}
    for mt in SALIENCE_SPECS:
        for field, d in descriptors_for(mt).items():
            flat.setdefault(field, d)
    return flat


def describe_field(field: str, measurement_type: Optional[str] = None) -> Optional[dict]:
    """The descriptor for `field`. Prefers the given measurement_type; else folds across all specs.
    None when the field is in no spec (use `classify_field` to get its role incl. envelope/unclassified)."""
    if not field:
        return None
    if measurement_type:
        return descriptors_for(measurement_type).get(field)
    return _flat_index().get(field)


def classify_field(field: str, measurement_type: Optional[str] = None) -> str:
    """The role of any emitted field: its spec role, else `envelope` (framework plumbing / private
    `_`-prefixed key), else `unclassified` (the work queue)."""
    d = describe_field(field, measurement_type)
    if d:
        return d["role"]
    if field in ENVELOPE_FIELDS or (field or "").startswith("_"):
        return ROLE_ENVELOPE
    return ROLE_UNCLASSIFIED


def stamp_measured(descriptor: dict, value) -> dict:
    """A copy of `descriptor` with `measured` set from the shared `is_measured` value-level rule."""
    return {**descriptor, "measured": is_measured(value)}


def describe_summary(summary: dict, measurement_type: Optional[str] = None) -> dict:
    """`{field: descriptor+measured}` for every field in a card `summary` dict — the per-package view:
    each field carries its role and whether THIS run measured it. Fields with no spec descriptor still
    appear, carrying only `{field, role, measured}` (role = envelope / unclassified)."""
    out: dict = {}
    for field, value in (summary or {}).items():
        d = describe_field(field, measurement_type)
        if d is None:
            d = {"field": field, "role": classify_field(field, measurement_type)}
        out[field] = {**d, "measured": is_measured(value)}
    return out


def coverage_report(summaries: Optional[list] = None) -> dict:
    """A coverage report, NOT a gate. With no `summaries`, reports the static catalog (how many fields
    carry each role, and whether every spec field resolved a gloss label). With `summaries` (a list of
    card `summary` dicts), also reports how many EMITTED fields have a descriptor vs land `unclassified`
    — the per-field work queue. `unclassified` being empty on real data means the classifier is
    fabricating roles, not that coverage is complete."""
    catalog = descriptor_catalog()
    role_counts: Counter = Counter()
    numeric_ungloss: list = []  # NUMERIC-role fields with no curated (label, units) — the real semantic gap
    for mt, fields in catalog.items():
        for field, d in fields.items():
            role_counts[d["role"]] += 1
            # a numeric field wants a curated METRIC_GLOSS entry; its absence (gloss fell back to the
            # snake->space default) is a real gap. Categorical/label/strata fields read fine from the
            # fallback and are excluded.
            if d["role"] in _NUMERIC_ROLES and field not in display_gloss.METRIC_GLOSS:
                numeric_ungloss.append(field)
    report = {
        "n_measurement_types": len(catalog),
        "n_descriptor_fields": sum(len(v) for v in catalog.values()),
        "role_counts": dict(role_counts),
        "n_atlas_live": role_counts.get(ROLE_FRAME_VALUE, 0),
        "numeric_fields_without_gloss": sorted(set(numeric_ungloss)),
    }
    if summaries is not None:
        emitted_role: Counter = Counter()
        unclassified: set = set()
        for summary in summaries:
            for field in summary or {}:
                role = classify_field(field)
                emitted_role[role] += 1
                if role == ROLE_UNCLASSIFIED:
                    unclassified.add(field)
        report["emitted_role_counts"] = dict(emitted_role)
        report["unclassified_fields"] = sorted(unclassified)
        report["n_unclassified"] = len(unclassified)
    return report


__all__ = [
    "ROLES",
    "ENVELOPE_FIELDS",
    "descriptors_for",
    "descriptor_catalog",
    "describe_field",
    "classify_field",
    "stamp_measured",
    "describe_summary",
    "coverage_report",
]
