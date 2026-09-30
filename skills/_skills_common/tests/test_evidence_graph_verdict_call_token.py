"""What `evidence_graph.verdict.id` is TYPED as, and why the corpus could not answer that question.

`docs/UNIFIED_OUTPUT_CONTRACT.md` declared surface (2) — `…evidence_graph.verdict.id` — to be a
*resolver* verdict token that "must be identical" to surface (1) `sub_verdicts.<axis>.verdict`, and
`skills/target-profile/tests/test_surface_authority.py` pinned the one axis that disagreed. Both were
describing a coincidence.

THE CONFOUND, because it is the whole reason this file exists
------------------------------------------------------------
`id` agreed with the resolver token on **619 of 683** composed rows, every one of the 64 exceptions on
`surface_modality`. That reads like a type rule with one violator. It is not: **ten of the eleven
skills pass their resolver verdict straight into `build_skill_report(verdict=…)`**, so on their rows
"id == resolver token" and "id == the skill's own call" are the SAME assertion and the corpus cannot
tell them apart. `surface-modality-fit` is the only skill where the two can differ — it passes the
composed `adc-tce-modality-fit` `fit_class` as its call on purpose, keeping the resolver's
safety/density downgrade in the top tension — and there the fork is **64 of 64**, i.e. total.

So the invariant that actually holds is `verdict.id == headline.skill_report.call`: **683/683**
composed rows and **218/218** per-skill rows where both are present, 0 exceptions, every axis.

★ An invariant measured only where two vocabularies COINCIDE cannot distinguish a type rule from a
shared habit. The two token sets here intersect in exactly one literal (`modality_ambiguous`), which
manufactured 4 accidental "agreements" and made a total fork look intermittent.

WHY A JOIN AND NOT A PIN
------------------------
`id == skill_report.call` was already true on every live row before this change — but only because
every `run.py` happens to hand the same token to both surfaces. Nothing joined them, so a skill that
passed different tokens would fork the two silently. `evidence_graph._verdict_call` now reads the
authoritative spine first, which makes the invariant structural. It is value-neutral by replay (the
old and new chains agree on 292/292 live artifacts) and cannot fill or blank a value, because the two
surfaces are co-present or co-absent on every row.

Every assertion below runs the REAL producers (`build_skill_report` → `build_evidence_graph`). The
builder here deliberately lets `headline_block.verdict.call` and `skill_report.call` DIFFER — which
the sibling `test_evidence_graph_verdict_polarity.py` builder cannot do, since it feeds one `verdict`
to both. A test that cannot separate the two inputs cannot observe this join at all.
"""

from __future__ import annotations

import pytest
from _skills_common.evidence_graph import build_evidence_graph  # noqa: E402
from _skills_common.skill_report import ROLE_GATING, build_skill_report  # noqa: E402

# The live `surface_modality` shape, which is the ONLY axis where the two candidate inputs differ.
# `fit_class` is what surface-modality-fit declares as its call (run.py: `_v = hl.get("fit_class")`);
# the resolver token lives elsewhere in the decision and is deliberately NOT the call.
FIT_CLASS = "TCE_preferred"
FIT_PHRASE = "TCE-favorable"
RESOLVER_TOKEN = "tce_unsafe_normal_liability"


def _decision(
    *,
    spine_call: str | None,
    hb_call: str | None,
    with_skill_report: bool = True,
    presence_verdict: str | None = None,
    phrase: str | None = FIT_PHRASE,
) -> dict:
    """A decision whose two call-bearing inputs are set INDEPENDENTLY.

    `hb_call` lands on `headline_block.verdict.call` (the pre-join source) and `spine_call` on
    `headline.skill_report.call` via the real helper. Keeping them separate is the whole point: a
    builder that feeds one value to both makes every assertion below pass for free.
    """
    hb = {
        "verdict": {
            "call": hb_call,
            "phrase": phrase,
            "polarity": "positive",
            "driving_rule_id": "surface-tce-preferred",
        },
        "headline_text": "TCE preferred on this surface",
        "confidence": {"level": "moderate", "coverage": 0.75},
    }
    headline: dict = {
        "headline_block": hb,
        "driving_rule_id": "surface-tce-preferred",
    }
    if presence_verdict is not None:
        headline["presence_verdict"] = presence_verdict
    if with_skill_report:
        headline["skill_report"] = build_skill_report(
            role=ROLE_GATING,
            verdict=spine_call,
            headline_block=hb,
            driving_rule_id="surface-tce-preferred",
        )
    return {
        "skill": "surface-modality-fit",
        "target": "CD79B",
        "indication": "DLBCL",
        "headline": headline,
    }


def _node(d: dict) -> dict:
    return build_evidence_graph(d)["verdict"]


# ── the invariant this file exists to make structural ─────────────────────────────────────────────


def test_the_graph_verdict_id_is_the_skills_own_call_token():
    """`verdict.id` must be the token the skill declared as its call on the authoritative spine —
    NOT whatever `headline_block.verdict.call` happens to hold. Measured 683/683 composed and 218/218
    per-skill; asserted here against the producer so it holds by construction rather than by every
    skill happening to agree with itself."""
    d = _decision(spine_call=FIT_CLASS, hb_call=RESOLVER_TOKEN)
    spine = d["headline"]["skill_report"]["call"]
    assert spine == FIT_CLASS, f"the spine stopped carrying the declared call: {spine!r}"
    assert _node(d)["id"] == FIT_CLASS, (
        f"verdict.id is {_node(d)['id']!r}, not the skill's declared call {FIT_CLASS!r} — the graph is "
        f"reading a different key than the authoritative spine, which is the fork this join closes"
    )


