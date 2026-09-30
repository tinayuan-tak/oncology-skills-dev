"""EMITTER <-> ENUM cross-check for contracts/vocabularies/concordance_class.enum.yaml (arc #2210, 0b).

The enum is a governance file in contracts/, and the contracts-side validator checks its SHAPE. Shape
is not truth: a perfectly-shaped roster can describe a vocabulary the code stopped emitting three PRs
ago, and nothing on the contracts side can tell, because contracts/ may not import skills/ (the
dependency direction is skills/ -> contracts/, never the reverse). This module is the truth half. It
re-derives the emitted token sets FROM THE BUILDERS on every run and asserts equality with the enum.

FOUR CLAUSES, and the reason each is here rather than on the contracts side:

  1. STATIC DISCOVERY == ENUM, PER FAMILY, BOTH DIRECTIONS. Every `concordance_class` token each
     fold-builder can assign is extracted from its AST and compared with the enum's roster for that
     family. Both directions, because one direction catches only half the drift: enum-minus-code is a
     stale roster, code-minus-enum is an ungoverned token. Neither is acceptable and they fail
     differently.

  2. THE EXTRACTOR FAILS LOUD. It models exactly four value shapes (a string constant, a conditional
     expression, a call into a module-level helper whose returned constants it collects, and a tuple
     assignment) and RAISES on anything else. A tolerant extractor is the trap here: an extractor that
     shrugged at an unrecognised shape would silently discover fewer tokens, the equality check would
     then compare two small sets, and the suite would go green while covering nothing. It also asserts
     each builder has EXACTLY ONE `concordance_class` emission fed by the local it tracks — so a
     builder that grows a second, differently-computed emission reds here rather than being missed.

  3. BEHAVIOURAL SWEEP. Every family in the live ENVELOPE_FAMILIES registry is actually CALLED with
     its resolving input, and the token it emits must be in the enum. Static discovery and execution
     answer different questions: the AST says what is reachable, the call says what happens. A token
     that the AST finds but no input can produce is a different defect from a token the AST misses.

  4. RELATION VOCABULARY EQUALITY AGAINST THE LIVE FROZENSET. The enum's relations block must equal
     `DEPENDENCE_RELATIONS` exactly. contracts/validators/validate_property_catalog.py keeps a
     HARDCODED mirror of that set (`VALID_RELATIONS`), which can drift silently; this clause pins the
     enum to the real thing, and the contracts-side validator pins the enum to the mirror, so the
     mirror is transitively checked. That is the only place the drift is catchable.

THE `contradicts` COVERAGE DIMENSION. The enum records that no family fold reaches `contradicts`, with
a named witness for where it IS reached. Both halves are EXECUTED here, not read: the witness is driven
until it returns a live `contradicts` edge, and the family folds are swept to confirm none of them do.
This is deliberately a DIMENSION (a count, asserted with a floor) and not a gate on the absence itself
— an absence-assertion that goes vacuous is a design change disguised as a pass, and the day a family
legitimately gains an opposed arm the honest outcome is that the witness/roster stops matching and the
decision gets re-made, not that a red appears claiming a regression.

Verdict-INERT: this module only READS emitted structures and asserts nothing about any verdict, in
either direction (SK#2091).
"""

from __future__ import annotations

import ast
import pathlib
import sys

import pytest
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # skills/ -> _skills_common
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # tests/ -> sibling registry module

from _skills_common import presence_claims  # noqa: E402
from _skills_common.dependence_edges import DEPENDENCE_RELATIONS, concordance_relation  # noqa: E402
from test_rung5_envelope_enforcement import ENVELOPE_FAMILIES  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SKILLS_COMMON = pathlib.Path(__file__).resolve().parents[1]
ENUM_PATH = REPO_ROOT / "contracts" / "vocabularies" / "concordance_class.enum.yaml"

ENUM = yaml.safe_load(ENUM_PATH.read_text())
ENUM_FAMILIES: dict = ENUM["families"]
EMITTED_KEY = "concordance_class"


# ==================================================================================================
# The fail-loud static extractor.
# ==================================================================================================


class UnreadableEmission(Exception):
    """An emission shape the extractor does not model.

    Raised rather than swallowed ON PURPOSE. Returning an empty or partial set here would make the
    equality clauses compare two small sets and pass while covering nothing — the exact shape of a
    green for the wrong reason. If this fires, extend the extractor; do not loosen it.
    """


