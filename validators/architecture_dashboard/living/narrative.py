"""narrative.py — the Docs fold.

Indexes the prose design docs (target-contracts docs/design/*.md + skills docs/*.md), and
keys each to the component type(s) it describes (via the `doc_keying` table in concepts.yaml).
Titles, first-paragraph summaries, and links are GENERATED; keying is the only hand input.

Links out (no inlining) — the docs are GitHub-flavored markdown.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

HOME = Path.home()


def _first_para(md_text: str) -> str:
    lines = md_text.splitlines()
    # skip title / blank / badge lines, take the first real prose paragraph
    buf = []
    started = False
    for ln in lines:
        s = ln.strip()
        if not started:
            if s.startswith("#") or not s or s.startswith("!") or s.startswith(">"):
                continue
            started = True
        if started:
            if not s:
                break
            buf.append(s)
        if sum(len(x) for x in buf) > 320:
            break
    return " ".join(buf)[:320]


def _title(md_text: str, fallback: str) -> str:
    for ln in md_text.splitlines():
        m = re.match(r"^#\s+(.*)", ln.strip())
        if m:
            return m.group(1).strip()
    return fallback


def _index_dir(root: Path, subdir: str, repo_tag: str) -> dict:
    out = {}
    d = root / subdir
    if not d.exists():
        return out
    for p in sorted(d.glob("*.md")):
        try:
            txt = p.read_text()
        except Exception:
            continue
        stem = p.stem
        out[stem] = {"stem": stem, "title": _title(txt, stem),
                     "summary": _first_para(txt),
                     "repo": repo_tag, "path": str(p.relative_to(root))}
    return out


def build_narrative(roots: dict) -> dict:
    here = Path(__file__).resolve().parent
    spec = yaml.safe_load((here / "concepts.yaml").read_text()) or {}
    keying = spec.get("doc_keying") or {}

    tc = Path(roots.get("target_contracts") or (HOME / "rnd-computational-biology-oncology-target-contracts"))
    sk = Path(roots.get("skills") or (tc.parent / "rnd-computational-biology-oncology-claude-oncology-skills"))

    docs = {}
    docs.update(_index_dir(tc, "docs/design", "tc"))
    docs.update(_index_dir(sk, "docs", "sk"))

    # attach component keys (from doc_keying); docs not keyed still listed under "general"
    by_component: dict = {}
    doc_list = []
    for stem, rec in sorted(docs.items()):
        comps = keying.get(stem, [])
        rec = {**rec, "components": comps}
        doc_list.append(rec)
        for c in (comps or ["general"]):
            by_component.setdefault(c, []).append(stem)

    return {"docs": doc_list, "by_component": by_component,
            "n_docs": len(doc_list), "n_keyed": sum(1 for r in doc_list if r["components"])}
