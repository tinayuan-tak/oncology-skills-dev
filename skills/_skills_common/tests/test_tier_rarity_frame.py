"""tier_rarity — the ORDINAL half of the known-target cohort ruler, asserted on the RENDERED STRING.

WHY THE ASSERTIONS ARE ON RENDERED TEXT AND NOT ON THE FRAME DICT: this reader's whole failure mode is
silent invisibility. `archetype_core.claim_tier_rarity` returns None for an unknown column, an
under-powered cohort or a non-discriminating one — which is correct — so a wiring defect (wrong atlas key,
un-rendered payload, chip never enriched) is indistinguishable from a correctly-gated column if the test
inspects the payload. A dict-shape assertion is GREEN under the bug. So every behavioural test here goes
in through `render_report`, the same entry a real run uses.

WHY THE EXPECTED NUMBERS ARE RE-DERIVED HERE: each expectation is computed by counting cells in the
shipped atlas column (`_share_pct` — a plain equality count over the raw column), never by calling
`tier_rarity`, whose implementation sorts and bisects. Deriving the expectation from the code under test
would make the test restate the implementation instead of checking it.

WHY POPULATION PREMISES ARE ASSERTED SEPARATELY: several tests below say "this column says nothing".
Every one of those is vacuously green if the column stopped existing, so
`test_the_shipped_atlas_still_holds_all_three_populations` pins the three populations (discriminating /
constant / under-powered) BY NAME and BY COUNT. A re-freeze that changes their shape reds there with a
reason, instead of quietly emptying the tests that depend on them.
"""

import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2]  # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common import archetype_core as ac
from _skills_common.archetype_core import (
    CLAIM_CORR_ORD,
    CLAIM_LADDERS,
    CLAIM_SIG_ORD,
    USABLE_TIER_RARITY_DISTINCT,
    claim_atlas_key,
    claim_features,
    claim_tier_rarity,
)
from _skills_common.report_render import render_report

# ── the columns these tests pin, BY NAME, one per population (measured on the shipped 297-target atlas) ──
# discriminating: 3 tiers over 293 measured targets, on BOTH ladders, with the SAME denominator.
DISCRIMINATING = ("cis_coherence", "CIS_DOSAGE")
# constant CORROBORATION, discriminating SIGNAL — the pair that proves the drop is PER-LADDER: 297 targets
# all read `moderate` corroboration, so a rarity sentence there is the same sentence for the whole fleet.
CONSTANT_CORROB = ("cis_coherence", "EXPR_DEP")
# under-powered on both ladders (n=5) although 2 tiers ARE present, so it isolates min_n from min_distinct.
UNDER_POWERED = ("combination_vulnerability", "COMBO")
# the measured DENOMINATOR ASYMMETRY: signal n=265, corroboration n=71 on the same claim (7 of 56 claim
# pairs differ this way) — one shared "of N known targets" tail would be wrong here.
SPLIT_DENOMINATOR = ("genomic_alteration", "DEP")
# a scoped cohort that genuinely clears min_n=20 (COADREAD holds 45 corpus rows; 242 (column, indication)
# pairs clear the gate). Asserting scoping against a column that FELL BACK would assert the fallback.
SCOPED_INDICATION = "COADREAD"

