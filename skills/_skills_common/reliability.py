"""reliability — the shared `_derive_reliability` deriver for the typed `reliability` facet.

Evidence-property architecture (epic claude-oncology-skills#1507); structure arc #2210; the #2306
rollout, STEP 2 (shared deriver + retrofit safety 1a & dependency 1b). The governance layer (STEP 1,
`contracts/vocabularies/reliability.enum.yaml` + `validate_reliability_enum.py` + the optional
`reliability` ENTRY_KEY in `validate_property_catalog.py`) landed first (PR #2311); this module is the
first EMITTER of the facet it governs.

WHAT THIS IS. `_derive_reliability` is a PURE PROJECTION over anchors the pipeline has ALREADY computed
(governance.derivation_is_a_projection): it never re-stores a datum that already lives in the entry's
`anchors`, and it never RECOMPUTES one. It is VERDICT-INERT (SK#2091) — it feeds no rule and moves no
cut. Absence degrades HONESTLY (governance.honest_degradation): a missing n-anchor omits `n_effective`
and reads `powered: unmeasured`; a measured property with no typed confound/artifact carries the EMPTY
LIST, never a fabricated "fine".

THE FACET SHAPE is locked by issue #2306's ratified comment and governed token-by-token by
reliability.enum.yaml. This module owns only the DERIVATION; it emits only governed tokens.

WHAT EMITS AT THIS STEP, HONESTLY (1a safety + 1b dependency):
  * `n_effective`        — projected from the property's designated n-anchor; OMITTED where the property
                           has no sample-N anchor (per-gene MLE / p-value / outcome-count / tissue-breadth
                           count — see the per-recipe `reliability` spec's `n_effective_absent_reason`).
  * `powered`            — tri-state. `true`/`false` where the property's KIND carries a calibrated floor
                           (#2327: the CRISPR/RNAi panel size and the partner-deficient stratum size —
                           each the property's OWN method admissibility guard, single-sourced from
                           onc_methods.reliability_calibration.powered_floors) AND `n_effective` resolved;
                           else the 'unmeasured' string sentinel (absence-discipline). Every safety kind
                           and the other dependency kinds stay 'unmeasured' BY calibration decision —
                           evidence counts / fixed reference panels are not power denominators (see
                           powered_floors.py::POWERED_FLOOR_UNMEASURED). A spec may also pass an explicit
                           `powered_floor`, which wins over the table.
  * `confound_flags`     — [] for every 1a/1b property: safety/dependency anchors carry no purity-confound
                           r. The `microenvironment_weighted` path is implemented and unit-tested on a
                           SYNTHETIC anchor (r <= CONFOUND_R), so it is proven though it does not fire here.
  * `artifact_flags`     — [] for every 1a/1b property: no 1a/1b anchor names a `floor_tie_anchor` (none
                           of their properties resolve from `allgene_percentile`). The
                           `floor_tie_percentile` path is implemented and unit-tested against a
                           SYNTHETIC anchor (the upstream `is_floor_tie` flag now emitted at
                           `build_tumor_rank.py`/`build_depmap_rank.py` and surfaced through
                           `lookup.py`, #2328), so it is proven though it does not fire on any 1a/1b
                           property today.
  * `detection_strength` — OMITTED for every 1a/1b property (none is detection/abundance-kind, so no
                           1a/1b spec names a `detection_strength_scheme`). Its cutpoints are now
                           CALIBRATED (#2329): a property whose spec names a `detection_strength_scheme`
                           + `detection_strength_anchor` projects that anchor's detection datum onto the
                           `weak|moderate|strong` ordinal via
                           onc_methods.reliability_calibration.detection_strength (each scheme mirrors
                           its own method's detection cuts, single-sourced). Below the detection floor
                           (or absent) -> the optional key is OMITTED (byte-stable conditional-key
                           idiom), never a fabricated strength. Exercised on SYNTHETIC anchors today
                           (presence/selectivity/surface L2a emission — #2212-#2214 — is not landed),
                           exactly like the floor-tie path.
"""

from __future__ import annotations

_MICROENVIRONMENT_WEIGHTED = "microenvironment_weighted"
_FLOOR_TIE_PERCENTILE = "floor_tie_percentile"


