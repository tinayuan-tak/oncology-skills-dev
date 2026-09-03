"""CLI: render a report from a nomination.json in any preset/level/medium/scope, to any backend.

    python -m _skills_common.report_render NOM.json --preset exec-brief
    python -m _skills_common.report_render NOM.json --level L2 --scope gating --backend markdown
    python -m _skills_common.report_render NOM.json --preset reviewer-dossier --all-backends --out OUTDIR

Standalone + additive — reads a nomination, writes/prints report artifacts. It does NOT touch the
target-profile render path (that migration is a separate, gated step). With --out, files are written
as report_<label>.<ext>; without --out, the (single) rendered backend prints to stdout.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import backend_names, build_ir_auto, resolve_spec
from .backends import BINARY_BACKENDS, EXTENSIONS, render as render_ir
from .spec import LEVELS, MEDIA, LEADS, PRESETS


def _parse_scope(s):
    if s in ("all", "gating"):
        return s
    return tuple(x.strip() for x in s.split(",") if x.strip())


def _overrides(args) -> dict:
    ov = {}
    if args.level:
        ov["level"] = args.level
    if args.medium:
        ov["medium"] = args.medium
    if args.scope:
        ov["scope"] = _parse_scope(args.scope)
    if args.lead:
        ov["lead"] = args.lead
    if args.bump_deciding:
        ov["bump_deciding"] = True
    return ov


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m _skills_common.report_render",
                                 description="Render a target report from a nomination.json spine.")
    ap.add_argument("input", type=Path,
                    help="path to a nomination.json OR a standalone skill decision.json")
    ap.add_argument("--target", default=None, help="override target label (for a decision.json)")
    ap.add_argument("--indication", default=None, help="override indication label")
    ap.add_argument("--preset", choices=sorted(PRESETS), default=None)
    ap.add_argument("--backend", choices=backend_names(), default="text")
    ap.add_argument("--all-backends", action="store_true", help="render every backend (needs --out)")
    ap.add_argument("--level", choices=LEVELS, default=None)
    ap.add_argument("--medium", choices=MEDIA, default=None)
    ap.add_argument("--scope", default=None, help="all | gating | comma-separated skill shorts")
    ap.add_argument("--lead", choices=LEADS, default=None)
    ap.add_argument("--bump-deciding", action="store_true", dest="bump_deciding")
    ap.add_argument("--out", type=Path, default=None, help="output dir (write files); else print stdout")
    args = ap.parse_args(argv)

    try:
        data = json.loads(args.input.read_text())
    except (OSError, json.JSONDecodeError) as e:
        ap.error(f"cannot read input {args.input}: {e}")

    spec = resolve_spec(args.preset, **_overrides(args))
    label = args.preset or f"{spec.level}-{spec.medium}"
    # auto-detect nomination.json (composed) vs a standalone skill decision.json.
    ir = build_ir_auto(data, spec, target=args.target, indication=args.indication)

    if args.all_backends:
        if not args.out:
            ap.error("--all-backends requires --out")
        names = backend_names()
    else:
        if not args.out and args.backend in BINARY_BACKENDS:
            ap.error(f"the {args.backend!r} backend is binary — use --out DIR (cannot print to stdout)")
        names = [args.backend]
    rendered = {name: render_ir(ir, name) for name in names}

    if not args.out:
        sys.stdout.write(next(iter(rendered.values())))
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    for name, content in rendered.items():
        ext = EXTENSIONS.get(name, "txt")
        path = args.out / f"report_{label}.{ext}"
        if name in BINARY_BACKENDS:
            path.write_bytes(content)
        else:
            path.write_text(content)
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
