"""The two polarity surfaces of ONE emitted object, and which disagreements are legitimate.

`headline.skill_report.polarity` (contract surface 4, "authoritative") and
`headline.headline_block…evidence_graph.verdict.polarity` (surface 5) are SIBLING keys describing the
same axis, and they answer different questions:

  * (4) = the axis's GATE CONTRIBUTION — `not_scored` when the role is `descriptive`/`inert`;
  * (5) = the axis's READ DIRECTION — always on the measurement scale, role-blind by design.

So they are *supposed* to differ on off-axis roles, and this file pins that asymmetry so a future
"make the two consistent" change cannot silently blank the direction badge on every descriptive axis
(**127 of 278** rows in the live per-skill corpus, on a field `report_render` reads for every
`_skill_graph_header`). And 127 is exactly **descriptive 109 + inert 18**, so "(4) != (5)" and "the role
is off-axis" are not merely correlated on this corpus — they select the SAME rows, with no remainder in
either direction. That is the stronger claim, and it is the one to defend: a single row where the two
predicates came apart would mean the asymmetry has a second cause nobody has characterised.
See docs/UNIFIED_OUTPUT_CONTRACT.md § "Type 2".

WHAT WAS ACTUALLY BROKEN, and why a fixture could not see it
------------------------------------------------------------
`killer` is a member of the ordinal_view scale that `evidence_graph._CANON_POLARITY` maps onto — and
it was UNREACHABLE from that function's only input. `headline_block.verdict.polarity` is the 3-band
`positive/neutral/negative` field, and `skill_report._HEADLINE_TO_CANONICAL` floors every negative at
`opposing` on purpose (severity needs the driving rule, which neither layer sees). A skill that KNOWS
its call is a veto therefore declares it via `build_skill_report(canonical_polarity_override="killer")`
— and the graph never read that sibling key, so a surface-axis KILL rendered as merely `opposing` on
the only surface any renderer reads.

Every assertion below runs the REAL producer (`build_skill_report` → `build_evidence_graph`) rather
than a hand-written graph dict, because the defect was a missing JOIN between those two producers: a
test that asserts over a literal graph cannot observe it, and neither can the frozen corpus in
`skills/target-profile/tests/fixtures/polarity_surface_projection.json` (a snapshot of pre-fix runs
still carries the pre-fix value, forever).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.evidence_graph import _CANON_POLARITY, build_evidence_graph  # noqa: E402
from _skills_common.skill_report import (  # noqa: E402
    ROLE_DESCRIPTIVE,
    ROLE_GATING,
    ROLE_INERT,
    build_skill_report,
)

# The ordinal_view scale, LEAST favourable first. Used to assert the join is monotone — it may only
# ever move a rendered direction DOWN this list, never up. `not_applicable` is off-scale and absent.
FAVOURABILITY = ["killer", "opposing", "neutral", "supportive"]

# The 3-band vocabulary `headline_block.verdict.polarity` actually carries, and what the authoritative
# spine makes of each band with no override. Pinned so a band added upstream shows up here as a red.
BANDS = {"negative": "opposing", "neutral": "neutral", "positive": "supportive"}


def _decision(*, role: str, band: str | None, override: str | None = None, verdict: str = "neither_viable") -> dict:
    """A minimal decision built the way a real skill's run.py builds one: one headline_block, and a
    skill_report assembled FROM it by the shared helper (so the role gate and the override travel
    through their real code path)."""
    hb = {
        "verdict": {
            "call": verdict,
            "phrase": "Neither ADC nor TCE viable",
            "polarity": band,
            "driving_rule_id": "surface-neither-viable-kill",
        },
        "headline_text": "Neither ADC nor TCE viable",
        "confidence": {"level": "moderate", "coverage": 0.75},
    }
    return {
        "skill": "surface-modality-fit",
        "target": "STEAP1",
        "indication": "SCLC",
        "headline": {
            "headline_block": hb,
            "driving_rule_id": "surface-neither-viable-kill",
            "skill_report": build_skill_report(
                role=role,
                verdict=verdict,
                headline_block=hb,
                driving_rule_id="surface-neither-viable-kill",
                canonical_polarity_override=override,
            ),
        },
    }


def _both(d: dict) -> tuple:
    """(authoritative spine polarity, graph verdict polarity) for one decision."""
    return (
        d["headline"]["skill_report"]["polarity"],
        build_evidence_graph(d)["verdict"]["polarity"],
    )


# ── the defect this file exists for ───────────────────────────────────────────────────────────────


def test_a_declared_veto_survives_into_the_graph():
    """The regression. Measured live before the fix on 2 gating rows — surface-modality-fit
    `neither_viable` (STEAP1/SCLC) and tumor-selectivity `selective_but_broadly_normal`
    (GAPDH/COADREAD) — where the spine said `killer` and the graph said `opposing`."""
    spine, graph = _both(_decision(role=ROLE_GATING, band="negative", override="killer"))
    assert spine == "killer", f"the producer stopped declaring the veto on the spine: {spine!r}"
    assert graph == "killer", (
        f"a declared veto was floored to {graph!r} on the graph surface — this is the surface "
        f"`report_render` reads for `_skill_graph_header`, so a KILL renders as merely negative"
    )


def test_the_veto_check_can_fail_without_the_override():
    """ANTI-VACUITY for the test above, and the reason it is not a tautology: the SAME decision with
    no override must still floor at `opposing` on BOTH surfaces. If the join were unconditional (or
    if `_HEADLINE_TO_CANONICAL` grew a `killer` band), the test above would pass for the wrong reason
    and this one goes red."""
    spine, graph = _both(_decision(role=ROLE_GATING, band="negative", override=None))
    assert (spine, graph) == ("opposing", "opposing"), (
        f"a negative call with NO declared veto reads {(spine, graph)!r} — the 3-band channel is not "
        f"supposed to be able to reach `killer` on its own, so the veto test above is now vacuous"
    )


def test_killer_is_reachable_from_the_real_producer_path():
    """`_CANON_POLARITY` has carried a `killer` entry all along; nothing could reach it. Assert both
    halves, so re-orphaning the token (the original defect) fails here rather than going quiet."""
    assert "killer" in _CANON_POLARITY.values(), "`killer` left the graph's canonical vocabulary"
    produced = {_both(_decision(role=ROLE_GATING, band=b, override="killer"))[1] for b in BANDS}
    assert produced == {"killer"}, f"a declared veto did not reach the graph from every band: {produced}"


# ── the invariant: for a GATING axis the two surfaces must agree exactly ──────────────────────────


@pytest.mark.parametrize("band", sorted(BANDS))
@pytest.mark.parametrize("override", [None, "killer"])
def test_gating_axes_agree_exactly_on_both_surfaces(band, override):
    """The whole point of the fix. A `gating` axis is scored, so BOTH surfaces are answering the same
    question and any difference is a value moving. Measured 149/151 before the fix; the 2 exceptions
    were exactly the declared vetoes above, so this now holds with no exception list.

    A NEW disagreement class landing here fails instead of being absorbed into a pinned count — which
    is how `killer → opposing` survived: it was pinned as a benign 25-row "refinement loss"."""
    spine, graph = _both(_decision(role=ROLE_GATING, band=band, override=override))
    assert spine == graph, (
        f"gating axis disagrees across surfaces: spine={spine!r} graph={graph!r} "
        f"(band={band!r}, override={override!r}). Either the join is incomplete or a new polarity "
        f"token needs a decision — do not add it to an allow-list"
    )


def test_the_join_is_escalate_only():
    """The safety property that makes the join safe to ship: honouring a declared severity may only
    move the rendered direction toward LESS favourable, never toward more. Stated as monotonicity on
    the ordinal scale rather than as a special case for `killer`, so a second override token added
    later is covered by this test on the day it is added."""
    moved = 0
    for role in (ROLE_GATING, ROLE_DESCRIPTIVE, ROLE_INERT):
        for band in BANDS:
            base = _both(_decision(role=role, band=band, override=None))[1]
            escalated = _both(_decision(role=role, band=band, override="killer"))[1]
            assert base in FAVOURABILITY and escalated in FAVOURABILITY, (
                f"off-scale polarity {(base, escalated)!r} for role={role!r} band={band!r}"
            )
            assert FAVOURABILITY.index(escalated) <= FAVOURABILITY.index(base), (
                f"the override made role={role!r} band={band!r} read MORE favourable "
                f"({base!r} → {escalated!r}) — the join must be escalate-only"
            )
            moved += FAVOURABILITY.index(escalated) < FAVOURABILITY.index(base)
    # Monotonicity is satisfied trivially by a join that does NOTHING (base == escalated everywhere),
    # which is exactly the pre-fix behaviour — so assert the escalation is also REACHABLE, or this
    # test would keep passing if the join were removed again.
    assert moved, "no case escalated at all — the join is inert and this monotonicity check is vacuous"


# ── the asymmetry that is CORRECT, pinned so it is not "fixed" ────────────────────────────────────


@pytest.mark.parametrize("role", [ROLE_DESCRIPTIVE, ROLE_INERT])
@pytest.mark.parametrize("band", sorted(BANDS))
def test_off_axis_roles_keep_their_read_direction_on_the_graph(role, band):
    """`descriptive`/`inert` axes are `not_scored` on the spine and still carry a DIRECTION on the
    graph. That is not the same defect as the veto above and must not be "fixed" by copying the
    spine: `not_scored` is not a member of the ordinal_view vocabulary, so writing it here would put
    an off-scale token on the display scale and blank the direction badge on **127 of 278** live rows
    (= descriptive 109 + inert 18, exactly — see this module's docstring).
    The harmful direction — an unscored axis reading as the favourable measured class — is pinned
    separately and by count in skills/target-profile/tests/test_surface_authority.py."""
    spine, graph = _both(_decision(role=role, band=band, override=None))
    assert spine == "not_scored", f"role {role!r} stopped being off-axis on the spine: {spine!r}"
    assert graph == BANDS[band], f"role {role!r} lost its read direction on the graph: {graph!r}"
    assert graph != "not_scored", "`not_scored` is off-scale for the ordinal_view display vocabulary"


def test_a_decision_without_a_skill_report_is_unaffected():
    """Back-compat, and not hypothetical: 14 of 278 live per-skill artifacts carry no `skill_report`
    at all (and 5 carry `headline` as a bare string). The join must fall through to the 3-band read
    rather than raise or blank."""
    d = _decision(role=ROLE_GATING, band="negative", override="killer")
    del d["headline"]["skill_report"]
    assert build_evidence_graph(d)["verdict"]["polarity"] == "opposing"

    d2 = _decision(role=ROLE_GATING, band="negative", override="killer")
    d2["headline"]["skill_report"] = "a bare string, as 5 live artifacts carry for `headline`"
    assert build_evidence_graph(d2)["verdict"]["polarity"] == "opposing"


def test_an_absent_headline_band_is_a_declared_asymmetry_not_a_regression():
    """The ONE place the gating surfaces still differ, recorded rather than left to be rediscovered:
    with no headline polarity at all the spine defaults to `neutral` while the graph emits None. Not
    swept into the fix because the direction is safe — an absent badge is not a favourable one — and
    it occurs 0 times in the live corpus, so a fix would be unmeasured. Pinned so it cannot drift
    into the harmful direction."""
    spine, graph = _both(_decision(role=ROLE_GATING, band=None, override=None))
    assert spine == "neutral", f"spine default for a missing band moved: {spine!r}"
    assert graph is None, f"graph now claims {graph!r} for an axis with no headline polarity"