# ── the 2026-09-14 measurement this gate is now sized against ─────────────────────────────────────────
# Measured by replaying all 504 corpus packages through both trunk trees around #1371 (`44ab7a2d` vs
# `698c203e`; control 32500/32760 cells reproduced the stored string exactly and 0 signals moved). The
# producer REROUTES populated rungs onto `single_arm` instead of adding a fourth population, so these
# columns collapse from {distinct today} tiers to exactly 1 and fall BELOW USABLE_TIER_RARITY_DISTINCT once
# the corpus is recomposed. This falsified the design call that shipped with this frame — see
# `test_the_corroboration_encoding_is_an_insert_not_a_renumber`.
#
# ⚠️ 2026-09-15: THE RE-FREEZE LANDED AND THIS PREDICTION IS NOW A MEASUREMENT. All five columns
# below collapsed to exactly 1 tier on the shipped n=504 artifact, so they no longer clear the gate.
# The dict is kept — with its `distinct today` values, which are now historical n=297 readings — because
# the whole point of pinning BY NAME was to make the crossing checkable after the fact, and deleting it
# would destroy the record of what was predicted. `test_..._are_pinned_by_name` now asserts the
# collapse HAPPENED rather than that it is pending.
CROSSES_DOWNWARD_ON_REFREEZE = {
    ("dependency", "CHEM"): 3,
    ("dependency", "SEL"): 2,
    ("safety", "BURDEN"): 2,
    ("selectivity", "DIST"): 3,
    ("target_intrinsic", "MODALITY_ROUTING"): 2,
}
# ::corrob columns clearing BOTH gates (n>=20 AND distinct>=2) on the SHIPPED artifact.
#
# 27 -> 21 when the n=504 re-freeze landed 2026-09-15. The two causes compose EXACTLY, with nothing
# unexplained and zero columns gained:
#     27  n=297 artifact, pre-#1371
#    -1   `expression::claim::D::corrob` — the presence-ladder fix (#1386) retired its ONE minority
#         cell (`{3.0:296, 1.0:1}` -> `{3.0:472, None:32}`), so the column is now constant. This is a
#         DIFFERENT cause from the five below and was never part of their prediction set.
#    -5   the #1371 `single_arm` reroute — exactly CROSSES_DOWNWARD_ON_REFREEZE, all five confirmed.
#    ---
#     21  measured on the n=504 artifact, matching the replay's predicted 21 exactly.
# ★ The replay's intermediate figure was 26 (n=504, pre-#1371) = 27 - 1: that tree already carried the
# ladder fix. Three populations, three numbers, and they only reconcile because each was recorded WITH
# its population. A bare count would have shown "27 -> 21" with no way to separate one 6-column drop
# from two overlapping causes. Still do not mix them.
SHIPPED_CORROB_REACH = 21
# The 27 that cleared on the n=297 artifact, BY NAME. Pinned as a set rather than a count so the
# "nothing gained on a re-freeze" direction assertion has something to be a subset OF — a reroute can
# only remove reach, so the post-re-freeze set must be a SUBSET of this one. A count cannot express that.
_CORROB_REACH_N297 = {
    "cis_coherence::claim::CIS_DOSAGE::corrob",
    "cis_coherence::claim::SILENCING::corrob",
    "dependency::claim::CHEM::corrob",
    "dependency::claim::DEP::corrob",
    "dependency::claim::SEL::corrob",
    "differentiation::claim::SURVIVAL::corrob",
    "expression::claim::A::corrob",
    "expression::claim::B::corrob",
    "expression::claim::C::corrob",
    "expression::claim::D::corrob",
    "genomic_alteration::claim::CN::corrob",
    "genomic_alteration::claim::DEP::corrob",
    "genomic_alteration::claim::FUS::corrob",
    "genomic_alteration::claim::ROLE::corrob",
    "genomic_alteration::claim::SNV::corrob",
    "immune_context::claim::IMMUNE::corrob",
    "safety::claim::BURDEN::corrob",
    "safety::claim::CONSTRAINT::corrob",
    "safety::claim::NORMAL_TISSUE::corrob",
    "selectivity::claim::DIST::corrob",
    "selectivity::claim::INT::corrob",
    "selectivity::claim::SAFE::corrob",
    "selectivity::claim::WIN::corrob",
    "surface_modality::claim::FIT::corrob",
    "surface_modality::claim::PMHC::corrob",
    "target_intrinsic::claim::MODALITY_ROUTING::corrob",
    "tractability_sm::claim::ACTIVITY::corrob",
}


def _atlas():
    a = ac._shipped_atlas_or_none()
    if a is None:
        pytest.skip("no shipped atlas artifact in this checkout")
    return a


def _raw_column(key: str) -> list:
    """The measured cells of one atlas column, UNSORTED — the independent read."""
    a = _atlas()
    j = a.feature_order.index(key)
    return [r[j] for r in a.X if j < len(r) and r[j] is not None]


