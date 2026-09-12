#!/usr/bin/env python3
"""build_architecture_explorer.py — the framework's WIRING, as a click-through map.

Companion to validators/framework_health (which answers "is it live?"). This answers
"what is wired to what?" — for every skill, the cards it composes; for every card, the
datasets it reads, the methods it calls, the outputs + vocab + figures it emits, and the
rules → resolver-verdict it drives. A Miller-columns (Finder-style) drill-down:

    SKILL  →  CARDS  →  CARD DETAIL (datasets · methods · outputs · rules→verdict)  →  DATASET

Two modes: skill-first (primary) and dataset-first (reverse coverage — "which datasets
have we wired, and into what?").

Reads three sibling repos (target-contracts, claude-oncology-skills, data-catalog) fresh,
and OPTIONALLY overlays health/framework_health.json for live/broken status. Emits ONE
self-contained HTML (inline CSS+JS, no CDN) so a colleague can open the file directly.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Repo roots (siblings by default; override via --tc/--sk/--dc).
# ---------------------------------------------------------------------------
HOME = Path.home()
# `tc` is derived from THIS FILE, not from $HOME: <tc>/validators/architecture_dashboard/<this>.
# It used to be hard-coded to ~/rnd-...-target-contracts, which meant `make atlas` run from a
# /tmp worktree read the PRIMARY checkout's cards/rules/resolvers while writing the feed into the
# worktree — so a branch could regenerate the committed atlas and silently publish TRUNK's wiring,
# and `--check` would compare trunk against trunk and report fresh. Deriving it makes the build
# describe the tree it is run from. Siblings default to the parent dir (the layout
# framework_health.probe and framework-health-cross-repo.yml already assume, and which
# new-worktree populates with symlinks), so the same derivation carries them.
# Siblings are additionally .resolve()d: new-worktree seeds them as SYMLINKS to the canonical
# clones, and paths harvested from them land in the committed feed (skills[].md_path), so leaving
# them unresolved would write the ephemeral worktree path into a published artifact.
_TC_ROOT = Path(__file__).resolve().parents[2]


def _sibling(name: str) -> Path:
    return (_TC_ROOT.parent / f"rnd-computational-biology-oncology-{name}").resolve()


DEFAULTS = {
    "tc": _TC_ROOT,
    "sk": _sibling("claude-oncology-skills"),
    "dc": _sibling("data-catalog"),
}


def _load_yaml(p: Path):
    try:
        with open(p) as fh:
            return yaml.safe_load(fh)
    except Exception as e:  # keep the build resilient — a single malformed file must not abort
        print(f"  ! yaml parse failed {p}: {e}")
        return None


# ---------------------------------------------------------------------------
# 1. Manifest index — resolve product_id -> manifest (id or product_id field).
# ---------------------------------------------------------------------------
def build_manifest_index(dc: Path) -> dict:
    idx: dict[str, dict] = {}
    mdir = dc / "manifests"
    if not mdir.exists():
        print(f"  ! no manifests/ under {dc}")
        return idx
    for p in sorted(mdir.rglob("*.yaml")):
        d = _load_yaml(p)
        if not isinstance(d, dict):
            continue
        keys = {d.get("id"), d.get("product_id")}
        rec = {
            "resolved_id": d.get("id") or d.get("product_id"),
            "kind": d.get("type", "source" if "/sources/" in str(p) else "derived"),
            "provider": d.get("provider"),
            "version": d.get("version"),
            "license": d.get("license"),
            "s3_uri": d.get("s3_uri"),
            "format": d.get("format")
            or (d.get("files", [{}])[0].get("format") if isinstance(d.get("files"), list) and d["files"] else None),
            "size_bytes": d.get("size_bytes") or d.get("total_size_bytes"),
            "sort_key": (d.get("parameters") or {}).get("sort_key") if isinstance(d.get("parameters"), dict) else None,
            "derived_from": d.get("derived_from") or [],
            "description": (d.get("description") or d.get("transformation") or "")[:600],
            "manifest_path": str(p.relative_to(dc)),
        }
        for k in keys:
            if k:
                idx[k] = rec
    return idx


# Resources tracked in the data-catalog repo OUTSIDE manifests/ — real, cataloged, but
# not source/derived manifests, so the bare "not in manifests/" flag is a false negative.
def add_nonmanifest_resources(dc: "Path", idx: dict) -> None:
    scat = dc / "subgroup-catalogs"
    if scat.exists():
        inds = sorted(d.name for d in scat.iterdir() if d.is_dir())
        idx["subgroup-catalog"] = {
            "resolved_id": "subgroup-catalog",
            "kind": "subgroup-catalog (non-manifest)",
            "provider": "target-contracts",
            "version": None,
            "license": "internal",
            "s3_uri": None,
            "format": "yaml",
            "size_bytes": None,
            "sort_key": None,
            "derived_from": [],
            "manifest_path": "subgroup-catalogs/",
            "description": (
                "Per-indication molecular-subgroup catalogs (atomic strata + composite "
                f"cohorts). Indications: {', '.join(inds)}."
            ),
            "resolution": "non-manifest resource",
        }
    rrel = dc / "resolver-releases"
    if rrel.exists():
        vers = sorted(p.stem for p in rrel.glob("*.yaml"))
        idx["target-id-resolver-release"] = {
            "resolved_id": "target-id-resolver-release",
            "kind": "resolver-release (non-manifest)",
            "provider": "data-catalog",
            "version": (vers[-1] if vers else None),
            "license": "internal",
            "s3_uri": None,
            "format": "yaml",
            "size_bytes": None,
            "sort_key": None,
            "derived_from": [],
            "manifest_path": "resolver-releases/",
            "description": (
                "Versioned target-id resolver release (HGNC/Ensembl/UniProt/NCBI/mygene "
                f"data-pins). Releases: {', '.join(vers)}."
            ),
            "resolution": "non-manifest resource",
        }


# Hand-curated notes for product_ids a card names that resolve to no catalog record — so the
# "uncataloged" list reads as a categorized gap map, not a bare ✗. category ∈
# {derivation-needed, on-S3-uncataloged, not-landed, commercial}.
GAP_NOTES = {
    "hpa-normal-tissue-expression": {
        "category": "derivation-needed",
        "note": (
            "HPA normal-tissue signal. The underlying data IS cataloged as hpa-v25-1 "
            "(master tables), but HPA v25 dropped the standalone normal_tissue.tsv — this "
            "product needs a derived extraction from the monolithic master file."
        ),
    },
    "surfaceome-cohort-ranking-per-indication-v1": {
        "category": "on-S3-uncataloged",
        "note": (
            "Per-indication derived product. The method reads "
            "s3://onc-compbio/data-catalog/derived/surfaceome-cohort-ranking-per-indication-v1/ "
            "and falls back to data_unavailable; built on-demand per indication, no manifest "
            "in manifests/derived/. (Card's skill is dropped from the target-profile fan-out.)"
        ),
    },
    "literature-snapshot": {
        "category": "not-landed",
        "note": (
            "No data landed. clinical-precedent + functional-blockade-rationale are placeholder "
            "cards; the literature/clinical-evidence source is not resolved."
        ),
    },
    "tempus-rwd-stratified-expression": {
        "category": "commercial",
        "note": ("Tempus real-world data (CRC-only iter-1). Commercial licensing not resolved — not landed."),
    },
}


# Known OncoTree-ish indication tokens that prefix per-indication derived products. Used
# to distinguish an indication-parameterized product ('coadread-dge-…', a pin for a
# {indication}-templated family) from a genuinely single-scope product.
_INDICATION_TOKENS = {
    "acc",
    "blca",
    "brca",
    "cesc",
    "coad",
    "coadread",
    "esca",
    "gbm",
    "hnsc",
    "kich",
    "kirc",
    "kirp",
    "lgg",
    "lihc",
    "luad",
    "lusc",
    "nsclc",
    "ov",
    "paad",
    "pcpg",
    "prad",
    "read",
    "sclc",
    "skcm",
    "stad",
    "tgct",
    "thca",
    "ucec",
    "ucs",
    "pancan",
    "aml",
    "dlbc",
    "laml",
    "meso",
    "chol",
    "uvm",
    "thym",
    "sarc",
}


def detect_indication_family(product_id: str, idx: dict) -> dict:
    """If product_id is '<indication>-<stem>' and >=2 indication siblings share <stem>, it's a
    {indication}-parameterized family — the card pins one but the reader resolves per-indication.
    Returns {is_family, stem, members:[tokens], count}."""
    tok, _, stem = product_id.partition("-")
    if tok not in _INDICATION_TOKENS or not stem:
        return {"is_family": False}
    members = set()
    for k in idx:
        kt, _, ks = k.partition("-")
        if ks == stem and kt in _INDICATION_TOKENS:
            members.add(kt)
    if len(members) < 2:
        return {"is_family": False}
    return {"is_family": True, "stem": stem, "members": sorted(members), "count": len(members)}


def resolve_dataset(product_id: str, idx: dict) -> dict:
    """Exact match, else longest-prefix (release-pinned families e.g. depmap-consortium-26q1)."""
    if product_id in idx:
        rec = idx[product_id]
        return {
            **rec,
            "product_id": product_id,
            "in_catalog": True,
            "matched_by": "exact",
            "resolution": rec.get("resolution", "manifest"),
            "gap_category": None,
            "gap_note": None,
        }
    # prefix: a card names 'depmap-consortium-26q1' but only '-rnai'/'-crispr' variants are cataloged
    cands = [k for k in idx if k.startswith(product_id) or product_id.startswith(k)]
    if cands:
        best = max(cands, key=len)
        rec = idx[best]
        return {
            **rec,
            "product_id": product_id,
            "in_catalog": True,
            "matched_by": "prefix",
            "resolution": rec.get("resolution", "manifest"),
            "gap_category": None,
            "gap_note": None,
        }
    gap = GAP_NOTES.get(product_id, {})
    return {
        "product_id": product_id,
        "in_catalog": False,
        "matched_by": None,
        "resolved_id": None,
        "kind": None,
        "provider": None,
        "license": None,
        "s3_uri": None,
        "format": None,
        "size_bytes": None,
        "sort_key": None,
        "derived_from": [],
        "description": "",
        "manifest_path": None,
        "resolution": "uncataloged",
        "gap_category": gap.get("category"),
        "gap_note": gap.get("note"),
    }


# ---------------------------------------------------------------------------
# 2. Skills — SKILL.md frontmatter.
# ---------------------------------------------------------------------------
FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_skill(md_path: Path) -> dict | None:
    text = md_path.read_text()
    m = FM_RE.match(text)
    if not m:
        return None
    fm = _load_yaml(Path("/dev/stdin")) if False else None  # placeholder to satisfy linters
    fm = yaml.safe_load(m.group(1))
    if not isinstance(fm, dict):
        return None
    comp = fm.get("composition") or {}
    meta = fm.get("metadata") or {}
    return {
        "name": fm.get("name") or md_path.parent.name,
        "status": comp.get("status") or "unknown",
        "phase": comp.get("phase") or [],
        "data_mode": comp.get("data_mode"),
        "cards_used": comp.get("cards_used") or [],
        "rules_scope": comp.get("rules_scope") or [],
        "measurement_types_pulled": comp.get("measurement_types_pulled") or [],
        "synthesis": comp.get("synthesis") or [],
        "output_shape": comp.get("output_shape") or [],
        "optional_lenses": comp.get("optional_lenses") or [],
        "version": meta.get("version"),
        "owner": meta.get("owner"),
        "description_short": _first_sentence(fm.get("description") or ""),
        "md_path": str(md_path),
    }


def _first_sentence(desc: str) -> str:
    desc = " ".join(desc.split())
    # first sentence up to a period followed by space+capital or quote-close
    m = re.search(r"^(.{20,240}?[.?!])(\s|$)", desc)
    return (m.group(1) if m else desc[:200]).strip()


def parse_target_profile_fanout(md_path: Path, skill_names: set) -> list:
    """The 12 fan-out sub-skills are listed as bullets in target-profile's description
    block. Parse them, keep only those that are real skill dirs (drops card bullets)."""
    out = []
    for line in md_path.read_text().splitlines():
        mm = re.match(r"^\s*-\s+([a-z][a-z0-9-]+)\b", line)
        if mm and mm.group(1) in skill_names:
            out.append(mm.group(1))
        if line.strip().startswith("cards_used") or line.strip().startswith("composition"):
            break  # stop at the composition block; fan-out is above it
    # dedup preserve order
    seen, ded = set(), []
    for s in out:
        if s not in seen:
            seen.add(s)
            ded.append(s)
    return ded


# ---------------------------------------------------------------------------
# 3. Cards.
# ---------------------------------------------------------------------------
def parse_card(p: Path) -> dict:
    d = _load_yaml(p) or {}
    outputs = d.get("outputs") or {}
    figs = outputs.get("figures") or []
    return {
        "card_id": d.get("card_id") or p.stem.replace(".card", ""),
        "version": d.get("version"),
        "question": d.get("question"),
        "measurement": d.get("measurement"),
        "measurement_type": d.get("measurement_type"),
        "entity_grains": d.get("entity_grains") or [],
        "sample_context": d.get("sample_context"),
        "required_inputs": [
            {"product_id": ri.get("product_id"), "release_pin": ri.get("release_pin")}
            for ri in (d.get("required_inputs") or [])
            if isinstance(ri, dict)
        ],
        "methods": [
            {"call": mm.get("call"), "args": mm.get("args") or {}}
            for mm in (d.get("methods") or [])
            if isinstance(mm, dict)
        ],
        "summary_fields": outputs.get("summary_fields") or [],
        "vocabulary": outputs.get("summary_fields_vocabulary") or {},
        "figures": [
            {
                "id": f.get("id"),
                "type": f.get("type"),
                "description": (f.get("description") or "")[:300],
                "primary": bool(f.get("primary")),
            }
            for f in figs
            if isinstance(f, dict)
        ],
        "thresholds": d.get("thresholds") or {},
        "warning_predicates": [
            {"warning_id": w.get("warning_id"), "if": w.get("if"), "message": w.get("message")}
            for w in (d.get("warning_predicates") or [])
            if isinstance(w, dict)
        ],
        "caveats": d.get("caveats") or [],
    }


# ---------------------------------------------------------------------------
# 4. Interpretation-rules -> rules_by_card ; 5. Resolvers -> verdict wiring.
# ---------------------------------------------------------------------------
def parse_rules(tc: Path) -> tuple[dict, dict]:
    """Returns (rules_by_card, rule_index). rules_by_card[card_id] = [rule dicts];
    rule_index[rule_id] = rule dict (for resolver cross-ref)."""
    rules_by_card: dict[str, list] = {}
    rule_index: dict[str, dict] = {}
    rdir = tc / "interpretation-rules"
    if not rdir.exists():
        return rules_by_card, rule_index
    for p in sorted(rdir.glob("*.rules.yaml")):
        d = _load_yaml(p) or {}
        axis = d.get("rules_id") or p.stem.replace(".rules", "")
        for r in d.get("rules") or []:
            if not isinstance(r, dict):
                continue
            when = r.get("when") or {}
            cid = when.get("card_id")
            field = when.get("field")
            # capture the trigger condition compactly (equals/in/gte/lte/...)
            cond = {k: v for k, v in when.items() if k not in ("card_id", "field")}
            rec = {
                "rule_id": r.get("rule_id"),
                "axis": axis,
                "card_id": cid,
                "field": field,
                "condition": cond,
                "signals": r.get("signals") or {},
                "is_killer": "killer" in str(r.get("signals") or {}) or bool(r.get("killer_message")),
            }
            if rec["rule_id"]:
                rule_index[rec["rule_id"]] = rec
            if cid:
                rules_by_card.setdefault(cid, []).append(rec)
    return rules_by_card, rule_index


def parse_resolvers(tc: Path) -> tuple[dict, dict]:
    """Returns (resolvers, rule_to_verdicts). resolvers[gate] = {version, verdicts:[{verdict, refs}]}.
    rule_to_verdicts[rule_id] = [ {gate, verdict}, ... ]."""
    resolvers: dict[str, dict] = {}
    rule_to_verdicts: dict[str, list] = {}
    rdir = tc / "resolvers"
    if not rdir.exists():
        return resolvers, rule_to_verdicts
    for p in sorted(rdir.glob("*.resolver.yaml")):
        d = _load_yaml(p) or {}
        gate = d.get("gate") or p.stem.replace(".resolver", "")
        verdicts = []
        for rung in d.get("resolve") or []:
            if not isinstance(rung, dict):
                continue
            v = rung.get("verdict")
            refs = []
            for key in ("when_fired", "when_any_fired", "when_all_fired", "when_none_fired"):
                val = rung.get(key)
                if isinstance(val, str):
                    refs.append(val)
                elif isinstance(val, list):
                    refs.extend([x for x in val if isinstance(x, str)])
            verdicts.append({"verdict": v, "refs": refs})
            for rid in refs:
                rule_to_verdicts.setdefault(rid, []).append({"gate": gate, "verdict": v})
        resolvers[gate] = {
            "gate": gate,
            "version": d.get("version"),
            "verdicts": verdicts,
            "n_verdicts": len({x["verdict"] for x in verdicts}),
        }
    return resolvers, rule_to_verdicts


# ---------------------------------------------------------------------------
# 6. Axis ontology (vocabularies/target_profiling_axes.yaml) — the objective→axis→card
#    organizing layer (v1.0.0). The dashboard's "Axes" tab renders this.
# ---------------------------------------------------------------------------
def parse_axes(tc: Path) -> dict | None:
    p = tc / "vocabularies" / "target_profiling_axes.yaml"
    if not p.exists():
        return None
    d = _load_yaml(p) or {}
    qs = []
    for q in d.get("questions", []):
        if not isinstance(q, dict):
            continue
        qs.append(
            {
                "short": q.get("short"),
                "question": q.get("question"),
                "band": q.get("band"),
                "risk_category": q.get("risk_category"),
                "home_skill": q.get("home_skill"),
                "foreign_consumers": q.get("foreign_consumers") or [],
                "coverage": q.get("framework_can_evidence"),
                "modality_relevance": q.get("modality_relevance") or [],
                "receives_facets": q.get("receives_facets") or [],
                "reports_into": q.get("reports_into") or [],
                "conditioned_by": q.get("conditioned_by") or [],
                "status": q.get("status"),
                "characterization_only": bool(q.get("characterization_only")),
                "unit_of_analysis": q.get("unit_of_analysis"),
                "coverage_note": (q.get("coverage_note") or "").strip(),
                "evidences": (q.get("evidences") or "").strip(),
                "legacy_letters": q.get("legacy_letters") or {},
            }
        )
    conds = []
    for c in d.get("conditioner_axes", []):
        if isinstance(c, dict):
            conds.append(
                {
                    "id": c.get("id") or c.get("short"),
                    "note": (c.get("note") or c.get("description") or c.get("what") or "").strip()[:240],
                }
            )
        elif isinstance(c, str):
            conds.append({"id": c, "note": ""})
    return {
        "version": d.get("version"),
        "coverage_vocab": d.get("coverage_vocab") or {},
        "bands": d.get("bands") or {},
        "questions": qs,
        "conditioner_axes": conds,
    }


# ---------------------------------------------------------------------------
# Assemble the graph.
# ---------------------------------------------------------------------------
def build(tc: Path, sk: Path, dc: Path, health_json_path: "Path|None" = None) -> dict:
    print("· indexing data-catalog manifests …")
    midx = build_manifest_index(dc)
    add_nonmanifest_resources(dc, midx)
    print(f"  {len(midx)} catalog keys (incl. non-manifest resources)")

    print("· parsing cards …")
    cards: dict[str, dict] = {}
    for p in sorted((tc / "cards").glob("*.card.yaml")):
        c = parse_card(p)
        cards[c["card_id"]] = c
    print(f"  {len(cards)} cards")

    print("· parsing rules + resolvers …")
    rules_by_card, rule_index = parse_rules(tc)
    resolvers, rule_to_verdicts = parse_resolvers(tc)
    print(f"  {sum(len(v) for v in rules_by_card.values())} rules · {len(resolvers)} resolvers")

    print("· parsing skills …")
    skills: dict[str, dict] = {}
    skill_dirs = [d for d in (sk / "skills").iterdir() if d.is_dir() and (d / "SKILL.md").exists()]
    skill_names = {d.name for d in skill_dirs}
    for d in sorted(skill_dirs):
        s = parse_skill(d / "SKILL.md")
        if s:
            skills[s["name"]] = s
    # target-profile fan-out
    fanout = []
    if (sk / "skills" / "target-profile" / "SKILL.md").exists():
        fanout = parse_target_profile_fanout(sk / "skills" / "target-profile" / "SKILL.md", skill_names)
    print(f"  {len(skills)} skills · target-profile fans out to {len(fanout)}")

    # health overlay (optional)
    health = {}
    hpath = Path(health_json_path) if health_json_path else (tc / "health" / "framework_health.json")
    if hpath.exists():
        try:
            hj = json.load(open(hpath))
            health["skill"] = {s["name"]: s.get("health_verdict") for s in hj.get("skills", [])}
            health["card"] = {c["card_id"]: c.get("card_health") for c in hj.get("cards", [])}
            health["generated_at"] = hj.get("generated_at")
            print(f"  overlaid health status from {hpath.name} ({health.get('generated_at', '')[:10]})")
        except Exception as e:
            print(f"  ! health overlay skipped: {e}")

    # ---- enrich cards with datasets(resolved) + rules + verdicts + consumers
    consumers: dict[str, list] = {}
    for sname, s in skills.items():
        for cid in s["cards_used"]:
            consumers.setdefault(cid, []).append(sname)

    ds_consumed_by: dict[str, list] = {}
    for cid, c in cards.items():
        # datasets
        c["datasets"] = []
        for ri in c["required_inputs"]:
            pid = ri["product_id"]
            if not pid:
                continue
            r = resolve_dataset(pid, midx)
            r["family"] = detect_indication_family(pid, midx)
            c["datasets"].append(r)
            ds_consumed_by.setdefault(pid, []).append(cid)
        # rules + verdicts
        rlist = rules_by_card.get(cid, [])
        vset = []
        for r in rlist:
            r_verdicts = rule_to_verdicts.get(r["rule_id"], [])
            r["verdicts"] = r_verdicts
            for vv in r_verdicts:
                if vv not in vset:
                    vset.append(vv)
        c["rules"] = rlist
        c["verdicts"] = vset
        c["is_verdict_bearing"] = bool(vset)
        c["consumers"] = sorted(consumers.get(cid, []))
        c["health"] = health.get("card", {}).get(cid)

    # ---- datasets table (union of card-referenced product_ids)
    datasets: dict[str, dict] = {}
    for cid, c in cards.items():
        for r in c["datasets"]:
            pid = r["product_id"]
            if pid not in datasets:
                datasets[pid] = {**r, "consumed_by_cards": sorted(set(ds_consumed_by.get(pid, [])))}
    # consuming skills per dataset (via cards)
    for pid, d in datasets.items():
        sk_set = set()
        for cid in d["consumed_by_cards"]:
            sk_set.update(consumers.get(cid, []))
        d["consumed_by_skills"] = sorted(sk_set)

    # ---- skill-level rollups (verdict-bearing card split via rules_scope + gate)
    for sname, s in skills.items():
        vb, disp = [], []
        gates = set()
        for cid in s["cards_used"]:
            c = cards.get(cid)
            in_scope = ("all" in s["rules_scope"]) or (cid in s["rules_scope"])
            if c and c.get("is_verdict_bearing") and in_scope:
                vb.append(cid)
                for vv in c["verdicts"]:
                    gates.add(vv["gate"])
            else:
                disp.append(cid)
        s["verdict_bearing_cards"] = vb
        s["display_cards"] = disp
        s["gates"] = sorted(gates)
        s["is_composed_root"] = sname == "target-profile"
        s["fanout"] = fanout if sname == "target-profile" else []
        s["health"] = health.get("skill", {}).get(sname)
        s["n_cards"] = len(s["cards_used"])

    # roots / shas
    def _sha(path: Path):
        try:
            import subprocess

            return (
                subprocess.check_output(
                    ["git", "-C", str(path), "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
                )
                .decode()
                .strip()
            )
        except Exception:
            return None

    return {
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "roots": {"target_contracts": str(tc), "skills": str(sk), "data_catalog": str(dc)},
        "root_shas": {"target_contracts": _sha(tc), "skills": _sha(sk), "data_catalog": _sha(dc)},
        "health_overlay_at": health.get("generated_at"),
        "skills": skills,
        "cards": cards,
        "datasets": datasets,
        "resolvers": resolvers,
        "fanout": fanout,
        "axes": parse_axes(tc),
        "summary": {
            "n_skills": len(skills),
            "n_wired_skills": sum(1 for s in skills.values() if s["status"] == "wired"),
            "n_cards": len(cards),
            "n_verdict_bearing_cards": sum(1 for c in cards.values() if c["is_verdict_bearing"]),
            "n_datasets": len(datasets),
            "n_datasets_in_catalog": sum(1 for d in datasets.values() if d["in_catalog"]),
            "n_broken_refs": sum(1 for d in datasets.values() if not d["in_catalog"]),
            "n_resolvers": len(resolvers),
            "n_verdicts": sum(r["n_verdicts"] for r in resolvers.values()),
        },
    }


# ---------------------------------------------------------------------------
# Render — self-contained HTML (Miller columns).
# ---------------------------------------------------------------------------
from render_arch import render_html  # noqa: E402  (split for readability)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tc", default=str(DEFAULTS["tc"]))
    ap.add_argument("--sk", default=str(DEFAULTS["sk"]))
    ap.add_argument("--dc", default=str(DEFAULTS["dc"]))
    ap.add_argument("--out", default=str(HOME / "dev/framework-runs/architecture-explorer/architecture_explorer.html"))
    ap.add_argument("--json", default=str(HOME / "dev/framework-runs/architecture-explorer/architecture_graph.json"))
    args = ap.parse_args()

    graph = build(Path(args.tc), Path(args.sk), Path(args.dc))
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    with open(args.json, "w") as fh:
        json.dump(graph, fh, indent=1)
    html_str = render_html(graph)
    with open(args.out, "w") as fh:
        fh.write(html_str)
    s = graph["summary"]
    print(
        f"\n✓ {s['n_skills']} skills · {s['n_cards']} cards "
        f"({s['n_verdict_bearing_cards']} verdict-bearing) · "
        f"{s['n_datasets']} datasets ({s['n_broken_refs']} uncataloged) · "
        f"{s['n_resolvers']} resolvers / {s['n_verdicts']} verdicts"
    )
    print(f"  HTML  → {args.out}  ({os.path.getsize(args.out) // 1024} KB)")
    print(f"  JSON  → {args.json}")


if __name__ == "__main__":
    main()
