"""SK#1825 — the TPHP DIA-MS TUMOR ARM as the 2nd `bulk_protein_ms/tumor` platform.

The deliverable of this file is MUTATION TEETH, not a test count. Three things can go wrong with a
second arm, and each gets a tooth that reds on the specific mutation:

  T1  THE ARM IS NOT ACTUALLY WIRED. Dropping the card from run.py CARDS / CARD_CONTEXT, or from
      presence_claims._MS_PRESENCE_SOURCES, must red — not silently degrade to "CPTAC-only, same as
      before". `test_tooth_dropping_the_tphp_arm_reds_*` fail on exactly that removal, and
      `test_tooth_a_tphp_only_target_loses_its_ms_read_without_the_arm` proves the wiring is what
      BUYS the read (the counterfactual, not just the presence of a string in a list).

  T2  A MISSING COHORT READS AS A MEASURED NEGATIVE. This is the failure mode the issue names, and the
      one with teeth in both directions. 22 carcinoma cohorts arrive, several with NO CPTAC counterpart
      (gallbladder, laryngeal, GIST, testis, fallopian-tube, thymoma) — so BOTH paths are live: the
      NEW-COVERAGE path (a cohort TPHP has and CPTAC does not) and the STILL-NO-COVERAGE path (neither
      has it). `test_tooth_every_no_coverage_shape_is_a_gap_never_a_measured_negative` parametrizes
      EVERY supply path to a gap — unmapped indication, gene absent, pan-cancer-extremum row, zero
      detection on an underpowered arm, null fields — and asserts each is `(False, None)`, i.e. a GAP,
      never `(True, False)`. Flipping any one of them to a measured absence reds.

  T3  THE SECOND ARM BUYS FALSE CORROBORATION. TPHP is corroboration-ineligible on TWO grounds — it is
      mass-spec (shares CPTAC's single modality arm) and its NORMAL arm IS the TPHP body atlas that
      `normal-tissue-protein-abundance-tphp` summarises (ONE DIA-MS measurement read twice, per the
      card header's mandate to collapse on `normal_arm_source`). The corroboration teeth assert that a
      resolved TPHP read never raises `corroborating_independent_arm_count`, never lifts
      `corroboration` across `CORROBORATION_ARM_FLOOR`, and that the collapse is declared from the DATA.

Plus the measurement the issue's acceptance criteria demand: VERDICT DELTA. `test_verdict_delta_*`
replays BOTH committed dossiers (EPCAM/COADREAD positive, CD19/COADREAD negative) through the REAL
run.py in three TPHP states — card absent, card resolved-DETECTED, card resolved-NOT-detected — and
asserts `presence_verdict`, `presence_verdict_by_modality` and the whole decision spine are
BYTE-IDENTICAL across all three. That is the verdict delta: measured, and zero. Only additive keys
(`headline.tphp_tumor_presence` and the claim-vector `source_support` record) may differ.

TUMOR ARM ONLY is itself a tooth: `test_tooth_tumor_vs_normal_contrast_never_leaks_into_presence`
feeds a `strong_down` contrast on a protein that IS detected in tumor and requires the presence read to
stay DETECTED. A tumor-vs-normal window means "lower than the body-atlas normal", not "absent from
tumor"; letting the contrast arm in would manufacture a protein-absent presence claim out of a
selectivity fact.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
import yaml
from _test_support import load_run_py

SKILL_DIR = Path(__file__).resolve().parent.parent
RUN_PY = SKILL_DIR / "scripts" / "run.py"
FIXTURES = SKILL_DIR / "tests" / "fixtures"

TPHP_CARD = "tumor-vs-normal-protein-abundance-tphp"
CPTAC_CARD = "tumor-protein-abundance-cptac"
TPHP_NORMAL_CARD = "normal-tissue-protein-abundance-tphp"
MS_BUCKET = ("bulk_protein_ms", "tumor")


# ── substrate ────────────────────────────────────────────────────────────────────────────────────
# A REALISTIC resolved TPHP tumor-arm row: every field the card declares, with the reader's own names
# (methods/onc_methods/tphp_tumor_vs_normal_protein/read.py::_row_to_summary). Built as a factory so a
# test mutates ONE field and nothing else — the per-field attribution the teeth depend on.
def _tphp_row(**over):
    row = {
        "protein_expression_class": "modest_up",
        "protein_effect_size": 0.72,
        "protein_median_log2_tumor": 21.4,
        "protein_median_log2_normal": 20.7,
        "protein_p_value": 0.0007,
        "protein_bh_q_value": 0.012,
        "n_tumor_samples": 11,
        "n_normal_samples": 8,
        "n_tumor_samples_total": 12,
        "n_normal_samples_total": 9,
        "protein_detection_rate_tumor": 11 / 12,
        "protein_detection_rate_normal": 8 / 9,
        "protein_detection_complete": False,
        "normal_arm_source": "body_atlas_same_organism_part",
        "cohort_pick_basis": "indication_mapped",
        "cohort": "gallbladder carcinoma",
        "tissue": "gallbladder",
        "uniprot_ac": "P16422",
        "stat_test_used": "welch_unpaired_tumor_vs_body_atlas_normal_same_organism_part",
        "method_version": "tphp_tumor_vs_normal_protein/1.1.0",
    }
    row.update(over)
    return row


def _empty_tphp_row(**over):
    """The reader's honest `data_unavailable` row (`read.py::_empty`): every declared field PRESENT,
    numerics None, class data_unavailable, the three provenance tokens null. This is what an unmapped
    indication or an absent gene returns — the shape that must never read as a measured zero."""
    row = {k: None for k in _tphp_row()}
    row["protein_expression_class"] = "data_unavailable"
    row.update(over)
    return row


@pytest.fixture(scope="module")
def pc():
    import _skills_common.presence_claims as m

    return m


@pytest.fixture(scope="module")
def run_mod():
    return load_run_py(SKILL_DIR, "_tp_run_tphp_arm")


# ── T1: the arm is wired, and the wiring is what buys the read ────────────────────────────────────
def test_tooth_dropping_the_tphp_arm_reds_the_card_roster(run_mod):
    """REDS IF the card is removed from CARDS or re-bucketed. The bucket must be the SAME
    `bulk_protein_ms/tumor` bucket the incumbent CPTAC card occupies — a second ARM in one bucket, the
    ProCan pattern — not a new bucket of its own (a new bucket would enter ALL_CONTEXTS and emit a new
    sub-verdict key, which is a spine change, not an additive one)."""
    assert TPHP_CARD in run_mod.CARDS, (
        f"{TPHP_CARD} is not in run.py CARDS — the TPHP tumor arm is unwired, so the 22 carcinoma "
        "cohorts (several with no CPTAC counterpart) reach no presence surface at all"
    )
    assert run_mod.CARD_CONTEXT[TPHP_CARD] == MS_BUCKET
    assert run_mod.CARD_CONTEXT[CPTAC_CARD] == MS_BUCKET, "the two tumor MS platforms must share ONE bucket"
    assert MS_BUCKET in run_mod.ALL_CONTEXTS and len(set(run_mod.ALL_CONTEXTS)) == len(run_mod.ALL_CONTEXTS)


def test_tooth_dropping_the_tphp_arm_reds_the_ms_source_roster(pc):
    """REDS IF the card is removed from `_MS_PRESENCE_SOURCES`, or demoted below the cell-line siblings.

    The ORDER is load-bearing and is the whole point of the issue: TPHP shares CPTAC's patient-tumor
    GRAIN, so when CPTAC is a gap a TPHP patient-tumor read must supply the MS arm's value in preference
    to a DepMap/ProCan CELL-LINE panel. Demoting it behind the cell-line siblings would silently keep
    a cell-line read as the tumor-presence MS arm in exactly the 22 cohorts this issue exists to serve."""
    keys = [k for k, _cid, _l in pc._MS_PRESENCE_SOURCES]
    assert keys[0] == "cptac_protein", "CPTAC remains the arm-supplying primary"
    assert keys[1] == "tphp_tumor_protein", (
        f"MS source preference order is {keys} — the TPHP tumor arm must sit SECOND, ahead of the "
        "cell-line siblings, because it shares CPTAC's patient-tumor grain"
    )
    assert set(keys[2:]) == {"gygi_protein", "procan_protein"}
    assert dict((k, cid) for k, cid, _l in pc._MS_PRESENCE_SOURCES)["tphp_tumor_protein"] == TPHP_CARD


def test_tooth_a_tphp_only_target_loses_its_ms_read_without_the_arm(pc):
    """THE COUNTERFACTUAL TOOTH — the one that proves the wiring buys something.

    A target in a TPHP-only cohort (gallbladder: no CPTAC, no cell-line MS) with an antibody-IHC read.
    WITH the TPHP arm the mass-spec layer resolves and is named in `source_support`; with the card
    withheld the SAME dossier has NO mass-spec source at all. If a refactor makes the TPHP read inert,
    the `withheld == wired` comparison below reds."""
    base = {"hpa-pathology-cancer-ihc": {"protein_presence_class": "ihc_detected_moderate", "n_high": 4, "n_medium": 3}}
    wired = pc._protein_presence_concordance_claim({**base, TPHP_CARD: _tphp_row()})
    withheld = pc._protein_presence_concordance_claim(dict(base))

    def _ms_resolved(claim):
        return sorted(
            s["source"] for s in claim["source_support"] if s.get("dependence_group") == "mass_spec" and s["resolved"]
        )

    assert _ms_resolved(withheld) == [], "no MS source should resolve for a TPHP-only target without the arm"
    assert _ms_resolved(wired) == ["tphp_tumor_protein"], (
        "the TPHP tumor arm must supply the mass-spec layer when CPTAC is a gap — this is the "
        "coverage-breadth payoff of the issue"
    )
    # and the read is LEGIBLE, not data_unavailable, on the protein-in-tumor surface
    rec = next(s for s in wired["source_support"] if s["source"] == "tphp_tumor_protein")
    assert rec["value"] == "protein_detected" and rec["present"] is True
    assert withheld["concordance_class"] == "single_source_only"
    assert wired["concordance_class"] == "protein_presence_concordant"


def test_tooth_cptac_still_outranks_tphp_as_the_arm_value_supplier(pc):
    """The new arm must not DISPLACE the incumbent: when CPTAC resolves, CPTAC supplies the arm value
    and TPHP is recorded as evidence beside it. Reds if the preference order is inverted."""
    c = {
        "hpa-pathology-cancer-ihc": {"protein_presence_class": "ihc_not_detected"},
        CPTAC_CARD: {"allgene_percentile_class": "top_decile"},
        TPHP_CARD: _tphp_row(),
    }
    claim = pc._protein_presence_concordance_claim(c)
    assert claim["concordance_support"] == {"detected_in": "mass_spec", "not_detected_in": "antibody"}
    srcs = {s["source"]: s for s in claim["source_support"]}
    assert srcs["cptac_protein"]["resolved"] is True and srcs["cptac_protein"]["corroboration_eligible"] is True
    assert srcs["tphp_tumor_protein"]["resolved"] is True, "TPHP is still recorded as evidence beside CPTAC"
    assert srcs["tphp_tumor_protein"]["corroboration_eligible"] is False


# ── T2: absence falls through to the conservative value, on EVERY supply path ──────────────────────
_NO_COVERAGE_SHAPES = {
    # the reader's honest data_unavailable row — unmapped indication, or the gene absent from the product
    "empty_data_unavailable_row": _empty_tphp_row(),
    # a pan-cancer extremum row: a REAL measurement, but of ANOTHER TISSUE. Reading it as this
    # indication's protein-presence would attribute a different cohort's detection to this indication
    # (card warning `tphp_tvn_pan_cancer_extremum`). Detection rate is high here ON PURPOSE.
    "pan_cancer_extremum_complete": _tphp_row(
        cohort_pick_basis="pan_cancer_max_abs_log2fc_detection_complete", cohort="thymoma", tissue="thymus"
    ),
    "pan_cancer_extremum_incomplete": _tphp_row(
        cohort_pick_basis="pan_cancer_max_abs_log2fc_no_detection_complete_row", cohort="testis germ cell tumour"
    ),
    # null basis with otherwise-populated fields — a half-built row must not resolve either
    "null_cohort_pick_basis": _tphp_row(cohort_pick_basis=None),
    # ZERO detections on an arm too small to power an absence: DIA censoring, not evidence of absence
    "zero_detection_underpowered_arm": _tphp_row(
        n_tumor_samples=0, n_tumor_samples_total=4, protein_detection_rate_tumor=0.0
    ),
    "zero_detection_unknown_arm_size": _tphp_row(
        n_tumor_samples=0, n_tumor_samples_total=None, protein_detection_rate_tumor=0.0
    ),
    # non-numeric / absent detection rate
    "null_detection_rate": _tphp_row(protein_detection_rate_tumor=None),
    "missing_detection_rate_key": {k: v for k, v in _tphp_row().items() if k != "protein_detection_rate_tumor"},
    # a BOOL is not a number (pandas/JSON round-trips make this reachable); True must not read as 1.0
    "bool_detection_rate": _tphp_row(protein_detection_rate_tumor=True),
    "empty_summary": {},
}


@pytest.mark.parametrize("shape", sorted(_NO_COVERAGE_SHAPES))
def test_tooth_every_no_coverage_shape_is_a_gap_never_a_measured_negative(pc, shape):
    """THE CENTRAL TOOTH. Every no-coverage supply path must be an UNMEASURED GAP — `(False, None)` —
    never a measured zero / `absent` / `not_detected`. Flipping any one of these to `(True, False)`
    reds here, and that is the silent-false-absence bug this issue warns about: a cohort TPHP simply
    does not cover would otherwise read as "protein not detected in tumor"."""
    resolved, present = pc._tphp_tumor_presence_call(_NO_COVERAGE_SHAPES[shape])
    assert (resolved, present) == (False, None), (
        f"no-coverage shape {shape!r} resolved as ({resolved}, {present}) — a cohort with no TPHP "
        "coverage must stay an unmeasured GAP, never a measured negative"
    )


def test_parametrize_is_not_vacuous():
    """A guard that deletes its own subject goes vacuous: an empty parametrize list is GREEN. Pin the
    shape count AND require every live gap mechanism to be represented by name."""
    assert len(_NO_COVERAGE_SHAPES) == 10
    for required in ("pan_cancer_extremum_complete", "zero_detection_underpowered_arm", "empty_data_unavailable_row"):
        assert required in _NO_COVERAGE_SHAPES


def test_new_coverage_path_resolves_detected(pc):
    """The OTHER half of the 22-cohort payoff: a cohort TPHP DOES cover resolves as a MEASURED
    detection. Without this, the test above could be satisfied by a call that never resolves anything."""
    assert pc._tphp_tumor_presence_call(_tphp_row()) == (True, True)
    # a single detected sample out of a large arm is still a detection (presence is one-armed)
    assert pc._tphp_tumor_presence_call(
        _tphp_row(n_tumor_samples=1, n_tumor_samples_total=40, protein_detection_rate_tumor=1 / 40)
    ) == (True, True)


def test_measured_absence_requires_a_powered_tumor_arm(pc):
    """Absence is held to a HIGHER bar than presence, and the bar is the tumor-arm DENOMINATOR. At or
    above the floor a zero detection rate IS a measured non-detection; below it, a gap. Reds if the
    floor is removed (every tiny-arm zero would become a false absence) or made unreachable (no
    measured absence could ever be expressed)."""
    floor = pc._TPHP_MIN_TUMOR_ARM_FOR_ABSENCE
    assert floor >= 2, "a floor below 2 cannot distinguish censoring from absence"
    at_floor = _tphp_row(n_tumor_samples=0, n_tumor_samples_total=floor, protein_detection_rate_tumor=0.0)
    below = _tphp_row(n_tumor_samples=0, n_tumor_samples_total=floor - 1, protein_detection_rate_tumor=0.0)
    assert pc._tphp_tumor_presence_call(at_floor) == (True, False), "a powered zero IS a measured non-detection"
    assert pc._tphp_tumor_presence_call(below) == (False, None), "an underpowered zero is a GAP"


def test_tooth_tumor_vs_normal_contrast_never_leaks_into_presence(pc):
    """READ THE TUMOR ARM ONLY. A `strong_down` tumor-vs-normal window on a protein that IS detected in
    11/12 tumor samples means "lower than the body-atlas normal" — a SELECTIVITY fact. The presence read
    must stay DETECTED. Reds if any contrast field (protein_expression_class / protein_effect_size /
    protein_bh_q_value / protein_median_log2_normal) is ever admitted to the presence call."""
    for over in (
        {"protein_expression_class": "strong_down", "protein_effect_size": -2.4, "protein_bh_q_value": 1e-9},
        {"protein_expression_class": "data_unavailable"},  # the CONTRAST is unavailable, the tumor arm is not
        {"protein_median_log2_normal": 99.0, "protein_effect_size": -78.0},
        {"protein_detection_complete": False, "protein_detection_rate_normal": 0.0},
    ):
        assert pc._tphp_tumor_presence_call(_tphp_row(**over)) == (True, True), (
            f"contrast/normal-arm mutation {sorted(over)} changed the PRESENCE call — a tumor-vs-normal "
            "window is not an absence, and the normal arm must never reach a presence claim"
        )
    # mirror: a flat/UP contrast on a tumor arm with ZERO detections is still an ABSENCE, not a presence
    assert pc._tphp_tumor_presence_call(
        _tphp_row(
            protein_expression_class="strong_up",
            n_tumor_samples=0,
            n_tumor_samples_total=30,
            protein_detection_rate_tumor=0.0,
        )
    ) == (True, False)


# ── T3: the second arm buys no corroboration ──────────────────────────────────────────────────────
def test_tooth_tphp_is_never_corroboration_eligible(pc):
    """Keyed on the ROSTER, not on a per-call outcome: only CPTAC may buy an independent arm, and a new
    MS source is ineligible BY DEFAULT. Reds if TPHP is ever added to `_MS_CORROBORATION_ELIGIBLE`."""
    assert pc._MS_CORROBORATION_ELIGIBLE == frozenset({"cptac_protein"})
    assert "tphp_tumor_protein" not in pc._MS_CORROBORATION_ELIGIBLE


def test_tooth_a_resolved_tphp_arm_does_not_cross_the_corroboration_floor(pc):
    """THE ARM-FLOOR TOOTH. `CORROBORATION_ARM_FLOOR` = 2 measured arms for anything above
    `single_arm`. A target with ONLY mass-spec protein evidence (no antibody-IHC) must stay
    `single_arm` no matter how many mass-spec sources resolve — one modality is one arm. Reds if a
    resolved TPHP read is folded into `corroboration_from_arms` as a second arm."""
    from _skills_common.claim_vector_core import CORROBORATION_ARM_FLOOR

    assert CORROBORATION_ARM_FLOOR == 2
    for extra in (
        {},
        {TPHP_CARD: _tphp_row()},
        {TPHP_CARD: _tphp_row(), CPTAC_CARD: {"allgene_percentile_class": "mid"}},
    ):
        c = {"hpa-pathology-cancer-ihc": {}, **extra}
        claim = pc._protein_presence_concordance_claim(c)
        if claim is None:
            continue
        assert claim["corroborating_independent_arm_count"] == 1, (
            f"mass-spec-only dossier with {sorted(extra)} reported "
            f"{claim['corroborating_independent_arm_count']} independent arms — mass-spec is ONE arm"
        )
        assert claim["corroboration"] == "single_arm", (
            "a mass-spec-only dossier must stay single_arm: adding MS sources is coverage, not corroboration"
        )


def test_resolved_tphp_raises_evidence_count_but_not_arm_count(pc):
    """The envelope's TWO COUNTS must move INDEPENDENTLY — that gap is how "extra MS reads are evidence,
    not extra arms" is legible. TPHP raises `resolved_source_count` and leaves
    `corroborating_independent_arm_count` alone. Reds if the two are ever conflated."""
    base = {
        "hpa-pathology-cancer-ihc": {"protein_presence_class": "ihc_detected_high", "n_high": 6},
        CPTAC_CARD: {"allgene_percentile_class": "top_decile"},
    }
    without = pc._protein_presence_concordance_claim(copy.deepcopy(base))
    with_tphp = pc._protein_presence_concordance_claim({**copy.deepcopy(base), TPHP_CARD: _tphp_row()})
    assert with_tphp["resolved_source_count"] == without["resolved_source_count"] + 1
    assert with_tphp["corroborating_independent_arm_count"] == without["corroborating_independent_arm_count"] == 2
    assert with_tphp["corroboration"] == without["corroboration"]


def test_tooth_shared_measurement_collapse_is_declared_from_the_data(pc):
    """The card header's MANDATE: "any consumer that counts corroborating platforms MUST key on the
    emitted `normal_arm_source` value and collapse the two to one". The collapse is therefore declared
    from the DATA — not from a hardcoded card-id allowlist a product rebuild could invalidate — and it
    names the sibling card it collapses with.

    THE DOUBLE-COUNT CASE: both TPHP cards present in one dossier. The MS group must still carry ONE
    TPHP member and the shared-measurement block, and the independent-arm count must not budge."""
    c = {
        "hpa-pathology-cancer-ihc": {"protein_presence_class": "ihc_detected_high", "n_high": 6},
        TPHP_CARD: _tphp_row(),
        TPHP_NORMAL_CARD: {
            "tphp_normal_protein_liability_class": "broad_normal_expression",
            "allgene_percentile_class": "top_decile",
        },
    }
    claim = pc._protein_presence_concordance_claim(c)
    ms_group = next(
        g for g in claim["evidence_dependence"]["groups"] if g["relationship"] == "same_modality_cross_grain"
    )
    shared = ms_group["shared_measurement"]
    assert shared["normal_arm_source"] == "body_atlas_same_organism_part"
    assert shared["collapses_with"] == [TPHP_NORMAL_CARD]
    assert ms_group["members"].count("tphp_tumor_protein") == 1, "the two TPHP cards must collapse to ONE member"
    assert TPHP_NORMAL_CARD not in str(ms_group["members"]), "the TPHP normal card is not a presence MS source"
    assert claim["corroborating_independent_arm_count"] == 2  # antibody + the ONE mass-spec arm
    rec = next(s for s in claim["source_support"] if s["source"] == "tphp_tumor_protein")
    assert rec["shared_measurement_group"] == "body_atlas_same_organism_part"
    assert rec["corroboration_eligible"] is False
    # DATA-KEYED, not hardcoded: strip the value and the declaration disappears rather than being asserted
    c2 = {**c, TPHP_CARD: _tphp_row(normal_arm_source=None)}
    g2 = next(
        g
        for g in pc._protein_presence_concordance_claim(c2)["evidence_dependence"]["groups"]
        if g["relationship"] == "same_modality_cross_grain"
    )
    assert "shared_measurement" not in g2, "the collapse must be read from normal_arm_source, not assumed"


def test_tphp_support_record_carries_tumor_arm_quantities_only(pc):
    """The `source_support` record is a PRESENCE record: it may retain tumor-arm quantities and must not
    retain normal-arm or contrast ones. Reds if a normal-arm quantity is ever added."""
    claim = pc._protein_presence_concordance_claim(
        {
            "hpa-pathology-cancer-ihc": {"protein_presence_class": "ihc_detected_high", "n_high": 6},
            TPHP_CARD: _tphp_row(),
        }
    )
    rq = next(s for s in claim["source_support"] if s["source"] == "tphp_tumor_protein")["retained_quantitative"]
    assert set(rq) == {
        "protein_detection_rate_tumor",
        "n_tumor_samples",
        "n_tumor_samples_total",
        "protein_median_log2_tumor",
    }
    assert not [k for k in rq if "normal" in k], f"normal-arm quantity leaked into a presence record: {sorted(rq)}"


# ── the display facet ─────────────────────────────────────────────────────────────────────────────
def test_facet_classes_and_gap_is_not_a_measured_zero(run_mod):
    """The headline facet's `tphp_tumor_presence_class`. `data_unavailable` is the CONSERVATIVE
    fall-through and is NOT in the measured vocabulary — the class name itself must never be a
    measured-negative token for a cohort TPHP does not cover."""

    def _facet(summary):
        return run_mod._tphp_tumor_presence_facet([{"card_id": TPHP_CARD, "summary": summary}])

    assert _facet(_tphp_row())["tphp_tumor_presence_class"] == "protein_detected_in_tumor"
    absent = _facet(_tphp_row(n_tumor_samples=0, n_tumor_samples_total=30, protein_detection_rate_tumor=0.0))
    assert absent["tphp_tumor_presence_class"] == "protein_not_detected_in_tumor"
    for shape, summary in _NO_COVERAGE_SHAPES.items():
        if not summary:
            continue
        f = _facet(summary)
        assert f["tphp_tumor_presence_class"] == "data_unavailable", f"{shape} must surface as a GAP"
    # the card absent entirely → key omitted (byte-stable), not a fabricated class
    assert run_mod._tphp_tumor_presence_facet([]) is None
    assert (
        run_mod._tphp_tumor_presence_facet([{"card_id": CPTAC_CARD, "summary": {"allgene_percentile_class": "mid"}}])
        is None
    )


def test_facet_carries_the_independence_constraint_as_a_datum(run_mod):
    """`tphp_corroboration_eligible: False` and the collapse key are DATA on the facet, not prose in a
    comment — so a downstream consumer that counts protein platforms can see the constraint."""
    f = run_mod._tphp_tumor_presence_facet([{"card_id": TPHP_CARD, "summary": _tphp_row()}])
    assert f["tphp_corroboration_eligible"] is False
    assert f["tphp_normal_arm_source"] == "body_atlas_same_organism_part"
    assert f["tphp_cohort"] == "gallbladder carcinoma" and f["tphp_cohort_pick_basis"] == "indication_mapped"
    assert f["tphp_n_tumor_samples_total"] == 12 and f["tphp_tumor_median_log2"] == 21.4
    assert not [k for k in f if "normal" in k and k != "tphp_normal_arm_source"], (
        "the facet must carry no normal-arm quantity"
    )


def test_facet_is_registered_on_the_headline(run_mod):
    """A computed facet nobody emits is dead code. Reds if the key is dropped from the headline spec."""
    assert "tphp_tumor_presence" in run_mod._SYNTHESIS_FACET_KEYS


# ── THE VERDICT DELTA — measured on the committed corpus ──────────────────────────────────────────
_SPINE_KEYS = ("presence_verdict", "presence_verdict_by_modality", "driving_rule_id", "presence_verdict_basis")

# THE MEASURED DELTA, as leaf PATHS. Redact every TPHP-named key and every TPHP-mentioning list item
# from the headline and the three states must collapse to ONE object except at exactly these paths —
# all of them EVIDENCE-INVENTORY COUNTS that increment by 1 because one more card resolved. No verdict,
# no class, no call, no narrative string may move. Measured 2026-10-01 on both committed dossiers; this
# is a CLOSED set, so a new differing path (e.g. a verdict word, or a count that DECREASES) reds.
_ALLOWED_COUNT_PATHS = {
    ".cards_available",
    ".claim_vector.protein_presence_concordance.resolved_source_count",
    ".skill_report.claim_scalars.protein_presence_concordance.resolved_source_count",
}


def _redact_tphp(obj):
    """Drop TPHP-named dict keys and TPHP-mentioning list items, recursively. Keys are matched on the
    NAME only (never on the serialized value) — redacting a key because its VALUE mentions TPHP would
    hide the very spine fields this test exists to compare."""
    if isinstance(obj, dict):
        return {k: _redact_tphp(v) for k, v in obj.items() if "tphp" not in k.lower()}
    if isinstance(obj, list):
        return [_redact_tphp(v) for v in obj if "tphp" not in json.dumps(v, default=str).lower()]
    return obj


# The MS arm-supplier re-pointing: the one NON-count, verdict-inert difference the new arm may make.
# Confined to the protein-presence claim's own subtree, and only CELL-LINE → TPHP (never the reverse).
_SUPPLIER_SUBTREE = ".protein_presence_concordance."
_CELL_LINE_MS_SOURCES = {"gygi_protein", "procan_protein"}


def _ppc(headline):
    return (headline.get("claim_vector") or {}).get("protein_presence_concordance") or {}


def _ms_arm_supplier(headline):
    """The source that SUPPLIES the mass-spec arm's value = the first resolved `mass_spec` record, in
    `_MS_PRESENCE_SOURCES` preference order (the order `source_support` is emitted in)."""
    return next(
        (
            s["source"]
            for s in _ppc(headline).get("source_support", [])
            if s.get("dependence_group") == "mass_spec" and s.get("resolved")
        ),
        None,
    )


def _cptac_resolved(headline):
    return next(
        (s["resolved"] for s in _ppc(headline).get("source_support", []) if s.get("source") == "cptac_protein"), None
    )


def _leaves(obj, prefix=""):
    """Leaf paths. A list of CLAIM-KEYED dicts (every item carrying a `claim_id`, e.g. the biology
    story's `caveats`) is keyed BY `claim_id` rather than by index: its order is not semantic, so an
    index-based path would report a whole block of spurious diffs the moment one claim's caveat is
    added or dropped, and hide WHICH claim moved."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _leaves(v, f"{prefix}.{k}")
    elif isinstance(obj, list):
        if obj and all(isinstance(v, dict) and v.get("claim_id") for v in obj):
            for v in obj:
                yield from _leaves(v, f"{prefix}.{v['claim_id']}")
        else:
            for i, v in enumerate(obj):
                yield from _leaves(v, f"{prefix}[{i}]")
    else:
        yield prefix, obj


_TPHP_STATES = {
    "card_absent": None,
    "resolved_detected": _tphp_row(cohort="colon carcinoma", tissue="colon"),
    "resolved_not_detected": _tphp_row(
        cohort="colon carcinoma",
        tissue="colon",
        n_tumor_samples=0,
        n_tumor_samples_total=30,
        protein_detection_rate_tumor=0.0,
        protein_expression_class="strong_down",
        protein_effect_size=-3.1,
    ),
}


def _replay(fixture_name, target, indication, tphp_state, tmp_path):
    """Replay a COMMITTED frozen dossier through the REAL run.py, with the TPHP card forced into one of
    three states. Only the live dispatcher is patched, so production CARDS + rule firing + the collapse
    ladder + _headline all execute exactly as in a real run."""
    import runpy

    import _skills_common as skc

    fx = FIXTURES / fixture_name
    if not fx.exists():
        pytest.skip(f"no committed fixture at {fx}")
    frozen = yaml.safe_load(fx.read_text()) or {}
    assert TPHP_CARD not in frozen, (
        f"{fixture_name} unexpectedly contains {TPHP_CARD}; this harness INJECTS it to control the "
        "three states, so a frozen copy would make the card_absent arm unreachable"
    )
    if tphp_state is not None:
        frozen = {**frozen, TPHP_CARD: tphp_state}

    def _real(s):
        return isinstance(s, dict) and bool(s) and not s.get("_freeze_error") and not s.get("_dispatcher_returned_none")

    def _factory():
        def _read_live(card_id, *a, **kw):
            s = frozen.get(card_id)
            return copy.deepcopy(s) if _real(s) else None

        return _read_live

    out = tmp_path / f"{target}-{indication}"
    mp = pytest.MonkeyPatch()
    mp.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)
    mp.setattr(skc, "_import_dispatcher", _factory)
    mp.setattr(sys, "argv", ["run.py", "--target", target, "--indication", indication, "--out", str(out)])
    try:
        runpy.run_path(str(RUN_PY), run_name="__main__")
    except SystemExit as e:
        assert e.code in (0, None), f"run.py exited {e.code} on the {target}/{indication} replay"
    finally:
        mp.undo()
    return json.loads((out / "decision.json").read_text())


