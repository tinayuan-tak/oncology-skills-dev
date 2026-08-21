#!/usr/bin/env python3
"""surfaceome-cohort-ranking — Phase-F target-scan skill (new 2026-07-08).

Emits a per-indication whole-surfaceome effect-size ranking parquet +
slide-drop PNG, filtered to cells_supporting >= 3. When --target is
provided, highlights the target's rank + concordance call.

Refactor (2026-07-09): decision.json now emits the canonical
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
    """Load the per-indication surface-protein ranking from the CATALOG-wired
    derived product (surfaceome-cohort-ranking-per-indication-v1), via the
    method module's S3-cache helper — NOT a hardcoded /tmp path.

    Fixed 2026-07-14: previously read a hardcoded
    `/tmp/surfaceome_cohort_ranking_v1.parquet` that NOTHING writes, so the
    skill returned empty even after the S3 product would land (and was a
    /tmp trust surface). Now uses the method reader's `_ensure_derived_cached`,
    which downloads from the pinned S3 key and returns None (→ honest
    data_unavailable) until the derived product is published.
    """
    import pandas as pd

    empty_cols = [
        "indication", "gene_symbol", "uniprot_ac",
        "surface_protein_family", "cells_ran", "cells_supporting",
        "max_abs_log2fc", "ranking_score",
        "tissue_rank", "tissue_percentile_rna",
        "tissue_percentile_protein", "rna_protein_concordance",
        "cohort_rank_class", "method_version",
    ]

    # Reach the method module's cache helper via the same compose-dashboard
    # method loader the dispatchers use. _skills_common knows where
    # _live_readers lives (COMPOSE_SCRIPTS). The whole import+cache chain is
    # wrapped: any failure (unimportable _live_readers/method module, S3
    # error) degrades to an EMPTY ranking (→ honest data_unavailable) rather
    # than crashing the skill — the old /tmp `.exists()` check never raised,
    # so we preserve that graceful-degradation contract.
    ranking_path = None
    try:
        from _skills_common import COMPOSE_SCRIPTS
        if str(COMPOSE_SCRIPTS) not in sys.path:
            sys.path.insert(0, str(COMPOSE_SCRIPTS))
        from _live_readers import _import_method
        _import_method("surfaceome_cohort_ranking")  # ensures methods repo on path
        from methods.surfaceome_cohort_ranking import read as _srm_read
        ranking_path = _srm_read._ensure_derived_cached()  # Path or None
    except Exception as e:
        print(f"[surfaceome-cohort-ranking] ranking load failed "
              f"({type(e).__name__}: {e}); treating as data_unavailable",
              file=sys.stderr)
        ranking_path = None

    if ranking_path is not None and Path(ranking_path).exists():
        df = pd.read_parquet(ranking_path)
        df = df[df["indication"] == indication]
        # NO skill-side re-filter: the product already applies the RELATIVE robustness filter at build
        # (cells_supporting >= min(2, cells_ran), dominant_direction==up). The old fixed `>= 3` re-filter
        # zeroed out low-comparator indications (OV cells_ran=1, 2-cell products) — see the manifest note.
    else:
        df = pd.DataFrame(columns=empty_cols)

    result = {
        "indication": indication,
        "n_ranked": len(df),                       # full indication ranking (product is pre-filtered)
        "robustness_filter": "product-level: cells_supporting >= min(2, cells_ran), dominant_direction==up",
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
                "cells_ran": _safe_int(row.get("cells_ran")),
                "cells_supporting": _safe_int(row.get("cells_supporting")),
                "tissue_percentile_rna": _safe_float(row.get("tissue_percentile_rna")),
                "tissue_percentile_protein": _safe_float(row.get("tissue_percentile_protein")),
                "rna_protein_concordance": row.get("rna_protein_concordance"),
                "cohort_rank_class": row.get("cohort_rank_class"),
            }
        else:
            result["target_context"] = {
                "gene_symbol": target,
                "note": "target not in the ranking — not tumor-up-significant "
                        "in this indication, OR absent from the surfaceome.",
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
        "n_ranked":                      ranking["n_ranked"],
        "robustness_filter":             ranking["robustness_filter"],
        "target_context":                ranking.get("target_context"),
        "cohort_rank_class":             (ranking.get("target_context") or {}).get(
                                             "cohort_rank_class"),
        "cards_available":               1 if ranking["n_ranked"] > 0 else 0,
        "cards_missing":                 [] if ranking["n_ranked"] > 0
                                          else ["surfaceome-cohort-ranking"],
    }

    # Synthesize card_output stub matching the wired-skill contract shape.
    # Use `_missing` (underscore) so resolve_cards/write_package + the RC1
    # coverage-honesty logic recognize an unavailable ranking; stamp
    # `_data_source` so it flows into provenance.yaml's data_provenance block.
    _unavailable = ranking["n_ranked"] == 0
    ranking["_data_source"] = "surfaceome-cohort-ranking-per-indication-v1"
    card_outputs = [{
        "card_id": "surfaceome-cohort-ranking",
        "summary": ranking,
        "_missing": _unavailable,
        "_missing_reason": "cohort_ranking_data_unavailable (derived product "
                           "not yet on S3)" if _unavailable else None,
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
          f"n_ranked={ranking['n_ranked']}, "
          f"target={args.target or '<none>'}")
    print()
    print(json.dumps(headline, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
