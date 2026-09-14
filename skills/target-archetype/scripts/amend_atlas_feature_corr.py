#!/usr/bin/env python
"""Add the `feature_corr` block to an ALREADY-FROZEN atlas, without re-running the corpus.

Why this exists rather than a re-freeze. `feature_corr` is a pure function of `X` + `feature_order`,
both of which are already IN the shipped artifact — so the numbers a re-freeze would produce are
exactly the numbers computable from the frozen file. A re-freeze, by contrast, costs a median 123s per
(target, indication) pair against live S3 (`regenerate_corpus.sh`; measured over the 504 logged pair
durations of the n=504 build, so ~17.8h serial and ~4.5h at the --jobs 4 cap), and it would move
EVERY other column — mu, sd, the PCA basis, the embedding, the anchors — to ship one derived block.
Re-deriving a function of the frozen basis is not the same act as re-freezing the basis.

So: ONE implementation, TWO callers. `build_atlas.feature_correlation` is called here and by
`build_atlas.build`, and `test_atlas_feature_corr.py` RECOMPUTES the shipped block from the shipped
`X` and asserts equality — the provenance claim below is checkable, not asserted.

What this does NOT do: touch `meta.build_git_sha` or `meta.build_date`. Those describe the freeze that
produced `X`, and it still did. The derived block gets its own `meta.feature_corr_provenance` stamp
saying it was added afterwards and from what, so nobody later reads the artifact as if the original
build emitted it. Every other key is written back byte-for-byte.

    python skills/target-archetype/scripts/amend_atlas_feature_corr.py [--atlas PATH] [--check]

`--check` verifies the shipped block matches a fresh recomputation and writes nothing (exit 1 on
mismatch) — safe to run in CI.
"""

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_atlas import feature_correlation  # noqa: E402

DEFAULT_ATLAS = Path(__file__).resolve().parents[1] / "atlas" / "atlas.json"


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(Path(__file__).resolve().parent), text=True
        ).strip()
    except Exception:
        return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--atlas", type=Path, default=DEFAULT_ATLAS)
    ap.add_argument("--check", action="store_true", help="verify only; write nothing")
    args = ap.parse_args()

    doc = json.loads(args.atlas.read_text())
    order, corr, counts = feature_correlation(doc["feature_order"], doc["X"])

    if args.check:
        ok = (
            doc.get("feature_corr_order") == order
            and doc.get("feature_corr") == corr
            and doc.get("feature_corr_n") == counts
        )
        if not ok:
            print("MISMATCH: the shipped feature_corr block is not what the frozen X yields", file=sys.stderr)
            return 1
        print(f"OK: feature_corr reproduces from the frozen X ({len(order)} columns)")
        return 0

    # insert at the SAME position build_atlas.build uses (right after reference_mask_fraction) rather than
    # appending, so an amended artifact and a re-frozen one lay their keys out identically.
    new = {}
    for k, v in doc.items():
        new[k] = v
        if k == "reference_mask_fraction":
            new["feature_corr_order"] = order
            new["feature_corr"] = corr
            new["feature_corr_n"] = counts
    if "feature_corr" not in new:  # artifact predates reference_mask_fraction — append rather than drop
        new["feature_corr_order"], new["feature_corr"], new["feature_corr_n"] = order, corr, counts
    doc = new
    doc["meta"]["feature_corr_provenance"] = {
        "derived_post_freeze": True,
        "derived_from": "X + feature_order of this same artifact (no corpus re-read)",
        "method": "pairwise_complete_pearson over ::num:: non-mask columns",
        "reason": (
            "feature_corr is a pure function of the frozen basis, so re-deriving it does not require "
            "re-freezing the basis; build_atlas.feature_correlation is the single implementation and "
            "test_atlas_feature_corr recomputes this block from the shipped X."
        ),
        "added_date": dt.date.today().isoformat(),
        "added_git_sha": _git_sha(),
        "basis_build_git_sha": doc["meta"].get("build_git_sha"),
        "basis_build_date": doc["meta"].get("build_date"),
    }
    # byte-identical serialisation to build_atlas.main (compact, insertion-ordered, NO trailing newline),
    # so the diff is the added block and nothing else.
    args.atlas.write_text(json.dumps(doc, separators=(",", ":"), sort_keys=False))
    nz = sum(1 for row in corr for v in row if v is not None)
    print(f"wrote {args.atlas}: {len(order)} columns, {nz} of {len(order) ** 2} cells populated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
