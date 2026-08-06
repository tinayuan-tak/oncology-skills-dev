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

SKILL_NAME = "bispecific-pair-scan"
SKILL_VERSION = "1.0.0"

# ~40 validated clinical TCE / bispecific / ADC surface antigens — the default partner "seed set"
# when --partners is not given (mirrors the biologics repo's semi-supervised seed list). A pragmatic
# starting universe for "what pairs well with my target"; override with --partners for a focused scan.
CLINICAL_SEED_ANTIGENS = [
    "EPCAM", "CEACAM5", "ERBB2", "MET", "MSLN", "FOLR1", "TACSTD2", "MUC1", "MUC16",
    "CD19", "MS4A1", "CD22", "TNFRSF17", "GPRC5D", "DLL3", "CLDN18", "CLDN6", "NECTIN4",
    "PSMA", "FOLH1", "GPC3", "PROM1", "CDH17", "CDH3", "EGFR", "MUC17", "STEAP1", "STEAP2",
    "DPEP1", "GUCY2C", "LY6G6D", "CEACAM6", "ROR1", "ROR2", "FGFR2", "FGFR3", "LRRC15",
    "MSLN", "SLC34A2", "TENB2",
]

GATE_CHOICES = ("AND", "OR", "NOT")

QUESTION = ("For {target} in {indication}, which partner antigens form a tumor-selective "
            "{gate}-gated bispecific pair (per-sample TCGA-tumor vs GTEx-normal), and how does "
            "each pair's selectivity rank?")


def _run_scan(target: str, partners: list, indication: str, gate: str) -> dict:
    """Drive the analysis-methods pair_selectivity_gate.scan_partner_set. Any failure (unimportable
    method, S3 error) degrades to an EMPTY ranked list → honest data_unavailable, never a crash."""
    results = []
    load_error = None
    try:
        from _skills_common import COMPOSE_SCRIPTS
        if str(COMPOSE_SCRIPTS) not in sys.path:
            sys.path.insert(0, str(COMPOSE_SCRIPTS))
        from _live_readers import _import_method
        _import_method("pair_selectivity_gate")  # ensures analysis-methods repo on path
        from methods.pair_selectivity_gate import read as _pair
        results = _pair.scan_partner_set(target, partners, indication, gate)
    except Exception as e:  # noqa: BLE001
        load_error = f"{type(e).__name__}: {e}"
        print(f"[bispecific-pair-scan] scan failed ({load_error}); data_unavailable",
              file=sys.stderr)
        results = []

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


def main() -> int:
    ap = argparse.ArgumentParser(description="Logic-gated AND/OR/NOT bispecific antigen-pair scan.")
    ap.add_argument("--target", required=True, help="HGNC symbol — the primary antigen (arm A).")
    ap.add_argument("--indication", required=True, help="OncoTree code (e.g. COADREAD, NSCLC, BRCA).")
    ap.add_argument("--gate", default="AND", choices=GATE_CHOICES,
                    help="AND (raise selectivity) | OR (heterogeneity backstop) | NOT (partner is the "
                         "veto antigen to spare a normal tissue). Default AND.")
    ap.add_argument("--partners", default=None,
                    help="Comma-separated HGNC symbols to pair against --target. Omit to use the "
                         "~40 clinical-seed surface antigens (a bounded default universe).")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    partners = ([p.strip().upper() for p in args.partners.split(",") if p.strip()]
                if args.partners else list(CLINICAL_SEED_ANTIGENS))
    scan = _run_scan(args.target.upper(), partners, args.indication.upper(), args.gate)

    top = scan["ranked_pairs"][0] if scan["ranked_pairs"] else None
    headline = {
        "target":               args.target.upper(),
        "indication":           args.indication.upper(),
        "gate":                 args.gate,
        "n_partners_scanned":   scan["n_partners_scanned"],
        "n_pairs_scored":       scan["n_pairs_scored"],
        "top_pair":             ({"partner": top.get("partner"), "selectivity": top.get("selectivity"),
                                  "tumor_fraction": top.get("tumor_fraction"), "call": top.get("call")}
                                 if top and top.get("selectivity") is not None else None),
        "cards_available":      1 if scan["n_pairs_scored"] > 0 else 0,
        "cards_missing":        [] if scan["n_pairs_scored"] > 0 else ["bispecific-pair-scan"],
    }

    _unavailable = scan["n_pairs_scored"] == 0
    scan["_data_source"] = "tcga-tumor-tpm-recount3-long-v1 + gtex-tpm-recount3-long-v1"
    # the mandatory avidity caveat (from the first scored pair, else a static copy)
    scan["_avidity_caveat"] = next((r.get("_avidity_caveat") for r in scan["ranked_pairs"]
                                    if r.get("_avidity_caveat")), None)
    card_outputs = [{
        "card_id": "bispecific-pair-scan",
        "summary": scan,
        "_missing": _unavailable,
        "_missing_reason": ("no pair scored (product unreadable, indication has no TCGA study, or "
                            "partners absent)" if _unavailable else None),
    }]

    decision = make_decision_json(
        skill_name=SKILL_NAME,
        target=args.target.upper(),
        indication=args.indication.upper(),
        question=QUESTION.format(target=args.target.upper(), indication=args.indication.upper(),
                                 gate=args.gate),
        card_outputs=card_outputs, fired=[],
        headline=headline, modality_lenses=None,
    )
    write_package(
        out_dir=args.out, decision=decision, card_outputs=card_outputs,
        target=args.target.upper(), indication=args.indication.upper(),
        skill_name=SKILL_NAME, skill_version=SKILL_VERSION, invoked_lenses={},
    )
    print(f"wrote data-package to {args.out}")
    print(f"  {args.gate}-gate scan: {args.target.upper()} x {scan['n_partners_scanned']} partners "
          f"in {args.indication.upper()}, {scan['n_pairs_scored']} scored")
    print(json.dumps(headline, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