def _share_pct(key: str, encoded: float) -> float:
    """The percentage of the measured cohort sitting at EXACTLY this tier, by counting (not bisecting)."""
    col = _raw_column(key)
    return round(100.0 * sum(1 for v in col if v == encoded) / len(col), 1)


def _chip(claim, signal=None, corroboration=None, evidence="ev"):
    return {
        "key": claim,
        "label": claim.lower(),
        "signal": signal,
        "corroboration": corroboration,
        "conflict": None,
        "evidence": evidence,
        "cites": [],
        "cite": None,
    }


def _nomination(short, chips, indication=None):
    """The minimum real nomination spine that renders one skill section with claim chips."""
    return {
        "target": "TESTTGT",
        "indication": indication,
        "target_report": {
            "schema": "target_report.v1",
            "skill_reports": {
                short: {
                    "call": "supportive",
                    "role": "gating",
                    "polarity": "supportive",
                    "honest_phrase": "phrase",
                    "confidence": None,
                    "top_tension": None,
                    "claim_chips": chips,
                    "question_table": [],
                    "per_phase_metrics": [],
                    "figures": [],
                    "provenance": {
                        "driving_rule_id": None,
                        "fired_rule_ids": [],
                        "cards_used": [],
                        "cards_missing": [],
                    },
                }
            },
            "target_call": {},
        },
    }


def _render(short, chips, indication=None, backend="text"):
    # L1 is where claim chips render: at L2+ a question_table SUPPRESSES the chips block (ir.py dedupe).
    return render_report(
        _nomination(short, chips, indication), backend=backend, level="L1", scope="all", indication=indication
    )


# ── the population premises every "says nothing" test below depends on ────────────────────────────────
def test_the_shipped_atlas_still_holds_all_three_populations():
    """ANTI-VACUITY. Each named column must still be in the population the test that uses it assumes, and
    the three populations must all be NON-EMPTY fleet-wide. A re-freeze that (say) gives every corroboration
    column a second tier makes `test_a_constant_corroboration_column_says_nothing` vacuous — it would keep
    passing while asserting nothing. It reds HERE instead, naming the reason."""
    a = _atlas()
    claim_keys = [k for k in a.feature_order if "::claim::" in k]
    assert len(claim_keys) > 50, f"the ladder half of the atlas collapsed: {len(claim_keys)} columns"

    disc = _raw_column(claim_atlas_key(*DISCRIMINATING, "corrob"))
    assert len(disc) >= 20 and len(set(disc)) >= USABLE_TIER_RARITY_DISTINCT, (
        f"{DISCRIMINATING} corroboration is no longer discriminating: n={len(disc)} distinct={len(set(disc))}"
    )
    const = _raw_column(claim_atlas_key(*CONSTANT_CORROB, "corrob"))
    assert len(const) >= 20 and len(set(const)) < USABLE_TIER_RARITY_DISTINCT, (
        f"{CONSTANT_CORROB} corroboration is no longer constant: distinct={sorted(set(const))}"
    )
    assert len(set(_raw_column(claim_atlas_key(*CONSTANT_CORROB, "signal")))) >= USABLE_TIER_RARITY_DISTINCT, (
        "the per-ladder test needs this claim's SIGNAL to still discriminate while its corroboration does not"
    )
    under = _raw_column(claim_atlas_key(*UNDER_POWERED, "signal"))
    assert len(under) < 20, f"{UNDER_POWERED} is no longer under-powered: n={len(under)}"
    assert len(set(under)) >= USABLE_TIER_RARITY_DISTINCT, (
        "this column must still hold >=2 tiers, or it stops isolating min_n from min_distinct"
    )
    sig = _raw_column(claim_atlas_key(*SPLIT_DENOMINATOR, "signal"))
    cor = _raw_column(claim_atlas_key(*SPLIT_DENOMINATOR, "corrob"))
    assert len(sig) != len(cor), f"{SPLIT_DENOMINATOR} denominators converged: {len(sig)} == {len(cor)}"
    assert min(len(set(sig)), len(set(cor))) >= USABLE_TIER_RARITY_DISTINCT and min(len(sig), len(cor)) >= 20, (
        "both ladders must still SPEAK, or the two-tail render is unreachable"
    )

    # and the fleet-wide shape: both a discriminating and a non-discriminating population exist.
    shapes = {}
    for k in claim_keys:
        col = _raw_column(k)
        shapes.setdefault("speaks" if (len(col) >= 20 and len(set(col)) >= 2) else "silent", []).append(k)
    assert shapes.get("speaks") and shapes.get("silent"), (
        f"one population is empty: { {k: len(v) for k, v in shapes.items()} }"
    )


