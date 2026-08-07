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

    # CARDS list in run.py (AST literal) + the optional SUBTYPE_CARDS list. A FOCUSED skill may
    # compose a tier:subtype PANORAMA card on a separate --subtypes-gated path (SUBTYPE_CARDS,
    # mirroring target-profile's SUB_SKILL subtype tier): the card needs subgroup_context threaded
    # so it is NOT on the scalar CARDS list, but it IS legitimately consumed and IS declared in
    # SKILL.md cards_used. Union it so the cards_used↔run.py check doesn't false-flag it as drift.
    cards = _find_assign_literal(tree, "CARDS")
    runpy_cards = [str(c) for c in cards] if isinstance(cards, list) else []
    subtype_cards = _find_assign_literal(tree, "SUBTYPE_CARDS")
    if isinstance(subtype_cards, list):
        runpy_cards += [str(c) for c in subtype_cards if str(c) not in runpy_cards]
    der["cards_in_runpy"] = runpy_cards

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
def dashboard_spec_card_ids(contracts_root: Path) -> dict[str, list[str]]:
    """card_id -> [spec names that list it]. Scans dashboards/*.dashboard_spec.yaml
    required_cards + optional_cards. A card consumed by a skill but absent from
    EVERY spec can never fire in an emitted package (the emission path pulls from a
    spec, not from a skill's cards_used) — the skill/spec coverage gap."""
    out: dict[str, list[str]] = {}
    ddir = contracts_root / "dashboards"
    if not ddir.is_dir():
        return out
    for p in sorted(ddir.glob("*.dashboard_spec.yaml")):
        try:
            spec = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError:
            continue
        name = spec.get("dashboard_id") or p.name[: -len(".dashboard_spec.yaml")]
        for key in ("required_cards", "optional_cards"):
            for entry in spec.get(key) or []:
                cid = entry.get("card_id") if isinstance(entry, dict) else None
                if cid:
                    out.setdefault(cid, []).append(name)
    return out


def list_all_card_ids(contracts_root: Path) -> list[str]:
    """Every card defined on disk (cards/*.card.yaml). The card-universe for the
    card-centric view — a superset of what any skill statically consumes, so it
    surfaces ORPHAN cards (defined but pulled by no skill)."""
    cdir = contracts_root / "cards"
    if not cdir.is_dir():
        return []
    return sorted(p.name[: -len(".card.yaml")] for p in cdir.glob("*.card.yaml"))


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


def catalog_manifests(catalog_root: Path) -> dict[str, dict]:
    """product_id -> {kind (source|derived), provider, version, license, size_bytes,
    file_count, system_of_record}, scanned from the data-catalog manifests.

    The dataset universe. A card's required_inputs.product_id is verified against
    this; a manifest here that no card references is an ORPHAN dataset.

    Keys are the manifest `id:` fields AND, additionally, each manifest's internal
    `product_id:` field when present. Indication-parameterized cards name the
    logical registry product (e.g. `expression-rna-tumor-vs-adjacent`), which is
    carried in the manifest's `product_id:` field rather than its per-indication
    `id:` (e.g. `coadread-dge-df06320`). Registering the product_id as an alias
    lets such a card resolve without falsely hard-coding one indication's id.
    A real manifest `id:` always wins over a product_id alias on key collision."""
    out: dict[str, dict] = {}
    aliases: dict[str, dict] = {}
    for kind in ("sources", "derived"):
        d = catalog_root / "manifests" / kind
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.yaml")):
            try:
                m = yaml.safe_load(p.read_text()) or {}
            except yaml.YAMLError:
                continue
            mid = m.get("id") or p.name[:-5]
            # STATIC access-cost inputs (no network): a declared query_optimization
            # sort/partition key is THE latency lever in this stack (sorted-read +
            # pushdown ~4x). Its PRESENCE is a structural signal; a large consumed
            # dataset without one is expensive to query. We record presence only —
            # never time an actual read (that would break the offline/deterministic
            # contract the whole dashboard rests on).
            qo = m.get("query_optimization") or {}
            has_sort_key = bool(isinstance(qo, dict) and (qo.get("sort_columns") or qo.get("sort_key")
                                                          or qo.get("primary_filter_column")))
            meta = {
                "kind": "source" if kind == "sources" else "derived",
                "provider": m.get("provider"),
                "version": m.get("version"),
                "license": m.get("license"),
                "size_bytes": m.get("total_size_bytes"),
                "file_count": m.get("file_count"),
                "system_of_record": m.get("system_of_record"),
                "derived_from": m.get("derived_from") or [],
                "has_sort_key": has_sort_key,   # static access-latency lever (query_optimization declared?)
            }
            out[mid] = meta
            # Register the logical registry product as an alias key. Multiple
            # per-indication manifests can share one product_id (e.g. the
            # tumor-vs-adjacent family); first one wins — the alias only needs to
            # prove the logical product exists in the catalog.
            prod = m.get("product_id")
            if prod and prod != mid and prod not in aliases:
                aliases[prod] = {**meta, "is_product_alias": True}

    # resolver-releases/ is a first-class catalog artifact tracked OUTSIDE manifests/
    # (versioned resolver pins keyed by `resolver_release:`, not `id:`). Cards that
    # depend on the resolver name it by the logical id `target-id-resolver-release`
    # (e.g. target-identity-summary), so register that id here — otherwise a real,
    # present artifact reads as a broken dataset ref (false positive). We register the
    # LOGICAL id once; individual release files are versions of the same product.
    rr_dir = catalog_root / "resolver-releases"
    if rr_dir.is_dir():
        releases = sorted(rr_dir.glob("*.yaml"))
        if releases:
            newest = releases[-1]  # lexical last ≈ newest version pin
            try:
                rm = yaml.safe_load(newest.read_text()) or {}
            except yaml.YAMLError:
                rm = {}
            out.setdefault("target-id-resolver-release", {
                "kind": "resolver_release",
                "provider": rm.get("provider"),
                "version": rm.get("resolver_release") or newest.name[:-5],
                "license": rm.get("license"),
                "size_bytes": None, "file_count": len(releases),
                "system_of_record": rm.get("system_of_record"),
                "derived_from": [],
            })

    # Real manifest ids take precedence over product_id aliases on collision.
    for k, v in aliases.items():
        out.setdefault(k, v)
    return out