@pytest.mark.parametrize(
    ("fixture_name", "target", "indication"),
    [("epcam_coadread.yaml", "EPCAM", "COADREAD"), ("cd19_coadread.yaml", "CD19", "COADREAD")],
)
def test_verdict_delta_is_zero_across_the_committed_corpus(fixture_name, target, indication, tmp_path):
    """THE VERDICT-DELTA MEASUREMENT the issue's acceptance criteria demand, over BOTH committed
    dossiers (a measured-positive and a measured-ABSENT/discordant one) × three TPHP states.

    `presence_verdict` and `presence_verdict_by_modality` must be BYTE-IDENTICAL whether the TPHP card
    is absent, resolves DETECTED, or resolves NOT-detected. That is what "additive display/corroboration,
    no new ladder rung" means operationally: the arm cannot move a headline word. Reds the moment the
    card is given a `_PROTEIN_RANK` rung or a `_MEASURED_UNRULED_PRESENT` entry — which is the correct
    red, because that is a verdict-MOVING change needing its own backtest (issue #1825)."""
    decisions = {k: _replay(fixture_name, target, indication, st, tmp_path / k) for k, st in _TPHP_STATES.items()}
    ref = decisions["card_absent"]["headline"]
    for state, d in decisions.items():
        h = d["headline"]
        for key in _SPINE_KEYS:
            assert json.dumps(h.get(key), sort_keys=True) == json.dumps(ref.get(key), sort_keys=True), (
                f"VERDICT DELTA on {target}/{indication}: {key} moved in TPHP state {state!r} "
                f"({h.get(key)!r} vs {ref.get(key)!r}) — the TPHP arm must be verdict-inert"
            )
        # and the bucket the new arm joined is specifically untouched
        assert (
            h["presence_verdict_by_modality"]["bulk_protein_ms/tumor"]
            == (ref["presence_verdict_by_modality"]["bulk_protein_ms/tumor"])
        )
        # ...and the FULL headline, with TPHP content redacted, differs ONLY at the declared
        # evidence-inventory COUNT paths — and there only UPWARD, by exactly the one card that resolved.
        a, b = dict(_leaves(_redact_tphp(ref))), dict(_leaves(_redact_tphp(h)))
        missing = object()
        differing = {k for k in set(a) | set(b) if a.get(k, missing) != b.get(k, missing)}

        # The ONE other thing the arm may move: on a dossier where CPTAC is a GAP, the MS arm's value
        # used to be supplied by a DepMap/ProCan CELL-LINE panel and is now supplied by the TPHP
        # PATIENT-TUMOR read (shared grain with CPTAC — the preference order this issue installs). That
        # re-points provenance and prose inside the protein-presence claim, and nothing else. It is
        # allowed ONLY in that direction and ONLY in that subtree.
        supplier_moved = _ms_arm_supplier(ref) != _ms_arm_supplier(h)
        if supplier_moved:
            assert _ms_arm_supplier(ref) in _CELL_LINE_MS_SOURCES, (
                f"{target}/{indication} state {state!r}: the TPHP arm displaced "
                f"{_ms_arm_supplier(ref)!r} as the MS arm supplier — it may only ever displace a "
                "LOWER-GRAIN cell-line panel, never CPTAC or the antibody arm"
            )
            assert _ms_arm_supplier(h) == "tphp_tumor_protein"
            assert _cptac_resolved(h) is False, "TPHP may only supply the arm value when CPTAC is a gap"
            # THE INDEPENDENCE TOOTH ON THE RE-POINTING PATH. Supplying the arm's VALUE must never be
            # mistaken for ADDING an arm: the count is fixed and TPHP stays corroboration-INELIGIBLE.
            tphp_rec = next(s for s in _ppc(h)["source_support"] if s["source"] == "tphp_tumor_protein")
            assert tphp_rec["corroboration_eligible"] is False
            assert _ppc(h)["corroborating_independent_arm_count"] == _ppc(ref)["corroborating_independent_arm_count"], (
                "the TPHP arm raised the INDEPENDENT arm count by re-pointing the supplier — it is a "
                "shared-measurement, same-modality read and may only ever change the arm's VALUE"
            )
            if _ppc(h)["corroboration"] != _ppc(ref)["corroboration"]:
                # corroboration MAY move — but only because the arm's measured value itself changed
                # (a patient-tumor non-detection now agreeing with patient IHC, where a cell-line
                # detection used to disagree). Never because an extra source was counted.
                prior = next(s for s in _ppc(ref)["source_support"] if s["source"] == _ms_arm_supplier(ref))
                assert tphp_rec["present"] != prior["present"], (
                    f"{target}/{indication} state {state!r}: corroboration moved "
                    f"{_ppc(ref)['corroboration']!r} -> {_ppc(h)['corroboration']!r} while the MS arm's "
                    "VALUE stayed the same — the new arm must not buy corroboration by being counted"
                )
            # the supplier-naming paths are forgiven; the COUNT paths in the same subtree are NOT —
            # they still have to move by exactly +1, so the forgiveness cannot swallow the measurement
            differing = {k for k in differing if _SUPPLIER_SUBTREE not in k or k in _ALLOWED_COUNT_PATHS}

        assert differing <= _ALLOWED_COUNT_PATHS, (
            f"{target}/{indication} TPHP state {state!r} moved non-additive headline content at "
            f"{sorted(differing - _ALLOWED_COUNT_PATHS)} — with TPHP redacted the headline must be "
            "byte-identical apart from evidence-inventory counts"
        )
        expected_bump = 0 if state == "card_absent" else 1
        for path in sorted(differing):
            assert b[path] - a[path] == expected_bump, (
                f"{path} moved {a[path]} -> {b[path]} in TPHP state {state!r}; one resolved card may "
                f"only add {expected_bump} to an evidence-inventory count"
            )
        if state != "card_absent":
            assert differing == _ALLOWED_COUNT_PATHS, (
                f"TPHP resolved in state {state!r} but the inventory counts at "
                f"{sorted(_ALLOWED_COUNT_PATHS - differing)} did not move — the arm is inert, not additive"
            )