# ── the render: the frame is VISIBLE, with the measured numbers ────────────────────────────────────────
def test_the_rendered_chip_names_the_cohort_share_for_both_ladders():
    """THE LOAD-BEARING RENDER TEST. Delete the clause from `_chip_summary` (or stop enriching the chip in
    the IR) and this reds — which is the point: without it the chip renders a plausible, unchanged sentence
    and the whole frame is silently discarded."""
    short, claim = DISCRIMINATING
    sig_tok, cor_tok = "strong", "high"
    out = _render(short, [_chip(claim, sig_tok, cor_tok)])

    n = len(_raw_column(claim_atlas_key(short, claim, "signal")))
    assert n == len(_raw_column(claim_atlas_key(short, claim, "corrob"))), "this pin assumes one denominator"
    s_share = _share_pct(claim_atlas_key(short, claim, "signal"), CLAIM_SIG_ORD[sig_tok])
    c_share = _share_pct(claim_atlas_key(short, claim, "corrob"), CLAIM_CORR_ORD[cor_tok])

    expected = f"(at this tier: signal {s_share:g}%, corroboration {c_share:g}% of {n} known targets)"
    assert expected in out, f"cohort share not rendered.\nexpected: {expected}\ngot:\n{out}"
    # the tier itself still reads as it did — the clause ADDS a frame, it does not replace the reading.
    assert f"{claim.lower()}: {sig_tok}" in out and f"[{cor_tok}]" in out


def test_every_chip_rendering_backend_shows_the_clause():
    """html imports `_chip_summary` FROM text (single source, no vocab drift) — this pins that, so a future
    divergent copy in the html backend cannot silently drop the frame from the HTML report. text and md go
    through the composed report; HTML is exercised via `_emit_standalone_section`, because the composed v6
    page no longer inlines the per-subskill sections where chips live (same reason and same route as
    test_report_render_dials.test_question_table_cells_render_label_not_dict_repr)."""
    from _skills_common.report_render import build_ir, resolve_spec
    from _skills_common.report_render.backends.html import HtmlBackend

    short, claim = DISCRIMINATING
    chips = [_chip(claim, "strong", "high")]
    n = len(_raw_column(claim_atlas_key(short, claim, "corrob")))
    needle = f"corroboration {_share_pct(claim_atlas_key(short, claim, 'corrob'), CLAIM_CORR_ORD['high']):g}% of {n}"
    for backend in ("text", "md"):
        assert needle in _render(short, chips, backend=backend), f"{backend}: cohort share missing"

    ir = build_ir(_nomination(short, chips), resolve_spec(level="L1", scope="all"))
    html = "".join(HtmlBackend()._emit_standalone_section(s) for s in ir.sections)
    assert needle in html, "html: cohort share missing"


def test_two_ladders_with_different_denominators_render_two_tails():
    """The clause groups by (n, scope) instead of sharing one tail. Measured reason: 7 of 56 claim pairs
    disagree on n, and this one disagrees 265 vs 71 — a single tail would attribute the corroboration share
    to the signal's denominator."""
    short, claim = SPLIT_DENOMINATOR
    sig_col, cor_col = claim_atlas_key(short, claim, "signal"), claim_atlas_key(short, claim, "corrob")
    sig_tok, cor_tok = "strong", "moderate"
    out = _render(short, [_chip(claim, sig_tok, cor_tok)])
    n_sig, n_cor = len(_raw_column(sig_col)), len(_raw_column(cor_col))
    assert f"signal {_share_pct(sig_col, CLAIM_SIG_ORD[sig_tok]):g}% of {n_sig} known targets" in out, out
    assert f"corroboration {_share_pct(cor_col, CLAIM_CORR_ORD[cor_tok]):g}% of {n_cor} known targets" in out, out
    assert out.count("known targets") == 2, f"expected one tail per denominator:\n{out}"


