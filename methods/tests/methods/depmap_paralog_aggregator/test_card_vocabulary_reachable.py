"""paralog-buffering: card-declared class vocabulary == reader-reachable set (2026-09-12).

The card declared FIVE `paralog_buffering_class` tokens; this reader emits FOUR. `no_paralog` had
no emitter anywhere in the five repos, and nothing noticed, because the fleet's reachability check
runs the other way round: `validate_interpretation_rules` flags a RULE whose token is not in the
card vocabulary, so a token that is declared-but-never-emitted is a silently dead interpretation
branch — a rule can be written against it, pass every validator, and never fire.

target-contracts#748 removed it and declared the record shape of `functional_paralogs`, which was
hiding a FIFTH token in the opposite direction: `_classify_buffering` returns `unmeasured` for a
partner with no single-KO baseline, and because the field was a bare `list<struct>` that token was
in no vocabulary at all — a consumer matching it against the scalar vocabulary would bucket it as
`none`, i.e. read "could not measure" as "confirmed no buffering".

This guard pins both directions at once, and pins them SEPARATELY for the two grains, because the
reachable sets genuinely differ:

  scalar  paralog_buffering_class            {strong, partial, none, data_unavailable}
  record  functional_paralogs[].buffering_class  {strong, partial, none, unmeasured}

`unmeasured` cannot reach the scalar and `data_unavailable` cannot reach a record — that asymmetry
is the contract, not an oversight, and a guard that merged the two grains would accept either token
in either place. See test_scalar_and_record_grains_are_not_interchangeable.

Reachability is established BEHAVIOURALLY (call the classifier and the empty-result builder) and
then cross-checked STATICALLY (AST-scan both modules for every literal assigned to the key), so the
guard cannot be satisfied by a reader that stopped emitting a token, nor by one that started
emitting an undeclared one from a code path these tests do not exercise.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest
import yaml

from onc_methods.depmap_paralog_aggregator import read as reader

REPO = Path(__file__).resolve().parents[3]
# TARGET_CONTRACTS_ROOT first (CI sets it; a /tmp worktree's REPO.parent is /tmp, so the sibling
# fallback alone would make this file skip silently outside the primary checkout), then the sibling.
_CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT") or REPO.parent / "rnd-computational-biology-oncology-target-contracts"
)
CARD = _CONTRACTS / "cards" / "paralog-buffering.card.yaml"

_MODULE_DIR = Path(reader.__file__).parent
_SCANNED = ("read.py", "cli.py")

# The card's own header records WHY `no_paralog` is unreachable rather than merely absent: the only
# substrate is a dual-KO SCREEN, so a paralog-free gene is simply not in the PARIS library and is
# indistinguishable from a gene that has paralogs but was not screened. Reinstating it needs a
# genome-wide Ensembl Compara join at READ time, which this reader does not have. If that join ever
# lands, this constant is the one line to change — deliberately not a silent `in` check.
_RETIRED_TOKENS = frozenset({"no_paralog"})


def _card() -> dict | None:
    """The parsed card, or None when the sibling contracts repo is not checked out."""
    if not CARD.exists():
        return None
    return yaml.safe_load(CARD.read_text())


def _card_or_skip() -> dict:
    card = _card()
    if card is None:
        pytest.skip(f"target-contracts not checked out at {_CONTRACTS} (set TARGET_CONTRACTS_ROOT)")
    return card


def _record_enum(card: dict) -> set[str]:
    """The declared per-partner buffering_class enum.

    A MISSING declaration is the pre-#748 state and the whole reason `unmeasured` went unnoticed,
    so it must fail with that explanation rather than a bare KeyError from a chained subscript.
    """
    records = card["outputs"].get("summary_fields_record_schemas") or {}
    spec = (records.get("functional_paralogs") or {}).get("buffering_class")
    assert isinstance(spec, dict) and isinstance(spec.get("enum"), list), (
        "the card does not declare functional_paralogs[].buffering_class in "
        "outputs.summary_fields_record_schemas. While it was a bare `list<struct>` this reader's "
        "`unmeasured` token lived in NO vocabulary, so a consumer matching the field against the "
        "scalar vocabulary read 'could not measure' as 'confirmed no buffering'. Declare it "
        f"(target-contracts#748). Got: {spec!r}"
    )
    return set(spec["enum"])


# --- behavioural reachability -----------------------------------------------------------------


def _reachable_record_tokens() -> set[str]:
    """Per-partner tokens, by calling the classifier across every branch of its cut ladder."""
    deltas = [None, -1.0, 0.0, 0.19, 0.2, 0.35, 0.5, 0.51, 3.0]
    return {reader._classify_buffering(d) for d in deltas}


def _reachable_scalar_tokens() -> set[str]:
    """Scalar tokens.

    The scalar is `strongest["buffering_class"]` where `strongest` is the top MEASURED partner, so
    it inherits the classifier's output for a NON-None delta only; plus `data_unavailable`, which
    every no-data exit routes through `_empty_result`.
    """
    measured = {reader._classify_buffering(d) for d in [-1.0, 0.0, 0.19, 0.2, 0.35, 0.5, 0.51, 3.0]}
    return measured | {reader._empty_result("probe")["paralog_buffering_class"]}


def test_scalar_vocabulary_matches_card():
    card = _card_or_skip()
    declared = set(card["outputs"]["summary_fields_vocabulary"]["paralog_buffering_class"])
    reachable = _reachable_scalar_tokens()
    assert declared == reachable, (
        f"paralog_buffering_class drift.\n"
        f"  declared but NOT emitted (dead interpretation branch — a rule on it can never fire): "
        f"{sorted(declared - reachable)}\n"
        f"  emitted but NOT declared (escapes validate_interpretation_rules' reachability check): "
        f"{sorted(reachable - declared)}"
    )


def test_record_vocabulary_matches_card():
    card = _card_or_skip()
    declared = _record_enum(card)
    reachable = _reachable_record_tokens()
    assert declared == reachable, (
        f"functional_paralogs[].buffering_class drift.\n"
        f"  declared but NOT emitted: {sorted(declared - reachable)}\n"
        f"  emitted but NOT declared: {sorted(reachable - declared)}  "
        f"(an undeclared per-partner token is the dangerous direction — a consumer matching this "
        f"field against the SCALAR vocabulary silently buckets it as `none`)"
    )


def test_scalar_and_record_grains_are_not_interchangeable():
    """The two vocabularies must stay DIFFERENT in exactly the way the substrate dictates."""
    card = _card_or_skip()
    out = card["outputs"]
    scalar = set(out["summary_fields_vocabulary"]["paralog_buffering_class"])
    record = _record_enum(card)
    assert "unmeasured" in record and "unmeasured" not in scalar, (
        "`unmeasured` is a PER-PARTNER state only. The scalar is taken from the strongest MEASURED "
        "partner, and when no partner is measured the reader returns _empty_result "
        "(`data_unavailable`) — never `unmeasured`. Declaring it on the scalar would invite a rule "
        "that can never fire."
    )
    assert "data_unavailable" in scalar and "data_unavailable" not in record, (
        "`data_unavailable` is a WHOLE-READ state, emitted by _empty_result, which returns "
        "functional_paralogs=[] — so no record can ever carry it."
    )


def test_unmeasured_is_not_a_confirmed_no_buffer():
    """The measured-vs-null discipline, at the one line where it is easiest to lose."""
    assert reader._classify_buffering(None) == "unmeasured", (
        "a partner with no single-KO baseline must NOT classify as `none` — absence of the baseline "
        "is not evidence of no buffering, and `none` is what earns small_molecule:supportive."
    )
    assert reader._classify_buffering(0.0) == "none", "a MEASURED zero delta IS a confirmed no-buffer"


def test_empty_result_is_always_data_unavailable():
    """Every no-data exit routes through here, so its token is the scalar's only non-classifier source."""
    for note in ("paralog_data_unavailable", "paralog_single_ko_baseline_unavailable"):
        assert reader._empty_result(note)["paralog_buffering_class"] == "data_unavailable"


