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
import operator
import re
from typing import Optional

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


__all__ = ["evaluate", "triage_predicate"]