def test_the_indication_scoped_cohort_names_itself():
    """A scoped cohort must SAY it is scoped, or the same percentage silently means two different
    populations between requests (the reason step 2 introduced `cohort_scope`). Wording is byte-identical
    to the numeric ruler's — pan-cancer unmarked, a scoped cohort named."""
    short, claim = DISCRIMINATING
    key = claim_atlas_key(short, claim, "corrob")
    scoped_n = len(ac._scoped_sorted_column(key, SCOPED_INDICATION))
    assert scoped_n >= 20, f"{SCOPED_INDICATION} no longer clears min_n on {key} (n={scoped_n}) — pin another"

    out = _render(short, [_chip(claim, None, "high")], indication=SCOPED_INDICATION)
    assert f"of {scoped_n} known targets in {SCOPED_INDICATION})" in out, out
    # and the pan-cancer render of the SAME chip is a DIFFERENT, unmarked cohort — otherwise the scoping
    # argument is being dropped somewhere between build_ir and the reader and this test proves nothing.
    pan = _render(short, [_chip(claim, None, "high")])
    assert SCOPED_INDICATION not in pan and f"of {len(_raw_column(key))} known targets)" in pan, pan
    assert pan != out


# ── the three ways it must say NOTHING ─────────────────────────────────────────────────────────────────
def test_a_constant_corroboration_column_says_nothing_while_its_signal_still_speaks():
    """26 of 56 corroboration columns are CONSTANT across the whole panel. Their rarity sentence would be
    the SAME sentence for every target in the fleet — plausible, identical, uninformative: the failure class
    already recorded for the ::mask columns that read 1.000 by construction. Drop `min_distinct` to 1 and
    this reds. Asserting the SIGNAL still speaks is what makes it a per-ladder drop rather than 'nothing
    rendered for this chip', which would pass even if the whole frame were broken."""
    short, claim = CONSTANT_CORROB
    out = _render(short, [_chip(claim, "strong", "moderate")])
    assert "corroboration" not in out, f"a constant column emitted a rarity sentence:\n{out}"
    sig_share = _share_pct(claim_atlas_key(short, claim, "signal"), CLAIM_SIG_ORD["strong"])
    assert f"signal {sig_share:g}%" in out, f"the discriminating ladder was dropped too:\n{out}"


def test_an_under_powered_cohort_says_nothing_even_though_it_holds_two_tiers():
    short, claim = UNDER_POWERED
    out = _render(short, [_chip(claim, "strong", "high")])
    assert "known targets" not in out, f"n<{20} cohort emitted a rarity sentence:\n{out}"
    assert claim.lower() in out and "strong" in out, "the chip itself must still render"


def test_an_unmeasured_tier_says_nothing():
    """`unmeasured`/`none` map to None in BOTH ladders, so there is no tier to position. A rarity clause
    here would be a confident statement about a measurement that was never made."""
    short, claim = DISCRIMINATING
    out = _render(short, [_chip(claim, "unmeasured", "unmeasured")])
    assert "known targets" not in out, out
    for tok in ("unmeasured", "none", "", None, "not_a_tier"):
        assert claim_tier_rarity(short, claim, "signal", tok) is None, tok


def test_a_missing_atlas_self_drops_rather_than_guessing():
    """A display frame must never break a render, and must never answer from nothing. NOTE the caches: the
    column readers are lru_cached, so patching the artifact loader without clearing them tests the WARM
    CACHE and passes for the wrong reason."""
    short, claim = DISCRIMINATING
    caches = (
        ac._shipped_atlas_or_none,
        ac._cohort_sorted_column,
        ac._scoped_sorted_column,
        ac._cohort_indication_groups,
    )
    for c in caches:
        c.cache_clear()
    try:
        # patch the RESOLVING namespace: `_cohort_sorted_column` looks this name up in archetype_core's
        # globals at call time, so replacing the module attribute is what the reader actually sees.
        orig = ac._shipped_atlas_or_none
        ac._shipped_atlas_or_none = lambda: None
        out = _render(short, [_chip(claim, "strong", "high")])
        assert "known targets" not in out, f"answered without an atlas:\n{out}"
        assert f"{claim.lower()}: strong" in out, "the chip must still render without the atlas"
    finally:
        ac._shipped_atlas_or_none = orig
        for c in caches:
            c.cache_clear()
    # and the frame comes back once the artifact does (proves the patch, not a permanent break)
    assert "known targets" in _render(short, [_chip(claim, "strong", "high")])


