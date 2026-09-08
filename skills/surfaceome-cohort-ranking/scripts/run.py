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

from _skills_common import card_input_manifest_ids, make_decision_json, write_package
from _skills_common.envelope import build_subskill_provenance
from _skills_common.gitmeta import skills_repo_sha
from _skills_common.headline_core import HeadlineSpec, build_headline
from _skills_common.skill_report import ROLE_DESCRIPTIVE, build_skill_report

SKILL_NAME = "surfaceome-cohort-ranking"
SKILL_VERSION = "1.1.0"


def _load_ranking(indication: str, target: str | None) -> dict:
    """Load the per-indication surface-protein ranking from the CATALOG-wired
    derived product (surfaceome-cohort-ranking-per-indication-v1), via the
    method module's S3-cache helper — NOT a hardcoded /tmp path.

    Fixed 2026-08-31 (SR-1): previously called `_srm_read._ensure_derived_cached()`, which the
    Aug-2026 read.py rewrite REMOVED (read.py switched to per-target streaming pushdown). The stale
    call raised AttributeError, was swallowed by the broad `except`, and the skill returned
    n_ranked=0 / data_unavailable on EVERY run despite the live product. Now calls the new
    `load_indication_ranking(indication)` — a streamed pushdown on the `indication` column that
    returns every ranked gene_symbol for the indication (None → honest data_unavailable).
    """
    import pandas as pd

    empty_cols = [
        "indication",
        "gene_symbol",
        "uniprot_ac",
        "surface_protein_family",
        "cells_ran",
        "cells_supporting",
        "max_abs_log2fc",
        "ranking_score",
        "tissue_rank",
        "tissue_percentile_rna",
        "tissue_percentile_protein",
        "rna_protein_concordance",
        "cohort_rank_class",
        "method_version",
    ]

    # Reach the method reader via the shared method loader the dispatchers use
    # (_skills_common._live_readers._import_method). The whole import+read chain is wrapped: any
    # failure (unimportable _live_readers/method module, S3 error) degrades to an EMPTY ranking
    # (→ honest data_unavailable) rather than crashing the skill — preserving the graceful-degradation
    # contract. load_indication_ranking returns list[dict] (rows already filtered to this indication),
    # [] for an indication with no ranked genes, or None on a definitive product absence.
    ranking_rows = None
    try:
        from _skills_common._live_readers import _import_method

        _import_method("surfaceome_cohort_ranking")  # ensures methods repo on path
        from methods.surfaceome_cohort_ranking import read as _srm_read

        ranking_rows = _srm_read.load_indication_ranking(indication)  # list[dict] or None
    except Exception as e:
        print(
            f"[surfaceome-cohort-ranking] ranking load failed ({type(e).__name__}: {e}); treating as data_unavailable",
            file=sys.stderr,
        )
        ranking_rows = None

    if ranking_rows:
        # rows are already pushed-down to this indication and the product already applies the RELATIVE
        # robustness filter at build (cells_supporting >= min(2, cells_ran), dominant_direction==up).
        df = pd.DataFrame(ranking_rows)
    else:
        df = pd.DataFrame(columns=empty_cols)

    result = {
        "indication": indication,
        "n_ranked": len(df),  # full indication ranking (product is pre-filtered)
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


QUESTION = (
    "Where does {target} rank among all surface proteins in "
    "{indication} by tumor-vs-normal effect size, and does the "
    "RNA signal agree with the CPTAC protein signal?"
)


# ── Descriptive headline block + unified skill_report spine (finalized data-product lock) ────────────
# surfaceome-cohort-ranking is a GATELESS, DESCRIPTIVE ranking SCAN (∉ target-profile _SHORT_TO_GATE):
# it emits NO verdict/call — the `cohort_rank_class` facet is a percentile READOUT, not a nomination
# gate. So the unified skill_report carries call=None / role=descriptive / polarity=not_scored. The
# spine still needs a non-null honest_phrase + confidence, so we build a THIN descriptive headline_block
# (the scan has no multi-axis claim_vector; confidence rides a data-availability certainty sidecar).
# VERDICT-INERT — nothing here enters `fired` or any resolver.
_RANK_CLASS_PHRASE = {
    "top_1_percent": "top 1%",
    "top_5": "top 5%",
    "top_25": "top 25%",
    "below_25_percent": "below the top 25%",
    "data_unavailable": "unavailable tier",
}
_SCR_HEADLINE_SPEC = HeadlineSpec(
    gate="surfaceome_cohort_ranking",
    axis_labels={},
    axis_keys=(),  # a cohort scan has no claim_vector axes; confidence rides the certainty sidecar
)


def _scr_headline_block(headline: dict) -> dict:
    """Descriptive headline (phrase + data-availability confidence, NO gate verdict). The phrase reports
    WHERE the target ranks (or the whole-cohort scan summary); confidence is a certainty sidecar keyed on
    whether the ranking resolved (moderate when the live product answered, insufficient when unavailable).
    A projection over the already-built headline — moves no verdict (there is none)."""
    ind = headline.get("indication")
    tgt = headline.get("target")
    n_ranked = headline.get("n_ranked") or 0
    tctx = headline.get("target_context") or {}
    rank_class = headline.get("cohort_rank_class")

    if n_ranked == 0:
        phrase = f"Surfaceome cohort ranking unavailable for {ind}"
        level = "insufficient"
    elif tgt and rank_class:
        rank = tctx.get("tissue_rank")
        conc = tctx.get("rna_protein_concordance")
        rank_bit = f" (rank {rank} of {n_ranked})" if rank else ""
        conc_bit = f"; RNA↔protein {conc}" if conc else ""
        phrase = (
            f"{tgt} ranks in the {_RANK_CLASS_PHRASE.get(rank_class, rank_class)} of the "
            f"{ind} tumor-up surfaceome{rank_bit}{conc_bit}"
        )
        level = "moderate"
    elif tgt:
        phrase = (
            f"{tgt} is not tumor-up-significant in the {ind} surfaceome ranking (n={n_ranked} ranked surface proteins)"
        )
        level = "moderate"
    else:
        phrase = f"Ranked {n_ranked} surface proteins in {ind} by tumor-vs-normal effect size (whole-cohort scan)"
        level = "moderate"

    return build_headline(
        headline,
        claim_vector=None,
        key_signals=None,
        spec=_SCR_HEADLINE_SPEC,
        verdict_token=None,
        descriptive_phrase=phrase,
        certainty={"level": level},
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--indication", required=True, help="OncoTree code (e.g. COADREAD, BRCA)")
    ap.add_argument(
        "--target",
        default=None,
        help="Optional HGNC symbol to highlight in the cohort "
        "context. target-scan mode without --target emits "
        "just the full ranking; --target adds a target_context "
        "annotation.",
    )
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    ranking = _load_ranking(args.indication, args.target)

    # Compose the canonical wired-skill headline
    headline = {
        "indication": args.indication,
        "target": args.target,
        "n_ranked": ranking["n_ranked"],
        "robustness_filter": ranking["robustness_filter"],
        "target_context": ranking.get("target_context"),
        "cohort_rank_class": (ranking.get("target_context") or {}).get("cohort_rank_class"),
        "cards_available": 1 if ranking["n_ranked"] > 0 else 0,
        "cards_missing": [] if ranking["n_ranked"] > 0 else ["surfaceome-cohort-ranking"],
    }

    # Synthesize card_output stub matching the wired-skill contract shape.
    # Use `_missing` (underscore) so resolve_cards/write_package + the RC1
    # coverage-honesty logic recognize an unavailable ranking; stamp
    # `_data_source` so it flows into provenance.yaml's data_provenance block.
    _unavailable = ranking["n_ranked"] == 0
    ranking["_data_source"] = "surfaceome-cohort-ranking-per-indication-v1"
    card_outputs = [
        {
            "card_id": "surfaceome-cohort-ranking",
            "summary": ranking,
            "_missing": _unavailable,
            "_missing_reason": "cohort_ranking_data_unavailable (derived product not yet on S3)"
            if _unavailable
            else None,
            # DECLARED input manifest ids (card_spec.required_inputs) — mirrors resolve_cards' per-card
            # provenance stamp so build_subskill_provenance names the real product in the run-level block.
            "provenance": {"input_manifest_ids": list(card_input_manifest_ids("surfaceome-cohort-ranking"))},
        }
    ]

    # Canonical descriptive headline block + unified skill_report spine (finalized data-product lock).
    # Both are VERDICT-INERT projections (call=None, role=descriptive, polarity=not_scored); best-effort,
    # so a projection fault degrades to None and never aborts the scan.
    try:
        headline["headline_block"] = _scr_headline_block(headline)
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the spine
        headline.setdefault("_enrichment_errors", {})["headline_block"] = f"{type(exc).__name__}: {exc}"
        headline["headline_block"] = None
    try:
        headline["skill_report"] = build_skill_report(
            role=ROLE_DESCRIPTIVE,
            verdict=None,  # gateless descriptive scan — no call
            headline_block=headline.get("headline_block"),
            fired_rule_ids=[],
            cards_used=[c["card_id"] for c in card_outputs if not c.get("_missing")],
            cards_missing=[c["card_id"] for c in card_outputs if c.get("_missing")],
        )
    except Exception as exc:  # noqa: BLE001 — verdict-inert normalizer; never abort the spine
        headline.setdefault("_enrichment_errors", {})["skill_report"] = f"{type(exc).__name__}: {exc}"
        headline["skill_report"] = None

    # Run-level provenance — this skill hand-rolls main() (no run_wired_skill), so it builds the
    # reproducibility block the shared dispatcher injects; without it the emitted decision.json is
    # missing the envelope-required top-level `provenance` key (the finalized data-product contract
    # requires it). Best-effort (build_subskill_provenance never raises). data_mode="live": the reader
    # streams the derived product live from S3 (no release pin).
    provenance = build_subskill_provenance(
        card_outputs,
        "live",
        None,
        skills_repo_sha(),
    )

    decision = make_decision_json(
        skill_name=SKILL_NAME,
        target=args.target or "(scan-mode; no target)",
        indication=args.indication,
        question=QUESTION.format(target=args.target or "(any surface protein)", indication=args.indication),
        card_outputs=card_outputs,
        fired=[],
        headline=headline,
        modality_lenses=None,
        provenance=provenance,
    )

    # Per-subskill RUN-HEALTH record — the other envelope-required top-level key the shared dispatcher
    # injects (observability; a sibling key that never touches the verdict spine). No rules fire for
    # this scan (fired=[]), so cards_fired is always empty.
    _cards_missing = sorted(c["card_id"] for c in card_outputs if c.get("_missing"))
    decision["run_health"] = {
        "skill_name": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "status": "degraded" if _cards_missing else "ok",
        "n_cards_consumed": len(card_outputs),
        "n_cards_resolved": sum(1 for c in card_outputs if not c.get("_missing")),
        "n_cards_fired": 0,
        "cards_fired": [],
        "cards_missing": _cards_missing,
    }

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
    print(f"  indication={args.indication}, n_ranked={ranking['n_ranked']}, target={args.target or '<none>'}")
    print()
    print(json.dumps(headline, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
