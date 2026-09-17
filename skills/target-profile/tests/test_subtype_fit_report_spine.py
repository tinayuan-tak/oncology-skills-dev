"""The inline subtype tier's skill_report[] spine (2026-09-17).

`subtype_fit` was the ONE fan-out axis with no `synthesis_facet`, so it emitted no `skill_report`, hence
no `provenance`, hence was invisible to every provenance reader (`risk_projection._axis_card_provenance`,
`evidence_coverage_by_axis`, `ir._dim_members`). That absence — not any mapping — is why the axis could
not be decided in the #1418/#1420 axis→dim settlement.

These guards exist because supplying that report touches surfaces a "display-only" framing does not
predict, and each one is pinned against an ORACLE OUTSIDE the code under test:

  * SCOPE FORECLOSURE (`tp_gates._SCOPE_OPTIN_GATING_AXES`) — the report must appear ONLY on a
    `--subtypes` run. A default run must still have NO `subtype_fit` key, because `_hard_gates_status`
    reads absence as `excluded` and presence-without-verdict as `latent`, and NEITHER may become `blind`
    (the cross-evidence fail-closed ceiling treats a blind gated axis as a veto ⇒ it would DECLINE every
    target on the default path).
  * FAVORABILITY (`build_skill_report_rollup.peak_gating_rank`) — a dormant axis must not raise a
    target's peak gating signal. `not_scored` is absent from `_SKILL_REPORT_POLARITY_RANK`, so it is
    visible in `gating_polarities` yet contributes no rank.
  * ATLAS BYTE-STABILITY (`archetype_core`) — "verdict-inert" does not imply "atlas-inert".
    `fired_rule_ids_from_sub_results` switches from its legacy `fired` fallback to the spine leg the
    moment `provenance.fired_rule_ids` is non-empty, so the two legs must yield the same SET.
  * THE VOCABULARY (`tp_gates._RECOGNIZED_GATING_VERDICTS`) — every recognized verdict must be mapped
    EXPLICITLY, and an unrecognized one must fail the same direction `tp_gates` fails.
  * THE NAMESPACE (`run.py`'s import ORDER) — this change's first draft named its helper `_subtype_facet`,
    which `tp_facets` already exports and `run.py` binds by name BEFORE its `from tp_fanout import *`.
    `__all__` overrides the "star-import skips `_names`" rule, so the later star-import silently rebound
    `run._subtype_facet` and red-lined 18 previously-green tests. Pinned here, with a positive control.

Every guard below was shown KILLABLE by mutation (13 mutants of `tp_fanout`, each verified applied via
`git diff` before running — an unapplied mutant reads as a coverage hole), EXCEPT two that cannot be
killed by mutating the code under test, by design:
`test_subtype_fit_is_still_the_scope_optin_gating_axis` reads its premise from `tp_gates` (it is the
ORACLE, not the subject), and `test_the_detector_for_star_import_rebinding_can_actually_fire` IS the
positive control for the guard after it. One caution recorded for the next person to mutate this file: a
`claim_vector` mutant only bites if its atom VALUE is a dict carrying `signal`/`corroboration` —
`claim_features` skips any other shape, so a scalar atom is an EQUIVALENT mutant, not a hole.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SKILLS = SCRIPTS.parent.parent
for _p in (str(SKILLS), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _skills_common.archetype_core import (  # noqa: E402
    fired_rule_ids_from_sub_results,
    vector_from_sub_results,
)
from _skills_common.feature_vectoriser import numeric_values_from_sub_results  # noqa: E402
from tp_facets import (  # noqa: E402
    _modality_scope_by_axis,
    _skill_reports_by_short,
    build_skill_report_rollup,
)
from tp_fanout import (  # noqa: E402
    _SHORT_TO_GATE,
    _SUBTYPE_UNRECOGNIZED_POLARITY,
    _SUBTYPE_VERDICT_POLARITY,
    SUBTYPE_SHORT,
    _subtype_spine_facet,
    _subtype_spine_skill_report,
)
from tp_gates import (  # noqa: E402
    _GATING_AXES,
    _GATING_AXIS_FAILCLOSED_ACTION,
    _RECOGNIZED_GATING_VERDICTS,
    _SCOPE_OPTIN_GATING_AXES,
)

TP_FANOUT = SCRIPTS / "tp_fanout.py"

# a realistic subtype-tier card pair: one resolved, one data-blocked (the `_missing` flag every wired
# skill's cards_used/cards_missing derivation reads — see tumor-selectivity/run.py, dispatcher.py:993).
_CARDS = [
    {"card_id": "subgroup-stratified-dependency", "summary": {}},
    {"card_id": "tumor-vs-normal-selectivity", "_missing": True},
]
_FIRED = [
    {"rule_id": "subtype-non-dependence-opposing", "tier": "subtype", "signals": {"subtype_fit_genomic": "opposing"}},
    {"rule_id": "subtype-expression-restricted-context", "tier": "subtype"},
]


def _tier(verdict_pair, *, facet: bool):
    """A subtype-tier sub_result, with or without the new synthesis_facet — the paired control."""
    r = {
        "skill_dir": None,
        "cards": _CARDS,
        "fired": _FIRED,
        "verdict": verdict_pair,
        "scope_subtypes": ["CMS4"],
    }
    if facet:
        r["synthesis_facet"] = _subtype_spine_facet(verdict_pair, _CARDS, _FIRED)
    return {SUBTYPE_SHORT: r}


# --- the WIN: the axis is now visible to the provenance readers -------------------------------------


def test_subtype_fit_now_reaches_the_skill_report_spine_with_real_provenance():
    """The point of the change. Before: `_skill_reports_by_short` skipped the tier entirely."""
    without = _skill_reports_by_short(_tier(("subtype_specific_non_dependence", "r1"), facet=False))
    with_ = _skill_reports_by_short(_tier(("subtype_specific_non_dependence", "r1"), facet=True))
    assert SUBTYPE_SHORT not in without, "precondition: the facet-less tier was invisible to the spine"
    assert SUBTYPE_SHORT in with_, "the tier must now appear on the skill_report[] spine"
    prov = with_[SUBTYPE_SHORT]["provenance"]
    # cards_used is the NOT-missing set and cards_missing the `_missing` set — a fully data-blocked tier
    # must NOT report itself as covered, which is what the coverage readers join on.
    assert prov["cards_used"] == ["subgroup-stratified-dependency"]
    assert prov["cards_missing"] == ["tumor-vs-normal-selectivity"]
    assert prov["driving_rule_id"] == "r1"
    assert prov["fired_rule_ids"] == [f["rule_id"] for f in _FIRED]


# --- SCOPE FORECLOSURE: the report may exist only where the tier does ------------------------------


def test_the_facet_is_emitted_INSIDE_the_subtypes_branch_only():
    """STRUCTURAL: the `_subtype_spine_facet(...)` call must sit inside `if subtypes:`. If it ever moved out,
    every default run would grow a `subtype_fit` key and `_hard_gates_status` would reclassify the axis
    (`excluded` → something else) on 100% of no-subtypes runs — the failure `_SCOPE_OPTIN_GATING_AXES`
    exists to prevent. Asserted on the AST, because no cheap functional test reaches the real fan-out."""
    tree = ast.parse(TP_FANOUT.read_text())
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef)
        and any(
            isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "_subtype_spine_facet"
            for c in ast.walk(n)
        )
    )
    guarded = [
        node
        for node in ast.walk(fn)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id == "subtypes"
        and any(
            isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "_subtype_spine_facet"
            for c in ast.walk(node)
        )
    ]
    assert guarded, "the _subtype_spine_facet call must be inside `if subtypes:` (scope foreclosure)"
    # and it must appear NOWHERE else in the module
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_subtype_spine_facet"
    ]
    assert len(calls) == 1, f"expected exactly one _subtype_spine_facet call site, found {len(calls)}"


def test_subtype_fit_is_still_the_scope_optin_gating_axis():
    """The premise of the guard above, read from tp_gates rather than restated."""
    assert SUBTYPE_SHORT in _SCOPE_OPTIN_GATING_AXES
    assert SUBTYPE_SHORT in _GATING_AXES


# --- FAVORABILITY: a dormant axis must not make a target read better ------------------------------


def test_dormant_tier_is_not_scored_and_cannot_raise_peak_gating_rank():
    """The fall-through that matters. With every other gating axis `opposing` (rank -1), a dormant
    subtype_fit emitting `neutral` (rank 0) would RAISE the target's peak gating signal — a target
    reading better because an axis said nothing. `not_scored` is unranked, so peak is unchanged."""
    others = {
        "dependency": {"role": "gating", "call": "non_dependent", "polarity": "opposing"},
        "safety": {"role": "gating", "call": "x", "polarity": "opposing"},
    }
    sr = _subtype_spine_skill_report(None, _CARDS, _FIRED)  # tier ran, nothing fired
    assert sr["polarity"] == "not_scored"
    before = build_skill_report_rollup(dict(others))
    after = build_skill_report_rollup({**others, SUBTYPE_SHORT: sr})
    assert before["peak_gating_rank"] == -1
    assert after["peak_gating_rank"] == before["peak_gating_rank"], (
        "a dormant subtype_fit must contribute NO favorability to peak_gating_rank"
    )
    # LABEL, do not DROP: still visible to the reader, just unranked.
    assert after["gating_polarities"][SUBTYPE_SHORT] == "not_scored"


def test_the_hold_verdict_is_opposing_and_never_enters_killer_axes():
    """A hold is not a veto. `killer` is the token `killer_axes` / the INV-6
    `recommendation_exceeds_signals` flag / `ir`'s de-escalation all switch on, so claiming it here
    would overstate a hold on surfaces with real readers."""
    sr = _subtype_spine_skill_report(("subtype_specific_non_dependence", "r1"), _CARDS, _FIRED)
    assert sr["polarity"] == "opposing"
    roll = build_skill_report_rollup({SUBTYPE_SHORT: sr}, target_call={"recommendation": "nominate"})
    assert roll["killer_axes"] == []
    assert roll["recommendation_exceeds_signals"] is False


def test_supportive_subtype_verdicts_are_supportive():
    for v in ("subtype_restricted_dependency", "subtype_restricted_selectivity"):
        assert _subtype_spine_skill_report((v, "r"), _CARDS, _FIRED)["polarity"] == "supportive", v


# --- THE VOCABULARY: mapped explicitly, and failing the same direction as the gate ----------------


def test_every_recognized_subtype_verdict_is_mapped_EXPLICITLY():
    """Pinned against tp_gates' vocabulary, so ADDING a recognized verdict forces a decision here
    instead of silently taking a default. NEVER `neutral`: `canonical_polarity`'s headline fall-through
    would produce exactly that (the fan-out builds no headline), which is the favorable direction."""
    recognized = set(_RECOGNIZED_GATING_VERDICTS[SUBTYPE_SHORT])
    unmapped = sorted(recognized - set(_SUBTYPE_VERDICT_POLARITY))
    assert not unmapped, f"recognized subtype verdicts with no explicit polarity: {unmapped}"
    assert recognized, "precondition: the recognized-verdict set must not be empty"
    for v in sorted(recognized):
        pol = _subtype_spine_skill_report((v, "r"), _CARDS, _FIRED)["polarity"]
        assert pol != "neutral", f"{v} must not land on the neutral headline fall-through"


def test_an_unrecognized_verdict_fails_the_same_direction_as_the_gate():
    """The SECOND fall-through, pointing the other way: a renamed/unknown token must not read as
    "nothing measured" on the spine while tp_gates is fail-closing to a hold on it."""
    assert _GATING_AXIS_FAILCLOSED_ACTION[SUBTYPE_SHORT] == "hold"
    assert _SUBTYPE_UNRECOGNIZED_POLARITY == "opposing"
    sr = _subtype_spine_skill_report(("subtype_renamed_tomorrow", "r"), _CARDS, _FIRED)
    assert sr["polarity"] == "opposing"
    # and the DORMANT case must NOT be swept into that same default
    assert _subtype_spine_skill_report(None, _CARDS, _FIRED)["polarity"] == "not_scored"


# --- role=gating is justified by the COMPOSER, not by _SHORT_TO_GATE ------------------------------


def test_role_is_gating_even_though_the_axis_is_absent_from_SHORT_TO_GATE():
    """The one axis where role=gating does NOT imply membership in `_SHORT_TO_GATE`: it has no resolver
    (its verdict is panorama-derived) yet tp_gates maps its verdict to a hold. Pinned so a future reader
    cannot "fix" the apparent inconsistency by flipping the role and silently demoting a hold-capable
    axis to descriptive."""
    assert SUBTYPE_SHORT not in _SHORT_TO_GATE, "premise: no resolver gate"
    assert SUBTYPE_SHORT in _GATING_AXES, "premise: recommendation-forcing"
    assert _subtype_spine_skill_report(("subtype_specific_non_dependence", "r"), _CARDS, _FIRED)["role"] == "gating"


# --- BYTE-STABILITY of the readers this report newly reaches --------------------------------------


def test_atlas_rule_fingerprint_is_unchanged_by_supplying_the_report():
    """`fired_rule_ids_from_sub_results` takes the SPINE leg as soon as `provenance.fired_rule_ids` is
    non-empty, abandoning its legacy `fired` fallback. The two must yield the same set, or a display
    projection would silently move the atlas rule-fingerprint ("verdict-inert" != "atlas-inert")."""
    pair = ("subtype_specific_non_dependence", "r1")
    assert fired_rule_ids_from_sub_results(_tier(pair, facet=True)) == fired_rule_ids_from_sub_results(
        _tier(pair, facet=False)
    )


def test_claim_vector_and_numeric_readers_are_unchanged():
    """The facet carries ONLY `skill_report` — no `claim_vector` — and the report's `claim_chips` are
    empty, so `vector_from_sub_results` still takes its legacy fallback leg and the numeric harvester's
    claim_vector guard still misses. Paired control over both readers."""
    pair = ("subtype_restricted_dependency", "r2")
    assert vector_from_sub_results(_tier(pair, facet=True)) == vector_from_sub_results(_tier(pair, facet=False))
    assert numeric_values_from_sub_results(_tier(pair, facet=True)) == numeric_values_from_sub_results(
        _tier(pair, facet=False)
    )
    assert _subtype_spine_skill_report(pair, _CARDS, _FIRED)["claim_chips"] == []


def test_modality_scope_by_axis_gains_no_subtype_fit_entry():
    """The recorded regression risk, neutralized BY CONSTRUCTION rather than by luck:
    `_modality_scope_by_axis` reads the spine first and falls back to `claim_record_shadow`. The tier
    emits neither, and `modality_scope=None` keeps it that way — emitting one would invent a per-channel
    FOR-WHAT claim the subtype tier never computed."""
    pair = ("subtype_restricted_selectivity", "r3")
    assert _subtype_spine_skill_report(pair, _CARDS, _FIRED)["modality_scope"] is None
    assert _modality_scope_by_axis(_tier(pair, facet=True)) == _modality_scope_by_axis(_tier(pair, facet=False))
    assert SUBTYPE_SHORT not in _modality_scope_by_axis(_tier(pair, facet=True))


# --- THE NAMESPACE: this module's `__all__` shares one with every earlier import in run.py -----------


def _star_exports(module: str) -> "set | None":
    """What `from <module> import *` would bind, read from the AST — no import, so this can never
    degrade to a skip on an ImportError. `__all__` if present (it OVERRIDES the underscore rule),
    else the module-level public names."""
    path = SCRIPTS / f"{module}.py"
    if not path.exists():
        return None
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            return {e.value for e in node.value.elts if isinstance(e, ast.Constant)}
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return {n for n in names if not n.startswith("_")}


def _rebinding_problems(source: str, exports) -> list:
    """Names `source` binds EXPLICITLY that a LATER `from X import *` silently rebinds."""
    bound: dict = {}
    problems = []
    for node in ast.parse(source).body:
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        names = [a.name for a in node.names]
        if names == ["*"]:
            ex = exports(node.module)
            assert ex is not None, f"unresolved star-import module {node.module!r} — guard would be blind"
            for name in sorted(ex & set(bound)):
                src_mod, src_line = bound[name]
                if src_mod != node.module:
                    problems.append(
                        f"{name!r}: bound from {src_mod} (line {src_line}), "
                        f"rebound by `from {node.module} import *` (line {node.lineno})"
                    )
        else:
            for name in names:
                bound.setdefault(name, (node.module, node.lineno))
    return problems


def test_the_detector_for_star_import_rebinding_can_actually_fire():
    """POSITIVE CONTROL for the guard below — a zero from a detector that cannot detect proves nothing.
    This synthetic source is the exact shape of the real defect: an explicit named import, then a later
    star-import of a module whose `__all__` claims the same name."""
    problems = _rebinding_problems(
        "from tp_facets import _subtype_facet\nfrom tp_fanout import *\n",
        lambda m: {"_subtype_facet"} if m == "tp_fanout" else set(),
    )
    assert len(problems) == 1 and "_subtype_facet" in problems[0], problems


def test_no_later_star_import_in_run_py_rebinds_an_earlier_named_import():
    """THE DEFECT THIS CHANGE SHIPPED WITH ON ITS FIRST DRAFT, pinned so it cannot return.

    `run.py` binds `_subtype_facet` BY NAME from `tp_facets` (the cross-axis subtype CONVERGENCE blob,
    `tp_facets_subtype._subtype_facet`) and only LATER does `from tp_fanout import *`. `__all__` overrides
    the "star-import skips `_names`" rule and this module lists its underscore names, so calling the new
    spine helper `_subtype_facet` REBOUND `run._subtype_facet` to a 3-arg projection: 18 previously-green
    tests failed with `TypeError: missing 2 required positional arguments`. Sequential star-imports make
    every module's `__all__` a shared mutable namespace, and the LAST writer wins silently."""
    problems = _rebinding_problems((SCRIPTS / "run.py").read_text(), _star_exports)
    assert not problems, "a later star-import silently rebinds an explicitly imported name:\n  " + "\n  ".join(problems)