def _module_ast(rel_builder: str) -> ast.Module:
    return ast.parse((REPO_ROOT / rel_builder).read_text(), filename=rel_builder)


def _toplevel_funcs(tree: ast.Module) -> dict:
    return {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _string_constants(node: ast.AST, where: str, funcs: dict, depth: int = 0) -> set:
    """Every string value an expression can evaluate to. Four modelled shapes; raises on the rest."""
    if depth > 3:
        raise UnreadableEmission(f"{where}: expression nests deeper than the extractor models")
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.IfExp):
        return _string_constants(node.body, where, funcs, depth + 1) | _string_constants(
            node.orelse, where, funcs, depth + 1
        )
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        target = funcs.get(node.func.id)
        if target is None:
            raise UnreadableEmission(f"{where}: call to `{node.func.id}` is not a module-level function here")
        out: set = set()
        for ret in (n for n in ast.walk(target) if isinstance(n, ast.Return)):
            if ret.value is None:
                continue
            out |= _string_constants(ret.value, f"{where}->{node.func.id}", funcs, depth + 1)
        if not out:
            raise UnreadableEmission(f"{where}: helper `{node.func.id}` returns no string constants")
        return out
    raise UnreadableEmission(f"{where}: unreadable {type(node).__name__} at line {getattr(node, 'lineno', '?')}")


def discover_tokens(rel_builder: str, func_name: str) -> set:
    """Every `concordance_class` token `func_name` can emit, read off its AST."""
    tree = _module_ast(rel_builder)
    funcs = _toplevel_funcs(tree)
    fn = funcs.get(func_name)
    if fn is None:
        raise UnreadableEmission(f"{rel_builder}: no top-level `{func_name}`")

    emissions = 0
    tokens: set = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == EMITTED_KEY:
                    emissions += 1
                    # The extractor tracks the local `concordance`; an emission fed by anything else
                    # would be discovered as an empty set, so make it LOUD instead.
                    if not (isinstance(value, ast.Name) and value.id == "concordance"):
                        raise UnreadableEmission(
                            f"{func_name}: `{EMITTED_KEY}` is fed by {type(value).__name__}, not the local "
                            f"`concordance` this extractor follows"
                        )
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "concordance":
                    tokens |= _string_constants(node.value, f"{func_name}:{node.lineno}", funcs)
                elif isinstance(target, ast.Tuple):
                    for i, element in enumerate(target.elts):
                        if isinstance(element, ast.Name) and element.id == "concordance":
                            if not isinstance(node.value, ast.Tuple):
                                raise UnreadableEmission(
                                    f"{func_name}:{node.lineno}: tuple target with a non-tuple value"
                                )
                            tokens |= _string_constants(node.value.elts[i], f"{func_name}:{node.lineno}", funcs)
    if emissions != 1:
        raise UnreadableEmission(f"{func_name}: expected exactly 1 `{EMITTED_KEY}` emission, found {emissions}")
    if not tokens:
        raise UnreadableEmission(f"{func_name}: discovered no tokens — the extractor read nothing")
    return tokens


DISCOVERED: dict = {
    family: discover_tokens(spec["builder"], spec["builder_function"]) for family, spec in ENUM_FAMILIES.items()
}


# ==================================================================================================
# Anti-vacuity. Every clause below is parametrized or set-based; these floors are what stop an empty
# population reading as a clean run.
# ==================================================================================================


def test_population_is_not_vacuous():
    # The floors over DISCOVERED are written as `len(DISCOVERED)` / `len(DISCOVERED.values())`
    # deliberately, naming the subject INSIDE the assert. An earlier version bound the count to a
    # local first (`total = sum(...); assert total >= 40`), which reads the same to a human but ties
    # the floor to nothing a static reader can follow back to `DISCOVERED` —
    # skills/tests/test_discovery_guards_carry_floors.py flagged this module as floorless on exactly
    # that basis, and it was right to: a floor the repo's own guard cannot see is a floor the next
    # refactor can delete without anything going red.
    assert len(ENUM_FAMILIES) == 13, f"expected 13 families in the enum, found {sorted(ENUM_FAMILIES)}"
    assert len(ENVELOPE_FAMILIES) >= 13, f"registry shrank to {len(ENVELOPE_FAMILIES)}"
    assert len(ENUM["values"]) >= 40, f"expected >= 40 tokens, found {len(ENUM['values'])}"
    assert len(DISCOVERED) == 13, f"static discovery covered {len(DISCOVERED)} families, not 13"
    assert sum(len(t) for t in DISCOVERED.values()) >= 40, (
        f"static discovery found only {sum(len(t) for t in DISCOVERED.values())} (family, token) "
        f"pairs across 13 builders"
    )
    assert all(DISCOVERED.values()), [f for f, t in DISCOVERED.items() if not t]


