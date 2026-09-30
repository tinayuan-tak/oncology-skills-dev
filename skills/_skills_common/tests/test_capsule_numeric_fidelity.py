"""A number in the report must MEAN what its slot says.

Two independent defects, both found while grounding the literature lane in the emitted evidence signals
(#1428), both reaching the shipped "Measured evidence" report view, both silent and verdict-INERT — which is
precisely why neither was caught: the view renders perfectly, it just states something false.

DEFECT A — A FIXED-DECIMAL ROUND ANNIHILATES EVERY p/q-VALUE.
`evidence_capsule._num` was `round(v, 4)`. That is right for effects, medians and counts, and catastrophic
for a significance value: `round(2.25e-51, 4) == 0.0`. Measured on 944 real decisions, **980 capsule
`numeric_anchors` values across 10 measurement_types sat at 0.0 with a NONZERO source field**, and 564
`key_evidence.effect` values inherited it through the anchors fallback. So the card's decisive datum read
"0" for the most significant results in the corpus, and the report could print `q-value = 0` beside the same
card's correct `q-value = 2.25e-51` — the `significance` slot already used `sig_round`, the anchors did not.

The obvious repair is wrong in the other direction, and that was measured too: swapping in `sig_round`
wholesale gives `sig_round(12345.678) == 12350.0`, degrading 172 real `surface_density`
`estimated_copies_per_cell_*` anchors. Significant figures are only better for SMALL magnitudes. Hence
`round_keep_tiny`: fixed-decimal, falling back to significant figures ONLY where fixed-decimal destroyed the
value. Corpus control on 300 decisions / 13,726 numeric values: 320 changed, **every one 0.0 -> a real
q/p-value, and NOTHING else moved** (13,406 byte-identical).

DEFECT B — A FRACTION IN THE SAMPLE-SIZE SLOT.
`subgroup_derivation._N_KEY` matches `_samples$`, so `intogen_max_pct_samples` — a PROPORTION — bound as the
alteration-role card's `n`, flowed through `evidence_graph._card_confidence` into `confidence.n`, and the
report rendered **n=0.447**: 0.447 patients. `_N_DENY` already existed for fields that match `_N_KEY` but
are not a sample size; this is a distinct and worse member of that class, because a wrong COUNT is at least
a count. Measured across 944 decisions the added pattern denies EXACTLY ONE field (281 runs, always in
[0.037, 0.7778]); every other field currently binding as `n` is a genuine integer count.

Neither fix can move a verdict, and for B that is provable rather than hopeful — see the power test below.
"""

from __future__ import annotations

from _skills_common import evidence_capsule as EC  # noqa: E402
from _skills_common.evidence_graph import _kenum, build_evidence_graph  # noqa: E402
from _skills_common.evidence_salience import round_keep_tiny, sig_round  # noqa: E402
from _skills_common.subgroup_derivation import (  # noqa: E402
    _N_DENY,
    _N_KEY,
    _heuristic_reader,
    _nbucket,
    derive_subgroups,
)

# The REAL alteration-role summary (KRAS / COADREAD), field for field. Its q is 2.25e-51 and its
# `intogen_max_pct_samples` is 0.447 — the two values both defects were measured on, so nothing below can
# pass on a shape the producer never emits.
_AR_SUMMARY = {
    "alteration_role": "direct_driver_gof",
    "functional_direction": "activating",
    "indication": "COADREAD",
    "intogen_cancer_types": ["COADREAD", "COAD", "READ"],
    "intogen_max_pct_samples": 0.447,
    "intogen_min_qvalue": 2.25e-51,
    "intogen_role": "Act",
    "intogen_scope": "indication",
    "method_version": "0.1.0",
    "oncokb_gene_type": "ONCOGENE",
    "sources": ["oncokb", "intogen"],
    "target": "KRAS",
}


def _ar_cards():
    return [{"card_id": "alteration-role", "measurement_type": "alteration_role", "summary": dict(_AR_SUMMARY)}]


