"""Unit tests for the shared field-disposition ledger guard primitives.

WHY THESE EXIST SEPARATELY from the fleet sweep in `skills/tests/test_field_disposition_ledgers.py`.
That sweep runs against the real tree, where the ledger is CLEAN — so it exercises only the passing
branch of every checker. A guard whose failing branch is never executed is indistinguishable from a
guard that cannot fail, and `wellformedness_problems` is now the single point of failure for every
ledger check in the repo: if it silently stopped detecting a class of problem, the fleet sweep and the
per-skill suite would BOTH go green together. So each problem class is driven here with a synthetic
document, one axis at a time.

ONE AXIS PER FIXTURE, on purpose. A doc mutated in five ways at once proves only that *something* was
detected — it cannot distinguish five working checks from one working check plus four dead ones.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from _skills_common import field_disposition as fd
from _skills_common import field_disposition_ledger as fdl

SKILLS_ROOT = Path(__file__).resolve().parents[2]


def _doc(**spec_overrides) -> dict:
    """A minimal VALID ledger, optionally with one row's spec overridden."""
    spec = {"role": "signal", "reason": "feeds the presence ladder"}
    spec.update(spec_overrides)
    return {
        "_meta": {"roles": "a signal must be wired or explicitly waived"},
        "some-card": {"_no_contract_fields": False, "a_field": spec},
    }


# ── the population: `_`-prefixed keys are metadata at BOTH levels ──────────────────────────────────


def test_iter_rows_skips_metadata_at_both_levels():
    """`_meta` sits beside the card entries and `_no_contract_fields` beside the field entries. A
    single-level skip treats `_meta` as a card and its keys as fields, which then fail every check for
    a reason that has nothing to do with the ledger's content."""
    rows = list(fdl.iter_rows(_doc()))
    assert rows == [("some-card", "a_field", {"role": "signal", "reason": "feeds the presence ladder"})]


def test_a_metadata_only_doc_yields_no_rows():
    """Documented vacuity boundary: a ledger with no real rows produces NO problems, so
    `wellformedness_problems` alone can never prove a ledger is being read. That is why every caller
    also pins a row count (MIN_SIGNAL_ROWS / MIN_FLEET_SIGNAL_ROWS / the run.py CARDS equality)."""
    assert list(fdl.iter_rows({"_meta": {"x": 1}})) == []
    assert fdl.wellformedness_problems({"_meta": {"x": 1}}) == []


# ── well-formedness: one axis per test ────────────────────────────────────────────────────────────


def test_clean_doc_has_no_problems():
    assert fdl.wellformedness_problems(_doc()) == []


@pytest.mark.parametrize(
    ("overrides", "needle"),
    [
        ({"role": "signalish"}, "bad role"),
        ({"role": None}, "bad role"),
        ({"reason": ""}, "empty reason"),
        ({"reason": "   "}, "empty reason"),
        ({"reason": None}, "empty reason"),
        ({"role": "display", "waived_because": "no consumer exists in analysis-methods yet"}, "only legal on signal"),
        ({"role": "context", "waived_because": "no consumer exists in analysis-methods yet"}, "only legal on signal"),
        ({"waived_because": "tbd"}, "name the missing consumer"),
        ({"waived_because": ""}, "name the missing consumer"),
        ({"reviewed": "true"}, "reviewed must be a bool"),
        ({"reviewed": 1}, "reviewed must be a bool"),
        ({"reviewed": "yes-really"}, "reviewed must be a bool"),
    ],
)
def test_each_wellformedness_problem_is_detected(overrides, needle):
    problems = fdl.wellformedness_problems(_doc(**overrides))
    assert problems, f"{overrides} produced NO problem — this check cannot fail"
    assert any(needle in p for p in problems), f"WRONG REASON for {overrides}: {problems}"


def test_reviewed_true_and_false_are_both_accepted():
    """`reviewed: false` must be legal, not just `true` — an `isinstance(..., bool)` check written as a
    truthiness check would reject the row that explicitly records "looked at, not confirmed"."""
    assert fdl.wellformedness_problems(_doc(reviewed=True)) == []
    assert fdl.wellformedness_problems(_doc(reviewed=False)) == []


def test_a_valid_waiver_on_a_signal_is_accepted():
    assert fdl.wellformedness_problems(_doc(waived_because="no consumer exists in analysis-methods yet")) == []


def test_all_problems_are_reported_not_just_the_first():
    """A fleet sweep over a growing set of ledgers must not degrade into one-fix-per-CI-run."""
    doc = _doc(role="displayy", reason="", reviewed="nope")
    assert len(fdl.wellformedness_problems(doc)) >= 3


# ── reach: only EXACT evidence counts, and a waiver is the only escape hatch ──────────────────────