def test_enum_families_match_the_live_registry():
    """The enum's roster and the live ENVELOPE_FAMILIES registry must be the same families.

    The contracts-side validator pins the enum to integrated_families.yaml; this pins it to the code.
    A family in the registry with no token roster is an ungoverned vocabulary; a family in the enum
    that the registry dropped is a stale claim of coverage.
    """
    assert set(ENUM_FAMILIES) == set(ENVELOPE_FAMILIES), {
        "only in enum": sorted(set(ENUM_FAMILIES) - set(ENVELOPE_FAMILIES)),
        "only in registry": sorted(set(ENVELOPE_FAMILIES) - set(ENUM_FAMILIES)),
    }


# ==================================================================================================
# CLAUSE 1 — static discovery == enum, per family, both directions.
# ==================================================================================================


@pytest.mark.parametrize("family", sorted(ENUM_FAMILIES))
def test_enum_tokens_match_what_the_builder_can_emit(family):
    enum_tokens = set(ENUM_FAMILIES[family]["tokens"])
    code_tokens = DISCOVERED[family]
    assert enum_tokens == code_tokens, {
        "family": family,
        "builder": f"{ENUM_FAMILIES[family]['builder']} :: {ENUM_FAMILIES[family]['builder_function']}",
        "in enum, NOT emitted (stale roster)": sorted(enum_tokens - code_tokens),
        "emitted, NOT in enum (ungoverned token)": sorted(code_tokens - enum_tokens),
    }


def test_the_inverse_index_agrees_with_the_code_too():
    """`values[*].families` is the enum's other index. The contracts validator checks the two indexes
    against each other; this checks the inverse one against the CODE, so they cannot both be wrong in
    the same direction and still agree."""
    from_values: dict = {}
    for entry in ENUM["values"]:
        for family in entry["families"]:
            from_values.setdefault(family, set()).add(entry["value"])
    assert from_values == DISCOVERED, {
        family: {
            "values index": sorted(from_values.get(family, set())),
            "code": sorted(DISCOVERED.get(family, set())),
        }
        for family in set(from_values) | set(DISCOVERED)
        if from_values.get(family, set()) != DISCOVERED.get(family, set())
    }


def test_extractor_is_loud_on_a_shape_it_cannot_read():
    """Clause 2's teeth. If the extractor ever degrades to returning a partial set, every equality
    clause above compares two small sets and passes while covering nothing."""
    tree = ast.parse(
        "def f():\n    concordance = some_unknown_call(x)\n    return {'concordance_class': concordance}\n"
    )
    funcs = _toplevel_funcs(tree)
    with pytest.raises(UnreadableEmission):
        discover_tokens_from(funcs, "f")


def discover_tokens_from(funcs: dict, name: str) -> set:
    """Extractor core against an already-parsed function table — used only by the teeth test above."""
    fn = funcs[name]
    tokens: set = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "concordance":
                    tokens |= _string_constants(node.value, f"{name}:{node.lineno}", funcs)
    return tokens


def test_extractor_finds_the_expected_shapes():
    """Positive control for the extractor: each of the four modelled shapes is actually present in the
    landed population, so the fail-loud branch above is not the only exercised path."""
    # a plain constant + conditional expressions (the majority)
    assert "single_source_only" in DISCOVERED["recurrence"]
    # a call into a module-level helper whose returns are collected
    assert DISCOVERED["abundance"] == {"abundance_concordant", "rna_high_protein_low", "rna_low_protein_high"}
    # a tuple assignment (`concordance, coverage_dir = "...", "..."`)
    assert DISCOVERED["coverage"] == {"coverage_concordant", "bulk_masks_low_coverage"}


