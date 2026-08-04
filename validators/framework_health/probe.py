"""probe.py — read-only ground-truth probes for framework-health.

Every probe reads what is ACTUALLY on disk and returns a small JSON-serializable
value. Probes never trust prose or a self-declared `status:` field — they derive
signals from files, then the rollup layer reconciles derived-vs-declared and
flags drift.

Two hard-won parsing rules (verified on disk 2026-08-04):
  1. CARD_DISPATCHERS and the `CARDS`/`SUB_SKILLS` lists carry inline comments and
     a COMMENTED example tail — so we AST-parse the literals, never grep/regex,
     which would over-count commented entries as live.
  2. A card being a KEY in CARD_DISPATCHERS does NOT mean it works — the backing
     method may be unbuilt or its import broken (e.g. normal-tissue-liability,
     tempus_rwd_aggregator). `fires_in_real_package` disambiguates registered-vs-working.

No probe raises: a read failure is recorded as an explicit value (error string /
None / False), mirroring the method live-readers' _live_read_error contract.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Optional

import yaml

# ---------------------------------------------------------------------------
# Repo-root discovery. This module lives at
#   <target-contracts>/validators/framework_health/probe.py
# so the contracts repo is two parents up. Sibling repos are resolved relative
# to that (all five repos are siblings under $HOME), overridable via CLI flags.
# ---------------------------------------------------------------------------
CONTRACTS_REPO = Path(__file__).resolve().parents[2]
_SIBLINGS = CONTRACTS_REPO.parent


def default_roots() -> dict[str, Path]:
    """Default sibling-repo roots; the CLI overrides any of these via flags."""
    return {
        "contracts": CONTRACTS_REPO,
        "skills": _SIBLINGS / "rnd-computational-biology-oncology-claude-oncology-skills",
        "methods": _SIBLINGS / "rnd-computational-biology-oncology-analysis-methods",
        "products": _SIBLINGS / "rnd-computational-biology-oncology-data-products",
        "catalog": _SIBLINGS / "rnd-computational-biology-oncology-data-catalog",
    }


# Skill dirs that are framework infra, not evaluation skills. Anything starting
# with "." (e.g. .pytest_cache) is also excluded by list_skill_names().
_NON_SKILL_DIRS = {"_skills_common", "tests"}


def list_skill_names(skills_root: Path) -> list[str]:
    """Enumerate real skill directories under <skills_root>/skills.

    A skill dir has a SKILL.md; infra dirs and dotdirs (.pytest_cache, __pycache__)
    are excluded so cache/artifact dirs never masquerade as broken skills.
    """
    sd = skills_root / "skills"
    if not sd.is_dir():
        return []
    return sorted(
        d.name for d in sd.iterdir()
        if d.is_dir()
        and not d.name.startswith(".")
        and d.name not in _NON_SKILL_DIRS
        and (d / "SKILL.md").exists()
    )


def _find_entrypoint(skill_dir: Path) -> Optional[Path]:
    """The skill's executable entrypoint.

    Prefers scripts/run.py (the wired-skill convention), else the sole/primary
    scripts/*.py — orchestration/retrieval/workflow skills use differently-named
    entrypoints (compose_dashboard.py, render_markdown.py, query_evidence.py, …),
    so assuming run.py wrongly marks them broken.
    """
    scripts = skill_dir / "scripts"
    if (scripts / "run.py").exists():
        return scripts / "run.py"
    if scripts.is_dir():
        pys = [p for p in sorted(scripts.glob("*.py")) if p.name != "__init__.py"]
        if pys:
            return pys[0]
    return None

# Prose maturity markers detected in SKILL.md bodies (declared-intent signal only —
# NOT authoritative; the derived probes decide actual health).
_PROSE_MARKERS = {
    "not_wired": re.compile(r"\bnot[_\s]wired\b|PLACEHOLDER SKILL", re.IGNORECASE),
    "placeholder": re.compile(r"\bplaceholder\b", re.IGNORECASE),
    "partial": re.compile(r"\bpartial\b", re.IGNORECASE),
    "graduated": re.compile(r"\bGRADUATED\b"),
    "wired": re.compile(r"\bstatus:\s*wired\b|\bfully wired\b", re.IGNORECASE),
}


# ===========================================================================
# Low-level AST helpers (the anti-over-count machinery)
# ===========================================================================
def _module_ast(py_path: Path) -> Optional[ast.Module]:
    try:
        return ast.parse(py_path.read_text())
    except (OSError, SyntaxError):
        return None


def _find_assign_literal(tree: ast.Module, name: str) -> Any:
    """Return the literal value of a module-level `name = <literal>` assignment.

    AST-based on purpose: the source lists carry inline comments and commented
    example tails that a regex would wrongly include. ast.literal_eval sees only
    the real literal nodes — comments never enter the tree.
    """
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    try:
                        return ast.literal_eval(node.value)
                    except (ValueError, SyntaxError):
                        return None
    return None


def _find_dict_keys(tree: ast.Module, name: str) -> Optional[list[str]]:
    """Return the string keys of a module-level `name = { ... }` dict literal.

    Used for CARD_DISPATCHERS: the values are function references (not literals,
    so literal_eval fails on the whole dict), but every KEY is a string constant.
    We walk the dict node and collect constant-string keys only — commented
    entries in the tail are not nodes, so they are excluded by construction.
    """
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name and isinstance(node.value, ast.Dict):
                    keys = []
                    for k in node.value.keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            keys.append(k.value)
                    return keys
    return None


def _calls_function(tree: ast.Module, func_name: str) -> bool:
    """True if the module contains any call to a function named func_name."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id == func_name:
                return True
            if isinstance(f, ast.Attribute) and f.attr == func_name:
                return True
    return False


def _resolver_gate_arg(tree: ast.Module) -> Optional[str]:
    """Extract the gate string from resolve_verdict_for_gate(fired, "<gate>")."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            fname = getattr(f, "id", None) or getattr(f, "attr", None)
            if fname == "resolve_verdict_for_gate":
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        return arg.value
    return None


# ===========================================================================
# SKILL.md frontmatter + prose
# ===========================================================================
def parse_skill_md(skill_dir: Path) -> dict:
    """Parse frontmatter (YAML between the first two `---` fences) + prose markers."""
    md = skill_dir / "SKILL.md"
    out: dict[str, Any] = {
        "skill_md_exists": md.exists(),
        "declared_status": None,
        "declared_phase": None,
        "cards_used": [],
        "rules_scope": [],
        "prose_markers": [],
        "parse_error": None,
    }
    if not md.exists():
        return out
    text = md.read_text()
    # Frontmatter: content between the first pair of --- fences.
    fm = None
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                fm = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError as e:
                out["parse_error"] = f"frontmatter yaml: {e}"
    if isinstance(fm, dict):
        comp = fm.get("composition") or {}
        # status/phase may be top-level, under composition, or under metadata.
        out["declared_status"] = (
            fm.get("status") or comp.get("status") or (fm.get("metadata") or {}).get("status")
        )
        out["declared_phase"] = fm.get("phase") or comp.get("phase")
        cu = comp.get("cards_used") or fm.get("cards_used") or []
        out["cards_used"] = [str(c) for c in cu] if isinstance(cu, list) else []
        # rules_scope names the verdict-driving (core) cards — the subset the rule
        # engine actually fires on. Cards in cards_used but NOT rules_scope are
        # additive/verdict-inert facet cards (biomarker facets, confidence meta).
        rs = comp.get("rules_scope") or []
        out["rules_scope"] = [str(c) for c in rs] if isinstance(rs, list) else []
    # Prose markers over the whole body (declared-intent signal only).
    out["prose_markers"] = sorted(name for name, rx in _PROSE_MARKERS.items() if rx.search(text))
    return out


# ===========================================================================
# Per-skill probe
# ===========================================================================
def probe_skill(skill_dir: Path) -> dict:
    """All ground-truth signals for one skill directory."""
    name = skill_dir.name
    run_py = _find_entrypoint(skill_dir)
    md = parse_skill_md(skill_dir)

    signals: dict[str, Any] = {
        "name": name,
        "declared": {
            "status": md["declared_status"],
            "phase": md["declared_phase"],
            "cards_used": md["cards_used"],
            "rules_scope": md.get("rules_scope", []),
            "prose_markers": md["prose_markers"],
            "skill_md_exists": md["skill_md_exists"],
            "skill_md_parse_error": md["parse_error"],
        },
        "derived": {
            "has_entrypoint": run_py is not None,
            "entrypoint": run_py.name if run_py else None,
            "kind": "UNKNOWN",
            "resolver_gate": None,
            "resolver_bound": False,
            "fans_out": False,
            "is_placeholder": False,
            "cards_in_runpy": [],
            "test_count": 0,
        },
    }
    der = signals["derived"]

    # Tests: skills/<skill>/tests/test_*.py
    tdir = skill_dir / "tests"
    der["test_count"] = len(list(tdir.glob("test_*.py"))) if tdir.is_dir() else 0

    if run_py is None:
        der["kind"] = "NO_ENTRYPOINT"
        return signals

    tree = _module_ast(run_py)
    if tree is None:
        der["kind"] = "UNPARSEABLE"
        return signals

    # CARDS list in run.py (AST literal).
    cards = _find_assign_literal(tree, "CARDS")
    der["cards_in_runpy"] = [str(c) for c in cards] if isinstance(cards, list) else []

    # Resolver binding.
    gate = _resolver_gate_arg(tree)
    der["resolver_gate"] = gate
    if gate is not None:
        der["resolver_bound"] = (CONTRACTS_REPO / "resolvers" / f"{gate}.resolver.yaml").exists()

    # Kind classification (from what run.py actually calls).
    der["is_placeholder"] = _calls_function(tree, "emit_placeholder")
    sub_skills = _find_assign_literal(tree, "SUB_SKILLS")
    der["fans_out"] = isinstance(sub_skills, list) and len(sub_skills) > 0

    if der["is_placeholder"]:
        der["kind"] = "PLACEHOLDER"
    elif der["fans_out"]:
        der["kind"] = "COMPOSED"
        # A composed skill's fan-out list is itself a probe target (count vs declared).
        der["fanout_count"] = len(sub_skills)
        der["fanout_members"] = [
            (list(x)[0] if isinstance(x, (list, tuple)) else str(x)) for x in sub_skills
        ]
    elif gate is not None:
        der["kind"] = "FOCUSED"
    elif _calls_function(tree, "run_wired_skill"):
        der["kind"] = "FOCUSED"  # wired dispatcher without an own resolver gate
    else:
        # Non-verdict skills: distinguish by the entrypoint name / known roles.
        ep = (run_py.name if run_py else "")
        if name in ("compose-dashboard", "render-evidence-package") or "compose" in ep or "render" in ep:
            der["kind"] = "ORCHESTRATION"
        elif name == "query-target-evidence" or "query" in ep:
            der["kind"] = "RETRIEVAL"
        elif name.startswith("workflow-") or "workflow" in ep or "report" in ep:
            der["kind"] = "WORKFLOW"
        else:
            der["kind"] = "OTHER"
    return signals


# ===========================================================================
# CARD_DISPATCHERS (live-reader registry) — AST dict keys, NOT grep
# ===========================================================================
def live_reader_card_ids(skills_root: Path) -> list[str]:
    """The set of card_ids that have a live-reader dispatcher.

    AST-parses the CARD_DISPATCHERS dict keys so the commented example tail
    (lines ~946-956) is excluded. A grep here over-counts rwd-stratified-expression
    et al. as live.
    """
    lr = skills_root / "skills" / "compose-dashboard" / "scripts" / "_live_readers.py"
    tree = _module_ast(lr)
    if tree is None:
        return []
    keys = _find_dict_keys(tree, "CARD_DISPATCHERS") or []
    return sorted(set(keys))


def dispatcher_method_imports(skills_root: Path) -> dict[str, str]:
    """card_id -> the method module the dispatcher actually imports.

    THE AUTHORITATIVE method-backing signal: the card's own `methods.call` label
    can be stale (e.g. tumor-vs-normal-selectivity labels `dge-tumor-vs-normal-selectivity`
    but the dispatcher imports `dge_deseq2`). The real routing is the dispatcher's
    `_import_method("<module>")` call. We map each _dispatch_* function to its first
    _import_method argument, then map card_id -> module via CARD_DISPATCHERS.
    """
    lr = skills_root / "skills" / "compose-dashboard" / "scripts" / "_live_readers.py"
    tree = _module_ast(lr)
    if tree is None:
        return {}

    # funcname -> imported module string (first _import_method call in that function).
    fn_to_module: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    f = sub.func
                    fname = getattr(f, "id", None) or getattr(f, "attr", None)
                    if fname == "_import_method" and sub.args:
                        a0 = sub.args[0]
                        if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                            fn_to_module[node.name] = a0.value
                            break

    # card_id -> dispatcher funcname (from the CARD_DISPATCHERS dict node).
    card_to_fn: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "CARD_DISPATCHERS" and isinstance(node.value, ast.Dict):
                    for k, v in zip(node.value.keys, node.value.values):
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            vname = getattr(v, "id", None)
                            if vname:
                                card_to_fn[k.value] = vname

    return {cid: fn_to_module[fn] for cid, fn in card_to_fn.items() if fn in fn_to_module}


# ===========================================================================
# Per-card probe
# ===========================================================================
def _load_card_yaml(card_id: str, contracts_root: Path) -> Optional[dict]:
    p = contracts_root / "cards" / f"{card_id}.card.yaml"
    if not p.exists():
        return None
    try:
        return yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError:
        return {"_parse_error": True}


_PLACEHOLDER_STATUS = {"blocked_needs_per_sample_reader", "out_of_scope"}
_PLACEHOLDER_TEXT = re.compile(r"placeholder|not yet landed|data not yet|not_wired", re.IGNORECASE)


def probe_card(
    card_id: str,
    contracts_root: Path,
    methods_root: Path,
    live_ids: set[str],
    fired_ids: set[str],
    dispatch_modules: dict[str, str] | None = None,
) -> dict:
    """Ground-truth signals for one card that a skill consumes.

    Method backing is resolved via the DISPATCHER's actual _import_method target
    (authoritative), NOT the card's methods.call label (which can be stale). The
    label is still recorded, and a mismatch surfaces as `stale_method_label`.
    """
    dispatch_modules = dispatch_modules or {}
    out: dict[str, Any] = {
        "card_id": card_id,
        "card_yaml_exists": False,
        "is_placeholder": False,
        "placeholder_reason": None,
        "measurement_type": None,
        "has_live_reader": card_id in live_ids,
        "method_call": None,           # card's declared label (may be stale)
        "dispatch_module": dispatch_modules.get(card_id),  # what the dispatcher imports
        "method_dir_exists": None,     # authoritative: does the dispatcher's module exist?
        "method_has_read": None,
        "stale_method_label": False,
        "fires_in_real_package": card_id in fired_ids,
    }
    card = _load_card_yaml(card_id, contracts_root)
    if card is None:
        return out
    out["card_yaml_exists"] = True
    out["measurement_type"] = card.get("measurement_type")

    status = card.get("status")
    if status in _PLACEHOLDER_STATUS:
        out["is_placeholder"] = True
        out["placeholder_reason"] = f"status:{status}"
    elif _PLACEHOLDER_TEXT.search(json.dumps(card)):
        out["is_placeholder"] = True
        out["placeholder_reason"] = "placeholder marker in card body"

    # Card's declared label (recorded for drift, NOT used as the backing truth).
    methods = card.get("methods") or []
    label_module = None
    if isinstance(methods, list) and methods and isinstance(methods[0], dict):
        call = methods[0].get("call")
        out["method_call"] = call
        if call:
            label_module = call.replace("-", "_")

    # AUTHORITATIVE backing = the module the dispatcher actually imports; fall back
    # to the card's label only when the card has no live-reader dispatcher.
    backing_module = out["dispatch_module"] or (label_module if not out["has_live_reader"] else None)
    if backing_module:
        # _import_method args may carry a submodule suffix (e.g. "opentargets_clingen.read",
        # "driver_role_overlay.cli") — the method DIR is the top-level package only.
        top_pkg = backing_module.split(".")[0]
        mdir = methods_root / "methods" / top_pkg
        out["method_dir_exists"] = mdir.is_dir()
        out["method_has_read"] = (mdir / "read.py").exists() if mdir.is_dir() else False
    # Stale-label hygiene flag: dispatcher routes to a different module than the card claims.
    if out["dispatch_module"] and label_module and out["dispatch_module"] != label_module:
        out["stale_method_label"] = True
    return out


# ===========================================================================
# data-products — which cards actually fired in a real emitted package
# ===========================================================================
def fired_card_ids(products_root: Path) -> set[str]:
    """card_ids that appear as pass/passed_with_warnings in any real evidence_package.json.

    Reads only non-.invalid packages. This is the signal that separates a card
    that is merely REGISTERED in the dispatcher map from one that actually WORKS
    end-to-end on a real target.
    """
    fired: set[str] = set()
    proot = products_root
    if not proot.exists():
        return fired
    for ep in proot.rglob("evidence_package.json"):
        if ".invalid" in ep.name:
            continue
        try:
            pkg = json.loads(ep.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for card in pkg.get("cards", []) or []:
            state = card.get("validation_state")
            if state in ("pass", "passed", "passed_with_warnings"):
                cid = card.get("card_id")
                if cid:
                    fired.add(cid)
    return fired


# ===========================================================================
# Registry-vs-disk drift (marketplace.json)
# ===========================================================================
def registry_drift(skills_root: Path, skill_names: list[str]) -> dict:
    """Compare the plugin marketplace registry against skills present on disk."""
    mp = skills_root / ".claude-plugin" / "marketplace.json"
    out: dict[str, Any] = {
        "marketplace_exists": mp.exists(),
        "registered": [],
        "on_disk": sorted(skill_names),
        "unregistered": sorted(skill_names),
    }
    if not mp.exists():
        return out
    try:
        data = json.loads(mp.read_text())
    except (OSError, json.JSONDecodeError):
        out["parse_error"] = True
        return out
    registered = []
    for plugin in data.get("plugins", []) or []:
        for s in plugin.get("skills", []) or []:
            registered.append(Path(str(s)).name)
    out["registered"] = sorted(set(registered))
    out["unregistered"] = sorted(set(skill_names) - set(registered))
    return out


# ===========================================================================
# short <-> skill_dir mapping (from target-profile SUB_SKILLS) + gate_coverage
# ===========================================================================
def sub_skill_map(skills_root: Path) -> dict[str, str]:
    """skill_dir -> short (gate key), parsed from target-profile's SUB_SKILLS."""
    run_py = skills_root / "skills" / "target-profile" / "scripts" / "run.py"
    tree = _module_ast(run_py)
    if tree is None:
        return {}
    subs = _find_assign_literal(tree, "SUB_SKILLS")
    out: dict[str, str] = {}
    if isinstance(subs, list):
        for item in subs:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                out[str(item[0])] = str(item[1])
    return out


def gate_coverage_by_short(contracts_root: Path) -> dict[str, dict]:
    """short -> {risk_category, framework_can_evidence, axis, gate} from gate_coverage.yaml.

    Reads the v2 three-list shape (biology_gates + modality_fit + biomarker_facets)
    and the v1 flat `gates:` fallback.
    """
    p = contracts_root / "vocabularies" / "gate_coverage.yaml"
    if not p.exists():
        return {}
    try:
        data = yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError:
        return {}
    out: dict[str, dict] = {}
    lists = ["biology_gates", "modality_fit", "biomarker_facets", "gates", "unbuilt"]
    for key in lists:
        for entry in data.get(key, []) or []:
            if isinstance(entry, dict) and "short" in entry:
                out[entry["short"]] = {
                    "risk_category": entry.get("risk_category"),
                    "framework_can_evidence": entry.get("framework_can_evidence"),
                    "axis": entry.get("axis"),
                    "gate": entry.get("gate"),
                }
    return out