def _confound_r_cut() -> float:
    """The purity-confound cut, reused (never re-declared) from methods so a second copy cannot drift.

    Imported lazily inside the deriver rather than at module top: only a property whose spec NAMES a
    purity-confound anchor touches methods, so no 1a/1b production path (none names one) imports it, and
    `_skills_common` test collection never depends on `onc_methods` being importable to load this module.
    """
    from onc_methods.expression_purity_confound.read import CONFOUND_R

    return CONFOUND_R


def _powered_floor_for(n_effective_anchor: "str | None") -> "int | None":
    """The calibrated per-property-kind `powered` floor for a spec's n-anchor, or None (-> 'unmeasured').

    Single-sourced (never re-declared) from onc_methods.reliability_calibration.powered_floors (#2327),
    which mirrors each property's OWN method admissibility guard (CRISPR/RNAi panel size, partner-deficient
    stratum size). Imported LAZILY — exactly like `_confound_r_cut` — so the deriver's import path never
    pulls methods unless a calibrated floor is actually resolved (an UNMEASURED kind returns None without
    importing anything). An unavailable calibration source degrades HONESTLY to None -> 'unmeasured', never
    a crash (governance.honest_degradation): `powered` is verdict-inert, so a missing source is an absence,
    not a failure.
    """
    if not n_effective_anchor:
        return None
    try:
        from onc_methods.reliability_calibration.powered_floors import powered_floor_for
    except ImportError:
        return None
    return powered_floor_for(n_effective_anchor)


def _detection_strength_for(scheme: "str | None", value) -> "str | None":
    """The calibrated `weak|moderate|strong` ordinal for a detection datum under `scheme`, or None.

    Single-sourced (never re-declared) from onc_methods.reliability_calibration.detection_strength
    (#2329), where each scheme mirrors its own detection method's classification cuts. Imported LAZILY —
    exactly like `_powered_floor_for` — so no production path that names no `detection_strength_scheme`
    (every 1a/1b property) pulls methods, and an unavailable calibration source degrades HONESTLY to
    None -> the optional key is OMITTED (governance.honest_degradation), never a crash: detection_strength
    is verdict-inert, so a missing source is an absence, not a failure.
    """
    if not scheme:
        return None
    try:
        from onc_methods.reliability_calibration.detection_strength import detection_strength_for
    except ImportError:
        return None
    return detection_strength_for(scheme, value)


# NO L2b island attachment at this step. The locked #2306 shape derives an L2b arm's reliability FROM
# THAT ARM'S OWN anchors / `retained_quantitative`, and says the island does not RESTATE the L2a values.
# The safety/dependency concordance islands (`_essentiality_concordance_claim`,
# `_normal_liability_concordance_claim`) read only categorical per-source DIRECTION tokens — they carry
# NO per-arm anchor list — so there is nothing to derive FROM, and the honest result is OMISSION of the
# facet (byte-stable), never an empty `{powered: unmeasured, [], []}` that would merely restate the L2a
# `powered`. Per-arm L2b reliability lands when the facet reaches the presence-style islands that DO
# carry per-arm anchors/`retained_quantitative` (a later #2306 step). See both island builders.