def test_the_spine_helpers_do_not_collide_with_the_convergence_facet_builder():
    """The specific collision, measured on the REAL binding rather than inferred from `__all__`:
    `run._subtype_facet` must still be the convergence builder that takes `sub_results` alone."""
    import inspect

    from _test_support import load_run_py

    run = load_run_py(SCRIPTS.parent, "tp_run_subtype_spine_collision")
    assert run._subtype_facet.__module__.endswith("tp_facets_subtype"), run._subtype_facet.__module__
    assert list(inspect.signature(run._subtype_facet).parameters) == [
        "sub_results",
        "indication",
        "contracts_repo",
    ]
    assert run._subtype_spine_facet is _subtype_spine_facet, "the spine helper must reach run.py unshadowed"


def test_the_facet_degrades_to_the_OLD_state_not_a_new_one(monkeypatch):
    """A provenance projection must never break the fan-out. On failure `_subtype_spine_facet` returns None,
    which is byte-identical to the pre-change behaviour (no facet ⇒ the spine reader skips the tier)."""
    import tp_fanout

    def _boom(*a, **k):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(tp_fanout, "build_skill_report", _boom)
    assert _subtype_spine_facet(("subtype_specific_non_dependence", "r"), _CARDS, _FIRED) is None
    assert _skill_reports_by_short({SUBTYPE_SHORT: {"synthesis_facet": None}}) == {}
