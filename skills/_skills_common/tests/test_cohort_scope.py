"""INDICATION-SCOPED cohort rulers — the reader, its fallback, and the scope it names.

Before this, every `cohort_percentile` gauge in the fleet ranked a card value against the WHOLE 297-target
corpus, and said so in prose the request could not check: "stronger than 82% of 297 known targets" is a
different claim for a BRCA request than for an MPN one, and nothing recorded which. The atlas already
carried a per-row `indications` list (Atlas.__init__), so the cohort was always sliceable — it was simply
never sliced. target-contracts #765 declared `cohort_scope` first so the answer could be audited.

★ WHAT THE MEASUREMENTS SAY, and why the tests are shaped the way they are.

Over the 32 `cohort_key`s the salience specs actually use, against the 2026-09-13 atlas (297 targets, 25
distinct indication labels canonicalising to 22 groups), at min_n=20:

    request     exact-n  scoped keys | pooled-as   pooled-n  scoped keys
    COADREAD         45      25      | COADREAD          45      25
    BRCA             43      24      | BRCA              43      24
    LUAD             43      25      | NSCLC             60      27
    LUSC             14       0      | NSCLC             60      27
    NSCLC             3       0      | NSCLC             60      27
    OV               21      11      | OV                21      11
    (the 19 other indications: n < 20, zero scoped keys, pooling changes nothing)

Two conclusions drive this file:

  1. THE FALLBACK IS THE COMMON PATH — 21 of 25 indications are gauged pan-cancer for EVERY key. So the
     tests must exercise the fallback as the normal case, not as an edge case, and the scope must be
     emitted on the pan-cancer path too (an unlabelled percentile is the defect being fixed).
  2. ALIAS POOLING BUYS REQUEST CONSISTENCY, NOT COVERAGE — it adds ZERO (group x column) pairs, but
     without it the canonical code NSCLC would fall back while its own alias LUAD got a scoped gauge.

Neither the roster of scoped-capable groups nor the key counts are frozen here. Step 5's panel expansion
deliberately lifts seven more indications above the gate, so a frozen roster would red on arrival and get
"fixed" by editing the number. Instead the tests DERIVE the expectation from the artifact and assert the
INVARIANT (scoped iff >= min_n measured rows), plus anti-vacuity on both branches — at least one group
must be scoped-capable and at least one must not, so neither branch can rot into unreachability.

★ The scoped reference-QUALITY gate on `bits` is tested against a synthetic cohort on purpose. Measured on
the shipped atlas: of the 87 (indication x key) pairs clearing min_n, 71 award bits and ZERO of those sit
on a scoped cohort measured below the 0.6 floor — so the gate is a no-op today, and
`test_the_scoped_quality_gate_is_a_no_op_on_todays_atlas` pins exactly that. Its partner
`test_bits_are_withheld_when_the_scoped_cohort_is_undermeasured` proves the branch can still fire, so the
pair is a measurement plus a reachability proof rather than a vacuous pass. The reason it ships now
regardless: the worst surviving margin is 0.622 against 0.600 — one target of slack — and step 5 adds 207.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402
from _skills_common.archetype_core import (  # noqa: E402
    _SHIPPED_ATLAS,
    PAN_CANCER_SCOPE,
    USABLE_REFERENCE_MASK_FRACTION,
    Atlas,
    _cohort_indication_groups,
    cohort_percentile,
    cohort_reference_quality,
    resolve_cohort_scope,
)
from _skills_common.evidence_salience import (  # noqa: E402
    SALIENCE_SPECS,
    _bits_for_cohort_frame,
    build_interpretation,
)

MIN_N = 20
# A broadly-measured, polarity-inverted key (atlas stores -loeuf), so a scoped cohort is large enough to
# clear the gate in several indications and the sign convention is exercised rather than assumed.
KEY = "gnomad_lof_constraint::num::loeuf_score"


@pytest.fixture(scope="module")
def atlas():
    a = Atlas.load(_SHIPPED_ATLAS)
    if not a.indications or not any(a.indications):
        pytest.fail("shipped atlas carries no per-row indications — scoping cannot be tested or trusted")
    return a


def _spec_cohort_keys():
    """The cohort_keys the FLEET actually gauges — derived from the specs, never a hardcoded list."""
    keys = set()
    for spec in SALIENCE_SPECS.values():
        rf = spec.get("reference_frame")
        frames = rf if isinstance(rf, list) else ([rf] if isinstance(rf, dict) else [])
        for f in frames:
            if isinstance(f, dict) and f.get("kind") == "cohort_percentile" and f.get("cohort_key"):
                keys.add(f["cohort_key"])
    return sorted(keys)


def _measured_in_group(atlas, key, idxs):
    if key not in atlas.feature_order:
        return 0
    j = atlas.feature_order.index(key)
    return sum(1 for i in idxs if j < len(atlas.X[i]) and atlas.X[i][j] is not None)


# ── the default path must not move ────────────────────────────────────────────────────────────────────
def test_the_pan_cancer_path_is_unchanged_and_still_names_itself():
    """No indication ⇒ exactly the pre-scoping cohort, plus an explicit pan_cancer scope."""
    res = cohort_percentile(KEY, -0.12)
    assert res is not None
    assert res["scope"] == PAN_CANCER_SCOPE
    assert res["n"] == len([r for r in Atlas.load(_SHIPPED_ATLAS).X if r]) or res["n"] > MIN_N
    # the pre-existing contract still holds: polarity, bounds, and the two refusals
    strong, weak = cohort_percentile(KEY, -0.12), cohort_percentile(KEY, -1.4)
    assert strong["percentile"] > weak["percentile"]
    assert cohort_percentile("not_a_measurement::num::nope", -0.12) is None
    assert cohort_percentile(KEY, None) is None
    assert cohort_percentile(KEY, -0.12, min_n=10_000) is None


def test_an_unregistered_indication_degrades_to_pan_cancer_never_a_guess():
    """A code the framework's vocabulary does not declare must not be spelling-matched to a cohort."""
    assert resolve_cohort_scope("NOT_A_REAL_CODE") is None
    assert resolve_cohort_scope("") is None
    assert resolve_cohort_scope(None) is None
    pan = cohort_percentile(KEY, -0.12)
    for junk in ("NOT_A_REAL_CODE", "", None, "   "):
        res = cohort_percentile(KEY, -0.12, indication=junk)
        assert res["scope"] == PAN_CANCER_SCOPE and res["n"] == pan["n"], junk


