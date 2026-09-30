#!/usr/bin/env python3
"""card_warnings — a CEL-subset evaluator for the cards' authored `warning_predicates` (Track C Stage 4).

74 cards author 168 `warning_predicates` ({warning_id, if: "<expr>", message}), but nothing EVALUATES
them — `validate_cards._shallow_predicate_check` only LINTS the expression (balanced parens, no
python-isms). So 168 authored warnings are dormant. This module evaluates one against a card summary.

THE EXPRESSION LANGUAGE (the CEL subset the cards actually use): field references, single-quoted string
literals, `true`/`false`/`null`, numbers, `THRESHOLD.<name>`, comparisons (`==` `!=` `>` `<` `>=` `<=`),
`&&` `||` `!`, and parens. It is evaluated by translating those tokens (OUTSIDE string literals) to their
Python spellings and walking the resulting `ast` with a WHITELIST of node types — never `eval`, and never
a construct the whitelist does not name.

TWO CONTRACTS a warning layer must honour, both encoded here:
  1. `evaluate()` returns `None` (NOT False) when the predicate cannot be decided — an unknown field (one
     the card did not emit), a `THRESHOLD.<name>` with no value, or an unsupported construct (array index,
     `len()`, a bare unquoted token compared with `==`). A warning must never fire on a guess, and
     "unevaluable" is a different state from "evaluated false" (the caller decides what to do with each).
  2. `triage_predicate()` classifies a predicate WITHOUT running it — fireable, or a reason it can never
     fire (references a field no card summary declares, or uses a construct the DSL lacks). This is the
     Stage-4 mandate "triage all 168 first": a predicate that cannot fire is a dead warning to fix or
     delete, not shipped as if it worked.

VERDICT-INERT: nothing here feeds a rule/resolver/gate; wiring the result into the dispatcher's
run_health (validation_state → passed_with_warnings + warning_ids) is a separate, later step.
"""

from __future__ import annotations

import ast
import json
import operator
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml
from oncology_target_contracts import loader as _contracts_loader

# The E2 calibration register: (card_id, warning_id) pairs whose predicate is NON-DISCRIMINATING (fires on
# >90% or <1% of runs, measured over the corpus) — such a predicate carries ~no per-run information, so it
# is reported to calibration, NOT emitted as a per-run warning (else the warning channel inherits the exact
# non-discrimination problem the emission arc diagnoses). Absent file → no suppression (fail-open to
# emitting, which is safe: a missing register just means warnings are un-calibrated, never wrong).
_CALIBRATION_PATH = Path(__file__).resolve().parent / "warning_calibration.json"

_CMP = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Gt: operator.gt,
    ast.Lt: operator.lt,
    ast.GtE: operator.ge,
    ast.LtE: operator.le,
}
_ORDERING = (ast.Gt, ast.Lt, ast.GtE, ast.LtE)
# arithmetic (numeric only) — the cards use it inside comparisons, e.g. `(ci_hi - ci_lo) > 0.20`.
_BINOP = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


class _Unevaluable(Exception):
    """The predicate cannot be decided from this summary (unknown field / unsupported construct)."""


def _to_python_expr(predicate: str) -> str:
    """Translate the CEL-subset operators to their Python spellings, OUTSIDE single-quoted strings.

    Splitting on `'` isolates string literals to the odd segments (the cards use only single-quoted
    strings), so an operator token inside a literal is never rewritten."""
    parts = predicate.split("'")
    for i in range(0, len(parts), 2):  # even segments are outside quotes
        s = parts[i]
        s = s.replace("&&", " and ").replace("||", " or ")
        s = re.sub(r"!(?!=)", " not ", s)  # `!` but not `!=`
        s = re.sub(r"\btrue\b", "True", s)
        s = re.sub(r"\bfalse\b", "False", s)
        s = re.sub(r"\bnull\b", "None", s)
        parts[i] = s
    # strip: a leading `!`→` not ` puts a space at position 0, which ast.parse(mode="eval") rejects as
    # an unexpected indent.
    return "'".join(parts).strip()