# --- static cross-check ------------------------------------------------------------------------


def _literals_assigned_to(key: str) -> set[str]:
    """Every string literal that appears as the value for `key` in a dict literal, across the
    reader modules. Catches a token emitted from a path the behavioural probes above never reach."""
    found: set[str] = set()
    for name in _SCANNED:
        tree = ast.parse((_MODULE_DIR / name).read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == key and isinstance(v, ast.Constant):
                    if isinstance(v.value, str):
                        found.add(v.value)
            # `row.get("paralog_buffering_class", "data_unavailable")` — the product-read default.
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and len(node.args) == 2
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == key
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
            ):
                found.add(node.args[1].value)
    return found


def test_static_scan_finds_no_undeclared_scalar_literal():
    card = _card_or_skip()
    declared = set(card["outputs"]["summary_fields_vocabulary"]["paralog_buffering_class"])
    literals = _literals_assigned_to("paralog_buffering_class")
    assert literals, (
        "the AST scan found NO literal assigned to paralog_buffering_class — the scan is broken (a "
        "refactor moved the emission, or _SCANNED is stale), so this guard would pass vacuously."
    )
    assert literals <= declared, (
        f"reader modules emit literal paralog_buffering_class value(s) the card does not declare: "
        f"{sorted(literals - declared)}"
    )


def test_retired_tokens_stay_retired():
    """A no-emitter token must not creep back into the card by a well-meaning 'completeness' edit."""
    card = _card_or_skip()
    out = card["outputs"]
    scalar = set(out["summary_fields_vocabulary"]["paralog_buffering_class"])
    record = _record_enum(card)
    offenders = _RETIRED_TOKENS & (scalar | record)
    assert not offenders, (
        f"{sorted(offenders)} is declared again. It is unreachable BY CONSTRUCTION on a dual-KO "
        "SCREEN substrate: a paralog-free gene is absent from the PARIS library, indistinguishable "
        "from an unscreened one, so both land in `data_unavailable`. Emitting it needs a genome-wide "
        "Ensembl Compara join at READ time. If that join has landed, add the emitter FIRST, then "
        "drop the token from _RETIRED_TOKENS here."
    )
    src = "\n".join((_MODULE_DIR / n).read_text() for n in _SCANNED)
    for token in _RETIRED_TOKENS:
        assert f'"{token}"' not in src and f"'{token}'" not in src, (
            f"{token!r} appears as a literal in the reader again — if it is now emitted, the card "
            "must declare it (and this guard's _RETIRED_TOKENS must drop it) in that order."
        )
