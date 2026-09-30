"""detection_strength — the per-detection-KIND cutpoints behind `reliability.detection_strength` (#2329).

WHAT `detection_strength` MEANS, and why the cutpoints are MEASUREMENTS, not round numbers.
`reliability.detection_strength` (#2306) is an OPTIONAL, verdict-INERT (SK#2091) three-level ordinal —
`weak` / `moderate` / `strong` — carried ONLY on detection/abundance-kind properties (protein/RNA
windows, single-cell detection, surface density), OMITTED everywhere else (the byte-stable
conditional-key idiom). It answers ONE question: how strongly is the target DETECTED behind this
property's own detection datum? It is not a quality score and it does not rank properties; `weak`
detection is an honest statement that little signal sits above the detection floor, not a criticism
(governance.honest_degradation).

THE CUTPOINTS ARE NOT NEW NUMBERS. Every detection kind ALREADY has a calibrated detection
classification in its own method (or upstream classifier): the cutpoints that decide `weak/moderate/
strong` are that classification's OWN cuts, re-expressed on the shared three-level ordinal so a
protein-IHC read, a single-cell detection fraction and a surface copies-per-cell band speak ONE
vocabulary. Nothing here re-declares a cut; each scheme mirrors (imports, where the constant is
importable) the method's own boundary, so a drift in the method reds the pin rather than the emit —
exactly the powered_floors.py single-source discipline. This is a PURE PROJECTION of an already-
computed detection breakdown (governance.derivation_is_a_projection), never a re-binning.

THE THREE CALIBRATED KINDS (the detection/abundance domains #2306 names — presence / surface, and the
single-cell detection facet that feeds selectivity/surface):

  ihc_protein_presence_class   (antibody-IHC protein presence, tumor-presence)
      The datum is the UPSTREAM-computed `protein_presence_class` token (the data-catalog classifier
      `scripts/derive_hpa_pathology_cancer_ihc.py:_classify` bins `fraction_detected` at 0.33 / 0.66,
      documented on `contracts/cards/hpa-pathology-cancer-ihc.card.yaml` thresholds). Those cuts live
      in a SEPARATE repo, so the honest single source is the class TOKEN they already produce — we
      project it, never re-bin `fraction_detected` with a second copy of 0.33/0.66:
        ihc_detected_high -> strong · ihc_detected_moderate -> moderate · ihc_detected_low -> weak
        ihc_not_detected / data_unavailable -> None (nothing detected -> the key is OMITTED).
      The canonical case: CD274 IHC `n_high=1, n_medium=1, n_not_detected=10` of 12 -> fraction_detected
      0.167 -> `ihc_detected_low` -> `detection_strength: weak`.

  sc_malignant_detection_fraction   (single-cell malignant detection fraction)
      The datum is the numeric cross-donor median malignant detection fraction. Binned at the
      sc_tumor_expression_celltype method's OWN dropout-aware cuts (IMPORTED, never re-declared):
        >= MALIGNANT_BROADLY_DETECTED_MIN (0.5)  -> strong  (detected in most malignant cells)
        >= MALIGNANT_SUBSET_DETECTED_MIN (0.10)  -> moderate (a real expressing malignant subset)
        >  BROADLY_LOW_MAX (0.05)                -> weak    (low but non-trivial)
        <= BROADLY_LOW_MAX                        -> None    (effectively undetected -> key OMITTED).
      scRNA under-detects (dropout), so these sit BELOW bulk fraction cutpoints by the method's design.

  surface_absolute_density   (surface antigen copies-per-cell band)
      The datum is the measured absolute surface density (copies/cell). Classified by the
      surface_antigen_density_ladder method's OWN `_classify` (IMPORTED and CALLED, never re-declaring
      its 100 / 1000 / 10000 boundaries):
        high -> strong · moderate -> moderate · low -> weak · very_low / unmeasured -> None (OMITTED).

WHY A NONE (OMITTED) TIER RATHER THAN A FOURTH TOKEN. `detection_strength` is a THREE-state closed set
(the #2306-ratified shape; the enum's additivity clause refuses a fourth). Below the detection floor
there is nothing DETECTED to grade — the property's own value already carries "not detected" — so the
honest outcome is to OMIT the optional key (byte-stable), never to assert a fabricated `weak` on a
zero-detection read (governance.honest_degradation: absence OUTRANKS a naive measurement).

WHY SINGLE-SOURCED HERE, NOT IN THE CATALOG YET. Mirrors powered_floors.py: the catalog's machine-
readable `reliability` spec shape does not yet admit a detection-scheme declaration, so the cutpoints
live in code (single-sourced from each method) exactly as PR#2326 single-sourced the deriver's
constants. No detection/abundance property emits `reliability` yet (presence/selectivity/surface L2a
emission — #2212-#2214 — is not landed), so this calibration is exercised on synthetic anchors in unit
tests today, and connects to a live datum when those properties wire the facet.
"""