# ── the contract the encoding forces ──────────────────────────────────────────────────────────────────
def test_the_frame_never_names_a_tier_because_the_encoding_is_not_invertible():
    """`absent` and `negative` BOTH encode to 0.0 in both ladders, so there is no inverse: a frame that
    named its own tier would have to pick between 'we looked and found nothing' and 'we measured a
    negative', which convention A keeps as separate readings. The caller supplies the token; this
    positions it."""
    assert CLAIM_SIG_ORD["absent"] == CLAIM_SIG_ORD["negative"] == 0.0
    assert CLAIM_CORR_ORD["absent"] == CLAIM_CORR_ORD["negative"] == 0.0
    short, claim = DISCRIMINATING
    a = claim_tier_rarity(short, claim, "signal", "absent")
    b = claim_tier_rarity(short, claim, "signal", "negative")
    assert a == b and a is not None, (a, b)
    # the rendered clause positions the tier without re-naming it from the ladder
    out = _render(short, [_chip(claim, "absent", "high")])
    assert "at this tier:" in out and "signal absent" not in out


def test_the_atlas_key_has_exactly_one_speller():
    """The producer (`claim_features`, used by BOTH the offline freeze and the runtime query) and the
    reader must spell the column the same way. A second copy of this format string is how the
    question_hierarchy/questions.yaml split mis-routed a scored band."""
    produced = set(claim_features({"cis_coherence": {"CIS_DOSAGE": {"signal": "strong", "corroboration": "high"}}}))
    assert produced == {
        claim_atlas_key("cis_coherence", "CIS_DOSAGE", "signal"),
        claim_atlas_key("cis_coherence", "CIS_DOSAGE", "corrob"),
    }
    # every ladder column in the frozen artifact is reproducible from its parts by the one speller
    a = _atlas()
    for k in a.feature_order:
        if "::claim::" not in k:
            continue
        short, rest = k.split("::claim::", 1)
        claim, ladder = rest.rsplit("::", 1)
        assert claim_atlas_key(short, claim, ladder) == k, k
    assert set(CLAIM_LADDERS) == {"signal", "corrob"}, CLAIM_LADDERS
    with pytest.raises(ValueError):
        claim_atlas_key("cis_coherence", "CIS_DOSAGE", "corroboration")  # the long spelling is NOT the key
    assert claim_tier_rarity("cis_coherence", "CIS_DOSAGE", "corroboration", "high") is None


def test_the_display_annotation_never_reaches_the_spine():
    """The same skill_report feeds the scorecard, the LLM synthesis prompt and the drift golden. A
    display-only annotation appearing in their input would make a verdict-inert frame verdict-relevant by
    accident."""
    short, claim = DISCRIMINATING
    nom = _nomination(short, [_chip(claim, "strong", "high")])
    render_report(nom, backend="text", level="L1", scope="all")
    chip = nom["target_report"]["skill_reports"][short]["claim_chips"][0]
    assert set(chip) == set(_chip(claim, "strong", "high")), f"the spine was mutated: {sorted(chip)}"


