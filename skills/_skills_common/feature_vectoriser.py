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

import math
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
    per axis, keyed off the PRIMARY (first) frame's value_field — the headline metric the axis leads with.

    A primary frame carrying `atlas_numeric: False` is EXCLUDED (2026-09-12). The ruler registry and the
    atlas numeric registry were the same registry with no opt-out, so a card could not be given a display
    ruler without also minting an atlas feature — even when its gauged value is not monotone with "more
    supportive of the phenotype" and _DIR_SIGN below would therefore sign it wrongly for part of the corpus.
    Two measured cases: a mutation-SHAPE fraction (high missense = driver for an oncogene, passenger for a
    TSG — no single polarity exists) and a driver q-value (≈0 for every gene that has one, so the value is
    degenerate and the ::mask carries all the information). Excluding them keeps the ruler DISPLAYED and the
    geometry honest. Do NOT drop the flag to "simplify" — it is load-bearing for polarity correctness."""
    out = {}
    for mt, spec in SALIENCE_SPECS.items():
        rf = spec.get("reference_frame")
        primary = rf[0] if isinstance(rf, list) and rf else (rf if isinstance(rf, dict) else None)
        if isinstance(primary, dict) and primary.get("value_field") and primary.get("atlas_numeric") is not False:
            out[mt] = (primary["value_field"], spec.get("direction"))
    return out


def numeric_source_cards() -> dict:
    """{measurement_type: card_id} — the card whose summary is AUTHORITATIVE for each metered axis's numeric,
    read off the PRIMARY reference_frame's cut. The cut already single-sources a NAMED card threshold, so the
    card_id is declared exactly once and cannot drift away from the ruler it gauges.

    WHY this exists (2026-09-12): `measurement_type` is NOT unique across cards. 8 of the 32 metered axes are
    carried by 2–4 cards each (a pan-cancer arm plus a by-subtype panorama; Gygi plus ProCan protein panels;
    tumor, cell-line and single-cell concordance arms). A plain {measurement_type: summary} index therefore
    silently kept whichever card came LAST in the package, which over the 223-run corpus meant:
      · tumor_protein_abundance harvested 0/223 — tumor-protein-distribution-by-subtype (which has no
        protein_effect_size) clobbered tumor-protein-abundance-cptac, so the axis was dropped as sparse at
        build and left an ORPHAN ::mask in the frozen atlas;
      · cell_line_protein_abundance read ProCan's percentile although its ruler is cut against the Gygi card;
      · rna_protein_concordance let the 13-target single-cell arm outvote the 156-target cell-line arm.
    Governed by test_reference_frame_governance (every metered primary frame must name a card_id)."""
    out = {}
    for mt, spec in SALIENCE_SPECS.items():
        if mt not in numeric_feature_specs():
            continue
        rf = spec.get("reference_frame")
        primary = (rf[0] if isinstance(rf, list) and rf else rf) or {}
        cuts = [primary.get("cut")] if primary.get("cut") else (primary.get("cuts") or [])
        for cut in cuts:
            if isinstance(cut, dict) and cut.get("card_id"):
                out[mt] = cut["card_id"]
                break
    return out


def _num(v) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    # drop any NON-FINITE value → None (unmeasured). NaN was already dropped (f == f is False for NaN) but
    # ±inf slipped through (inf == inf is True): CPTAC ships protein_effect_size = +inf for genes with no
    # estimable normal contrast (protein_median_log2_normal = NaN), which is UNESTIMABLE, not a measured
    # effect — admitting it poisons the atlas column (nanmean → inf, PCA rejects) AND falsely sets the
    # measured-mask to 1. A non-finite number is not a feature value.
    return f if math.isfinite(f) else None


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


def _first_numeric(*vals) -> Optional[float]:
    for v in vals:
        n = _num(v)
        if n is not None:
            return n
    return None


def numeric_values_from_package(pkg: dict) -> dict:
    """Harvest {measurement_type: {value_field: number}} for every metered SALIENCE_SPECS axis from ONE
    composed evidence_package (build_atlas's per-run input). The metered numeric lives in one of three
    places in the package; _resolve_numerics checks them in order of ATTRIBUTABILITY (see its docstring):
      1. cards[].summary[value_field]        — the frame-named card first, then a sibling of the same
                                               measurement_type (the clean source; nearly all axes)
      2. synthesis.claim_vectors[*].claim_vector[*].evidence_atom.values[value_field]  — atom-carried numerics
      3. synthesis.evidence_capsules[*].capsules[*].n_basis[value_field]                — capsule n_basis
    (2 and 3 are flat, card-less maps, so they are used only for value_fields no other axis shares.)
    Absent everywhere → the axis is simply not in the result (→ mask 0 downstream). Best-effort, pure."""
    pkg = pkg or {}
    syn = pkg.get("synthesis") or {}
    cards = pkg.get("cards")
    clist = cards if isinstance(cards, list) else list(cards.values()) if isinstance(cards, dict) else []
    atom_values = _atom_values(
        [e.get("claim_vector") for e in (syn.get("claim_vectors") or {}).values() if isinstance(e, dict)]
    )
    n_basis: dict = {}
    for entry in (syn.get("evidence_capsules") or {}).values():
        for cap in ((entry or {}).get("capsules") or {}).values():
            nb = (cap or {}).get("n_basis") if isinstance(cap, dict) else None
            if isinstance(nb, dict):
                n_basis.update(nb)
    return _resolve_numerics(clist, atom_values, n_basis)


def numeric_values_from_sub_results(sub_results: dict) -> dict:
    """RUNTIME twin of numeric_values_from_package: harvest {mt: {value_field: number}} from the in-process
    fan-out `sub_results` (short -> r), mirroring the SAME two primary sources the package harvester uses so
    offline build == runtime query — (1) each sub-skill's own cards[].summary (r['cards'], resolved through
    the same card-attributed order) and (2) its synthesis_facet.claim_vector[*].evidence_atom.values.
    Both halves funnel through _resolve_numerics, so the card-attribution fix applies to both by
    construction. Best-effort, pure."""
    cards, cvs = [], []
    for r in (sub_results or {}).values():
        if not isinstance(r, dict):
            continue
        cards += [c for c in (r.get("cards") or []) if isinstance(c, dict)]
        facet = r.get("synthesis_facet") or {}
        if isinstance(facet.get("claim_vector"), dict):
            cvs.append(facet["claim_vector"])
    return _resolve_numerics(cards, _atom_values(cvs), {})


def _summaries_by_mt(cards_list) -> dict:
    """{measurement_type: [summary, ...]} in package order — a LIST, because several cards can share one
    measurement_type (see numeric_source_cards for the 8 metered axes where they do)."""
    out: dict = {}
    for c in cards_list:
        if isinstance(c, dict) and c.get("measurement_type"):
            out.setdefault(c["measurement_type"], []).append(c.get("summary") or {})
    return out


def _summaries_by_card_id(cards_list) -> dict:
    """{card_id: summary} — the attributable index the numeric resolution prefers."""
    return {c.get("card_id"): (c.get("summary") or {}) for c in cards_list if isinstance(c, dict) and c.get("card_id")}


def _atom_values(claim_vectors) -> dict:
    """Flatten every claim's evidence_atom.values across a list of claim_vector dicts (value_fields are
    ~unique across claims, so a flat map is an adequate fallback lookup)."""
    out: dict = {}
    for cv in claim_vectors:
        for claim in (cv or {}).values():
            vals = (claim or {}).get("evidence_atom", {}).get("values") if isinstance(claim, dict) else None
            if isinstance(vals, dict):
                out.update(vals)
    return out


def _resolve_numerics(cards_list, atom_values: dict, n_basis: dict) -> dict:
    """Per metered spec, resolve the axis numeric from the most ATTRIBUTABLE source available:

      1. the frame-NAMED card's summary — the card the ruler's cut is taken from (numeric_source_cards);
      2. any sibling card sharing the measurement_type, in package order — the named arm did not run for this
         target but a sibling arm measured the same quantity (ProCan when Gygi is absent);
      3. atom.values / capsule n_basis, but ONLY when the field name is unique across the metered specs.
         Those two are FLAT maps with no card attribution, so a name several axes share (`allgene_percentile`
         is the primary value_field of 3) cannot be attributed — refused rather than guessed. Unrefused, it
         imported ANOTHER axis's percentile for 17 of the 223 corpus targets.

    Step 2 keeps the harvest working for cards that carry no card_id at all (older/synthetic packages)."""
    summ_by_card = _summaries_by_card_id(cards_list)
    summ_by_mt = _summaries_by_mt(cards_list)
    named = numeric_source_cards()
    shared_fields = {vf for vf, n in _value_field_counts().items() if n > 1}
    out: dict = {}
    for mt, (vf, _dir) in numeric_feature_specs().items():
        val = _num(summ_by_card.get(named.get(mt) or "", {}).get(vf))
        if val is None:
            val = _first_numeric(*(s.get(vf) for s in summ_by_mt.get(mt, [])))
        if val is None and vf not in shared_fields:
            val = _first_numeric(atom_values.get(vf), n_basis.get(vf))
        if val is not None:
            out[mt] = {vf: val}
    return out


def _value_field_counts() -> dict:
    counts: dict = {}
    for vf, _dir in numeric_feature_specs().values():
        counts[vf] = counts.get(vf, 0) + 1
    return counts


def build_feature_vector(claim_vectors: dict, numeric_values: Optional[dict] = None) -> dict:
    """The extended atlas feature vector for ONE target: ordinal claim features (delegated to
    archetype_core.claim_features) merged with the polarity-signed numeric features + masks. Verdict
    features are not yet included (VERDICT_FEATURES_STATUS='deferred'). Deterministic; `None` = unmeasured.

    Pure over its inputs — the caller (build_atlas offline / archetype_core runtime) supplies the SAME
    harvested data so offline==runtime holds by construction."""
    feats = dict(claim_features(claim_vectors or {}))
    feats.update(numeric_features(numeric_values or {}))
    return feats