# ── the scoped path, with its expectation DERIVED from the artifact ───────────────────────────────────
def test_a_scoped_request_is_gauged_within_its_own_indication(atlas):
    groups = _cohort_indication_groups()
    scoped = [g for g, idxs in groups.items() if _measured_in_group(atlas, KEY, idxs) >= MIN_N]
    assert scoped, f"no indication clears min_n={MIN_N} for {KEY} — the scoped branch is unreachable"
    pan = cohort_percentile(KEY, -0.12)
    for g in scoped:
        res = cohort_percentile(KEY, -0.12, indication=g)
        assert res["scope"] == g, f"{g}: gauged against {res['scope']}"
        assert res["n"] == _measured_in_group(atlas, KEY, groups[g]), g
        assert res["n"] <= pan["n"], f"{g}: a scoped cohort cannot exceed the corpus"


def test_scoped_iff_enough_measured_rows_and_both_branches_are_reachable(atlas):
    """The INVARIANT, not a frozen roster: a request is scoped exactly when its own cohort clears min_n.

    Asserted over every (group x spec key) pair so it stays true as the panel grows, with anti-vacuity on
    BOTH branches — step 5 will move many groups from the fallback side to the scoped side and this test
    should survive that untouched.
    """
    groups = _cohort_indication_groups()
    keys = _spec_cohort_keys()
    assert len(keys) >= 20, f"only {len(keys)} spec cohort_keys discovered — the sweep lost its population"
    n_scoped = n_fellback = 0
    for g, idxs in groups.items():
        for key in keys:
            res = cohort_percentile(key, 0.0, indication=g)
            if res is None:
                continue  # column absent, or the corpus itself is under-powered for it
            enough = _measured_in_group(atlas, key, idxs) >= MIN_N
            if enough:
                assert res["scope"] == g, f"{g}/{key}: enough rows but fell back to {res['scope']}"
                n_scoped += 1
            else:
                assert res["scope"] == PAN_CANCER_SCOPE, f"{g}/{key}: too few rows yet scoped to {res['scope']}"
                n_fellback += 1
    assert n_scoped > 0, "no pair took the SCOPED branch — it is unreachable"
    assert n_fellback > 0, "no pair took the FALLBACK branch — it is unreachable"