def test_signal_reach_counts_exact_evidence_only_and_ignores_non_signal_rows():
    """`name_only` evidence is excluded because a bare field name credits every card declaring that
    name — the over-crediting direction, which would let the ratchet congratulate itself."""
    doc = {
        "c1": {"reached": {"role": "signal", "reason": "r"}},
        "c2": {"name_only_only": {"role": "signal", "reason": "r"}},
        "c3": {"absent_from_census": {"role": "signal", "reason": "r"}},
        "c4": {"not_a_signal": {"role": "display", "reason": "r"}},
    }
    cen = {
        ("c1", "reached"): {"exact": {"gating_rule"}, "name_only": set()},
        ("c2", "name_only_only"): {"exact": set(), "name_only": {"metric_gloss"}},
        ("c4", "not_a_signal"): {"exact": {"skill_code"}, "name_only": set()},
    }
    reach = fdl.signal_reach(doc, cen)
    assert reach == {
        ("c1", "reached"): {"gating_rule"},
        ("c2", "name_only_only"): set(),
        ("c3", "absent_from_census"): set(),
    }


def test_unwired_signals_flags_unreached_and_a_waiver_suppresses_it():
    doc = {
        "c1": {"unwired": {"role": "signal", "reason": "r"}},
        "c2": {"waived": {"role": "signal", "reason": "r", "waived_because": "owner is target-contracts"}},
        "c3": {"blank_waiver": {"role": "signal", "reason": "r", "waived_because": "   "}},
    }
    reach = {("c1", "unwired"): set(), ("c2", "waived"): set(), ("c3", "blank_waiver"): set()}
    assert fdl.unwired_signals(doc, reach) == ["c1.unwired", "c3.blank_waiver"]


def test_a_reached_signal_is_never_flagged():
    doc = {"c1": {"f": {"role": "signal", "reason": "r"}}}
    assert fdl.unwired_signals(doc, {("c1", "f"): {"salience"}}) == []


# ── the non-vacuity primitive ─────────────────────────────────────────────────────────────────────


def test_dark_reach_sources_names_each_half_independently():
    """The point of returning SOURCES rather than a bool: a partially degraded census keeps most reach
    and flips only a few fields, so a total cannot see it. Each independent census input must report
    dark when it alone finds nothing: contracts-only reach reports the skills side (and, per #1525, the
    cross-repo resolver side) dark, and vice versa."""
    assert fdl.dark_reach_sources({}) == sorted(fd.exact_capable_sources())
    contracts_only = {("c", "f"): {"gating_rule", "capsule"}}
    assert fdl.dark_reach_sources(contracts_only) == ["analysis_methods_resolver", "skills_tree_ast"]
    code_only = {("c", "f"): {"skill_code", "figure"}}
    assert fdl.dark_reach_sources(code_only) == ["analysis_methods_resolver", "contracts_declarations"]
    # #1525: the analysis-methods property resolver is a third independent census input (cross-repo
    # reach, kind `resolver_input`); resolver-only reach must report BOTH skills-side inputs dark.
    resolver_only = {("c", "f"): {"resolver_input"}}
    assert fdl.dark_reach_sources(resolver_only) == ["contracts_declarations", "skills_tree_ast"]
    all_three = {
        ("c", "f"): {"salience"},
        ("c", "g"): {"question_table"},
        ("c", "h"): {"gating_rule"},
        ("c", "i"): {"resolver_input"},
    }
    assert fdl.dark_reach_sources(all_three) == []


def test_exact_capable_sources_excludes_name_only_kinds():
    """`gloss_table` holds only `metric_gloss`, a NAME_ONLY kind, so it can never appear in `exact`
    evidence. Asserting it alive against exact reach would be a condition false by construction — the
    reason this set is derived rather than hand-listed. `analysis_methods_resolver` (#1525) IS exact-
    capable — its `resolver_input` kind is a literal cross-repo read — so it belongs in this set."""
    srcs = fd.exact_capable_sources()
    assert "gloss_table" not in srcs
    assert set(srcs) == {"analysis_methods_resolver", "contracts_declarations", "skills_tree_ast"}
    for kinds in srcs.values():
        assert not (kinds & fd.NAME_ONLY_KINDS)


# ── discovery ─────────────────────────────────────────────────────────────────────────────────────


def test_discover_finds_the_live_ledgers_and_they_parse():
    """Non-vacuity for the fleet sweep's own population: discovery must find something real in this
    tree, and what it finds must load and contain rows."""
    found = fdl.discover_ledgers(SKILLS_ROOT)
    assert found, f"no {fdl.LEDGER_NAME} discovered under {SKILLS_ROOT}"
    assert "tumor-presence" in found
    for skill, path in found.items():
        rows = list(fdl.iter_rows(fdl.load_ledger(path)))
        assert rows, f"{skill}: ledger discovered but yields no rows"


def test_discover_returns_empty_for_a_tree_with_no_ledgers(tmp_path):
    """Pins that an empty result is possible — so the fleet sweep's `assert found` is load-bearing and
    not asserting something that could never be false."""
    (tmp_path / "some-skill").mkdir()
    assert fdl.discover_ledgers(tmp_path) == {}


def test_discover_ignores_a_ledger_nested_below_the_skill_root(tmp_path):
    """A ledger describes one skill's cards and lives at the skill root. A recursive glob would pick up
    fixtures and copies under tests/ and silently gate them as if they were real."""
    nested = tmp_path / "some-skill" / "tests" / "fixtures"
    nested.mkdir(parents=True)
    (nested / fdl.LEDGER_NAME).write_text(yaml.safe_dump({"c": {"f": {"role": "signal", "reason": "r"}}}))
    assert fdl.discover_ledgers(tmp_path) == {}
