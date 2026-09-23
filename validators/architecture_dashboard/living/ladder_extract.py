"""ladder_extract.py — a rule-engine skill's rule→verdict precedence ladder, from source.

AST-parses a skill's ``scripts/run.py`` for its ``_*_RANK`` precedence ladders — module-level
``list[tuple[rule_id, verdict]]`` literals — into an ordered ``[{rule_id, verdict, tier, layer}]``
map, WITHOUT importing or executing the skill (so no pixi / skill deps are needed, and reading
untrusted-ish source is side-effect-free). Precedence is positional: ``tier`` is the rung's index
in its ladder, 0 = highest precedence (the consumer `_rank_verdict` returns the first fired rung).

Two skill shapes, one extractor:

* **rule-engine / python-ladder** (e.g. tumor-presence): defines ``_*_RANK`` list-of-2-tuple
  literals and computes the verdict inline (no resolver). ``verdict_source = "python_ladder"``.
* **resolver-backed** (e.g. tumor-selectivity): NO ``_*_RANK`` literals; delegates to
  ``resolve_or_raise(fired, "<gate>")`` (``_skills_common.resolver``), the precedence ladder
  living in ``resolvers/<gate>.resolver.yaml`` in target-contracts. The extractor short-circuits:
  ``verdict_source = "resolver_yaml"`` + the ``gate`` name, and the assembler reads the ladder
  from ``graph["resolvers"][gate]`` instead.

Validation (best-effort; only runs where inputs are supplied): every ladder verdict token must be
in the skill's pinned verdict enum (which lives in *this* repo, so it is available even on a
sibling-free CI runner), and every rung's ``rule_id`` must exist among the atlas graph's card
rules. Findings are returned as ``errors`` rather than raised so a build never aborts on drift.

stdlib only (ast/json/pathlib).
"""

from __future__ import annotations

import ast
from pathlib import Path

# A skill whose run.py calls resolve_or_raise(fired, "<gate>") delegates precedence to a resolver
# YAML; this is the callee name we scan for to detect the short-circuit + recover the gate.
_RESOLVER_CALLS = {"resolve_or_raise", "resolve"}


def _const_str(node: ast.AST) -> str | None:
    """The string value of an ast.Constant str node, else None."""
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _ladder_rungs(value: ast.AST) -> list[tuple[str, str]] | None:
    """If ``value`` is a ``[("rule_id", "verdict"), ...]`` literal (every element a 2-tuple of
    string constants), return the rungs; else None. This naturally excludes computed ladders
    (``_VERDICT_RANK`` is a BinOp concatenation) and the ``_MEASUREMENT_RANK`` dict."""
    if not isinstance(value, (ast.List, ast.Tuple)):
        return None
    rungs: list[tuple[str, str]] = []
    for elt in value.elts:
        if not isinstance(elt, ast.Tuple) or len(elt.elts) != 2:
            return None
        rid, verdict = _const_str(elt.elts[0]), _const_str(elt.elts[1])
        if rid is None or verdict is None:
            return None
        rungs.append((rid, verdict))
    return rungs or None


def _assignments(tree: ast.Module):
    """Yield (name, value_node) for every module-level ``NAME = ...`` / ``NAME: T = ...``."""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    yield tgt.id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            yield node.target.id, node.value


def _measurement_layers(tree: ast.Module) -> dict[str, str]:
    """Reverse of ``_MEASUREMENT_RANK = {"<layer>": _SOME_RANK, ...}``: map each ladder constant
    name → its measurement layer (bulk_rna / bulk_protein_ms / sc_rna), so a rung can be labelled
    with the data layer it decides, not just the constant it came from."""
    out: dict[str, str] = {}
    for name, value in _assignments(tree):
        if name != "_MEASUREMENT_RANK" or not isinstance(value, ast.Dict):
            continue
        for k, v in zip(value.keys, value.values):
            layer = _const_str(k)
            if layer and isinstance(v, ast.Name):
                out[v.id] = layer
    return out