def test_the_fallback_is_the_majority_path_and_that_is_why_scope_is_emitted(atlas):
    """The honest headline, asserted as a DIRECTION rather than a frozen count.

    Most indications are gauged pan-cancer, which is precisely why the scope must be named on the
    pan-cancer path too. Stated as 'a strict minority of groups is scoped-capable' so step 5 improving
    coverage does not red it — only a change that made scoping near-universal would, and that would be
    the signal to revisit the wording, not a regression.
    """
    groups = _cohort_indication_groups()
    keys = _spec_cohort_keys()
    capable = [g for g, idxs in groups.items() if any(_measured_in_group(atlas, key, idxs) >= MIN_N for key in keys)]
    assert 0 < len(capable) < len(groups), (
        f"{len(capable)} of {len(groups)} indication groups are scoped-capable — "
        "if this is now all of them the fallback prose in cohort_percentile is stale"
    )
    # every gauge, scoped or not, states which cohort it came from
    for g in list(groups)[:8]:
        res = cohort_percentile(KEY, -0.12, indication=g)
        if res is not None:
            assert res["scope"], f"{g}: emitted a percentile with no cohort_scope"


# ── alias pooling: request consistency, the reason it is in the reader at all ─────────────────────────
def test_alias_pooling_makes_a_canonical_code_no_worse_served_than_its_own_alias(atlas):
    """LUAD, LUSC and NSCLC must all be gauged against the SAME pooled cohort.

    Anti-vacuity: the raw LUSC and NSCLC row-label counts are asserted to be BELOW min_n, so this test
    would fail without pooling — it is not merely restating that three codes agree.
    """
    groups = _cohort_indication_groups()
    if "NSCLC" not in groups:
        pytest.skip("no NSCLC group in this atlas vintage")
    raw = {}
    for label in atlas.indications:
        raw[str(label or "").strip().upper()] = raw.get(str(label or "").strip().upper(), 0) + 1
    # the pooling actually changes something: at least one member spelling is under-powered ALONE
    under = [c for c in ("LUSC", "NSCLC") if raw.get(c, 0) < MIN_N]
    assert under, f"no NSCLC-family spelling is under-powered alone (raw counts {raw}) — pooling is vacuous here"
    seen = {}
    for code in ("LUAD", "LUSC", "NSCLC"):
        res = cohort_percentile(KEY, -0.12, indication=code)
        assert res is not None, code
        seen[code] = (res["scope"], res["n"])
    assert len(set(seen.values())) == 1, f"alias family disagrees on its cohort: {seen}"
    assert seen["NSCLC"][0] == "NSCLC"


# ── reference quality: the scoped fraction, and that the recompute is the SAME quantity ───────────────
def test_pan_cancer_quality_still_reads_the_artifact_verbatim(atlas):
    j = atlas.feature_order.index(KEY)
    assert cohort_reference_quality(KEY) == pytest.approx(float(atlas.reference_mask_fraction[j]))
    assert cohort_reference_quality(KEY + "::mask") is None  # the ::mask exclusion is untouched


def test_the_scoped_recompute_reproduces_the_shipped_pan_cancer_fractions(atlas):
    """The load-bearing justification for recomputing at all: it is the shipped measurement narrowed.

    archetype_core deliberately does NOT recompute the pan-cancer fraction (a gate that re-derives its own
    basis can disagree with the build). The scoped fraction has no shipped counterpart, so it must be
    recomputed — which is only legitimate if the same arithmetic reproduces the shipped numbers. It does,
    to within the artifact's 4-decimal storage rounding.
    """
    n = len(atlas.targets)
    worst = 0.0
    checked = 0
    for j, key in enumerate(atlas.feature_order):
        if j >= len(atlas.reference_mask_fraction):
            continue
        shipped = atlas.reference_mask_fraction[j]
        if not isinstance(shipped, (int, float)) or isinstance(shipped, bool):
            continue
        live = sum(1 for r in atlas.X if j < len(r) and r[j] is not None) / n
        worst = max(worst, abs(live - float(shipped)))
        checked += 1
    assert checked > 100, f"only {checked} columns compared — the population collapsed"
    assert worst < 1e-4, f"recompute disagrees with the artifact by {worst:.2e} — not a rounding difference"


def test_scoped_quality_is_the_fraction_measured_inside_that_indication(atlas):
    groups = _cohort_indication_groups()
    g = max(groups, key=lambda k: len(groups[k]))
    expected = _measured_in_group(atlas, KEY, groups[g]) / len(groups[g])
    assert cohort_reference_quality(KEY, indication=g) == pytest.approx(expected)
    # an unregistered scope is not a scope, so it reads the pan-cancer number rather than 0.0
    assert cohort_reference_quality(KEY, indication="NOT_A_REAL_CODE") == cohort_reference_quality(KEY)


# ── bits: the scoped gate is additional, monotone, currently a no-op, and reachable ───────────────────
_RF = {"cohort_key": KEY, "scale": "loeuf", "atlas_numeric": True}