def probe_card(
    card_id: str,
    contracts_root: Path,
    methods_root: Path,
    live_ids: set[str],
    fired_ids: set[str],
    dispatch_modules: dict[str, str] | None = None,
    catalog_ids: set[str] | None = None,
    modality_types: dict[str, list[str]] | None = None,
) -> dict:
    """Ground-truth signals for one card that a skill consumes.

    Method backing is resolved via the DISPATCHER's actual _import_method target
    (authoritative), NOT the card's methods.call label (which can be stale). The
    label is still recorded, and a mismatch surfaces as `stale_method_label`.

    Datasets: required_inputs.product_id are captured and (if catalog_ids given)
    verified against the data-catalog — a referenced id absent from the catalog
    is a broken data reference.

    P4 modality-vector lens: `modality_relevance` + a derived `modality_routing` verdict are
    recorded when `modality_types` (the vocab's type->routing-set map) is supplied. This is a
    PARALLEL dimension to card_health — routing metadata, NOT liveness — so it never feeds the
    card_health ladder (a card is equally "live" whether or not it declares a modality vector).
    """
    dispatch_modules = dispatch_modules or {}
    catalog_ids = catalog_ids if catalog_ids is not None else set()
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
        "datasets": [],                # required_inputs product_ids + catalog status
        # P4 modality-vector lens (routing metadata, parallel to card_health):
        "modality_relevance": None,    # the card's declared routing set (or None if absent)
        "modality_routing": "unknown",  # declared|not_required|missing|drift|not_applicable|unknown — see below
    }
    card = _load_card_yaml(card_id, contracts_root)
    if card is None:
        # No .card.yaml on disk (a broken ref / not-yet-authored id): routing is not applicable —
        # keep it out of the P4 tally's real states (a missing card is a card-existence problem,
        # already surfaced as card_health=broken, not a P4 non-compliance).
        out["modality_routing"] = "not_applicable"
        return out
    out["card_yaml_exists"] = True
    out["measurement_type"] = card.get("measurement_type")

    # Datasets: required_inputs[].product_id, each verified against the catalog.
    # Cards often name a LOGICAL id (e.g. "depmap-predictability") while the catalog
    # carries a version-suffixed id ("depmap-predictability-26q1-v2"). So match exact
    # first, then a prefix fallback — recording HOW it matched so a bare id-convention
    # mismatch (matched_by=prefix) isn't conflated with a genuinely absent dataset.
    ds = []
    for ri in (card.get("required_inputs") or []):
        if isinstance(ri, dict) and ri.get("product_id"):
            pid = str(ri["product_id"]).split("#")[0].strip()  # strip trailing inline comment
            if pid in catalog_ids:
                matched_by, resolved = "exact", pid
            else:
                pref = sorted(c for c in catalog_ids if c.startswith(pid + "-"))
                matched_by, resolved = ("prefix", pref[0]) if pref else (None, None)
            ds.append({"product_id": pid, "in_catalog": matched_by is not None,
                       "matched_by": matched_by, "resolved_id": resolved})
    out["datasets"] = ds

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
    # Stale-label hygiene flag: dispatcher routes to a different METHOD PACKAGE than the card claims.
    # Compare TOP-LEVEL packages — the dispatcher's _import_method arg routinely carries an
    # entry-point submodule suffix (e.g. "tcga_gtex_expression_distribution.cli",
    # "expression_purity_confound.cli") that is NOT a stale label; only a different top-level package
    # is a real drift (e.g. card says depmap-protein-abundance-distribution but dispatcher imports
    # depmap_protein_abundance). Stripping the suffix removes the false-positive on the .cli/.read
    # convention while still catching a genuine module mismatch. (Fixed 2026-08-04.)
    if out["dispatch_module"] and label_module:
        if out["dispatch_module"].split(".")[0] != label_module.split(".")[0]:
            out["stale_method_label"] = True

    # ── P4 modality-vector lens ────────────────────────────────────────────
    # Mirror the commit-time validator's verdict (validate_cards.py::_modality_relevance_check)
    # as a DASHBOARD-VISIBLE signal — surfacing P4 adoption/drift in the health artifact rather
    # than re-deriving anything the validator doesn't already own. Verdicts:
    #   declared     — field present (and, if the type routes, subset of the type's routing set)
    #   not_required — measurement_type is not a modality-routing type (correctly silent)
    #   missing      — type IS modality-routing but field absent (the validator's ERROR state)
    #   drift        — declared values not a subset of the type's routing set (validator WARNING)
    #   unknown      — vocab unavailable (isolated checkout) → no verdict asserted
    mr = card.get("modality_relevance")
    out["modality_relevance"] = list(mr) if isinstance(mr, list) else ([mr] if mr else None)
    if modality_types is None:
        out["modality_routing"] = "unknown"
    else:
        routing_set = modality_types.get(out["measurement_type"]) if out["measurement_type"] else None
        is_required = routing_set is not None  # type declares modality_relevance in the vocab
        if out["modality_relevance"]:
            if is_required and not set(out["modality_relevance"]).issubset(set(routing_set)):
                out["modality_routing"] = "drift"
            else:
                out["modality_routing"] = "declared"
        else:
            out["modality_routing"] = "missing" if is_required else "not_required"
    return out