def _ar_capsule():
    return EC.emit_capsules(_ar_cards(), "COADREAD")["capsules"]["alteration-role"]


# ── DEFECT A: the rounding helper ─────────────────────────────────────────────────────────────────────
def test_a_tiny_qvalue_survives_rounding_instead_of_becoming_zero():
    """The defect itself. `round(2.25e-51, 4)` is 0.0 — asserting "not significant" about the single most
    significant result in the corpus. Both real values are pinned, not illustrative ones."""
    assert round(2.25e-51, 4) == 0.0  # the baseline being fixed, stated so the delta is measured
    assert round_keep_tiny(2.25e-51) == 2.25e-51
    assert round_keep_tiny(1.77e-25) == 1.77e-25  # human_genetic_safety min_pvalue, 118 runs


def test_a_genuine_zero_stays_zero():
    """The over-repair guard. 675 anchors in the corpus are CORRECTLY 0.0 — a real `patient_homdel_fraction`
    of 0 means no patient had a homozygous deletion, and must not be perturbed into a tiny float."""
    assert round_keep_tiny(0.0) == 0.0
    assert isinstance(round_keep_tiny(0.0), float)
    assert round_keep_tiny(0) == 0


def test_a_large_value_keeps_fixed_decimal_precision():
    """The POSITIVE CONTROL FOR THE DESIGN, not for the code: it fails if someone later "simplifies" this
    into a bare `sig_round`. 4 significant figures would round 12345.678 to 12350.0, degrading 172 real
    surface_density copies-per-cell anchors. This test is the reason the helper is a hybrid at all."""
    assert round_keep_tiny(12345.678) == 12345.678
    assert sig_round(12345.678) == 12350.0, "sig_round changed; the trade-off this test guards has moved"
    assert round_keep_tiny(12345.678) != sig_round(12345.678)


def test_values_that_already_round_trip_are_returned_byte_identically():
    """This must be a REPAIR, not a re-rounding of the corpus: 13,406 of 13,726 measured values were
    byte-identical across the change, and that is what makes it landable without a golden churn."""
    for v in (0.447, 0.2016, -0.9, 1.5, 0.05, 0.0402, -0.0281, 12345.678):
        assert round_keep_tiny(v) == round(v, 4), v
    assert round_keep_tiny(1084) == 1084  # an int is not re-typed to float


def test_non_floats_and_non_finite_pass_through():
    assert round_keep_tiny("0.5") == "0.5"
    assert round_keep_tiny(None) is None
    assert round_keep_tiny(True) is True
    assert round_keep_tiny(float("inf")) == float("inf")
    assert round_keep_tiny(float("nan")) != round_keep_tiny(float("nan"))  # NaN, passed through unchanged


# ── DEFECT A, through the two producers that render it ────────────────────────────────────────────────
def test_the_capsule_surfaces_the_real_qvalue_as_its_anchor():
    """End-to-end at the site that shipped the defect: the anchor the dashboard and evidence graph SHOW."""
    by_metric = {a["metric"]: a["value"] for a in (_ar_capsule()["numeric_anchors"] or [])}
    assert by_metric["intogen_min_qvalue"] == 2.25e-51
    assert by_metric["intogen_min_qvalue"] != 0.0
    assert by_metric["intogen_max_pct_samples"] == 0.447  # its sibling anchor is untouched


def test_key_evidence_effect_no_longer_contradicts_its_own_significance():
    """The visible symptom: `alteration_role` declares no `effect_field`, so key_evidence.effect falls back
    to numeric_anchors[0] — which was 0.0 while `significance`, reading the summary through sig_round, said
    2.25e-51. One card, one number, two slots, two different answers."""
    decision = {
        "target": "KRAS",
        "indication": "COADREAD",
        "cards": _ar_cards(),
        "fired_rules": [],
        "headline": {"evidence_capsules": {"capsules": {"alteration-role": _ar_capsule()}}},
    }
    card = next(c for c in build_evidence_graph(decision)["cards"] if c["id"] == "alteration-role")
    ke = card["key_evidence"]
    assert ke["effect"]["value"] == 2.25e-51
    assert ke["significance"]["value"] == 2.25e-51
    assert ke["effect"]["value"] == ke["significance"]["value"], "the two slots disagree about one number"


