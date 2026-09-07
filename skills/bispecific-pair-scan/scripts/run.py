#!/usr/bin/env python3
"""bispecific-pair-scan — logic-gated AND/OR/NOT antigen-PAIR tumor-selectivity scan (new 2026-08-06).

A NET-NEW capability the v2 framework did not have: two-antigen (bispecific) selectivity. Given a
target antigen + a partner set, scores each pair under a logic gate (AND raises selectivity, NOT
spares a normal tissue, OR backstops heterogeneity) over per-sample TCGA-tumor vs GTEx-normal TPM,
and emits a RANKED pair list. Ports the biologics-target-discovery bstrat.gates physics; the compute
lives in analysis-methods/methods/pair_selectivity_gate.

WHY A SCAN-HOOK SKILL, NOT A CARD (architectural): the framework's card / resolver / run_plan spine
is SINGLE-TARGET (run_plan.schema requires exactly target_symbol + indication; entity grains are
target / target_indication — there is no target_pair grain). A pair evidence card would break that
contract. So — exactly like surfaceome-cohort-ranking — this is a SCAN skill with a bespoke CLI that
emits a ranked derived list + the canonical wired-skill decision.json shape, sitting OUTSIDE the
per-target verdict spine. Its output is candidate GENERATION (pairs to confirm), handed to a human.

HONEST LIMITATION (on every result): bulk co-expression in a SAMPLE is necessary but NOT sufficient
for same-CELL co-expression, which is what an AND-gate bispecific needs (avidity). Same-cell
confirmation needs single-cell / spatial (CELLxGENE Census) — a documented gap. And: the scan is a
BOUNDED BACKGROUND job (~60-90s per pair — the GTEx per-sample read dominates), NOT an interactive
per-target lookup; keep the partner set to dozens (a surfaceome / clinical-seed subset), not thousands.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common import make_decision_json, write_package
from _skills_common.skill_report import build_skill_report, ROLE_DESCRIPTIVE
from _skills_common.envelope import build_subskill_provenance
from _skills_common.gitmeta import skills_repo_sha

SKILL_NAME = "bispecific-pair-scan"
SKILL_VERSION = "1.0.0"

# The two per-sample TPM products the pair scan reads (TCGA tumor + GTEx normal). DECLARED here as the
# card's input_manifest_ids so build_subskill_provenance resolves them into the envelope-required
# provenance.resolved_releases block — stable across a read miss (the run's DECLARED input set, not only
# a successful read), so the data_unavailable degrade emit still carries a resolved-release fingerprint.
SCAN_INPUT_MANIFEST_IDS = ("tcga-tumor-tpm-recount3-long-v1", "gtex-tpm-recount3-long-v1")

# ~40 validated clinical TCE / bispecific / ADC surface antigens — the default partner "seed set"
# when --partners is not given (mirrors the biologics repo's semi-supervised seed list). A pragmatic
# starting universe for "what pairs well with my target"; override with --partners for a focused scan.
CLINICAL_SEED_ANTIGENS = [
    "EPCAM",
    "CEACAM5",
    "ERBB2",
    "MET",
    "MSLN",
    "FOLR1",
    "TACSTD2",
    "MUC1",
    "MUC16",
    "CD19",
    "MS4A1",
    "CD22",
    "TNFRSF17",
    "GPRC5D",
    "DLL3",
    "CLDN18",
    "CLDN6",
    "NECTIN4",
    # FOLH1 is the HGNC symbol for PSMA — list the gene ONCE, canonically (was "PSMA","FOLH1",
    # which resolve to the same gene → a duplicate pair). MSLN also appeared twice below.
    "FOLH1",
    "GPC3",
    "PROM1",
    "CDH17",
    "CDH3",
    "EGFR",
    "MUC17",
    "STEAP1",
    "STEAP2",
    "DPEP1",
    "GUCY2C",
    "LY6G6D",
    "CEACAM6",
    "ROR1",
    "ROR2",
    "FGFR2",
    "FGFR3",
    "LRRC15",
    "SLC34A2",
    "TENB2",
]

GATE_CHOICES = ("AND", "OR", "NOT")

QUESTION = (
    "For {target} in {indication}, which partner antigens form a tumor-selective "
    "{gate}-gated bispecific pair (per-sample TCGA-tumor vs GTEx-normal), and how does "
    "each pair's selectivity rank?"
)


def _run_scan(target: str, partners: list, indication: str, gate: str) -> dict:
    """Drive the analysis-methods pair_selectivity_gate.scan_partner_set. Any failure (unimportable
    method, S3 error) degrades to an EMPTY ranked list → honest data_unavailable, never a crash."""
    results = []
    load_error = None
    try:
        from _skills_common._live_readers import _import_method

        _import_method("pair_selectivity_gate")  # ensures analysis-methods repo on path
        from methods.pair_selectivity_gate import read as _pair

        results = _pair.scan_partner_set(target, partners, indication, gate)
    except Exception as e:  # noqa: BLE001
        load_error = f"{type(e).__name__}: {e}"
        print(f"[bispecific-pair-scan] scan failed ({load_error}); data_unavailable", file=sys.stderr)
        results = []

    # SAME-CELL AVIDITY CONFIRMATION (biologics-augment item 1): the bulk gate scan NOMINATES pairs
    # from sample-level co-expression; for an AND gate that is necessary but NOT sufficient (two
    # antigens can be high in a tumor sample yet on DIFFERENT cells). Attach the single-cell same-cell
    # confirmation (sc-samecell-coexpr cube) to each AND-gate pair — closing the avidity caveat. OR/NOT
    # gates are not same-cell-avidity questions, so they are left unconfirmed. Best-effort: if the cube
    # is not landed for the indication, each pair carries samecell_avidity_call='data_unavailable'
    # (the bulk verdict + caveat still stand — never a fabricated confirmation).
    if gate == "AND" and results:
        try:
            from methods.pair_selectivity_gate import samecell as _sc

            for r in results:
                if r.get("partner"):
                    r["samecell_confirmation"] = _sc.confirm_pair_samecell(target, r["partner"], indication)
        except Exception as e:  # noqa: BLE001
            print(f"[bispecific-pair-scan] same-cell confirmation skipped ({type(e).__name__}: {e})", file=sys.stderr)

    scored = [r for r in results if r.get("selectivity") is not None]
    return {
        "target": target,
        "indication": indication,
        "gate": gate,
        "n_partners_scanned": len(partners),
        "n_pairs_scored": len(scored),
        "ranked_pairs": results,
        "load_error": load_error,
    }


def _build_headline_block(scan: dict, target: str, indication: str, gate: str) -> dict:
    """Descriptive hero payload for the unified skill_report spine (build_skill_report reads
    honest_phrase off verdict.phrase + confidence off .confidence). This is a RANKING scan — NOT a
    gated verdict (skill_report.call stays null) — so the phrase reports the top-ranked pair (or the
    honest data_unavailable), confidence rides a scan-coverage sidecar, and the load-bearing avidity
    caveat (bulk co-expression ≠ same-cell) is the top tension. VERDICT-INERT projection; never a call."""
    top = scan["ranked_pairs"][0] if scan.get("ranked_pairs") else None
    scored = scan.get("n_pairs_scored") or 0
    n_scanned = scan.get("n_partners_scanned") or 0
    if scored and top and top.get("selectivity") is not None:
        sel = top.get("selectivity")
        sel_str = f"{sel:.1f}" if isinstance(sel, (int, float)) else str(sel)
        partner = top.get("partner")
        sc = top.get("samecell_confirmation") or {}
        sc_call = sc.get("samecell_avidity_call")
        samecell_ok = gate == "AND" and sc_call and sc_call not in ("data_unavailable", None)
        phrase = (
            f"Top {gate}-gated pair: {target}+{partner} — {sel_str}x tumor-selective "
            f"({scored} of {n_scanned} partners scored; ranked candidate-generation scan, "
            f"not a verdict)"
        )
        level = "moderate" if samecell_ok else "weak"
        basis = "bulk sample co-expression ranks the pair; " + (
            "single-cell same-cell avidity confirmed"
            if samecell_ok
            else "same-cell avidity unconfirmed (bulk co-expression ≠ same-cell)"
        )
    else:
        phrase = (
            f"No {gate}-gated {target} pair scored in {indication} — data unavailable "
            f"(indication maps to no TCGA study, the TPM products are unreadable, or no partner "
            f"scored)"
        )
        level = "insufficient"
        basis = scan.get("load_error") or "no pair scored"
    caveat = scan.get("_avidity_caveat") or (
        "Bulk co-expression in a SAMPLE is necessary but NOT sufficient for same-CELL co-expression "
        "(avidity — what an AND-gate bispecific needs); confirm on single-cell / spatial (CELLxGENE)."
    )
    return {
        "verdict": {"phrase": phrase, "polarity": "not_scored"},
        "confidence": {"level": level, "basis": basis, "coverage": None},
        "top_tension": {"text": caveat, "source": "bispecific-pair-scan avidity caveat"},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Logic-gated AND/OR/NOT bispecific antigen-pair scan.")
    ap.add_argument("--target", required=True, help="HGNC symbol — the primary antigen (arm A).")
    ap.add_argument("--indication", required=True, help="OncoTree code (e.g. COADREAD, NSCLC, BRCA).")
    ap.add_argument(
        "--gate",
        default="AND",
        choices=GATE_CHOICES,
        help="AND (raise selectivity) | OR (heterogeneity backstop) | NOT (partner is the "
        "veto antigen to spare a normal tissue). Default AND.",
    )
    ap.add_argument(
        "--partners",
        default=None,
        help="Comma-separated HGNC symbols to pair against --target. Omit to use the "
        "~40 clinical-seed surface antigens (a bounded default universe).",
    )
    ap.add_argument("--out", required=True, type=Path)
    # Data-provenance posture carried into the emitted provenance block (mirrors the shared dispatcher's
    # run_wired_skill argparse) — this scan hand-rolls main(), so it stamps the same run-level posture.
    ap.add_argument(
        "--data-mode", default="live", help="Data-provenance posture carried into the emitted provenance block."
    )
    ap.add_argument(
        "--release-pin", default=None, help="Optional catalog release pin carried into the emitted provenance block."
    )
    args = ap.parse_args()

    partners = (
        [p.strip().upper() for p in args.partners.split(",") if p.strip()]
        if args.partners
        else list(CLINICAL_SEED_ANTIGENS)
    )
    scan = _run_scan(args.target.upper(), partners, args.indication.upper(), args.gate)

    top = scan["ranked_pairs"][0] if scan["ranked_pairs"] else None
    headline = {
        "target": args.target.upper(),
        "indication": args.indication.upper(),
        "gate": args.gate,
        "n_partners_scanned": scan["n_partners_scanned"],
        "n_pairs_scored": scan["n_pairs_scored"],
        "top_pair": (
            {
                "partner": top.get("partner"),
                "selectivity": top.get("selectivity"),
                "tumor_fraction": top.get("tumor_fraction"),
                "call": top.get("call"),
                # same-cell avidity confirmation (AND-gate only) — closes the bulk-
                # nomination avidity gap: is the bulk co-expression genuinely same-cell?
                "samecell_avidity_call": (top.get("samecell_confirmation") or {}).get("samecell_avidity_call"),
                "samecell_both_fraction": (top.get("samecell_confirmation") or {}).get("samecell_both_fraction_median"),
            }
            if top and top.get("selectivity") is not None
            else None
        ),
        "cards_available": 1 if scan["n_pairs_scored"] > 0 else 0,
        "cards_missing": [] if scan["n_pairs_scored"] > 0 else ["bispecific-pair-scan"],
    }

    _unavailable = scan["n_pairs_scored"] == 0
    scan["_data_source"] = "tcga-tumor-tpm-recount3-long-v1 + gtex-tpm-recount3-long-v1"
    # the mandatory avidity caveat (from the first scored pair, else a static copy)
    scan["_avidity_caveat"] = next(
        (r.get("_avidity_caveat") for r in scan["ranked_pairs"] if r.get("_avidity_caveat")), None
    )
    card_outputs = [
        {
            "card_id": "bispecific-pair-scan",
            "summary": scan,
            "_missing": _unavailable,
            "_missing_reason": (
                "no pair scored (product unreadable, indication has no TCGA study, or partners absent)"
                if _unavailable
                else None
            ),
            # DECLARED input products (stable across a read miss) → provenance.resolved_releases + the
            # per-card input_manifest_ids in the emitted cards[] / provenance.yaml.
            "provenance": {"input_manifest_ids": list(SCAN_INPUT_MANIFEST_IDS)},
        }
    ]

    # ── Unified skill_report spine (finalized data-product lock) ───────────────────────────────────
    # This scan is GATELESS-DESCRIPTIVE: it emits a RANKED pair list, not a scalar verdict, so
    # skill_report.call is null (role=descriptive → polarity=not_scored). The headline_block gives the
    # spine a non-null honest_phrase (top-ranked pair, else the honest data_unavailable) + a coverage
    # confidence sidecar + the avidity caveat as top-tension. Best-effort: a projection fault degrades
    # (skill_report=None; a healthy run always emits it) — it never aborts the scan output.
    try:
        headline["headline_block"] = _build_headline_block(
            scan, args.target.upper(), args.indication.upper(), args.gate
        )
        _q = QUESTION.format(target=args.target.upper(), indication=args.indication.upper(), gate=args.gate)
        headline["skill_report"] = build_skill_report(
            role=ROLE_DESCRIPTIVE,
            verdict=None,  # gateless ranking → no scalar call
            headline_block=headline["headline_block"],
            question_table=[
                {
                    "id": "bispecific_pair_scan",
                    "question": _q,
                    "answer": headline["headline_block"]["verdict"]["phrase"],
                }
            ],
            fired_rule_ids=[],
            cards_used=[] if _unavailable else ["bispecific-pair-scan"],
            cards_missing=["bispecific-pair-scan"] if _unavailable else [],
        )
    except Exception as exc:  # noqa: BLE001 — verdict-inert projection; never abort the scan output
        headline.setdefault("_enrichment_errors", {})["skill_report"] = f"{type(exc).__name__}: {exc}"
        headline["skill_report"] = None

    # Run-level provenance — this scan hand-rolls main() (no run_wired_skill), so it builds the
    # reproducibility block the shared dispatcher injects, or the emitted decision.json is missing the
    # envelope-required top-level `provenance`. Best-effort (never raises).
    provenance = build_subskill_provenance(card_outputs, args.data_mode, args.release_pin, skills_repo_sha())

    decision = make_decision_json(
        skill_name=SKILL_NAME,
        target=args.target.upper(),
        indication=args.indication.upper(),
        question=QUESTION.format(target=args.target.upper(), indication=args.indication.upper(), gate=args.gate),
        card_outputs=card_outputs,
        fired=[],
        headline=headline,
        modality_lenses=None,
        provenance=provenance,
    )
    # Per-run RUN-HEALTH record (observability; envelope-required sibling key — never a verdict input).
    decision["run_health"] = {
        "skill_name": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "status": "degraded" if _unavailable else "ok",
        "n_cards_consumed": 1,
        "n_cards_resolved": 0 if _unavailable else 1,
        "n_partners_scanned": scan["n_partners_scanned"],
        "n_pairs_scored": scan["n_pairs_scored"],
        "load_error": scan.get("load_error"),
    }
    write_package(
        out_dir=args.out,
        decision=decision,
        card_outputs=card_outputs,
        target=args.target.upper(),
        indication=args.indication.upper(),
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        invoked_lenses={},
    )
    print(f"wrote data-package to {args.out}")
    print(
        f"  {args.gate}-gate scan: {args.target.upper()} x {scan['n_partners_scanned']} partners "
        f"in {args.indication.upper()}, {scan['n_pairs_scored']} scored"
    )
    print(json.dumps(headline, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
