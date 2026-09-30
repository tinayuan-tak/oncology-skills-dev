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
  * `powered`            — 'unmeasured' UNIFORMLY: no calibrated per-property-kind floor exists yet for
                           ANY 1a/1b property. `true`/`false` fire only once a floor is supplied (a
                           #2219-style calibration follow-on). This is the honest absence-discipline
                           outcome, not a stub.
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
  * `detection_strength` — OMITTED for every 1a/1b property. DEFERRED (#2306 follow-on): its cutpoints are
                           uncalibrated and no 1a/1b property is detection/abundance-kind, so the optional
                           key is not carried (the byte-stable conditional-key idiom).
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

    # detection_strength — DEFERRED (#2306 follow-on): cutpoints uncalibrated and no 1a/1b property is
    # detection/abundance-kind, so the OPTIONAL key is OMITTED (byte-stable conditional-key idiom).
    return out