# ===========================================================================
# skills — per-subskill "runs clean?" health (the deterministic smoke tier)
# ===========================================================================
def subskill_run_health(skills_root: Path) -> dict[str, dict]:
    """skill_name -> its committed run-health record from the skills repo's
    _skills_common/subskill_health.json (produced by the framework_health_smoke harness).

    This is the "RUNS CLEAN?" liveness tier: a DETERMINISTIC, OFFLINE smoke of each
    wired subskill's real run.py (card readers stubbed — NO live data). Distinct from
    fired_card_ids(), which asks "did a card fire in a real compose-dashboard package?"
    (the incidental, coverage-limited signal). runs-clean decouples subskill liveness
    from which orchestrator happened to run + get committed.

    Degrades gracefully to {} when the artifact is absent (e.g. the skills repo has a
    different branch checked out, or an isolated checkout) — exactly like every other
    sibling-repo probe. Absence → the dashboard simply omits the runs-clean tier, never
    a false negative.
    """
    p = skills_root / "skills" / "_skills_common" / "subskill_health.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    subs = data.get("subskills")
    return subs if isinstance(subs, dict) else {}


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


def modality_relevant_types(contracts_root: Path) -> Optional[dict[str, list[str]]]:
    """measurement_type -> its declared modality_relevance routing set, for every type whose
    vocab entry declares `modality_relevance:` (the P4 modality-fit-routing types).

    Mirrors validate_cards.py::_modality_relevant_types (the commit-time enforcer) but kept LOCAL
    to the health module — the dashboard must not import the validator (different path assumptions,
    and the probe layer never imports sibling tooling). Vocab-anchored, so a type stamped in the
    vocab automatically becomes a P4-requiring type here too. Returns None if the vocab is absent
    (graceful-skip → the P4 lens reports `unknown`, never a false verdict, in an isolated checkout).
    """
    p = contracts_root / "vocabularies" / "measurement_types.yaml"
    if not p.exists():
        return None
    try:
        data = yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError:
        return None
    types = data.get("measurement_types")
    if not isinstance(types, dict):
        return None
    out: dict[str, list[str]] = {}
    for name, entry in types.items():
        if isinstance(entry, dict) and entry.get("modality_relevance"):
            mr = entry["modality_relevance"]
            out[name] = list(mr) if isinstance(mr, list) else [mr]
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