# ==================================================================================================
# CLAUSE 3 — behavioural sweep.
# ==================================================================================================


@pytest.mark.parametrize("family", sorted(ENVELOPE_FAMILIES))
def test_emitted_token_is_governed(family):
    """Call the builder for real. The AST says what is reachable; this says what happens."""
    spec = ENVELOPE_FAMILIES[family]
    claim = spec["builder"](spec["resolving"])
    assert claim is not None, f"{family}: the registry's resolving input no longer emits a claim"
    token = claim.get(EMITTED_KEY)
    assert token is not None, f"{family}: emitted no `{EMITTED_KEY}`"
    roster = ENUM_FAMILIES.get(family, {}).get("tokens", [])
    assert token in roster, f"{family}: emitted ungoverned token {token!r}; enum lists {sorted(roster)}"


def test_behavioural_sweep_covers_every_family_in_the_enum():
    """Anti-vacuity for the parametrization above: a registry entry that stopped resolving would make
    its case vanish rather than fail, so assert the coverage explicitly."""
    emitted = {}
    for family, spec in ENVELOPE_FAMILIES.items():
        claim = spec["builder"](spec["resolving"])
        if claim is not None and claim.get(EMITTED_KEY) is not None:
            emitted[family] = claim[EMITTED_KEY]
    missing = sorted(set(ENUM_FAMILIES) - set(emitted))
    assert not missing, f"no executed token for {missing} — those families' behavioural cases were inert"


# ==================================================================================================
# CLAUSE 4 — relation vocabulary equality against the live frozenset.
# ==================================================================================================


def test_enum_relations_equal_the_live_dependence_vocabulary():
    """EQUALITY against the real `DEPENDENCE_RELATIONS`, not against the contracts-side mirror.

    contracts/validators/validate_property_catalog.py hardcodes `VALID_RELATIONS` as a copy of this
    frozenset. That copy can drift silently. The contracts validator pins the enum to the copy and
    this pins the enum to the original, so the copy is transitively checked — this is the only place
    that drift is catchable.
    """
    named = {entry["relation"] for entry in ENUM["relations"]["values"]}
    assert named == set(DEPENDENCE_RELATIONS), {
        "in enum only": sorted(named - set(DEPENDENCE_RELATIONS)),
        "in DEPENDENCE_RELATIONS only": sorted(set(DEPENDENCE_RELATIONS) - named),
    }


def test_disposition_relation_map_matches_what_the_constructor_returns():
    """Derive the expected relation from `concordance_relation()` itself rather than asserting mere
    membership in the closed set.

    The first version of this test only checked `dependence_relation in DEPENDENCE_RELATIONS`, and a
    planted mutant that remapped `concordant` to `contradicts` sailed through it — `contradicts` is a
    member. Membership is not the claim worth making; the claim is that the enum's semantics are the
    ones the constructor implements, and the only way to assert that is to call it.
    """
    for disposition in ENUM["dispositions"]:
        name = disposition["disposition"]
        expected = concordance_relation(concordant=(name == "concordant"))
        assert disposition["dependence_relation"] == expected, (
            f"disposition `{name}` declares `{disposition['dependence_relation']}` but "
            f"concordance_relation(concordant={name == 'concordant'}) returns `{expected}`"
        )


def test_contradicts_needs_an_explicit_opposed_flag():
    """Why the conservative value sits on the fall-through: reaching `contradicts` takes an explicit
    `opposed=True`, so no disposition can arrive there by default. This is the property that makes
    `contradicts` absent from the family folds a consequence of construction rather than a coincidence
    the enum happens to record."""
    assert concordance_relation(concordant=False) == "qualifies"
    assert concordance_relation(concordant=False, opposed=True) == "contradicts"
    # `opposed` is only honoured when NOT concordant — a fold cannot both agree and contradict.
    assert concordance_relation(concordant=True, opposed=True) == "corroborates"


# ==================================================================================================
# The `contradicts` coverage DIMENSION — both halves executed, neither gated on an absence.
# ==================================================================================================


def _relation_entry(name: str) -> dict:
    return next(e for e in ENUM["relations"]["values"] if e["relation"] == name)