def test_the_corroboration_encoding_is_an_insert_not_a_renumber():
    """The ENCODING is stable under `single_arm`: it sits strictly between its neighbours on a fresh value,
    and every pre-existing rung keeps the integer it was frozen with, so the 12855 measured ::corrob cells in
    the shipped atlas still mean what they meant and their frozen mu/sd stay valid.

    ★ THIS PROVES A PROPERTY OF THE MAP AND SAYS NOTHING ABOUT THE DISTRIBUTION. An earlier version of this
    test carried the name `test_the_gate_is_monotone_under_a_new_rung` and a docstring concluding that the
    distinct-count gate "can admit more columns, never fewer" — with exactly the two assertions below, which
    cannot see a distribution at all. Both assertions were and remain true; the conclusion was false, and
    because the assertions could never fail the test stayed green while asserting it. See
    `test_the_distinct_gate_is_not_monotone_when_the_producer_reroutes_rungs`."""
    assert CLAIM_CORR_ORD["low"] < CLAIM_CORR_ORD["single_arm"] < CLAIM_CORR_ORD["moderate"]
    assert CLAIM_CORR_ORD["single_arm"] not in {v for k, v in CLAIM_CORR_ORD.items() if k != "single_arm"}
    # insert, NOT renumber: the persisted rungs keep their original integers
    assert (CLAIM_CORR_ORD["low"], CLAIM_CORR_ORD["moderate"], CLAIM_CORR_ORD["high"]) == (1.0, 2.0, 3.0)


def _one_column_atlas(key: str, values: list) -> ac.Atlas:
    """A synthetic single-column atlas, so a distinct-count can be varied independently of the artifact."""
    return ac.Atlas(
        {
            "feature_order": [key],
            "mu": [0.0],
            "sd": [1.0],
            "X": [[v] for v in values],
            "targets": [f"T{i}" for i in range(len(values))],
            "labels": ["?"] * len(values),
        }
    )


def test_the_distinct_gate_is_not_monotone_when_the_producer_reroutes_rungs():
    """★ AN ADDITIVE CHANGE TO A VOCABULARY IS NOT AN ADDITIVE CHANGE TO A DISTRIBUTION. `single_arm` is a
    NEW value in the map, but the producer does not hand it to a new population — `corroboration_from_arms`
    REROUTES cells that used to read `moderate`/`high`/`low` onto it and deliberately never returns
    `moderate`. So a column can LOSE distinct tiers when the rung lands, and this gate then silences it.

    Measured 2026-09-14 over all 504 corpus packages at `44ab7a2d` vs `698c203e`: 5 of the atlas's 56
    ::corrob columns collapse from 2-3 tiers to exactly 1 (see CROSSES_DOWNWARD_ON_REFREEZE). This test
    reproduces that mechanism on a synthetic column so it is falsifiable WITHOUT waiting for a re-freeze."""
    key = claim_atlas_key(*DISCRIMINATING, "corrob")
    caches = (
        ac._shipped_atlas_or_none,
        ac._cohort_sorted_column,
        ac._scoped_sorted_column,
        ac._cohort_indication_groups,
    )
    orig = ac._shipped_atlas_or_none
    try:
        # BEFORE: three populated rungs over a powered cohort — the frame speaks.
        before = [CLAIM_CORR_ORD["high"]] * 40 + [CLAIM_CORR_ORD["moderate"]] * 40 + [CLAIM_CORR_ORD["low"]] * 40
        for c in caches:
            c.cache_clear()
        ac._shipped_atlas_or_none = lambda: _one_column_atlas(key, before)
        spoke = ac.tier_rarity(key, CLAIM_CORR_ORD["moderate"])
        assert spoke is not None and spoke["distinct"] == 3, spoke

        # AFTER: the SAME 120 cells, same n, rerouted onto one rung. Nothing was added; a tier was taken away.
        after = [CLAIM_CORR_ORD["single_arm"]] * 120
        for c in caches:
            c.cache_clear()
        ac._shipped_atlas_or_none = lambda: _one_column_atlas(key, after)
        assert ac.tier_rarity(key, CLAIM_CORR_ORD["single_arm"]) is None, (
            "a rerouting producer collapsed this column to one tier, so the gate MUST silence it — "
            "the falsified claim was that a new rung can only admit more columns, never fewer"
        )
        assert len(before) == len(after), "n is held constant so this isolates min_distinct from min_n"
    finally:
        ac._shipped_atlas_or_none = orig
        for c in caches:
            c.cache_clear()
    # the real artifact is back (proves the patch, not a permanent break)
    assert ac.tier_rarity(key, CLAIM_CORR_ORD["moderate"]) is not None


