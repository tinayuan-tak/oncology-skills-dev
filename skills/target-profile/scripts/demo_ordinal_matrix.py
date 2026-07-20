#!/usr/bin/env python3
"""Reproducible demo: the ordinal evidence-matrix VIEW for a (target, indication).

Runs the DETERMINISTIC sub-skills (no Bedrock) and renders the gate × modality ordinal matrix
(gap #3 "now" + gap #4 demo). Zero new data — it's a labeled projection of the categorical
signals the framework already computes. Regenerate the committed KRAS×COADREAD artifact with:

    AWS_PROFILE=cbg /opt/conda/bin/python skills/target-profile/scripts/demo_ordinal_matrix.py \
        --target KRAS --indication COADREAD \
        --out skills/target-profile/examples/ordinal_matrix_kras_coadread.md

Needs AWS_PROFILE=cbg + /opt/conda/bin/python for the live DepMap reads (see the framework env
notes). The RENDERING is deterministic given the same catalog pin; the demo does not call an LLM.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common import ordinal_view  # noqa: E402


def _load_run():
    spec = importlib.util.spec_from_file_location(
        "tp_run", Path(__file__).resolve().parent / "run.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["tp_run"] = m
    spec.loader.exec_module(m)
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--out", type=Path, default=None,
                    help="write the rendered markdown here; else print to stdout")
    args = ap.parse_args()

    tp = _load_run()
    sub_results = tp._run_sub_skills(args.target, args.indication)
    matrix = tp._ordinal_matrix(sub_results)
    md = ordinal_view.render_matrix_md(matrix, args.target, args.indication)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(md)
        print(f"[demo] wrote {args.out}", file=sys.stderr)
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
