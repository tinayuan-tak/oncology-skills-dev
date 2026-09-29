"""code_maps_extract.py — the subskill→gate and subskill→risk-category maps the atlas omits.

AST-parses three ``claude-oncology-skills`` source modules (no import / execution needed):

* ``skills/target-profile/scripts/tp_fanout.py`` — ``SUB_SKILLS`` (skill_dir → short),
  ``_SHORT_TO_GATE`` (the 8 gating shorts → resolver gate), ``_CONFIDENCE_AXIS_TO_GATE``.
* ``skills/_skills_common/risk_projection.py`` — ``AXIS_TO_DIM`` (axis → risk-6dim bin, the
  RUNTIME authority), ``AXIS_DIM_EXCLUSIONS`` (axis → declared-exclusion state).
* ``skills/_skills_common/report_render/ir.py`` — ``_CONTEXT_DIM`` (gateless display axes → dim,
  deliberately disjoint from AXIS_TO_DIM).

It then emits ``registry_vs_code_risk_drift``: per registry question (from
``vocabularies/target_profiling_axes.yaml``), the ``risk_category`` the registry declares vs the
risk dim the runtime code actually bins into. Runtime ``risk_6dim`` bins come from the CODE, so
the code is authoritative and the registry is the thing that drifts. This surfaces the finding as
data (it is NOT fixed here — see issue #856); the block is non-empty iff registry ≠ code.

stdlib only (ast/pathlib) + pyyaml for the registry read.
"""

from __future__ import annotations

import ast
from pathlib import Path

# tp_fanout.py, risk_projection.py, ir.py — relative to the skills-repo root.
_TP_FANOUT = "skills/target-profile/scripts/tp_fanout.py"
_RISK_PROJECTION = "skills/_skills_common/risk_projection.py"
_IR = "skills/_skills_common/report_render/ir.py"


def _module_str_consts(tree: ast.Module) -> dict[str, str]:
    """Module-level ``NAME = "literal"`` string constants, so ``Name`` references inside other
    literals (e.g. ``AXIS_DIM_EXCLUSIONS`` uses ``DECLARED_DESCRIPTIVE``) resolve to their value."""
    consts: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                consts[node.targets[0].id] = node.value.value
    return consts