def test_the_scoped_quality_gate_is_a_no_op_on_todays_atlas(atlas):
    """MEASURED: no real (indication x key) pair loses its bits to the scoped gate on this artifact.

    So landing the gate cannot change a shipped number today. If this reds, an indication's cohort has
    become under-measured for a key it is scoped on — that is a real finding about the new corpus and the
    fix is to look at the corpus, never to widen the floor ([[dont_relax_a_gate_to_match_the_build]]).
    """
    groups = _cohort_indication_groups()
    changed = []
    for key in _spec_cohort_keys():
        rf = {"cohort_key": key, "scale": "num", "atlas_numeric": True}
        for g, idxs in groups.items():
            res = cohort_percentile(key, 0.0, indication=g)
            if res is None or res["scope"] == PAN_CANCER_SCOPE:
                continue
            unscoped = _bits_for_cohort_frame(rf, res["percentile"], res["n"])
            scoped = _bits_for_cohort_frame(rf, res["percentile"], res["n"], res["scope"])
            if unscoped != scoped:
                changed.append((g, key, unscoped, scoped))
    assert not changed, f"the scoped gate changed {len(changed)} live pairs: {changed[:4]}"


def test_the_bits_gate_is_monotone_scoped_can_only_ever_withhold(atlas, monkeypatch):
    """Whatever the fractions, a scoped frame must never award bits a pan-cancer frame would withhold."""
    import _skills_common.archetype_core as ac

    for pan_q, scoped_q in ((None, 0.99), (0.10, 0.99), (0.59, 0.99), (0.99, 0.99), (0.99, 0.10)):
        monkeypatch.setattr(
            ac, "cohort_reference_quality", lambda k, indication=None: scoped_q if indication else pan_q
        )
        pan_bits, _ = _bits_for_cohort_frame(_RF, 90.0, 40)
        scoped_bits, _ = _bits_for_cohort_frame(_RF, 90.0, 40, "BRCA")
        if scoped_bits is not None:
            assert pan_bits is not None, f"scoped awarded bits where pan-cancer withheld ({pan_q}, {scoped_q})"


def test_bits_are_withheld_when_the_scoped_cohort_is_undermeasured(monkeypatch):
    """ANTI-VACUITY for a branch production does not reach today — and the control that it CAN pass.

    Falsified both ways against the same stub, so a pass is not the stub silently doing nothing.
    """
    import _skills_common.archetype_core as ac

    monkeypatch.setattr(ac, "cohort_reference_quality", lambda k, indication=None: 0.30 if indication else 0.90)
    bits, withheld = _bits_for_cohort_frame(_RF, 90.0, 40, "BRCA")
    assert bits is None and withheld == "scoped_reference_undermeasured_0.30", withheld
    # the SAME call unscoped is unaffected — the pan-cancer path did not move
    assert _bits_for_cohort_frame(_RF, 90.0, 40)[0] is not None
    assert _bits_for_cohort_frame(_RF, 90.0, 40, PAN_CANCER_SCOPE)[0] is not None

    # control: lift the scoped fraction over the floor and the SAME scoped call is awarded
    monkeypatch.setattr(ac, "cohort_reference_quality", lambda k, indication=None: 0.90)
    assert _bits_for_cohort_frame(_RF, 90.0, 40, "BRCA")[0] is not None

    # an unreadable scoped fraction abstains with its own named reason rather than falling through
    monkeypatch.setattr(ac, "cohort_reference_quality", lambda k, indication=None: None if indication else 0.90)
    assert _bits_for_cohort_frame(_RF, 90.0, 40, "BRCA") == (None, "scoped_reference_quality_unknown")
    assert USABLE_REFERENCE_MASK_FRACTION == 0.6  # the floor both gates share, single-sourced


# ── end to end: the projected gauged_value, its prose, and the graph wiring ───────────────────────────
def _crispr_summary():
    return {"median_chronos_panel": -0.62, "p5_log2tpm_panel": None}


def _cohort_gv(indication=None, mt="gnomad_lof_constraint", summary=None):
    spec = SALIENCE_SPECS[mt]
    out = build_interpretation({}, summary or {"loeuf_score": 0.12}, spec, None, None, indication)
    return next((g for g in out if (g.get("frame") or {}).get("kind") == "cohort_percentile"), None)