def test_the_contradicts_witness_actually_returns_a_contradicts_edge():
    """Drive the witness the enum names. `contradicts` IS reachable in landed production code — the
    prior recorded premise ("no landed builder emits contradicts") was false as stated, and only
    becomes true once scoped to family FOLDS. A witness that is merely written down would let the
    corrected premise rot back into the wrong one.
    """
    witness = _relation_entry("contradicts")["emitted_outside_family_folds_by"]
    assert witness["builder_function"] == "_provider_call_corroboration"
    fn = getattr(presence_claims, witness["builder_function"], None)
    assert fn is not None, (
        f"the enum's `contradicts` witness names {witness['builder_function']} in "
        f"{witness['builder']}, which no longer exists — the recorded absence is now unverified"
    )
    # re-derived direction `up`, provider significant but DOWN => direction_discordant => opposed
    result = fn(("up", "high"), True, False, 500.0)
    assert result is not None
    assert result["concordance"] == "direction_discordant"
    assert result["edge"]["relation"] == "contradicts", result["edge"]
    # The field it emits is `concordance`, NOT `concordance_class` — which is why this vocabulary is
    # recorded in the enum as related-but-ungoverned rather than as values.
    assert EMITTED_KEY not in result
    assert witness["emits_field"] == "concordance"


def test_the_contradicts_control_still_reaches_corroborates():
    """Control for the test above: the same function on agreeing inputs must NOT say contradicts, or
    its red would not be attributable to the discordant branch."""
    result = presence_claims._provider_call_corroboration(("up", "high"), True, True, 500.0)
    assert result["concordance"] == "concordant"
    assert result["edge"]["relation"] == "corroborates"


def test_relation_emission_coverage_dimension_is_measured_not_gated():
    """The dimension itself: how many family folds reach each relation, asserted as a COUNT with a
    floor rather than as an absence.

    The floor is what has teeth — it fails if the sweep goes vacuous. The `contradicts` count is
    recorded and compared against the enum's own claim, so the day a family gains an opposed arm the
    enum and the code disagree and the decision is re-made deliberately. There is deliberately NO
    assertion of the form "contradicts never appears": that is the absence-assertion that goes
    vacuous, and it would be false at repository grain anyway (see the witness test above).
    """
    disposition_relation = {d["disposition"]: d["dependence_relation"] for d in ENUM["dispositions"]}
    token_disposition = {e["value"]: e["disposition"] for e in ENUM["values"]}

    reached: dict = {relation: set() for relation in DEPENDENCE_RELATIONS}
    for family, spec in ENVELOPE_FAMILIES.items():
        for token in DISCOVERED.get(family, set()):
            relation = disposition_relation[token_disposition[token]]
            reached[relation].add(family)

    # Anti-vacuity floors — the part that can fail.
    assert len(reached["corroborates"]) >= 13, sorted(reached["corroborates"])
    assert len(reached["qualifies"]) >= 11, sorted(reached["qualifies"])

    # The measured dimension, reconciled against what the enum claims rather than gated.
    for relation, families in sorted(reached.items()):
        claimed = _relation_entry(relation)["emitted_by_family_folds"]
        assert bool(families) == claimed, (
            f"relation `{relation}`: {len(families)} family fold(s) reach it "
            f"({sorted(families)}) but the enum records emitted_by_family_folds={claimed} — "
            f"re-make the Wave-0b decision deliberately rather than editing the flag"
        )


def test_documented_not_emitted_tokens_are_really_not_emitted():
    """The `documented_not_emitted` block records tokens named in a builder's own prose but absent
    from its behaviour. If one of them ever starts being emitted it must move to `values`, so assert
    the absence against the CODE rather than trusting the block."""
    all_discovered = set().union(*DISCOVERED.values())
    for entry in ENUM.get("documented_not_emitted") or []:
        assert entry["token"] not in all_discovered, (
            f"{entry['token']} is recorded as documented-but-not-emitted, but static discovery found "
            f"it — it is now a value and belongs in `values`"
        )


def test_related_ungoverned_vocabulary_is_really_a_different_field():
    """The ungoverned register names concordance-shaped vocabularies this enum does NOT govern. If one
    of them turned out to be on `concordance_class` after all, it would be an ungoverned token in the
    governed field — the exact gap this file closes."""
    for entry in ENUM.get("related_ungoverned_vocabularies") or []:
        assert entry["field"] != EMITTED_KEY, entry
        assert entry["tokens"], entry
