"""concepts.py — the Concepts & Schemas layer.

For each of the ~8 component types (concepts.yaml), emit a record:
  {id, title, order, narration, schema{shape}, example{fields}, defined_in{count, glob, link}}
The narration is the only hand-authored prose (type-level, in concepts.yaml); the schema
shape, example fields, counts, and links are ALL generated from disk on every build.

stdlib + pyyaml + json only — NO skill execution, NO network. Example instances are read
from committed files in the sibling repos.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

HOME = Path.home()
_DEFAULT_REPO_DIR = {
    "tc": "rnd-computational-biology-oncology-target-contracts",
    "sk": "rnd-computational-biology-oncology-claude-oncology-skills",
    "dc": "rnd-computational-biology-oncology-data-catalog",
    "dp": "rnd-computational-biology-oncology-data-products",
}


def _load_yaml(p: Path):
    try:
        with open(p) as fh:
            return yaml.safe_load(fh)
    except Exception:
        return None


def _repo_root(repo: str, roots: dict) -> Path:
    """Resolve a concepts.yaml repo tag (tc/sk/dc/dp) to a checkout path."""
    key = {"tc": "target_contracts", "sk": "skills", "dc": "data_catalog", "dp": "data_products"}.get(repo)
    if key and roots.get(key):
        return Path(roots[key])
    # fall back to sibling-of-target-contracts, else $HOME
    tc = Path(roots.get("target_contracts") or (HOME / _DEFAULT_REPO_DIR["tc"]))
    return tc.parent / _DEFAULT_REPO_DIR.get(repo, "")


def _first(root: Path, glob: str) -> Path | None:
    matches = sorted(root.glob(glob))
    return matches[0] if matches else None


def _schema_shape(path: Path, defs_key: str | None = None) -> dict:
    """Compact shape of a JSON schema: required + top prop names/types + enums. Not the full file."""
    try:
        d = json.loads(path.read_text())
    except Exception as e:
        return {"error": f"unreadable schema {path.name}: {e}"}
    node = d
    if defs_key:
        node = (d.get("$defs") or d.get("definitions") or {}).get(defs_key, {})
    props = node.get("properties") or {}
    fields = []
    req = set(node.get("required") or [])
    for name, spec in props.items():
        spec = spec if isinstance(spec, dict) else {}
        typ = spec.get("type")
        if isinstance(typ, list):
            typ = "|".join(typ)
        enum = spec.get("enum")
        fields.append({"name": name, "type": typ or "", "required": name in req,
                       "enum": [str(e) for e in enum][:12] if isinstance(enum, list) else None,
                       "desc": (spec.get("description") or "")[:140]})
    # if a oneOf/tagged union with no direct props, note the branches
    branches = []
    if not fields and node.get("oneOf"):
        for b in node["oneOf"]:
            branches.append(sorted((b.get("properties") or {}).keys())[:8])
    return {"title": node.get("title") or path.stem, "required": sorted(req),
            "fields": fields, "branches": branches,
            "n_props": len(fields), "defs_key": defs_key}


def _python_schema_shape(path: Path) -> dict:
    """For the skill composition contract (a .py module) — surface the declared keys, best-effort."""
    try:
        txt = path.read_text()
    except Exception as e:
        return {"error": f"unreadable {path.name}: {e}"}
    # Grab REQUIRED_KEYS / ALLOWED_KEYS-ish literals if present, else the known composition keys.
    import re
    keys = []
    for m in re.finditer(r'"([a-z_]+)"\s*:', txt):
        keys.append(m.group(1))
    known = ["data_mode", "phase", "cards_used", "rules_scope", "measurement_types_pulled",
             "synthesis", "output_shape", "optional_lenses", "steps_covered", "status"]
    present = [k for k in known if k in set(keys)] or known
    return {"title": "composition block (SKILL.md frontmatter)",
            "required": ["data_mode", "cards_used", "status"],
            "fields": [{"name": k, "type": "", "required": k in ("data_mode", "cards_used", "status"),
                        "enum": None, "desc": ""} for k in present],
            "branches": [], "n_props": len(present), "defs_key": None}


# fields worth surfacing per example type (load-bearing, not the whole file)
_EXAMPLE_KEYS = {
    "source_manifest": ["id", "type", "provider", "dataset", "version", "s3_uri",
                        "license", "data_subject", "system_of_record"],
    "derived_manifest": ["id", "type", "transformation", "git_commit", "s3_uri",
                         "derived_from", "data_subject"],
    "card": ["card_id", "question", "measurement_type", "entity_grains",
             "required_inputs", "methods", "modality_relevance"],
    "resolver": ["gate", "version", "default", "evaluation"],
    "evidence_package": ["package_id", "framework_version", "generated_by",
                         "dashboard_spec_ref", "schema_version"],
}


def _example_instance(t: dict, graph: dict, roots: dict) -> dict:
    """Read the selected on-disk instance and surface its load-bearing fields."""
    ex = t.get("example") or {}
    tid = t["id"]
    repo = ex.get("repo", "tc")
    root = _repo_root(repo, roots)
    # locate the file
    path = None
    if ex.get("path"):
        path = root / ex["path"]
    elif ex.get("glob"):
        path = _first(root, ex["glob"])
    if not path or not path.exists():
        return {"resolved": False, "note": f"no example matched ({ex.get('glob') or ex.get('path')})",
                "source_path": None}
    rel = str(path.relative_to(root)) if str(path).startswith(str(root)) else path.name

    # cards/rules/resolvers/skills — reuse the graph's already-parsed dict where possible
    if tid == "card":
        cid = path.stem.replace(".card", "")
        c = (graph.get("cards") or {}).get(cid)
        if c:
            return {"resolved": True, "source_path": rel, "id": cid,
                    "fields": {k: c.get(k) for k in _EXAMPLE_KEYS["card"] if c.get(k) is not None},
                    "vocab_sample": {f: c["vocabulary"][f]
                                     for f in list((c.get("vocabulary") or {}))[:1]} or None}
    if tid == "resolver":
        gate = path.stem.replace(".resolver", "")
        r = (graph.get("resolvers") or {}).get(gate)
        if r:
            return {"resolved": True, "source_path": rel, "id": gate,
                    "fields": {"gate": gate, "version": r.get("version"),
                               "n_verdicts": r.get("n_verdicts"),
                               "verdicts_sample": [v.get("verdict") for v in (r.get("verdicts") or [])][:6]}}

    # generic: parse yaml/json from disk and surface selected keys
    if ex.get("kind") == "python":
        return {"resolved": True, "source_path": rel, **_flatten_python_hint(path)}
    if ex.get("kind") == "skill_md":
        return {"resolved": True, "source_path": rel, **_skill_md_fields(path)}
    if path.suffix == ".json":
        try:
            d = json.loads(path.read_text())
        except Exception as e:
            return {"resolved": False, "source_path": rel, "note": str(e)}
    else:
        d = _load_yaml(path) or {}
    keys = _EXAMPLE_KEYS.get(tid)
    fields = ({k: d.get(k) for k in keys if d.get(k) is not None} if keys
              else {k: d.get(k) for k in list(d)[:8]})
    # compact big values
    fields = {k: _compact(v) for k, v in fields.items()}
    return {"resolved": True, "source_path": rel, "id": d.get("id") or d.get("card_id") or d.get("package_id"),
            "fields": fields}


def _skill_md_fields(path: Path) -> dict:
    import re
    txt = path.read_text()
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", txt, re.DOTALL)
    fm = yaml.safe_load(m.group(1)) if m else {}
    comp = (fm or {}).get("composition") or {}
    return {"id": (fm or {}).get("name"),
            "fields": {"name": (fm or {}).get("name"),
                       "status": comp.get("status"),
                       "phase": comp.get("phase"),
                       "data_mode": comp.get("data_mode"),
                       "n_cards_used": len(comp.get("cards_used") or []),
                       "n_rules_scope": len(comp.get("rules_scope") or [])}}


def _flatten_python_hint(path: Path) -> dict:
    return {"id": path.name,
            "fields": {"note": "declared in Python (composition_schema.py) — see schema shape"}}


def _compact(v, limit=6):
    if isinstance(v, list):
        return v[:limit] + (["…"] if len(v) > limit else [])
    if isinstance(v, str):
        return v if len(v) <= 400 else v[:400] + "…"
    return v


def _defined_in(t: dict, roots: dict) -> dict:
    inv = t.get("inventory") or {}
    repo = inv.get("repo", "tc")
    root = _repo_root(repo, roots)
    glob = inv.get("glob")
    count = len(list(root.glob(glob))) if glob else None
    return {"repo": repo, "glob": glob, "count": count,
            "root_name": root.name}


def build_concepts(graph: dict, roots: dict) -> list:
    """Return the ordered list of concept records for the Concepts tab."""
    here = Path(__file__).resolve().parent
    spec = _load_yaml(here / "concepts.yaml") or {}
    out = []
    for t in sorted(spec.get("types") or [], key=lambda x: x.get("order", 99)):
        sch = t.get("schema") or {}
        repo = sch.get("repo", "tc")
        root = _repo_root(repo, roots)
        schema_path = None
        if sch.get("path"):
            schema_path = root / sch["path"]
        elif sch.get("glob"):
            schema_path = _first(root, sch["glob"])
        if sch.get("kind") == "python" and schema_path:
            shape = _python_schema_shape(schema_path)
        elif schema_path and schema_path.exists():
            shape = _schema_shape(schema_path, sch.get("defs_key"))
        else:
            shape = {"error": f"schema not found ({sch.get('path') or sch.get('glob')})"}
        shape_rel = (str(schema_path.relative_to(root))
                     if schema_path and str(schema_path).startswith(str(root)) else None)
        out.append({
            "id": t["id"],
            "title": t["title"],
            "order": t.get("order", 99),
            "narration": " ".join((t.get("narration") or "").split()),
            "schema": {"repo": repo, "path": shape_rel, **shape},
            "example": _example_instance(t, graph, roots),
            "defined_in": _defined_in(t, roots),
            "doc_keys": t.get("doc_keys") or [],
        })
    return out