def test_verdict_delta_harness_is_not_vacuous(tmp_path):
    """A byte-stability test that compares a thing to itself can never fail. Prove the three states are
    REALLY different runs: the additive facet must actually MOVE across them, and the injected card must
    actually reach the headline. Without this, `test_verdict_delta_*` could pass on a dispatcher patch
    that silently dropped the injected card."""
    seen = {}
    for state, st in _TPHP_STATES.items():
        d = _replay("epcam_coadread.yaml", "EPCAM", "COADREAD", st, tmp_path / state)
        seen[state] = (d["headline"] or {}).get("tphp_tumor_presence")
    assert seen["card_absent"] is None, "with the card absent the facet key must be omitted (byte-stable)"
    assert seen["resolved_detected"]["tphp_tumor_presence_class"] == "protein_detected_in_tumor"
    assert seen["resolved_not_detected"]["tphp_tumor_presence_class"] == "protein_not_detected_in_tumor"
    assert seen["resolved_detected"] != seen["resolved_not_detected"]


def test_the_arm_supplier_upgrade_actually_happens_on_a_committed_dossier(tmp_path):
    """THE MEASURED COVERAGE PAYOFF, on real committed data — and the non-vacuity guard for the
    supplier-re-pointing branch of `test_verdict_delta_*`.

    CD19/COADREAD has NO CPTAC read, so before this change the mass-spec arm's value was supplied by the
    DepMap/Gygi CELL-LINE panel. With the TPHP tumor arm wired, a PATIENT-TUMOR read supplies it instead
    — the grain-correct supplier, and the whole point of putting TPHP second in the preference order.
    Reds if the preference order is ever demoted behind the cell-line siblings (the supplier would stay
    `gygi_protein` and this dossier's protein-in-tumor read would remain cell-line-grain)."""
    before = _replay("cd19_coadread.yaml", "CD19", "COADREAD", None, tmp_path / "before")["headline"]
    after = _replay("cd19_coadread.yaml", "CD19", "COADREAD", _TPHP_STATES["resolved_detected"], tmp_path / "after")[
        "headline"
    ]
    assert _cptac_resolved(before) is False, "this dossier is the CPTAC-gap case; a frozen CPTAC read would void it"
    assert _ms_arm_supplier(before) in _CELL_LINE_MS_SOURCES
    assert _ms_arm_supplier(after) == "tphp_tumor_protein"
    # ...and the upgrade is VERDICT-INERT: the bucket verdict and the collapsed verdict do not move
    assert after["presence_verdict"] == before["presence_verdict"]
    assert after["presence_verdict_by_modality"] == before["presence_verdict_by_modality"]
    # the supplier is named in the prose, not silently swapped — and never as a bare `None`
    assert "TPHP tumor arm" in _ppc(after)["evidence"] and "None" not in _ppc(after)["evidence"]


def test_still_no_coverage_path_on_a_committed_dossier(tmp_path):
    """The STILL-NO-COVERAGE path, end-to-end on a committed dossier: neither frozen fixture carries the
    TPHP card, so a real run of them must leave `bulk_protein_ms/tumor` reading exactly what it read
    before and must NOT fabricate a TPHP facet. This is the half of the 22-cohort story where the
    indication has no TPHP cohort either — it must stay a GAP, silently correct, not a measured zero."""
    d = _replay("cd19_coadread.yaml", "CD19", "COADREAD", None, tmp_path)
    h = d["headline"]
    assert "tphp_tumor_presence" not in h or h["tphp_tumor_presence"] is None
    bucket = h["presence_verdict_by_modality"]["bulk_protein_ms/tumor"]
    assert "absent" not in json.dumps(bucket) or "data_unavailable" in json.dumps(bucket), (
        f"bulk_protein_ms/tumor read {bucket!r} with no TPHP coverage — an uncovered cohort must not "
        "acquire a measured negative from the new arm"
    )