def test_the_key_evidence_rounding_shares_the_capsules_helper():
    """`_kenum` destroys nothing today (all 564 annihilated effects reached it via the anchors fallback),
    but it is the identical one-line bug on the SAME numbers, and it goes live the moment an axis pins an
    `effect_field` that can be tiny. Pinned so the two roundings cannot drift apart."""
    assert _kenum(2.25e-51) == 2.25e-51
    assert _kenum(0.0) == 0.0
    assert _kenum(12345.678) == 12345.678
    for v in (2.25e-51, 0.0, 0.447, 12345.678, 1.77e-25):
        assert _kenum(v) == round_keep_tiny(v), "key_evidence and capsule rounding have diverged"


# ── DEFECT B: a fraction is not a sample size ────────────────────────────────────────────────────────
def test_a_percent_field_is_not_bound_as_a_sample_size():
    """`intogen_max_pct_samples` matches `_samples$`, which is why it became n=0.447 in a shipped view."""
    assert _N_KEY.search("intogen_max_pct_samples"), "the field no longer matches _N_KEY — test is vacuous"
    assert _N_DENY.search("intogen_max_pct_samples")
    reader = _heuristic_reader(dict(_AR_SUMMARY))
    assert reader is not None
    assert "intogen_max_pct_samples" not in reader["n"]
    assert reader["n"] == [], "no field in this summary is a sample size; the reader must say so"


def test_genuine_sample_size_fields_still_bind():
    """Both sides of the narrowing. Every one of these binds as `n` on real runs; the added pattern must
    not reach any of them, or the fix silently strips power from the whole fleet."""
    for f in (
        "n_patients",
        "n_samples",
        "n_tumor_samples",
        "n_cell_lines_evaluated",
        "cn_n_cell_lines_evaluated",
        "pred_n_cell_lines_evaluated",
        "malignant_n_cells",
        "malignant_n_donors",
        "n_pathogenic_germline",
        "n_donors",
        "n_events",
    ):
        assert _N_KEY.search(f), f
        assert not _N_DENY.search(f), f"{f} is a real sample size and was denied"


def test_denying_the_fraction_cannot_move_power():
    """PROVABLE, not hopeful: `_nbucket` returns "low" for everything below 20, and the field's measured
    range across 944 decisions is [0.037, 0.7778]. So the fraction and the resulting None bucket
    IDENTICALLY — for all 281 runs, not merely the one observed. Power feeds `confidence`, so this is what
    makes the fix display-only."""
    assert _nbucket(None) == "low"
    for v in (0.037, 0.447, 0.7778):
        assert _nbucket(v) == _nbucket(None) == "low"


def test_the_card_reports_no_sample_size_rather_than_a_false_one():
    """UNMEASURED means NULL, not 0 and not a fraction. Pins the whole derived source row so a future
    change that reintroduces a number here has to come through this assertion."""
    # measurement_types hang off a QUESTION, not the sub_group — `derive_subgroups` walks
    # sub_groups[].questions[].measurement_types[], and a flat shape here would silently derive NOTHING.
    hierarchy = {"sub_groups": [{"id": "SNV", "questions": [{"measurement_types": ["alteration_role"]}]}]}
    sg = derive_subgroups(hierarchy, _ar_cards())
    src = next(s for s in sg["SNV"]["sources"] if s["card"] == "alteration-role")
    assert src["n"] is None
    assert src["n"] != 0.447
    assert src["value"] == "direct_driver_gof"  # the card's actual signal is untouched
    assert sg["SNV"]["power"] == "low"
