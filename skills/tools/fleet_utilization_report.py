#!/usr/bin/env python
"""Fleet card-utilization report (signals-first).

For every skill with a question_hierarchy.yaml, classify each of its consumed CARDS by how it is
used toward the key biological questions, using only the governed measurement_type binding:

  * source     - measurement_type binds to a sub-group QUESTION (a scored signal source)
  * context    - measurement_type is a sub-group context_type (conditions, does not score)
  * other-lens - routed to another skill's question via other_lenses
  * no-type    - card has no per-target measurement_type (population-ranking etc.) -> exempt
  * ORPHAN     - measures a question the skill owns but binds to nothing (the connectivity guard
                 fails on these per-skill; this report aggregates the fleet count, expected 0)

This quantifies "are the cards fully used toward the key questions" fleet-wide, and is safe to run
in CI as a report (it asserts nothing; it prints a table and exits 0). Requires target-contracts on
TARGET_CONTRACTS_ROOT for the card measurement_types; prints a skip notice and exits 0 without it.

    python skills/tools/fleet_utilization_report.py
"""
from __future__ import annotations

import importlib.util
import os
import sys
from functools import lru_cache
from pathlib import Path

import yaml

SKILLS_DIR = Path(__file__).resolve().parent.parent
CONTRACTS = Path(
    os.environ.get(
        "TARGET_CONTRACTS_ROOT",
        str(SKILLS_DIR.parent.parent / "rnd-computational-biology-oncology-target-contracts"),
    )
)
CARDS_DIR = CONTRACTS / "cards"


@lru_cache(maxsize=None)
def measurement_type(card_id: str):
    p = CARDS_DIR / f"{card_id}.card.yaml"
    if not p.exists():
        return None
    return (yaml.safe_load(p.read_text()) or {}).get("measurement_type")


def cards_of(skill_dir: Path):
    """The CARDS list a skill's run.py consumes (imported without executing __main__)."""
    rp = skill_dir / "scripts" / "run.py"
    if not rp.exists():
        return []
    name = f"_util_{skill_dir.name.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(name, rp)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SKILLS_DIR))
    try:
        spec.loader.exec_module(mod)
    except Exception:
        return []
    return list(getattr(mod, "CARDS", []))


def classify_skill(skill_dir: Path):
    hp = skill_dir / "question_hierarchy.yaml"
    if not hp.exists():
        return None
    h = yaml.safe_load(hp.read_text()) or {}
    q_types, ctx = set(), set()
    for sg in h.get("sub_groups", []):
        ctx.update(sg.get("context_types", []))
        for q in sg.get("questions", []):
            q_types.update(q.get("measurement_types", []))
    lens = {t for e in h.get("other_lenses", []) for t in e.get("measurement_types", [])}

    counts = dict(total=0, source=0, context=0, other_lens=0, orphan=0, no_type=0)
    orphans = []
    for c in cards_of(skill_dir):
        counts["total"] += 1
        t = measurement_type(c)
        if t is None:
            counts["no_type"] += 1
        elif t in q_types:
            counts["source"] += 1
        elif t in ctx:
            counts["context"] += 1
        elif t in lens:
            counts["other_lens"] += 1
        else:
            counts["orphan"] += 1
            orphans.append(c)
    counts["orphans"] = orphans
    return counts


def build_report():
    skills = sorted(
        d for d in SKILLS_DIR.iterdir() if d.is_dir() and (d / "question_hierarchy.yaml").exists()
    )
    rows, T = [], dict(total=0, source=0, context=0, other_lens=0, orphan=0, no_type=0)
    for d in skills:
        r = classify_skill(d)
        for k in T:
            T[k] += r[k]
        rows.append((d.name, r))

    lines = [
        "# Signals-first fleet card-utilization report",
        "",
        "Each consumed card is a **source** (binds to a sub-group question by measurement_type), "
        "**context**, routed to **another lens**, has **no measurement_type** (exempt), or is an "
        "**ORPHAN** (owns the question but binds to nothing -> per-skill connectivity guard fails).",
        "",
        "| skill | cards | source | context | other-lens | no-type | ORPHAN |",
        "|---|--:|--:|--:|--:|--:|--:|",
    ]
    for name, r in rows:
        flag = "" if r["orphan"] == 0 else f" WARN {r['orphans']}"
        lines.append(
            f"| {name} | {r['total']} | {r['source']} | {r['context']} | {r['other_lens']} "
            f"| {r['no_type']} | {r['orphan']}{flag} |"
        )
    lines.append(
        f"| **FLEET** | **{T['total']}** | **{T['source']}** | **{T['context']}** "
        f"| **{T['other_lens']}** | **{T['no_type']}** | **{T['orphan']}** |"
    )
    accounted = T["total"] - T["orphan"]
    lines += [
        "",
        f"**{accounted}/{T['total']} cards accounted for; {T['orphan']} orphans "
        f"(per-skill connectivity guard enforces 0).** {T['source']} bind directly to a sub-group "
        f"question as scored sources; {T['context']} context; {T['other_lens']} routed to another "
        f"lens; {T['no_type']} exempt (no per-target measurement_type).",
    ]
    return "\n".join(lines), T


def main():
    if not CARDS_DIR.exists():
        print(f"[skip] no target-contracts cards at {CARDS_DIR} (set TARGET_CONTRACTS_ROOT)")
        return
    report, _ = build_report()
    print(report)


if __name__ == "__main__":
    main()
