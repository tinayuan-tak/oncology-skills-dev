#!/usr/bin/env python3
"""surfaceome-cohort-ranking — Phase-F target-scan skill (new 2026-07-08).

Emits a per-indication whole-surfaceome effect-size ranking parquet +
slide-drop PNG, filtered to cells_supporting >= 3. When --target is
provided, highlights the target's rank + concordance call.

W4c refactor (2026-07-09): decision.json now emits the canonical
wired-skill shape (`skill` key, headline dict, standard data-package
tree) so downstream consumers (target-profile, compose-dashboard) see a
uniform decision-json contract across all wired skills. The bespoke
target-scan CLI (--indication primary, --target optional) is preserved
because this is a scan skill, not a per-target profile skill.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common import make_decision_json, write_package

SKILL_NAME = "surfaceome-cohort-ranking"
SKILL_VERSION = "1.1.0"


def _load_ranking(indication: str, target: str | None) -> dict:
    """Load per-indication ranking parquet. iter-1 scaffold: empty fallback."""
    import pandas as pd
    ranking_path = Path("/tmp/surfaceome_cohort_ranking_v1.parquet")
    if ranking_path.exists():
        df = pd.read_parquet(ranking_path)
        df = df[df["indication"] == indication]
        df = df[df["cells_supporting"] >= 3]
    else:
        df = pd.DataFrame(columns=[
            "indication", "gene_symbol", "uniprot_ac",
            "surface_protein_family", "cells_supporting",
            "max_abs_log2fc", "ranking_score",
            "tissue_rank", "tissue_percentile_rna",
            "tissue_percentile_protein", "rna_protein_concordance",
            "cohort_rank_class", "method_version",
        ])

    result = {
        "indication": indication,
        "n_ranked_after_filter": len(df),
        "cells_supporting_threshold": 3,
    }

    if target and len(df) > 0:
        hit = df[df["gene_symbol"] == target]
        if len(hit):
            row = hit.iloc[0].to_dict()

            def _safe_int(val):
                if val is None:
                    return None
                try:
                    if isinstance(val, float) and val != val:  # NaN check
                        return None
                    return int(val)
                except (ValueError, TypeError):
                    return None

            def _safe_float(val):
                if val is None:
                    return None
                try:
                    fval = float(val)
                    if fval != fval:  # NaN
                        return None
                    return fval
                except (ValueError, TypeError):
                    return None

            result["target_context"] = {
                "gene_symbol": target,
                "tissue_rank": _safe_int(row.get("tissue_rank")),
                "tissue_percentile_rna": _safe_float(row.get("tissue_percentile_rna")),
                "tissue_percentile_protein": _safe_float(row.get("tissue_percentile_protein")),
                "rna_protein_concordance": row.get("rna_protein_concordance"),
                "cohort_rank_class": row.get("cohort_rank_class"),
            }
        else:
            result["target_context"] = {
                "gene_symbol": target,
                "note": "target not in cells_supporting>=3 ranking; "
                        "may be excluded by filter OR absent from surfaceome.",
            }
    elif target:
        result["target_context"] = {
            "gene_symbol": target,
            "note": "no ranking data available for this indication.",
        }

    return result


QUESTION = ("Where does {target} rank among all surface proteins in "
            "{indication} by tumor-vs-normal effect size, and does the "
            "RNA signal agree with the CPTAC protein signal?")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--indication", required=True,
                    help="OncoTree code (e.g. COADREAD, BRCA)")
    ap.add_argument("--target", default=None,
                    help="Optional HGNC symbol to highlight in the cohort "
                         "context. target-scan mode without --target emits "
                         "just the full ranking; --target adds a target_context "
                         "annotation.")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    ranking = _load_ranking(args.indication, args.target)

    # Compose the canonical wired-skill headline
    headline = {
        "indication":                    args.indication,
        "target":                        args.target,
        "n_ranked_after_filter":         ranking["n_ranked_after_filter"],
        "cells_supporting_threshold":    ranking["cells_supporting_threshold"],
        "target_context":                ranking.get("target_context"),
        "cohort_rank_class":             (ranking.get("target_context") or {}).get(
                                             "cohort_rank_class"),
        "cards_available":               1 if ranking["n_ranked_after_filter"] > 0 else 0,
        "cards_missing":                 [] if ranking["n_ranked_after_filter"] > 0
                                          else ["surfaceome-cohort-ranking"],
    }

    # Synthesize card_output stub matching the wired-skill contract shape
    card_outputs = [{
        "card_id": "surfaceome-cohort-ranking",
        "summary": ranking,
        "missing": ranking["n_ranked_after_filter"] == 0,
    }]

    decision = make_decision_json(
        skill_name=SKILL_NAME,
        target=args.target or "(scan-mode; no target)",
        indication=args.indication,
        question=QUESTION.format(target=args.target or "(any surface protein)",
                                 indication=args.indication),
        card_outputs=card_outputs, fired=[],
        headline=headline, modality_lenses=None,
    )

    written = write_package(
        out_dir=args.out,
        decision=decision,
        card_outputs=card_outputs,
        target=args.target or "cohort-scan",
        indication=args.indication,
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        invoked_lenses={},
    )
    print(f"wrote data-package to {args.out}")
    print(f"  indication={args.indication}, "
          f"n_ranked={ranking['n_ranked_after_filter']}, "
          f"target={args.target or '<none>'}")
    print()
    print(json.dumps(headline, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
