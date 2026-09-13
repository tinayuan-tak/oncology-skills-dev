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


# skill_report keys the harvest record deliberately DROPS: bulky render payloads with no concordance
# meaning. Declared as an EXCLUSION set, not an include-list, so a new decision-bearing key on the
# spine is carried automatically — an include-list would silently omit exactly the coordinate a future
# case needs (the CASE-034 failure re-run one level up). `_skill_report_dropped_keys` on the record
# names what was removed on THIS run, so the omission is auditable rather than assumed.
_SKILL_REPORT_BULK_KEYS = frozenset({"evidence_graph", "figures", "per_phase_metrics", "question_table"})


def _skill_report_projection(facet: dict) -> "tuple[dict | None, list[str]]":
    """(projection, dropped_keys) over `synthesis_facet['skill_report']`.

    CASE-034 part B: the harvest record carried the claim_vector and the raw sub-verdict but NOT the
    skill_report, so the panel's pre-registered predictions about `polarity` / `honest_phrase` /
    `top_tension` were NOT MEASURABLE — the corpus simply did not record the surface they were about.
    Verdict-inert: a projection over an already-composed projection."""
    sr = facet.get("skill_report") if isinstance(facet, dict) else None
    if not isinstance(sr, dict) or not sr:
        return None, []
    dropped = sorted(k for k in sr if k in _SKILL_REPORT_BULK_KEYS)
    return {k: v for k, v in sr.items() if k not in _SKILL_REPORT_BULK_KEYS}, dropped


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
        skill_report, sr_dropped = _skill_report_projection(facet)
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
                # CASE-034 part B: the UNIFIED-OUTPUT spine projection (call/role/polarity/honest_phrase/
                # confidence/top_tension/claim_chips/claim_scalars/modality_scope/provenance). None when the
                # sub-skill composes no skill_report — honest, and distinguishable from "recorded as empty".
                "skill_report": skill_report,
                "_skill_report_dropped_keys": sr_dropped,
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
    # ── The 20-pair MECHANISM discordance panel (2026-09-12) ─────────────────────────────────────
    # Registers the panel that produced discordances D1-D5 in the mechanism-and-pharmacology
    # production-finalize pass. That pass ran the 20 pairs AD HOC (skill CLI per target, report written
    # to /tmp), so the assessment was neither reproducible nor ledgered — and, because an ad-hoc run
    # never touches _PANELS, it also BYPASSED the two guards below (skills-are-real-dirs and
    # indications-resolve). This entry puts the pairs back under both. The strata probe where a CURATED
    # SIGNALING NETWORK is least able to describe the operative mechanism — the class the skill is
    # structurally most likely to get wrong:
    #   (1) RTK / kinase hubs (the well-served base case, and the CONTROLS — prose must not move).
    #   (2) NON-SIGNALING drivers: metabolic/neomorphic (IDH1), LoF TSG actionable only via SL (TP53),
    #       transcriptional/epigenetic (MYC, EZH2, CTNNB1, TEAD1), apoptotic (BCL2). SIGNOR+CollecTRI
    #       under-read these by construction → the D1 class.
    #   (3) SURFACE ANTIGENS (CEACAM5, MSLN): target of an ADC/CAR, mechanism is DELIVERY not signaling
    #       → a thin network is the CORRECT read, and the gap-note must not over-call it (the D5 fix).
    #   (4) SL / paralog (WRN, SMARCA2): mechanism lives in a PARTNER's genotype, not the target's edges.
    #   (5) PHOSPHO-PD readability (ALK, CDK4): the D2 class — a fusion-activated RTK whose CPTAC
    #       phospho coverage is a FLOOR, not a biological negative.
    # ★ INDICATION CODES ARE CORRECTED HERE. The ad-hoc run used HGSOC, PLMESO (x2) and DLBCL (x2),
    # none of which is a canonical_code or alias in indication_crosswalk.yaml — precisely the silent
    # pan-scope degradation the EPAS1/RCC note above documents, and it hit 5 of the 20 pairs, 4 of them
    # in the D1 "non-signaling driver under-read" stratum whose disposition was therefore read off a
    # degraded scope. Corrected: HGSOC->OV, PLMESO->MESO, DLBCL->DLBC (COAD->COADREAD normalized from
    # alias to canonical). test_panel_indications_resolve_in_the_crosswalk now covers all 20.
    "mechanism-and-pharmacology-20": {
        "skills": ["mechanism-and-pharmacology"],
        "pairs": [
            # (1) RTK / kinase-hub base case + controls
            ("EGFR", "LUAD"),  # CONTROL: the best-served shape (dense curated network, approved drugs)
            ("BRAF", "SKCM"),  # CONTROL: prose must stay stable
            ("KRAS", "PAAD"),  # CONTROL: well_characterized hub, 71 upstream regulators
            ("MET", "LUAD"),
            ("ERBB2", "BRCA"),
            ("PIK3CA", "BRCA"),
            ("CDK4", "LUAD"),  # cell-cycle kinase; 0 phosphosites in 9/10 CPTAC cohorts (D2-adjacent)
            ("AR", "PRAD"),  # nuclear receptor: ligand-driven, not a kinase cascade
            # (2) non-signaling drivers — the D1 class
            ("IDH1", "LGG"),  # metabolic / neomorphic: n_dn~0 by construction
            ("TP53", "OV"),  # LoF TSG, actionable only via SL (WEE1/DDR), never direct  [was HGSOC]
            ("MYC", "BRCA"),  # transcriptional hub, undruggable directly
            ("CTNNB1", "COADREAD"),  # WNT/TF output  [was COAD, an alias — normalized]
            ("TEAD1", "MESO"),  # HIPPO transcriptional output  [was PLMESO]
            ("EZH2", "DLBC"),  # epigenetic writer  [was DLBCL]
            ("BCL2", "DLBC"),  # apoptotic effector, not a signaling node  [was DLBCL]
            # (3) surface antigens — mechanism is DELIVERY (the D5 gap-note false-positive class)
            ("CEACAM5", "LUAD"),
            ("MSLN", "MESO"),  # [was PLMESO]
            # (4) SL / paralog — mechanism lives in a partner's genotype
            ("WRN", "COADREAD"),  # MSI-H SL  [was COAD, an alias — normalized]
            ("SMARCA2", "LUAD"),  # SMARCA4-mutant SL
            # (5) phospho-PD readability — the D2 class this arc retired `not_phosphoprotein` for
            ("ALK", "LUAD"),  # fusion-activated RTK; 0 phosphosites in ALL 10 CPTAC cohorts
        ],
    },
    # ── The 20-pair GENOMIC-ALTERATION discordance panel (2026-09-12) ─────────────────────────────
    # Registers the panel exercising genomic-alteration-profile after the SPL-out-of-FUS split (TC #757
    # + skills #1339) and the F9 DEP-axis routing (#1336). The skill answers a MULTI-CLASS question —
    # which alteration class (SNV/indel · copy-number · fusion · splice · biomarker-stratified
    # dependency) DRIVES — so it fails in a distinct way from a single-verdict skill: not "wrong
    # yes/no" but "names the wrong DRIVING CLASS", or reads a non-mutated but amplification-/fusion-/
    # splice-driven target as "not a driver". Six strata target exactly those failure modes, and — per
    # the confidence-rung pre-check (a panel that lands every row on one rung measures nothing) — they
    # deliberately span recurrent drivers, amp-only drivers, fusions, an exon-skip driver, and true
    # genomic negatives, so `contradicts==0` would mean the instrument discriminates, not that it is blunt.
    # Every indication code is a resolvable canonical_code/alias in indication_crosswalk.yaml (an
    # unresolvable code silently degrades that pair to a PAN-SCOPE read — the EPAS1/RCC failure above).
    #   (1) SNV/indel recurrent-driver base case + CONTROLS (prose must stay byte-stable).
    #   (2) COPY-NUMBER-amplification drivers — the "reads NOT a driver because unmutated" trap the
    #       skill's multi-class framing exists to prevent (ERBB2/MYC/MDM2/CCND1 are amp, not SNV).
    #   (3) FUSION drivers — the LIVE tcga-fusion-consensus lane; the class must be read as fusion, not
    #       dismissed as a low SNV frequency.
    #   (4) SPLICE driver — MET/LUAD METex14, the exact axis the SPL split just made scorable on its own
    #       axis; a genomic run here must read SPL, not lift FUS.
    #   (5) BIOMARKER-STRATIFIED dependency / mutation-drug-response — the F9 DEP axis: an SNV whose
    #       action is a stratified drug response (PIK3CA, IDH1/2, FLT3-ITD), not a bare recurrence count.
    #   (6) TSG copy-number DELETION + NEGATIVE antigen controls: SMARCA4/PTEN loss must read as a
    #       deletion driver; CD19/DLL3/FOLR1 carry NO recurrent somatic alteration, so genomic SHOULD
    #       read no-driver and a literature "contradicts" there is a modality mismatch, not a gap.
    "genomic-alteration-profile-20": {
        "skills": ["genomic-alteration-profile"],
        "pairs": [
            # (1) SNV/indel recurrent-driver base + controls
            ("KRAS", "COADREAD"),  # CONTROL: canonical recurrent SNV driver; the replay anchor
            ("BRAF", "SKCM"),  # CONTROL: V600E hotspot driver; prose must stay stable
            ("EGFR", "LUAD"),  # recurrent driver AND a stratified drug-response axis (overlaps stratum 5)
            # (2) copy-number-amplification drivers (must NOT read "not a driver")
            ("ERBB2", "BRCA"),  # focal amplification, rarely SNV — the multi-class touchstone
            ("MYC", "BRCA"),  # amplification-driven transcription factor, never a recurrent SNV
            ("MDM2", "LGG"),  # focal amplification in glioma; TP53-axis, no recurrent MDM2 SNV
            ("CCND1", "HNSC"),  # 11q13 amplification driver
            # (3) fusion drivers (LIVE tcga-fusion-consensus)
            ("ALK", "LUAD"),  # EML4-ALK fusion; low SNV frequency must not read as passenger
            ("NTRK1", "THCA"),  # TRK fusion driver
            ("FGFR3", "BLCA"),  # FGFR3-TACC3 fusion + activating SNV mix
            # (4) splice driver — exercises the just-split SPL axis
            ("MET", "LUAD"),  # METex14 exon-skipping driver; must score SPL, not lift FUS
            # (5) biomarker-stratified dependency / mutation-drug-response (F9 DEP axis)
            ("PIK3CA", "BRCA"),  # hotspot + alpelisib stratified response
            ("IDH1", "GBM"),  # neomorphic R132; the mixed_pattern gap candidate
            ("IDH2", "AML"),  # neomorphic R140/R172 + enasidenib response
            ("FLT3", "AML"),  # FLT3-ITD; midostaurin/quizartinib stratified drug response
            # (6) TSG copy-number deletion + negative antigen controls
            ("SMARCA4", "LUAD"),  # LoF/deletion driver (not amp)
            ("PTEN", "PRAD"),  # deletion/LoF TSG
            ("CD19", "DLBC"),  # NEGATIVE: validated CAR-T antigen, NO recurrent somatic alteration
            ("DLL3", "SCLC"),  # NEGATIVE: ADC/TCE antigen driven by ASCL1 lineage, not a genomic driver
            ("FOLR1", "OV"),  # NEGATIVE: ADC antigen, no recurrent alteration
        ],
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