def test_the_two_inputs_actually_differ_so_the_check_above_is_not_vacuous():
    """ANTI-VACUITY. The assertion above only tests anything if the two candidate sources hold
    DIFFERENT tokens in this fixture — otherwise it passes for a producer that reads either key. Pin
    that, so a later edit to the builder that collapses them fails HERE instead of quietly making the
    real test tautological."""
    d = _decision(spine_call=FIT_CLASS, hb_call=RESOLVER_TOKEN)
    hb_call = d["headline"]["headline_block"]["verdict"]["call"]
    spine_call = d["headline"]["skill_report"]["call"]
    assert hb_call != spine_call, (
        "the fixture's two call inputs are equal, so `id` matches both sources and the invariant test "
        "above can no longer tell which key the producer read"
    )
    # And state the pre-join behaviour explicitly: the OLD chain returned `hb_call` for this decision,
    # so this exact input is the one that used to fork the two surfaces.
    assert _node(d)["id"] != hb_call, (
        f"verdict.id fell back to headline_block.verdict.call ({hb_call!r}) — that is the pre-join "
        f"behaviour, and on this input it is exactly the resolver/call confusion being fixed"
    )


def test_the_display_phrase_is_untouched_by_the_join():
    """`verdict.call` (the human phrase) and `verdict.id` (the token) are different fields with
    different jobs. The join moves the token only; a phrase regression here would be a visible
    rendered change, which this fix is not allowed to make."""
    node = _node(_decision(spine_call=FIT_CLASS, hb_call=RESOLVER_TOKEN))
    assert node["call"] == FIT_PHRASE, f"the rendered phrase moved to {node['call']!r}"


# ── the fall-throughs, all three measured on the live corpus ──────────────────────────────────────


def test_a_spine_with_no_call_falls_through_to_the_headline_block():
    """Not hypothetical: 60 of 292 live artifacts carry a `skill_report` with NO `call`
    (combination-and-vulnerability 25, literature-context 21, translational-readiness 9,
    target-intrinsic 3, surface-modality-fit 2 — gateless skills pass `verdict=None`). The join must
    fall through rather than blank the token."""
    d = _decision(spine_call=None, hb_call=RESOLVER_TOKEN)
    assert d["headline"]["skill_report"]["call"] is None, "fixture no longer models a gateless spine"
    assert _node(d)["id"] == RESOLVER_TOKEN, (
        "a gateless spine blanked verdict.id — the join must fall through to the headline channel, not "
        "overwrite it with None"
    )


def test_a_decision_without_a_skill_report_is_unaffected():
    """The other 14 of 292: no `skill_report` key at all. Same requirement as the veto join's
    back-compat case in test_evidence_graph_verdict_polarity.py."""
    d = _decision(spine_call=FIT_CLASS, hb_call=RESOLVER_TOKEN, with_skill_report=False)
    assert "skill_report" not in d["headline"]
    assert _node(d)["id"] == RESOLVER_TOKEN

    d2 = _decision(spine_call=FIT_CLASS, hb_call=RESOLVER_TOKEN)
    d2["headline"]["skill_report"] = "a bare string, as live artifacts carry for `headline`"
    assert _node(d2)["id"] == RESOLVER_TOKEN, "a non-dict spine must not raise or blank the token"


def test_presence_verdict_still_wins_when_the_spine_is_silent():
    """`tumor-presence` puts its call on `headline.presence_verdict`, and that key led the pre-join
    chain. It must keep leading the FALLBACK, or the presence axis silently retypes. (On the live
    corpus this is moot — presence's spine call equals its `presence_verdict`, which is why the replay
    showed 292/292 — but the ordering is load-bearing for any artifact where the spine is absent.)"""
    d = _decision(spine_call=None, hb_call=RESOLVER_TOKEN, presence_verdict="present_high_uniform")
    assert _node(d)["id"] == "present_high_uniform"


# ── the safety property that makes the join provably value-preserving ─────────────────────────────


@pytest.mark.parametrize(
    "spine_call,hb_call,with_sr",
    [
        (FIT_CLASS, RESOLVER_TOKEN, True),  # 218 live rows: both surfaces set
        (None, RESOLVER_TOKEN, True),  # 60 live rows: spine present, no call
        (None, None, True),  # spine present, nothing anywhere
        (FIT_CLASS, RESOLVER_TOKEN, False),  # 14 live rows: no spine at all
    ],
)
def test_the_join_can_neither_fill_a_blank_nor_blank_a_value(spine_call, hb_call, with_sr):
    """The safety argument, stated as a property rather than as a count. On the live corpus
    `skill_report.call` and the fall-through chain are CO-PRESENT OR CO-ABSENT — 218 rows both set,
    74 both falsy, and no one-sided cell — so the join cannot invent a token where there was none nor
    lose one that existed. Asserted here as an equivalence of TRUTHINESS between the joined output and
    the pre-join chain, which is what "value-neutral" actually means and is stronger than replaying
    one corpus."""
    d = _decision(spine_call=spine_call, hb_call=hb_call, with_skill_report=with_sr)
    h = d["headline"]
    hb_verdict = h["headline_block"]["verdict"]
    pre_join = h.get("presence_verdict") or hb_verdict.get("call") or h.get("verdict")
    joined = _node(d)["id"]
    assert bool(joined) == bool(pre_join), (
        f"the join changed PRESENCE of verdict.id: pre-join {pre_join!r} -> joined {joined!r} "
        f"(spine_call={spine_call!r}, hb_call={hb_call!r}, with_skill_report={with_sr})"
    )
