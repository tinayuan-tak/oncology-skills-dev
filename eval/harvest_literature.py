#!/usr/bin/env python3
"""harvest_literature — Component 2 of the literature↔deterministic discordance loop.

Runs the opt-in `--literature` lane across the fan-out sub-skills for a set of (target,
indication) pairs, SNAPSHOTS each sub-skill's `literature_synthesis` (joined with its
deterministic sub-verdict + claim_vector) into a pinned corpus, and — optionally — feeds
`build_discordance_ledger` to emit the ranked candidate-gap ledger.

WHY A PINNED SNAPSHOT. The lane is an Opus read of abstracts and is NOT bit-reproducible
(model-default temperature; `_prompt_hash` drifts). So we harvest ONCE into a frozen corpus and
compute/review the ledger against that snapshot — never re-roll the lane live per review. Each
record is stamped with `_model_id` + `_prompt_hash`.

COST. This is the expensive, live half of the loop. It runs the full in-process fan-out
(`_run_sub_skills`) — every wired reader hits live S3 — plus one Opus call per lane. Scope the
lanes with `--literature-scope gating` (the ~gating axes only) to bound Bedrock spend. Keep the
target list to the calibration set (dozens), NOT a blind fleet sweep (see the plan §5).

ENV: `AWS_PROFILE=cbg` (live readers, onc-compbio bucket) + `BEDROCK_AWS_PROFILE=cmp-dev`
(the Opus lane). After a SageMaker restart, re-export PATH for gh/pixi.

Usage:
    AWS_PROFILE=cbg BEDROCK_AWS_PROFILE=cmp-dev pixi run python eval/harvest_literature.py \
        --pairs KRAS/COADREAD,MET/LUAD --literature-scope gating \
        --snapshot-dir eval/literature-snapshots --build-ledger \
        --calibration-set ../rnd-computational-biology-oncology-target-contracts/vocabularies/known_target_calibration_set.yaml
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_EVAL = Path(__file__).resolve().parent
_SKILLS = _EVAL.parents[0] / "skills"
for _p in (str(_EVAL), str(_SKILLS), str(_SKILLS / "target-profile" / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import build_discordance_ledger as bdl  # noqa: E402


def _normalize_verdict(verdict) -> tuple[str | None, str | None]:
    """res['verdict'] is (verdict_str, driving_rule_id) | None."""
    if isinstance(verdict, (list, tuple)) and verdict:
        return verdict[0], (verdict[1] if len(verdict) > 1 else None)
    return None, None


def _canonical_symbol(target: str) -> str:
    """Map a display/alias symbol (the calibration-set KEY, e.g. HER2/TROP2/BCMA/CD20) to the
    HGNC-canonical gene symbol the gene-keyed data products are keyed by (ERBB2/TACSTD2/TNFRSF17/
    MS4A1). Single-sources run_known_target_panel.TARGET_CANON so the harvest resolves the SAME
    symbol as the nomination backtest — WITHOUT this, the fan-out queried every gene-keyed reader
    (PRISM/DGIdb/ChEMBL/structure) with an ALIAS that matches no HGNC row, so each gene-keyed axis
    read a spurious data-unavailable / no-compounds-found and the ledger logged a phantom
    calibration_gap (CASE-011: HER2/BRCA tractability read chemically_unhit via
    prism-no-compounds-found-neutral, though the resolved ERBB2 run reads chemically_active with 37
    PRISM compounds + 201 DGIdb approved interactions). Canonical / unknown symbols pass through."""
    try:
        from run_known_target_panel import TARGET_CANON
    except Exception:  # noqa: BLE001 — a canon-map import fault must never abort a harvest
        TARGET_CANON = {}
    sym = (target or "").strip()
    return TARGET_CANON.get(sym, sym)


def harvest_pair(
    target: str,
    indication: str,
    *,
    literature_scope: str = "all",
    model: str | None = None,
    skills: "list[str] | None" = None,
) -> list[dict]:
    """Run the fan-out with the --literature lane ON and project each sub-skill into a
    normalized harvest record. Records are only produced for sub-skills whose lane actually
    ran (a skill with no narrator lens, or a lit-native skill, is honestly skipped).

    The fan-out runs on the HGNC-canonical symbol (see _canonical_symbol) so gene-keyed readers
    resolve; the record keeps `target` = the ORIGINAL display/alias symbol (the calibration-set
    key) so calibration_gap tagging + the snapshot filename stay keyed by that symbol, mirroring
    run_known_target_panel (curated `name` vs resolved `emit_target`)."""
    from tp_fanout import _run_sub_skills  # imported lazily so --help needs no skills path

    run_symbol = _canonical_symbol(target)
    sub_results = _run_sub_skills(
        run_symbol,
        indication,
        subskill_literature=True,
        subskill_literature_scope=literature_scope,
        synthesis_model=model,
        skills=skills,  # None → full fan-out; else only the named sub-skills' lanes run (compute subset)
    )
    records: list[dict] = []
    for short, res in sub_results.items():
        facet = res.get("synthesis_facet") or {}
        lit = facet.get("literature_synthesis") if isinstance(facet, dict) else None
        if not isinstance(lit, dict) or not lit:
            continue
        v, rule = _normalize_verdict(res.get("verdict"))
        fired = res.get("fired") or []
        fired_ids = [f.get("rule_id") for f in fired if isinstance(f, dict)] if fired else []
        records.append(
            {
                "target": target,
                # HGNC symbol the fan-out actually resolved (== target unless an alias was canonicalized).
                # Audit trail for CASE-011; downstream (build_discordance_ledger) ignores unknown keys.
                "resolved_symbol": run_symbol,
                "indication": indication,
                "skill": res.get("skill_dir") or short,  # skill DIR id (matches atlas-exclusion set)
                "axis_short": short,
                "sub_verdict": {
                    "gate": short,
                    "verdict": v,
                    "driving_rule_id": rule,
                    "fired_rule_ids": fired_ids,
                },
                "claim_vector": (facet.get("claim_vector") if isinstance(facet, dict) else None),
                "literature_synthesis": lit,
                "_provenance": {"model_id": lit.get("_model_id"), "prompt_hash": lit.get("_prompt_hash")},
            }
        )
    return records


def _parse_pairs(spec: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for tok in (spec or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        t, _, ind = tok.partition("/")
        out.append((t.strip(), ind.strip()))
    return out


# Ground-truth sections keyed BY TARGET SYMBOL; each value carries `indication`. Composite/multi
# targets (e.g. CDK4_6, EGFR_cMET_VEGF) and `multi` indications are skipped — they are not a
# single (gene, indication) the fan-out can run.
_PAIR_SECTIONS = ("reference_profiles", "known_gap_watchlist", "positive_controls")


def _pairs_from_calibration(path: str | Path) -> list[tuple[str, str]]:
    """(target, indication) pairs from known_target_calibration_set.yaml. The sections are DICTS
    keyed by target symbol (the symbol is the KEY, not a `target:` field). Skips composite targets
    and non-specific `multi` indications; de-dupes."""
    try:
        import yaml  # type: ignore

        doc = yaml.safe_load(Path(path).read_text()) or {}
    except Exception:  # noqa: BLE001
        return []
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for section in _PAIR_SECTIONS:
        sec = doc.get(section)
        if not isinstance(sec, dict):
            continue
        for target, v in sec.items():
            if "_" in target or "." in target:  # composite / fusion pseudo-target — skip
                continue
            ind = v.get("indication") if isinstance(v, dict) else None
            if not ind or ind == "multi":
                continue
            pair = (str(target), str(ind))
            if pair not in seen:
                seen.add(pair)
                out.append(pair)
    return out


def _snapshot_path(snapshot_dir: Path, target: str, indication: str) -> Path:
    return snapshot_dir / f"{target}__{indication}.json"


# ── Curated GAP-ENRICHED PANELS (skill-scoped discordance loops) ─────────────────────────────────
# A panel binds a small (target, indication) list to the sub-skill(s) whose KNOWN weak-spot class it
# is chosen to exercise (sourced from the CASE_LOG history). Running a panel harvests ONLY those
# skills' lanes over those pairs — a cheap, targeted enrichment for gaps in one skill rather than a
# blind fleet sweep. `--panel <name>` sources both `pairs` and `skills` (either overridable on the CLI).
_PANELS: dict[str, dict] = {
    # measured subtype signal → legibility / omics-blind (the CD274/MSI-H class). COADREAD is the
    # pinned by-subtype axis, so the panel is COADREAD antigens with real subtype structure.
    "tumor-presence-subtype": {
        "skills": ["tumor-presence"],
        "pairs": [("CD274", "COADREAD"), ("HLA-DRA", "COADREAD"), ("CDX2", "COADREAD"), ("MUC2", "COADREAD")],
    },
    # biomarker-conditional dependency false-negatives (the EPAS1×VHL / SMARCA2 class).
    # NOTE: EPAS1's indication was "RCC", which is NOT a canonical_code (nor an alias) in the
    # target-contracts indication_crosswalk — the codes are KIRC/KIRP/KICH. So the FR run resolved no
    # DepMap lineage and silently produced a PAN-SCOPE read for what the panel name calls a within-RCC
    # probe. (run_known_target_panel.py:118 remaps "RCC"->"COADREAD" for the NOMINATION harness, but
    # that remap is local to that file and never reached the harvest lane.) Corrected to KIRC — clear-cell
    # RCC is the VHL-mutant histology the EPAS1×VHL hypothesis is about, and it resolves to Kidney.
    "functional-requirement-conditional": {
        "skills": ["functional-requirement"],
        "pairs": [("EPAS1", "KIRC"), ("SMARCA2", "LUAD"), ("MET", "LUAD"), ("WRN", "COADREAD")],
    },
    # ── The 20-pair FR discordance panel (2026-09-12) ────────────────────────────────────────────
    # Built to exercise the dependency lens where it is most likely to be WRONG, across the breadth of
    # cancer targets rather than one motivating example. Every indication code below is a resolvable
    # canonical_code or alias (checked against indication_crosswalk.yaml — an unresolvable code is
    # exactly the silent pan-scope failure the EPAS1/RCC entry above shows, so this is not optional).
    # Six deliberate strata:
    #   (1) VERDICT-PROVENANCE coverage — the four branches skills#1315 keyed indication_scope_note on.
    #       BRAF/COADREAD and KRAS/COADREAD are CONTROLS: their prose must not move.
    #   (2) COARSE-LINEAGE DILUTION — the class AM#600's absolute-depth floor addresses, where an
    #       OncotreeLineage median hides a sublineage-restricted dependency (IRF4 Lymphoid -0.455 vs
    #       myeloma -2.041; SPI1 Myeloid -0.364 vs AML -0.552).
    #   (3) PAN-ESSENTIAL / BROAD-TOX — literature calls these great targets; the lens must read them as
    #       a therapeutic-window LIABILITY, not support (the "oncogene reads pan-essential" trap inverted).
    #   (4) PARALOG BUFFERING — single-gene KO under-calls a real, redundancy-masked dependency.
    #   (5) PARTNER-CONDITIONAL SL — the pooled-median-dilutes-a-substratum trap #1315 fixed.
    #   (6) VALIDATED LINEAGE ADDICTIONS + one NEGATIVE control (CD19: a validated CAR-T target that is
    #       NOT a genetic dependency — FR SHOULD read non_dependent, and a literature "contradicts" here
    #       is a modality mismatch the lens must not chase into the verdict).
    "functional-requirement-20": {
        "skills": ["functional-requirement"],
        "pairs": [
            # (1) provenance coverage
            ("WRN", "COADREAD"),  # stratified: MSI-H colorectal SL; pooled Bowel median only -0.17
            ("EGFR", "LUAD"),  # KNOWN discordance: dependency confined to an EGFR-MUTANT substratum
            ("BRAF", "COADREAD"),  # CONTROL: genuinely Skin-enriched → prose must stay byte-identical
            ("KRAS", "COADREAD"),  # CONTROL: dependent_not_enriched; the replay anchor
            ("MDM2", "UVM"),  # newly-repaired Eye path (n=8) — TP53-WT-conditional, inverse polarity
            ("GATA3", "NBL"),  # admitted via the NBL sublineage despite a diluted coarse PNS median
            # (2) coarse-lineage dilution
            ("IRF4", "DLBC"),  # Lymphoid dilution; ABC-DLBCL IRF4 addiction
            ("SPI1", "AML"),  # Myeloid dilution
            # (3) pan-essential / broad-tox liability
            ("PLK1", "OV"),  # heavily-drugged in the literature, pan-essential in DepMap
            ("RBM39", "AML"),  # the pan_essential_killer restraint (indisulam)
            # (4) paralog buffering
            ("SMARCA2", "LUAD"),  # SMARCA4-mutant SL, buffered by SMARCA4 itself
            ("STAG2", "BLCA"),  # STAG1 paralog SL
            ("MAPK1", "COADREAD"),  # MAPK1/MAPK3 redundancy
            # (5) partner-conditional synthetic lethality
            ("PARP1", "BRCA"),  # HRD-conditional; the canonical pooled-vs-stratified trap
            ("PRMT5", "MESO"),  # MTAP-deletion-conditional
            ("EPAS1", "KIRC"),  # VHL-conditional (CASE-014 precedent, now correctly scoped)
            # (6) validated lineage addictions + negative control
            ("ERBB2", "BRCA"),  # approved; amplification-conditional
            ("SOX10", "SKCM"),  # melanocytic lineage-survival TF
            ("AR", "PRAD"),  # validated, but few prostate lines → power, not biology, may decide
            ("CD19", "DLBC"),  # NEGATIVE: validated CAR-T target, NOT a genetic dependency
        ],
    },
    # biologics-approved → small-molecule druggability INFLATION (CASE-008 modality-blindness).
    "tractability-sm-inflation": {
        "skills": ["tractability-small-molecule"],
        "pairs": [("DLL3", "SCLC"), ("STEAP1", "PRAD"), ("FOLR1", "OV"), ("NECTIN4", "BLCA"), ("CEACAM5", "NSCLC")],
    },
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pairs", default=None, help="comma list of TARGET/INDICATION (e.g. KRAS/COADREAD,MET/LUAD)")
    ap.add_argument(
        "--calibration-set",
        default=None,
        help="known_target_calibration_set.yaml — source of (target,indication) pairs AND calibration_gap tagging",
    )
    ap.add_argument(
        "--use-calibration-pairs",
        action="store_true",
        help="derive the pair list from --calibration-set (else --pairs is the source)",
    )
    ap.add_argument(
        "--panel",
        choices=sorted(_PANELS),
        default=None,
        help="curated gap-enriched panel — sources pairs + skills for a skill-scoped loop (see _PANELS)",
    )
    ap.add_argument(
        "--skills",
        default=None,
        help="comma list of sub-skill dir/short names — harvest ONLY these lanes (compute subset). "
        "Overrides the panel's skills. Omit for the full fan-out.",
    )
    ap.add_argument("--literature-scope", choices=["all", "gating"], default="all")
    ap.add_argument("--model", default=None, help="override the lane's Bedrock model id")
    ap.add_argument("--snapshot-dir", default="eval/literature-snapshots")
    ap.add_argument("--build-ledger", action="store_true", help="run build_discordance_ledger over the snapshot dir")
    ap.add_argument("--ledger-out", default="eval/discordance_ledger.json")
    a = ap.parse_args(argv)

    panel = _PANELS[a.panel] if a.panel else None
    # pair source precedence: explicit --pairs > --use-calibration-pairs > --panel
    if a.pairs:
        pairs = _parse_pairs(a.pairs)
    elif a.use_calibration_pairs and a.calibration_set:
        pairs = _pairs_from_calibration(a.calibration_set)
    elif panel:
        pairs = list(panel["pairs"])
    else:
        pairs = []
    if not pairs:
        ap.error("no (target, indication) pairs — pass --pairs, --panel, or --use-calibration-pairs+--calibration-set")
    # skill subset: --skills wins, else the panel's skills, else None (full fan-out)
    skills = [s.strip() for s in a.skills.split(",") if s.strip()] if a.skills else (panel["skills"] if panel else None)

    snapshot_dir = Path(a.snapshot_dir)
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    print(f"[harvest] {len(pairs)} pair(s); skills={skills or 'ALL (full fan-out)'}", flush=True)
    total = 0
    for target, indication in pairs:
        print(f"[harvest] {target}/{indication} (scope={a.literature_scope}) ...", flush=True)
        try:
            records = harvest_pair(
                target, indication, literature_scope=a.literature_scope, model=a.model, skills=skills
            )
        except Exception as e:  # noqa: BLE001 — one pair failing must not lose the others
            print(f"[harvest] !! {target}/{indication} failed: {e}", file=sys.stderr)
            continue
        _snapshot_path(snapshot_dir, target, indication).write_text(json.dumps(records, indent=2))
        total += len(records)
        print(f"[harvest]   {len(records)} lane record(s) snapshotted")

    print(f"[harvest] done — {total} records across {len(pairs)} pair(s) → {snapshot_dir}")

    if a.build_ledger:
        cal = bdl._load_calibration_targets(a.calibration_set) if a.calibration_set else set()
        ledger = bdl.build_ledger(snapshot_dir, cal)
        Path(a.ledger_out).write_text(json.dumps(ledger, indent=2))
        s = ledger["summary"]["by_gap_class"]
        print(f"[ledger] {ledger['n_rows']} rows ({ledger['n_actionable']} actionable) → {a.ledger_out}")
        print(f"[ledger] by_gap_class: {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