def _resolver_gate(tree: ast.Module) -> str | None:
    """The gate string in the first ``resolve_or_raise(fired, "<gate>")`` call found, else None."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        callee = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else None)
        if callee not in _RESOLVER_CALLS:
            continue
        # positional gate is the 2nd arg; also accept gate=/name= keyword forms.
        if len(node.args) >= 2:
            g = _const_str(node.args[1])
            if g:
                return g
        for kw in node.keywords:
            if kw.arg in ("gate", "name"):
                g = _const_str(kw.value)
                if g:
                    return g
    return None


def _layer_label(const_name: str, measurement: dict[str, str]) -> str:
    """The measurement layer if the ladder is wired into ``_MEASUREMENT_RANK``, else a readable
    fallback derived from the constant name (``_EXPRESSION_RANK`` → ``expression``)."""
    if const_name in measurement:
        return measurement[const_name]
    return const_name.strip("_").removesuffix("_RANK").lower()


def skill_of(run_py: Path) -> str:
    """``.../skills/<skill>/scripts/run.py`` → ``<skill>`` (best-effort)."""
    parts = Path(run_py).resolve().parts
    if "skills" in parts:
        i = parts.index("skills")
        if i + 1 < len(parts):
            return parts[i + 1]
    return Path(run_py).stem


def extract_ladder(
    run_py: str | Path,
    *,
    enum: list[str] | set[str] | None = None,
    graph_rule_ids: set[str] | None = None,
) -> dict:
    """Extract the rule→verdict ladder from a skill's ``run.py``.

    Returns a dict with a stable shape regardless of skill kind::

        {
          "skill": "tumor-presence",
          "verdict_source": "python_ladder" | "resolver_yaml" | None,  # None = no verdict ladder
          "gate": None | "<gate>",           # set only for resolver_yaml
          "ladders": [ {"name": "_EXPRESSION_RANK", "layer": "bulk_rna",
                        "rungs": [{"rule_id","verdict","tier","layer"}, ...]}, ... ],
          "rungs":   [ ...flat, ladder-declaration order then rung order... ],
          "verdict_tokens": [ ...sorted unique... ],
          "rule_ids":       [ ...sorted unique... ],
          "errors":  [ ...token-not-in-enum / rule_id-not-in-graph... ],
        }
    """
    run_py = Path(run_py)
    src = run_py.read_text()
    tree = ast.parse(src)
    skill = skill_of(run_py)

    measurement = _measurement_layers(tree)
    ladders: list[dict] = []
    for name, value in _assignments(tree):
        if not name.endswith("_RANK"):
            continue
        rungs = _ladder_rungs(value)
        if rungs is None:
            continue  # computed / dict ranks (e.g. _VERDICT_RANK, _MEASUREMENT_RANK)
        layer = _layer_label(name, measurement)
        ladders.append(
            {
                "name": name,
                "layer": layer,
                "rungs": [
                    {"rule_id": rid, "verdict": verdict, "tier": tier, "layer": layer}
                    for tier, (rid, verdict) in enumerate(rungs)
                ],
            }
        )

    if not ladders:
        gate = _resolver_gate(tree)
        # Three skill shapes, one extractor. With no ``_*_RANK`` ladder either:
        #   * a ``resolve_or_raise`` gate is found → resolver-backed (``resolver_yaml``); the
        #     assembler reads the ladder from ``graph["resolvers"][gate]``.
        #   * NO gate either → a descriptive / support / gateless skill (literature-context,
        #     target-intrinsic, catalog-query, …) that legitimately collapses to NO verdict.
        #     This is a CLEAN classification (``verdict_source = None``), not drift, so no error
        #     is surfaced — the product page renders it as an honest "no verdict ladder" block
        #     rather than fabricating a spine. (A gating skill whose gate we FAILED to recover is
        #     caught downstream by product_page.build against the code-map's gating shorts.)
        return {
            "skill": skill,
            "verdict_source": "resolver_yaml" if gate else None,
            "gate": gate,
            "ladders": [],
            "rungs": [],
            "verdict_tokens": [],
            "rule_ids": [],
            "errors": [],
        }

    flat = [rung for lad in ladders for rung in lad["rungs"]]
    verdict_tokens = sorted({r["verdict"] for r in flat})
    rule_ids = sorted({r["rule_id"] for r in flat})

    errors: list[str] = []
    if enum is not None:
        enum_set = set(enum)
        for v in verdict_tokens:
            if v not in enum_set:
                errors.append(f"{skill}: verdict '{v}' not in pinned enum")
    if graph_rule_ids is not None:
        for rid in rule_ids:
            if rid not in graph_rule_ids:
                errors.append(f"{skill}: rule_id '{rid}' not among atlas card rules")

    return {
        "skill": skill,
        "verdict_source": "python_ladder",
        "gate": None,
        "ladders": ladders,
        "rungs": flat,
        "verdict_tokens": verdict_tokens,
        "rule_ids": rule_ids,
        "errors": errors,
    }