def _ev(node, summary: dict, thresholds: dict):
    if isinstance(node, ast.BoolOp):
        vals = [_ev(v, summary, thresholds) for v in node.values]
        return all(vals) if isinstance(node.op, ast.And) else any(vals)
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.Not):
            return not _ev(node.operand, summary, thresholds)
        operand = _ev(node.operand, summary, thresholds)
        if isinstance(node.op, (ast.USub, ast.UAdd)) and isinstance(operand, (int, float)):
            return -operand if isinstance(node.op, ast.USub) else +operand
        raise _Unevaluable(f"unary op {type(node.op).__name__}")
    if isinstance(node, ast.BinOp):
        fn = _BINOP.get(type(node.op))
        left = _ev(node.left, summary, thresholds)
        right = _ev(node.right, summary, thresholds)
        if fn is None or not (isinstance(left, (int, float)) and isinstance(right, (int, float))):
            raise _Unevaluable("arithmetic on non-numeric / unsupported op")
        return fn(left, right)
    if isinstance(node, ast.Compare):
        left = _ev(node.left, summary, thresholds)
        for op, comp in zip(node.ops, node.comparators):
            right = _ev(comp, summary, thresholds)
            fn = _CMP.get(type(op))
            if fn is None:
                raise _Unevaluable(f"comparison op {type(op).__name__}")
            if isinstance(op, _ORDERING) and not (isinstance(left, (int, float)) and isinstance(right, (int, float))):
                raise _Unevaluable("ordering comparison on non-numeric")
            if not fn(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        # True/False/None already parsed as Constant; a bare Name is a summary field reference.
        if node.id not in summary:
            raise _Unevaluable(f"unknown field {node.id!r}")
        return summary[node.id]
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "THRESHOLD":
        if node.attr not in thresholds:
            raise _Unevaluable(f"THRESHOLD.{node.attr} not provided")
        return thresholds[node.attr]
    raise _Unevaluable(f"unsupported construct {type(node).__name__}")


def evaluate(predicate: str, summary: dict, thresholds: Optional[dict] = None) -> Optional[bool]:
    """Evaluate a warning predicate against a card `summary`. Returns True/False, or **None** when it
    cannot be decided (unknown field, missing THRESHOLD, unsupported construct, or a malformed expr) —
    a warning must never fire on a guess, and unevaluable ≠ false."""
    if not predicate or not predicate.strip():
        return None
    try:
        tree = ast.parse(_to_python_expr(predicate), mode="eval")
        return bool(_ev(tree.body, summary or {}, thresholds or {}))
    except _Unevaluable:
        return None
    except (SyntaxError, ValueError, TypeError):
        return None


# ── triage (Stage-4 mandate: know which of the 168 can fire before wiring the evaluator) ──────────────
_SUPPORTED_NODES = (
    (
        ast.Expression,
        ast.BoolOp,
        ast.And,
        ast.Or,
        ast.UnaryOp,
        ast.Not,
        ast.USub,
        ast.UAdd,
        ast.BinOp,
        ast.Compare,
        ast.Constant,
        ast.Name,
        ast.Load,
        ast.Attribute,
    )
    + tuple(_CMP)
    + tuple(_BINOP)
)


def triage_predicate(predicate: str, known_fields: set) -> tuple[bool, str]:
    """Classify a predicate WITHOUT a summary: `(fireable, reason)`. Not fireable when it fails to parse,
    uses a construct the DSL lacks (array index, call like len(), an attribute other than THRESHOLD.*), or
    references a field that is not a declared summary field (so no run can ever satisfy it)."""
    if not predicate or not predicate.strip():
        return (False, "empty predicate")
    try:
        tree = ast.parse(_to_python_expr(predicate), mode="eval")
    except (SyntaxError, ValueError):
        return (False, "does not parse")
    referenced: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if not (isinstance(node.value, ast.Name) and node.value.id == "THRESHOLD"):
                return (False, f"unsupported attribute access {getattr(node, 'attr', '?')}")
            continue
        if isinstance(node, ast.Name):
            if node.id != "THRESHOLD":
                referenced.add(node.id)
            continue
        if not isinstance(node, _SUPPORTED_NODES):
            return (False, f"unsupported construct {type(node).__name__} (e.g. index / len() / bare token)")
    missing = referenced - set(known_fields)
    if missing:
        return (False, f"references non-summary field(s): {sorted(missing)}")
    return (True, "fireable")


@lru_cache(maxsize=None)
def _card_warning_spec(card_id: str, contracts_root_str: str) -> tuple:
    """`((warning_id, if_expr), ...), thresholds` for a card — loaded from its contract. `((), {})` when
    the card yaml is absent or unreadable (best-effort; never raises into the emission path)."""
    # Route the card read through the packaged contracts loader (SK#2144 stage 3a) —
    # loader.load_card reads root/cards/{card_id}.card.yaml via yaml.safe_load, raising
    # FileNotFoundError when absent (in place of the prior is_file() guard). Best-effort
    # contract preserved: absent card OR malformed YAML → ((), {}), never raise.
    try:
        spec = _contracts_loader.load_card(card_id, root=Path(contracts_root_str)) or {}
    except (FileNotFoundError, yaml.YAMLError):
        return ((), {})
    preds = tuple(
        (w.get("warning_id"), w.get("if", ""))
        for w in (spec.get("warning_predicates") or [])
        if isinstance(w, dict) and w.get("warning_id")
    )
    return (preds, spec.get("thresholds") or {})


@lru_cache(maxsize=1)
def _load_calibration() -> frozenset:
    """The E2 register as `{(card_id, warning_id)}` to suppress. Empty when the file is absent."""
    if not _CALIBRATION_PATH.is_file():
        return frozenset()
    try:
        d = json.loads(_CALIBRATION_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return frozenset()
    return frozenset((c, w) for c, w in d.get("suppressed", []))


def fired_warnings(card_id: str, summary: dict, contracts_root=None, apply_calibration: bool = True) -> list:
    """The `warning_id`s whose predicate fires True on this card `summary`.

    Loads the card's `warning_predicates` + `thresholds` from its contract and evaluates each. A predicate
    that cannot be decided (`evaluate()` is None — unknown field, etc.) never fires. When
    `apply_calibration`, E2 non-discriminating (card_id, warning_id) pairs are skipped. Best-effort:
    absent card / no predicates → []."""
    from _skills_common.paths import target_contracts_root

    root = contracts_root or target_contracts_root()
    preds, thresholds = _card_warning_spec(card_id, str(root))
    if not preds:
        return []
    suppressed = _load_calibration() if apply_calibration else frozenset()
    return [
        wid for wid, expr in preds if (card_id, wid) not in suppressed and evaluate(expr, summary, thresholds) is True
    ]


__all__ = ["evaluate", "triage_predicate", "fired_warnings"]