from __future__ import annotations

# Ordinal tokens — the exact governed reliability.enum.yaml detection_strength roster.
WEAK = "weak"
MODERATE = "moderate"
STRONG = "strong"

# Scheme identifiers (the value a property's `reliability` spec passes as `detection_strength_scheme`).
IHC_PROTEIN_PRESENCE_CLASS = "ihc_protein_presence_class"
SC_MALIGNANT_DETECTION_FRACTION = "sc_malignant_detection_fraction"
SURFACE_ABSOLUTE_DENSITY = "surface_absolute_density"

# ihc_protein_presence_class: a PURE projection of the upstream class token (cuts owned by the
# data-catalog classifier, documented on the IHC card). Tokens NOT in this map -> None (OMIT):
# `ihc_not_detected` (fraction 0) and `data_unavailable` are absence, not a gradable detection.
_IHC_CLASS_TO_STRENGTH = {
    "ihc_detected_high": STRONG,
    "ihc_detected_moderate": MODERATE,
    "ihc_detected_low": WEAK,
}

# surface_absolute_density: map the surface_antigen_density_ladder `_classify` band (its OWN
# copies/cell boundaries) onto the ordinal. `very_low` / `unmeasured` are below the detection floor.
_SURFACE_BAND_TO_STRENGTH = {
    "high": STRONG,
    "moderate": MODERATE,
    "low": WEAK,
}


def _ihc_strength(value) -> "str | None":
    """Project the upstream `protein_presence_class` token onto the ordinal. Unknown / not-detected /
    unavailable -> None (OMIT). No cut is re-declared here — the classifier owns the 0.33/0.66 cuts."""
    return _IHC_CLASS_TO_STRENGTH.get(value)


def _sc_strength(value) -> "str | None":
    """Bin the single-cell malignant detection fraction at the sc method's OWN dropout-aware cuts
    (imported, never re-declared). None / non-numeric / <= the undetected floor -> None (OMIT)."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    from onc_methods.sc_tumor_expression_celltype.stats import (
        BROADLY_LOW_MAX,
        MALIGNANT_BROADLY_DETECTED_MIN,
        MALIGNANT_SUBSET_DETECTED_MIN,
    )

    if value >= MALIGNANT_BROADLY_DETECTED_MIN:
        return STRONG
    if value >= MALIGNANT_SUBSET_DETECTED_MIN:
        return MODERATE
    if value > BROADLY_LOW_MAX:
        return WEAK
    return None


def _surface_strength(value) -> "str | None":
    """Classify the measured absolute surface density via the surface method's OWN `_classify`
    (imported and CALLED, never re-declaring its copies/cell boundaries), then map the band onto the
    ordinal. None / non-numeric / very_low / unmeasured -> None (OMIT)."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    from onc_methods.surface_antigen_density_ladder.read import _classify

    return _SURFACE_BAND_TO_STRENGTH.get(_classify(float(value)))


# scheme name -> the resolver for that detection kind. Mirrors powered_floors._CALIBRATED_FLOOR_SOURCES.
_SCHEME_RESOLVERS = {
    IHC_PROTEIN_PRESENCE_CLASS: _ihc_strength,
    SC_MALIGNANT_DETECTION_FRACTION: _sc_strength,
    SURFACE_ABSOLUTE_DENSITY: _surface_strength,
}


def detection_strength_for(scheme: "str | None", value) -> "str | None":
    """The `weak|moderate|strong` ordinal for a detection datum under a named scheme, or None (-> the
    optional `detection_strength` key is OMITTED).

    `None` is returned for an unknown/absent scheme, an absent/None value, or a value below the scheme's
    detection floor — every path degrades HONESTLY to omission, never a fabricated strength. Only a
    scheme that actually needs a method boundary triggers a (lazy) method import.
    """
    resolver = _SCHEME_RESOLVERS.get(scheme)
    if resolver is None:
        return None
    return resolver(value)


def calibrated_detection_schemes() -> "frozenset[str]":
    """The detection schemes that carry a calibrated cutpoint set — for the flip matrix and its teeth."""
    return frozenset(_SCHEME_RESOLVERS)