def _literal(node: ast.AST, consts: dict[str, str]):
    """Evaluate a restricted literal: Constant, dict/list/tuple/set of literals, a ``Name`` that
    resolves via ``consts``, and ``str + str`` concatenation (BinOp Add). Anything else → None,
    so a value we cannot statically resolve is recorded as absent rather than guessed."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [_literal(e, consts) for e in node.elts]
    if isinstance(node, ast.Dict):
        return {_literal(k, consts): _literal(v, consts) for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _literal(node.left, consts), _literal(node.right, consts)
        if isinstance(left, str) and isinstance(right, str):
            return left + right
    return None


def _named(tree: ast.Module, name: str, consts: dict[str, str]):
    """The evaluated literal of module-level ``name = ...`` / ``name: T = ...``, else None."""
    for node in tree.body:
        tgt = None
        if isinstance(node, ast.Assign):
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                tgt = node.targets[0].id
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            tgt = node.target.id
        if tgt == name and getattr(node, "value", None) is not None:
            return _literal(node.value, consts)
    return None


def _parse(path: Path) -> tuple[ast.Module, dict[str, str]]:
    tree = ast.parse(path.read_text())
    return tree, _module_str_consts(tree)


def extract_code_maps(sk_root: str | Path) -> dict:
    """Extract the code maps from the three source modules under ``sk_root``.

    Returns::

        {
          "sub_skills": [{"skill","short"}, ...],       # SUB_SKILLS
          "short_to_gate": {short: gate},               # _SHORT_TO_GATE (8 gating shorts)
          "confidence_axis_to_gate": {axis: gate},      # _CONFIDENCE_AXIS_TO_GATE
          "axis_to_dim": {axis: dim},                   # AXIS_TO_DIM (runtime risk authority)
          "axis_dim_exclusions": {axis: state},         # AXIS_DIM_EXCLUSIONS (state only)
          "context_dim": {axis: dim},                   # _CONTEXT_DIM (gateless display map)
          "errors": [ ...missing-file / unparsed-constant... ],
        }
    """
    sk_root = Path(sk_root)
    errors: list[str] = []

    def _get(rel: str, names: list[str]) -> dict:
        p = sk_root / rel
        if not p.exists():
            errors.append(f"missing source: {rel}")
            return {n: None for n in names}
        tree, consts = _parse(p)
        out = {}
        for n in names:
            v = _named(tree, n, consts)
            if v is None:
                errors.append(f"{rel}: could not extract {n}")
            out[n] = v
        return out

    fan = _get(_TP_FANOUT, ["SUB_SKILLS", "_SHORT_TO_GATE", "_CONFIDENCE_AXIS_TO_GATE"])
    risk = _get(_RISK_PROJECTION, ["AXIS_TO_DIM", "AXIS_DIM_EXCLUSIONS"])
    ir = _get(_IR, ["_CONTEXT_DIM"])

    # SUB_SKILLS is a list of (skill_dir, short) tuples → list of {skill, short}
    sub_skills = []
    for pair in fan.get("SUB_SKILLS") or []:
        if isinstance(pair, list) and len(pair) == 2:
            sub_skills.append({"skill": pair[0], "short": pair[1]})

    # AXIS_DIM_EXCLUSIONS values are {"state": <const>, "reason": <prose>} → keep state only.
    exclusions = {}
    for axis, spec in (risk.get("AXIS_DIM_EXCLUSIONS") or {}).items():
        exclusions[axis] = spec.get("state") if isinstance(spec, dict) else None

    return {
        "sub_skills": sub_skills,
        "short_to_gate": fan.get("_SHORT_TO_GATE") or {},
        "confidence_axis_to_gate": fan.get("_CONFIDENCE_AXIS_TO_GATE") or {},
        "axis_to_dim": risk.get("AXIS_TO_DIM") or {},
        "axis_dim_exclusions": exclusions,
        "context_dim": ir.get("_CONTEXT_DIM") or {},
        "errors": errors,
    }


def risk_drift(code_maps: dict, axes: dict) -> list[dict]:
    """Diff the registry's per-question ``risk_category`` against the runtime code's risk dim.

    ``axes`` is the parsed ``target_profiling_axes.yaml``. For each question the code dim is
    ``AXIS_TO_DIM[short]`` (a gated/counted axis) or, failing that, ``_CONTEXT_DIM[short]`` (a
    gateless display axis). An entry is emitted when the two disagree, OR when the code has no
    mapping for that short at all (a key mismatch — e.g. registry ``translational`` vs code
    ``translational_readiness``), so nothing silently passes.

    Returned rows (sorted by short) each carry the classification of the disagreement::

        {short, registry_risk_category, code_risk_dim, code_source, exclusion_state, kind}
        kind ∈ {"category_mismatch", "unmapped_in_code"}
    """
    axis_to_dim = code_maps.get("axis_to_dim") or {}
    context_dim = code_maps.get("context_dim") or {}
    exclusions = code_maps.get("axis_dim_exclusions") or {}
    rows: list[dict] = []
    for q in axes.get("questions") or []:
        short = q.get("short")
        registry = q.get("risk_category")
        if short in axis_to_dim:
            code_dim, source = axis_to_dim[short], "AXIS_TO_DIM"
        elif short in context_dim:
            code_dim, source = context_dim[short], "_CONTEXT_DIM"
        else:
            code_dim, source = None, None
        if code_dim is None:
            rows.append(
                {
                    "short": short,
                    "registry_risk_category": registry,
                    "code_risk_dim": None,
                    "code_source": None,
                    "exclusion_state": exclusions.get(short),
                    "kind": "unmapped_in_code",
                }
            )
        elif code_dim != registry:
            rows.append(
                {
                    "short": short,
                    "registry_risk_category": registry,
                    "code_risk_dim": code_dim,
                    "code_source": source,
                    "exclusion_state": exclusions.get(short),
                    "kind": "category_mismatch",
                }
            )
    return sorted(rows, key=lambda r: r["short"] or "")
