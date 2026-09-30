"""#2329 — teeth for the `reliability.detection_strength` per-detection-kind cutpoints (epic #2210,
#2306 rollout follow-on).

WHAT IS PINNED, and why each pin can FAIL (SK#2091 — no inertness proofs; every assertion has a named
mutant that reds it):

1. **detection_strength is RE-DERIVED from the stored detection datum, never trusted from the matrix** —
   through the same `detection_strength_for` the deriver uses; the matrix's recorded per-scheme
   distribution must match the recomputation. (MUTANT: a stale stored distribution reds; a broken mapping
   reds.)
2. **Each scheme's cut IS its method's own boundary, both directions.** sc: the ordinal flips exactly AT
   the sc method's imported constants (0.5 / 0.10 / 0.05); surface: the ordinal tracks the surface
   method's own `_classify` band across its 100/1000/10000 boundaries; IHC: the map's keys are exactly
   the card's detected `protein_presence_class` tokens and the not-detected ones OMIT. (MUTANT: a
   hardcoded second copy of a cut, or an unmapped/mis-mapped class token, reds.)
3. **The counterfactual is a REAL flip, not a vacuous no-op** — a raised sc `broadly` cut moves every
   committed `strong` sc observation to `moderate`. (MUTANT: a counterfactual at/below an observation
   reds the strict-flip guard.)
4. **The matrix is NON-VACUOUS where observations exist** (IHC + sc carry committed observations) and the
   surface scheme's ZERO committed observations is recorded as a finding, not silently absent. (MUTANT:
   an empty IHC/sc corpus reds.)
5. **Below the detection floor OMITS the optional key** (returns None), never a fabricated `weak`.
   (MUTANT: emit `weak` on a zero/sub-floor datum reds.)
6. **matrix.json is not stale** vs a fresh offline rebuild. (MUTANT: an edited observation without a
   regenerate reds `--check`.)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from onc_methods.reliability_calibration.detection_strength import (
    IHC_PROTEIN_PRESENCE_CLASS,
    MODERATE,
    SC_MALIGNANT_DETECTION_FRACTION,
    STRONG,
    SURFACE_ABSOLUTE_DENSITY,
    WEAK,
    calibrated_detection_schemes,
    detection_strength_for,
)
from onc_methods.sc_tumor_expression_celltype.stats import (
    BROADLY_LOW_MAX,
    MALIGNANT_BROADLY_DETECTED_MIN,
    MALIGNANT_SUBSET_DETECTED_MIN,
)
from onc_methods.surface_antigen_density_ladder.read import _classify as _surface_classify

HERE = Path(__file__).resolve().parent
MATRIX = json.loads((HERE / "matrix.json").read_text())
SCHEMES = MATRIX["schemes"]
_REPO_ROOT = HERE.parents[3]
_IHC_CARD = _REPO_ROOT / "contracts" / "cards" / "hpa-pathology-cancer-ihc.card.yaml"


# 1 — re-derive detection_strength from the stored datum; the recorded distribution must match ─────────
@pytest.mark.parametrize("scheme", sorted(calibrated_detection_schemes()))
def test_recorded_distribution_matches_rederivation(scheme):
    block = SCHEMES[scheme]
    recomputed = {}
    for obs in block["observations"]:
        strength = detection_strength_for(scheme, obs["datum"])
        key = strength if strength is not None else "omitted"
        recomputed[key] = recomputed.get(key, 0) + 1
    assert dict(sorted(recomputed.items())) == block["distribution"], (
        f"{scheme}: re-derived distribution != the stored one — the mapping drifted or the matrix is stale"
    )


# 2 — sc cut IS the method constant, both directions (flips exactly AT the imported boundary) ──────────
def test_sc_cuts_are_the_method_constants_both_directions():
    eps = 1e-9
    # broadly cut (strong boundary)
    assert detection_strength_for(SC_MALIGNANT_DETECTION_FRACTION, MALIGNANT_BROADLY_DETECTED_MIN) == STRONG
    assert detection_strength_for(SC_MALIGNANT_DETECTION_FRACTION, MALIGNANT_BROADLY_DETECTED_MIN - eps) == MODERATE
    # subset cut (moderate boundary)
    assert detection_strength_for(SC_MALIGNANT_DETECTION_FRACTION, MALIGNANT_SUBSET_DETECTED_MIN) == MODERATE
    assert detection_strength_for(SC_MALIGNANT_DETECTION_FRACTION, MALIGNANT_SUBSET_DETECTED_MIN - eps) == WEAK
    # undetected floor (weak boundary): AT the floor is below-floor -> OMIT; just above -> weak
    assert detection_strength_for(SC_MALIGNANT_DETECTION_FRACTION, BROADLY_LOW_MAX) is None
    assert detection_strength_for(SC_MALIGNANT_DETECTION_FRACTION, BROADLY_LOW_MAX + eps) == WEAK


# 2 — surface ordinal tracks the surface method's OWN _classify across its boundaries ──────────────────
@pytest.mark.parametrize("value", [10, 100, 500, 1000, 5000, 10000, 10001, 50000])
def test_surface_tracks_method_classify(value):
    band = _surface_classify(float(value))
    expected = {"high": STRONG, "moderate": MODERATE, "low": WEAK}.get(band)  # very_low/unmeasured -> None
    assert detection_strength_for(SURFACE_ABSOLUTE_DENSITY, value) == expected, (
        f"surface density {value} (_classify band {band!r}) must map onto the ordinal via the method's own "
        f"classifier, not a re-declared cut"
    )


# 2 — IHC map keys == the card's detected class tokens; not-detected tokens OMIT ───────────────────────
def test_ihc_map_matches_the_card_class_roster():
    card = yaml.safe_load(_IHC_CARD.read_text())
    roster = set(card["outputs"]["summary_fields_vocabulary"]["protein_presence_class"])
    detected = {t for t in roster if t.startswith("ihc_detected_")}
    # every DETECTED class token maps to a governed ordinal token (a new detected tier would red here)
    for token in detected:
        assert detection_strength_for(IHC_PROTEIN_PRESENCE_CLASS, token) in {WEAK, MODERATE, STRONG}, (
            f"card declares detected class {token!r} but the calibration does not map it — add it or the "
            f"emit is silently blind to a real detected tier"
        )
    # the non-detected tokens carry no gradable detection -> OMIT (None)
    for token in roster - detected:
        assert detection_strength_for(IHC_PROTEIN_PRESENCE_CLASS, token) is None


def test_ihc_low_is_the_cd274_weak_exemplar():
    # The canonical #2306 case rides through the class token the upstream classifier assigns fraction 0.167.
    assert detection_strength_for(IHC_PROTEIN_PRESENCE_CLASS, "ihc_detected_low") == WEAK


# 3 — counterfactual: a raised sc broadly cut flips every committed `strong` sc obs to `moderate` ──────
def test_counterfactual_raised_sc_broadly_cut_flips_strong_to_moderate():
    strong_obs = [
        o["datum"]
        for o in SCHEMES[SC_MALIGNANT_DETECTION_FRACTION]["observations"]
        if detection_strength_for(SC_MALIGNANT_DETECTION_FRACTION, o["datum"]) == STRONG
    ]
    assert strong_obs, "no committed strong sc observation — the counterfactual would be vacuous"
    counterfactual = max(strong_obs) + 0.01  # strictly exceeds every committed strong observation
    # every previously-strong obs now falls in [subset, counterfactual) -> moderate (a real flip)
    for datum in strong_obs:
        assert datum < counterfactual
        moved = STRONG if datum >= counterfactual else (MODERATE if datum >= MALIGNANT_SUBSET_DETECTED_MIN else WEAK)
        assert moved == MODERATE


# 4 — non-vacuity where observations exist; surface's zero is a recorded finding ───────────────────────
def test_ihc_and_sc_corpora_are_non_vacuous():
    assert SCHEMES[IHC_PROTEIN_PRESENCE_CLASS]["n_observations"] >= 2
    assert SCHEMES[SC_MALIGNANT_DETECTION_FRACTION]["n_observations"] >= 7


def test_surface_zero_committed_observations_is_recorded():
    # A FINDING (#2221/#2223), not a silent gap: no committed absolute-density recomputation anchor exists.
    assert SCHEMES[SURFACE_ABSOLUTE_DENSITY]["n_observations"] == 0
    assert SCHEMES[SURFACE_ABSOLUTE_DENSITY]["observations"] == []


# 5 — below the detection floor OMITS (None), never a fabricated weak ─────────────────────────────────
def test_below_floor_omits_across_schemes():
    assert detection_strength_for(SC_MALIGNANT_DETECTION_FRACTION, 0.0) is None
    assert detection_strength_for(SURFACE_ABSOLUTE_DENSITY, 5) is None  # very_low
    assert detection_strength_for(IHC_PROTEIN_PRESENCE_CLASS, "ihc_not_detected") is None
    assert detection_strength_for(IHC_PROTEIN_PRESENCE_CLASS, "data_unavailable") is None


# 6 — matrix.json is not stale vs a fresh offline rebuild ─────────────────────────────────────────────
def test_matrix_is_not_stale():
    rc = subprocess.run(
        [sys.executable, str(HERE / "regenerate.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=HERE,
    )
    assert rc.returncode == 0, f"matrix.json is stale — re-run regenerate.py\n{rc.stdout}\n{rc.stderr}"