def test_the_columns_that_cross_the_distinct_gate_on_a_refreeze_are_pinned_by_name():
    """★ Pinned BY NAME, not by a count, because a count cannot say WHICH column changed.

    ⚠️ REWRITTEN 2026-09-15: THE PREDICTION CAME TRUE AND THIS TEST NOW VERIFIES IT, not awaits it.
    Its previous form asserted these five columns still CLEAR the gate and were measured to collapse once
    the corpus was recomposed at `698c203e`. The n=504 re-freeze landed, the test went red exactly as its
    own docstring said it would, and each name was re-measured rather than re-asserted:

        all five predicted columns collapsed to exactly 1 tier    -> confirmed, 5 of 5
        columns that lost reach but were NOT predicted            -> exactly 1, and for a DIFFERENT
                                                                    cause: expression::claim::D::corrob,
                                                                    retired by the #1386 presence ladder
        columns that GAINED reach                                 -> 0
        reach 27 -> 21                                            -> matches the replay's predicted 21

    ★ Direction matters more than the count. The falsified design call was that adding a rung can only
    ADMIT more columns; the producer REROUTES populated rungs onto `single_arm` instead of adding a fourth
    population, so recomposing the corpus SHRANK this frame's reach by 6 of 27. See
    `test_the_corroboration_encoding_is_an_insert_not_a_renumber`.

    NOTE THE POPULATIONS ARE DIFFERENT AND THE NUMBERS MUST NOT BE MIXED: 27 on the n=297 artifact
    pre-#1371, 26 on the n=504 corpus pre-#1371 (the ladder fix already in that tree), 21 on the n=504
    artifact now shipped. Same gate, three populations. Mixing them is how "39 of 40" became "39 of 62".
    If THIS reds, the corpus moved again — re-measure all three groups below, do not adjust the count."""
    a = _atlas()
    clears = {
        k
        for k in a.feature_order
        if k.endswith("::corrob") and len(_raw_column(k)) >= 20 and len(set(_raw_column(k))) >= 2
    }
    assert len(clears) == SHIPPED_CORROB_REACH, f"reach moved: {len(clears)} != {SHIPPED_CORROB_REACH}"

    # GROUP 1 — the five predicted collapses. Each must now be SILENT: one tier, below the distinct gate,
    # and `tier_rarity` refusing to speak. `distinct_before` is the historical n=297 reading, kept so the
    # size of the collapse stays on the record rather than just its fact.
    for (short, claim), distinct_before in sorted(CROSSES_DOWNWARD_ON_REFREEZE.items()):
        key = claim_atlas_key(short, claim, "corrob")
        col = _raw_column(key)
        assert key not in clears, (
            f"{key} STILL clears the distinct gate. The `single_arm` reroute was measured to collapse it "
            f"to 1 tier (from {distinct_before} at n=297) and the shipped artifact says otherwise — "
            f"re-measure the reroute, do not delete this name"
        )
        assert len(set(col)) == 1, f"{key}: expected 1 tier after the reroute, got {len(set(col))}"
        assert ac.tier_rarity(key, col[0]) is None, (
            f"{key} collapsed to one tier but tier_rarity still speaks — the gate that is supposed to "
            f"silence a non-discriminating column is not firing"
        )

    # GROUP 2 — the ONE unpredicted loss, and it has a different cause. Asserted by name so a future
    # reader cannot mistake it for a sixth `single_arm` casualty.
    ladder = claim_atlas_key("expression", "D", "corrob")
    assert ladder not in clears, f"{ladder} clears the gate again — the #1386 presence-ladder fix regressed"
    assert len(set(_raw_column(ladder))) == 1, "expression::D::corrob should be constant post-#1386"

    # GROUP 3 — nothing was GAINED. This is the direction assertion: a rerouting producer can only take
    # reach away, so any gain means the encoding stopped being an insert.
    assert clears <= _CORROB_REACH_N297, (
        f"columns GAINED reach on the re-freeze: {sorted(clears - _CORROB_REACH_N297)}. A reroute cannot "
        f"add a tier, so this contradicts `test_the_corroboration_encoding_is_an_insert_not_a_renumber`"
    )