def _derive_reliability(anchors, spec: dict) -> dict:
    """Project already-computed anchors into the typed, verdict-inert `reliability` facet (#2306).

    Parameters
    ----------
    anchors : iterable of {'field', 'value', ...} anchor dicts
        The entry's / arm's RETAINED quantitative anchors, exactly as projected upstream. Read-only;
        never recomputed. An L2b island with no quantitative anchors passes an empty iterable.
    spec : mapping (the per-property `reliability` spec attached to each recipe). Recognised keys, all
        optional:
          n_effective_anchor     : the field name whose value is the effective N. None/absent -> the key
                                    is OMITTED and `powered` is 'unmeasured'.
          powered_floor          : a CALIBRATED per-property-kind N floor. None/absent -> 'unmeasured'
                                    (NO floor is calibrated for any 1a/1b property at this step).
          purity_confound_anchor : the field name of an expression-purity r. When present with a value
                                    r <= CONFOUND_R, appends `microenvironment_weighted`. None/absent for
                                    every 1a/1b property (their anchors carry no purity r) -> [].
          floor_tie_anchor       : the field name of the upstream `is_floor_tie` boolean (#2297/#2328,
                                    e.g. `allgene_percentile_is_floor_tie` from
                                    `allgene_percentile_precompute.lookup`). When present and truthy,
                                    appends `floor_tie_percentile`. A PURE PROJECTION of the upstream
                                    flag — never recomputed here (governance.derivation_is_a_projection).
                                    None/absent for every 1a/1b property (none resolve from
                                    `allgene_percentile`) -> [].
          detection_strength_scheme : the calibration scheme for a detection/abundance-kind property
                                    (`ihc_protein_presence_class` / `sc_malignant_detection_fraction` /
                                    `surface_absolute_density`; see
                                    onc_methods.reliability_calibration.detection_strength). None/absent
                                    for every non-detection property -> the OPTIONAL `detection_strength`
                                    key is OMITTED (byte-stable).
          detection_strength_anchor : the field name of the detection datum the scheme reads (the
                                    upstream class token or the numeric detection value). Read from the
                                    same `by_field` projection; a value below the scheme's detection
                                    floor, absent, or an unknown scheme -> key OMITTED.

    Returns the `reliability` dict. `powered`, `confound_flags` and `artifact_flags` are always present
    (required by the enum); `n_effective` and `detection_strength` are conditionally carried.
    """
    by_field = {a["field"]: a.get("value") for a in anchors if isinstance(a, dict) and "field" in a}

    out: dict = {}

    # n_effective — projected int from the designated anchor; OMITTED when the anchor is absent/None
    # (honest_degradation). A bool is not a count and is rejected defensively.
    n_anchor = spec.get("n_effective_anchor")
    n_eff = by_field.get(n_anchor) if n_anchor else None
    if isinstance(n_eff, (int, float)) and not isinstance(n_eff, bool):
        out["n_effective"] = int(n_eff)

    # powered — tri-state. Boolean true/false ONLY when n_effective is present AND a calibrated floor is
    # supplied; else the 'unmeasured' STRING sentinel (absence OUTRANKS a naive "powered"). No 1a/1b
    # property supplies a floor today, so this is 'unmeasured' uniformly.
    floor = spec.get("powered_floor")
    if floor is None:
        floor = _powered_floor_for(spec.get("n_effective_anchor"))
    if "n_effective" in out and floor is not None:
        out["powered"] = out["n_effective"] >= floor
    else:
        out["powered"] = "unmeasured"

    # confound_flags — default []. microenvironment_weighted iff a purity-confound r anchor is present
    # with r <= CONFOUND_R (reused from methods). No 1a/1b anchor carries a purity r -> [] for all.
    confound_flags: list = []
    purity_anchor = spec.get("purity_confound_anchor")
    if purity_anchor:
        r = by_field.get(purity_anchor)
        if isinstance(r, (int, float)) and not isinstance(r, bool) and r <= _confound_r_cut():
            confound_flags.append(_MICROENVIRONMENT_WEIGHTED)
    out["confound_flags"] = confound_flags

    # artifact_flags — default []. floor_tie_percentile (#2297/#2328) PROJECTS the upstream
    # is_floor_tie flag (never recomputed here): appended iff the spec names a floor_tie_anchor AND
    # that anchor's value is truthy. No 1a/1b anchor names one today -> [] for all.
    artifact_flags: list = []
    floor_tie_anchor = spec.get("floor_tie_anchor")
    if floor_tie_anchor and bool(by_field.get(floor_tie_anchor)):
        artifact_flags.append(_FLOOR_TIE_PERCENTILE)
    out["artifact_flags"] = artifact_flags

    # detection_strength — OPTIONAL, detection/abundance-kind properties only (#2329). PROJECTS the
    # property's own detection datum (an upstream class token or a numeric detection value) onto the
    # weak|moderate|strong ordinal via the calibrated, single-sourced scheme the spec names — never a
    # recompute. OMITTED (byte-stable) when the spec names no scheme, the anchor is absent, or the datum
    # is below the scheme's detection floor (honest_degradation: absence OUTRANKS a fabricated strength).
    strength = _detection_strength_for(
        spec.get("detection_strength_scheme"), by_field.get(spec.get("detection_strength_anchor"))
    )
    if strength is not None:
        out["detection_strength"] = strength
    return out


# `_derive_reliability` keeps its leading underscore for history, but it is a DE-FACTO PUBLIC entrypoint:
# it is the shared deriver imported cross-module by every emitter of the typed `reliability` facet
# (source_properties_core + the selectivity/genomic/surface claim modules). `__all__` makes that
# intent explicit (#2382) so the underscore no longer reads as "do not import me". The other names here
# (`_powered_floor_for`, `_detection_strength_for`, `_confound_r_cut`, `_detection_strength_for`) stay
# genuinely module-private.
__all__ = ["_derive_reliability"]