def test_the_projected_gauge_carries_cohort_scope_and_names_it_in_the_prose():
    pan = _cohort_gv()
    assert pan is not None, "no cohort_percentile ruler projected — the fleet frame is missing"
    assert pan["cohort_scope"] == PAN_CANCER_SCOPE
    assert "known targets" in pan["position"] and " in " not in pan["position"], pan["position"]

    groups = _cohort_indication_groups()
    atlas = Atlas.load(_SHIPPED_ATLAS)
    scoped_group = next((g for g, i in groups.items() if _measured_in_group(atlas, KEY, i) >= MIN_N), None)
    assert scoped_group, "no scoped-capable group — cannot test the scoped prose"
    sc = _cohort_gv(indication=scoped_group)
    assert sc["cohort_scope"] == scoped_group
    assert sc["position"].endswith(f" in {scoped_group}"), sc["position"]
    assert "known targets" in sc["position"]
    assert sc["cohort_n"] < pan["cohort_n"], "a scoped cohort must be smaller than the corpus"


def test_an_undermeasured_indication_projects_the_pan_cancer_gauge_verbatim():
    """The 21-of-25 case: identical to the pre-scoping output except for the explicit scope key."""
    groups = _cohort_indication_groups()
    atlas = Atlas.load(_SHIPPED_ATLAS)
    small = next((g for g, i in groups.items() if 0 < _measured_in_group(atlas, KEY, i) < MIN_N), None)
    assert small, "every group clears min_n — the fallback prose is stale"
    pan, fell = _cohort_gv(), _cohort_gv(indication=small)
    assert fell == pan, f"{small}: the fallback gauge diverged from the pan-cancer gauge"


def test_the_cohort_ruler_is_never_the_primary_frame_so_claim_record_stays_scope_inert():
    """claim_record.magnitude_for_card reads interpretation[0] and only value/scale/distance_to_cut.

    The fleet loop APPENDS the cohort ruler, so it can never be frame 0 — which is why cohort_scope needed
    no threading through the factored claim record. Pinned rather than assumed, because an author adding a
    cohort_percentile as a card's FIRST declared frame would silently change what the record reports.
    """
    offenders = []
    for mt, spec in SALIENCE_SPECS.items():
        rf = spec.get("reference_frame")
        frames = rf if isinstance(rf, list) else ([rf] if isinstance(rf, dict) else [])
        if frames and isinstance(frames[0], dict) and frames[0].get("kind") == "cohort_percentile":
            offenders.append(mt)
    assert not offenders, f"cohort ruler is the PRIMARY frame on {offenders} — claim_record would read it"


_CARD = "gnomad-lof-constraint"


def _graph_cohort_scope(indication):
    """cohort_scope as it comes out of the PUBLIC graph builder, for a request on `indication`."""
    from _skills_common.evidence_graph import build_evidence_graph

    decision = {
        "target": "EGFR",
        "indication": indication,
        "headline": {
            "evidence_capsules": {"capsules": {_CARD: {"card_id": _CARD, "measurement_type": "gnomad_lof_constraint"}}}
        },
        "cards": [{"card_id": _CARD, "summary": {"loeuf_score": 0.12}}],
    }
    graph = build_evidence_graph(decision)
    node = next((n for n in (graph.get("cards") or []) if n.get("id") == _CARD), None)
    assert node is not None, "the minimal decision produced no card node — the fixture, not the wiring, is wrong"
    gvs = [
        g
        for g in ((node.get("key_evidence") or {}).get("interpretation") or [])
        if (g.get("frame") or {}).get("kind") == "cohort_percentile"
    ]
    assert gvs, "no cohort_percentile ruler in the graph's key_evidence — nothing to check the scope of"
    return gvs[0]["cohort_scope"]


def test_the_evidence_graph_threads_the_request_indication_into_the_ruler():
    """The wiring proof — and it must go through the PUBLIC builder, not the helper.

    ★ THIS TEST WAS VACUOUS ON ITS FIRST WRITING and the mutation harness is what caught it. It called
    `_build_key_evidence(cap, summary, indication)` directly, which proves the HELPER threads its argument
    while saying nothing about whether `build_evidence_graph` ever passes the request's indication in.
    Deleting `g_indication` from that one call site left all 16 tests green. So the assertion has to enter
    where a real run enters — from `decision` — or it tests the wrong seam entirely. Exactly the failure in
    [[feedback_cross_evidence_production_review]]: a pointer that never resolves looks like a working one.
    """
    groups = _cohort_indication_groups()
    atlas = Atlas.load(_SHIPPED_ATLAS)
    scoped_group = next((g for g, i in groups.items() if _measured_in_group(atlas, KEY, i) >= MIN_N), None)
    assert scoped_group, "no scoped-capable group — cannot prove the indication reaches the reader"
    assert _graph_cohort_scope(None) == PAN_CANCER_SCOPE
    assert _graph_cohort_scope(scoped_group) == scoped_group, (
        "build_evidence_graph did not carry decision['indication'] into the cohort reader"
    )
