#!/usr/bin/env python3
"""
ScholarEval Runner Script
Extracts evidence from Step 1 and Step 2 outputs, runs deterministic scoring.

Usage:
    python run_scholareval.py --gene CDCP1 --disease nsclc --output-dir /path/to/output

This script ensures deterministic scoring by:
1. Parsing Step 1 (risk assessment) and Step 2 (omics) outputs
2. Extracting structured evidence
3. Calling scoring_engine.py with the evidence
4. Generating YAML output with full audit trail
"""

import argparse
import csv
import yaml
import re
import sys
from pathlib import Path
from typing import Dict, Any, Optional

# Import scoring engine from same directory
from scoring_engine import ScoringEngine, ScholarEvalResult


def _resolve_step2_input(output_dir: Path, gene: str, disease: str, kind: str) -> Optional[Path]:
    """Resolve a Step 2 output file path (ai-sci naming).

    kind: 'idas' | 'report' | 'tcga_stats'
    Returns the Path if it exists on disk, else None.
    """
    skill_name = f"analysis-bulk-rna-{disease}"
    catalog = {
        "idas": f"{gene}_{skill_name}_idas.yaml",
        "report": f"{gene}_{skill_name}_report.md",
        "tcga_stats": f"{gene}_{skill_name}_tcga-stats.csv",
        "suitability": f"{gene}_{skill_name}_suitability.csv",
    }
    path = output_dir / catalog[kind]
    return path if path.exists() else None


def parse_tcga_stats_csv(stats_file: Path) -> Dict[str, Any]:
    """
    Parse the TCGA cohort statistics CSV to extract per-cohort medians directly.
    Avoids fragile markdown-table regex that confused n-count and median columns.
    """
    medians: Dict[str, float] = {}
    with open(stats_file, newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            cohort = row.get("cohort", "").strip()
            try:
                medians[cohort] = float(row["median"])
            except (KeyError, ValueError):
                continue
    return medians


def parse_risk_assessment(risk_file: Path) -> Dict[str, Any]:
    """
    Parse risk assessment markdown to extract structured literature evidence.

    Returns dict with keys: biological_validation, clinical_validation, druggability
    """
    content = risk_file.read_text()
    evidence = {
        "biological_validation": {
            "n_crispr_studies": 0,
            "n_rnai_studies": 0,
            "n_animal_models": 0,
            "n_human_genetic": 0,
            "n_overexpression": 0
        },
        "clinical_validation": {
            "highest_phase": 0,
            "n_trials": 0,
            "indication_specific": False
        },
        "druggability": {
            "has_approved_drug": False,
            "has_clinical_compound": False,
            "has_tool_compound": False,
            "best_ic50_nm": None,
            "has_structure": False,
            "has_binding_pocket": False
        }
    }

    # Parse biological validation. Counts are the number of *distinct mentions*
    # in the biological-validation section (capped to avoid runaway over-counting
    # from prose where the same study gets cited multiple times).
    bio_section = _extract_section(content, "Biological Risk Assessment") or content
    evidence["biological_validation"]["n_animal_models"] = _capped_count(
        bio_section,
        r'\b(in[- ]vivo|PDX|patient[- ]derived xenograft|patient[- ]derived organoid|PDO|GEMM|orthotopic|xenograft)\b',
        cap=5,
    )
    evidence["biological_validation"]["n_crispr_studies"] = _capped_count(
        bio_section,
        r'\b(CRISPR|knockout|KO mice|sgRNA)\b',
        cap=5,
    )
    evidence["biological_validation"]["n_rnai_studies"] = _capped_count(
        bio_section,
        r'\b(RNAi|knockdown|siRNA|shRNA)\b',
        cap=5,
    )
    evidence["biological_validation"]["n_human_genetic"] = _capped_count(
        bio_section,
        r'\b(GWAS|germline|somatic mutation|driver mutation|loss[- ]of[- ]function|gain[- ]of[- ]function|TCGA mutation)\b',
        cap=5,
    )
    evidence["biological_validation"]["n_overexpression"] = _capped_count(
        bio_section,
        r'\b(overexpressed|overexpression|upregulated|amplified|amplification)\b',
        cap=5,
    )

    # Parse clinical validation
    # Support both Arabic ("Phase 2") and Roman ("Phase II", "Phase I/II") forms.
    # Take the highest phase observed anywhere in the risk assessment.
    phase_values = _extract_phase_numbers(content)
    if phase_values:
        evidence["clinical_validation"]["highest_phase"] = max(phase_values)
        evidence["clinical_validation"]["n_trials"] = len(phase_values)

    # Bounded "no trial" check: only zero out if the claim is in the
    # Clinical Validation section to avoid over-greedy matches.
    clinical_section = _extract_section(content, "Clinical Risk Assessment")
    if clinical_section and re.search(
        r'\bno (clinical trials?|trials? to date|approved drug)\b|preclinical[- ]only',
        clinical_section,
        re.IGNORECASE,
    ):
        evidence["clinical_validation"]["highest_phase"] = 0
        evidence["clinical_validation"]["n_trials"] = 0

    # Mark indication-specific only when a Phase appears alongside the disease
    # within a small window (~80 chars) - keeps the heuristic conservative.
    disease_terms = {
        "crc": r"\b(CRC|colorectal|COAD|READ)\b",
        "nsclc": r"\b(NSCLC|lung adenocarcinoma|LUAD|LUSC|squamous cell)\b",
    }
    # disease arg flows in via the larger pipeline; default to scanning both
    indication_pattern = "|".join(disease_terms.values())
    if re.search(
        rf'(?:Phase\s*(?:[IVX]+|\d+)).{{0,80}}(?:{indication_pattern})|'
        rf'(?:{indication_pattern}).{{0,80}}Phase\s*(?:[IVX]+|\d+)',
        content,
        re.IGNORECASE | re.DOTALL,
    ):
        evidence["clinical_validation"]["indication_specific"] = True

    # Parse druggability — require explicit FDA / regulatory language.
    if re.search(
        r'\bFDA[- ]approved\b|approved by (?:the )?FDA|regulatory approval',
        content,
        re.IGNORECASE,
    ):
        evidence["druggability"]["has_approved_drug"] = True

    if re.search(r'clinical[- ]stage|in (?:Phase|clinical) trials?|clinical PoC',
                 content, re.IGNORECASE):
        evidence["druggability"]["has_clinical_compound"] = True

    if re.search(r'tool compound|tool molecules?|preclinical compound|ADC validated',
                 content, re.IGNORECASE):
        evidence["druggability"]["has_tool_compound"] = True

    if re.search(r'crystal structure|co-crystal|X-ray|cryo-EM|PDB entry',
                 content, re.IGNORECASE):
        evidence["druggability"]["has_structure"] = True

    # Druggable pocket / binding site evidence — distinct from having a crystal
    # structure (a target can have a structure but no tractable pocket).
    if re.search(
        r'\b(druggable pocket|binding pocket|allosteric site|active[- ]site|orthosteric|cryptic pocket|ATP[- ]binding pocket)\b',
        content, re.IGNORECASE,
    ):
        evidence["druggability"]["has_binding_pocket"] = True

    # Best IC50 — extract numeric IC50 values and take the lowest (most potent).
    # Matches forms like "IC50 = 50 nM", "IC50: 5 nM", "(IC50 ~10 nM)".
    ic50_values = []
    for match in re.finditer(
        r'IC50\s*[=:~<>]?\s*(\d+\.?\d*)\s*(nM|μM|uM)',
        content, re.IGNORECASE,
    ):
        value = float(match.group(1))
        unit = match.group(2).lower()
        if unit in ("um", "μm"):
            value *= 1000  # convert to nM
        ic50_values.append(value)
    if ic50_values:
        evidence["druggability"]["best_ic50_nm"] = min(ic50_values)

    return evidence


def _capped_count(text: str, pattern: str, cap: int = 5) -> int:
    """Count regex matches in text, capped at `cap`. Used to translate prose
    mentions into evidence weights without runaway over-counting from
    repeated references to the same study.
    """
    matches = re.findall(pattern, text, re.IGNORECASE)
    return min(len(matches), cap)


_ROMAN_TO_INT = {"I": 1, "II": 2, "III": 3, "IV": 4}


def _extract_phase_numbers(content: str) -> list:
    """Find all 'Phase N' mentions and return a list of ints.

    Supports Arabic ('Phase 2'), Roman ('Phase II'), and slash-separated
    forms ('Phase I/II', 'Phase II/III'). For slash forms, the highest
    component is taken.
    """
    phases = []
    pattern = re.compile(
        r'\bPhase\s*([IVX]+|\d+)(?:\s*/\s*([IVX]+|\d+))?\b',
        re.IGNORECASE,
    )
    for match in pattern.finditer(content):
        for group in match.groups():
            if not group:
                continue
            token = group.upper()
            if token in _ROMAN_TO_INT:
                phases.append(_ROMAN_TO_INT[token])
            elif token.isdigit():
                phases.append(int(token))
    return phases


def _extract_section(content: str, header_keyword: str) -> Optional[str]:
    """Return the body of a markdown section whose header contains the keyword.

    Returns text from the matched header up to the next header of the **same or
    higher** level (so subsections like `### Foo` under a `## Section` are
    included). Returns None if no matching section is found.
    """
    pattern = re.compile(
        r'^(#{1,4})\s+([^\n]*)\n', re.MULTILINE,
    )
    matches = list(pattern.finditer(content))
    for i, m in enumerate(matches):
        level = len(m.group(1))
        title = m.group(2)
        if header_keyword.lower() not in title.lower():
            continue
        body_start = m.end()
        # Find the next header at same-or-higher level (i.e. '#' count <= level).
        body_end = len(content)
        for next_m in matches[i + 1:]:
            if len(next_m.group(1)) <= level:
                body_end = next_m.start()
                break
        return content[body_start:body_end]
    return None


def parse_pathway_relevance(risk_file: Path) -> Dict[str, Any]:
    """Score pathway relevance based on mentions of disease-relevant pathways
    and mechanistic links to the target gene.

    Heuristic: count mentions of canonical pathway/mechanism terms in the
    Biological Risk Assessment section. The signal is presence + diversity
    of pathway terms, not a single keyword.

    Returns: {'pathway_score': 1..5, 'pathway_evidence_count': int}
    """
    content = risk_file.read_text()
    bio_section = _extract_section(content, "Biological Risk Assessment") or content

    pathway_terms = [
        r'\b(DNA damage response|DDR)\b',
        r'\b(cell cycle|G1/S|G2/M|checkpoint)\b',
        r'\b(apoptosis|mitotic catastrophe|programmed cell death)\b',
        r'\b(synthetic lethal|synthetic[- ]lethality)\b',
        r'\b(PI3K|MAPK|ERK|JAK[/\-]STAT|WNT|TGF[- ]?β|NF[- ]?κB)\b',
        r'\b(replication stress|genome instability|mutational burden)\b',
        r'\b(EMT|epithelial[- ]mesenchymal transition|stemness)\b',
        r'\b(angiogenesis|VEGF|tumour microenvironment|tumor microenvironment|TME)\b',
        r'\b(immune evasion|antigen presentation|MHC|interferon)\b',
        r'\b(pathway|signaling|signalling)\b',
    ]
    count = 0
    for pattern in pathway_terms:
        if re.search(pattern, bio_section, re.IGNORECASE):
            count += 1

    # Map count of distinct pathway-term categories to 1..5 score.
    if count >= 6:
        score = 5
    elif count >= 4:
        score = 4
    elif count >= 2:
        score = 3
    elif count >= 1:
        score = 2
    else:
        score = 1

    return {"pathway_score": score, "pathway_evidence_count": count}


def parse_disease_association(
    risk_file: Path,
    suitability_file: Optional[Path],
    bio_validation: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Score disease association by combining literature evidence with
    omics-derived subgroup suitability.

    Literature signal: combination of (a) generic prognostic / driver-mutation
    language in the risk assessment, and (b) the strength of biological-
    validation evidence already extracted (animal models + human genetics +
    overexpression studies all indicate disease association).

    Omics signal: max of subgroup-suitability scores from the Step 2
    suitability CSV, with the average as a tie-breaker. Using max captures
    "exists at least one strong subgroup" rather than averaging away
    targeted populations.

    Returns: {
      'disease_assoc_score': 1..5,
      'literature_signal': 1..5,
      'omics_signal': 1..5 or None,
    }
    """
    content = risk_file.read_text()
    bio_section = _extract_section(content, "Biological Risk Assessment") or content
    safety_section = _extract_section(content, "Safety Risk Assessment") or ""

    # (a) Generic disease-association language anywhere in bio + safety sections.
    text = bio_section + "\n" + safety_section
    literature_terms = [
        r'\b(prognostic|prognosis)\b',
        r'\b(driver mutation|oncogenic driver|tumour suppressor|tumor suppressor)\b',
        r'\b(frequently mutated|recurrently mutated|hotspot mutation|highly mutated)\b',
        r'\b(synthetic lethal|synthetic[- ]lethality)\b',
        r'\b(TP53|p53|KRAS|EGFR|BRAF|PIK3CA|APC).{0,40}(CRC|NSCLC|colorectal|lung|cancer|tumor|tumour)\b',
        r'\b(survival|overall survival|disease[- ]free survival|recurrence)\b',
        r'\b(metastatic|metastasis|advanced disease|late[- ]stage)\b',
    ]
    text_count = sum(
        1 for p in literature_terms
        if re.search(p, text, re.IGNORECASE | re.DOTALL)
    )

    # (b) Reuse already-extracted biological-validation evidence weight.
    bio_total = 0
    if bio_validation:
        bio_total = (
            bio_validation.get("n_animal_models", 0)
            + bio_validation.get("n_human_genetic", 0)
            + bio_validation.get("n_overexpression", 0)
        )

    # Compose literature signal: text terms + capped bio-validation weight.
    raw_lit = text_count + min(bio_total, 5)
    if raw_lit >= 8:
        lit_signal = 5
    elif raw_lit >= 6:
        lit_signal = 4
    elif raw_lit >= 4:
        lit_signal = 3
    elif raw_lit >= 2:
        lit_signal = 2
    else:
        lit_signal = 1

    # Omics signal from suitability CSV.
    omics_signal: Optional[float] = None
    if suitability_file is not None and suitability_file.exists():
        scores = []
        with open(suitability_file, newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    scores.append(float(row["score"]))
                except (KeyError, ValueError):
                    continue
        if scores:
            # Use max + avg blend: presence of any 4-5 subgroup matters more
            # than the average dragged down by lower-priority subgroups.
            omics_signal = (max(scores) + sum(scores) / len(scores)) / 2

    # Combine: average lit + omics if both present, else use whichever exists.
    if omics_signal is not None:
        final = (lit_signal + omics_signal) / 2
    else:
        final = lit_signal
    final_score = round(final)
    final_score = max(1, min(5, final_score))

    return {
        "disease_assoc_score": final_score,
        "literature_signal": lit_signal,
        "omics_signal": omics_signal,
    }


def parse_biomarker_potential(
    risk_file: Path,
    idas_file: Optional[Path],
) -> Dict[str, Any]:
    """Score biomarker potential based on availability of patient-selection
    biomarkers (literature) and detection-rate evidence (omics).

    Literature signal: mentions of clinical-grade biomarker terms in the
    Clinical Risk Assessment section.
    Omics signal: % detected in the iDAS YAML's key-iDAS-population block,
    if present (>80% = strong, 50-80% = moderate, <50% = weak).

    Returns: {
      'biomarker_score': 1..5,
      'has_clinical_grade_biomarker': bool,
      'detection_rate_pct': float or None,
    }
    """
    content = risk_file.read_text()
    clinical_section = _extract_section(content, "Clinical Risk Assessment") or content

    has_clinical_grade = bool(re.search(
        r'\b(clinical[- ]grade|companion diagnostic|CDx|NGS panel|FDA[- ]approved (test|assay)|standard of care testing)\b',
        clinical_section, re.IGNORECASE,
    ))
    has_emerging = bool(re.search(
        r'\b(biomarker (development|strategy)|patient selection|stratif|enrich)\b',
        clinical_section, re.IGNORECASE,
    ))

    # Detection rate from iDAS YAML.
    detection_rate: Optional[float] = None
    if idas_file is not None and idas_file.exists():
        with open(idas_file) as fh:
            data = yaml.safe_load(fh) or {}
        # Look for a 'pct_detected' or similar key under whitespace_alignment.
        ws = data.get("whitespace_alignment", {}) or {}
        for entry in ws.values():
            if isinstance(entry, dict):
                for key in ("pct_detected", "percent_detected", "detection_rate"):
                    if key in entry:
                        try:
                            detection_rate = float(entry[key])
                            break
                        except (TypeError, ValueError):
                            continue
                if detection_rate is not None:
                    break

    # Compose final score.
    if has_clinical_grade:
        score = 5 if (detection_rate is None or detection_rate >= 80) else 4
    elif has_emerging:
        score = 4 if (detection_rate is None or detection_rate >= 50) else 3
    else:
        score = 2

    return {
        "biomarker_score": score,
        "has_clinical_grade_biomarker": has_clinical_grade,
        "detection_rate_pct": detection_rate,
    }


def parse_idas_yaml(idas_file: Path) -> Dict[str, Any]:
    """
    Parse iDAS assessment YAML to extract omics evidence.

    Returns dict with keys: rna_expression, idas_alignment
    """
    with open(idas_file, 'r') as f:
        data = yaml.safe_load(f)

    evidence = {
        "rna_expression": {
            "tumor_vs_adjacent_fc": 1.0,
            "tumor_median_log2tpm": 4.0,  # Default if not found
            "normal_median_log2tpm": 3.5  # Default if not found
        },
        "idas_alignment": {}
    }

    # Extract on-target toxicity data
    if "on_target_toxicity" in data:
        tox = data["on_target_toxicity"]
        log2fc = tox.get("tumor_vs_adjacent_log2FC", 0)
        if log2fc is None:
            log2fc = 0
        evidence["rna_expression"]["tumor_vs_adjacent_fc"] = 2 ** log2fc  # Convert to linear FC

    # Extract iDAS whitespace alignments
    if "whitespace_alignment" in data:
        evidence["idas_alignment"] = data["whitespace_alignment"]

    return evidence


def parse_comprehensive_report(report_file: Path) -> Dict[str, Any]:
    """
    Parse comprehensive report markdown for evidence not present in YAML or CSV.

    Median expression values are NOT parsed here — they come from the structured
    stats CSV via parse_tcga_stats_csv() to avoid markdown-table column-position
    bugs (e.g. picking the n-count column when looking for the median column).
    """
    content = report_file.read_text()
    evidence: Dict[str, Any] = {}

    # log2FC fallback: only used if the iDAS YAML didn't provide it.
    # Anchor the match to the on-target toxicity executive summary row,
    # not any "log2FC:" mention elsewhere in the report.
    fc_match = re.search(
        r'On-Target Toxicity[^|]*\|[^|]*log2FC[:\s]+([0-9.-]+)',
        content,
        re.IGNORECASE,
    )
    if fc_match:
        log2fc = float(fc_match.group(1))
        evidence["tumor_vs_adjacent_log2fc"] = log2fc
        evidence["tumor_vs_adjacent_fc"] = 2 ** log2fc

    return evidence


def _select_tumor_median(medians: Dict[str, float], disease: str) -> Optional[float]:
    """Pick the most relevant tumor cohort median for the disease."""
    # Prefer a representative tumor cohort; for CRC and NSCLC the bulk RNA
    # skill emits multiple molecular subgroups. We use the largest non-MSI-H,
    # non-resectable MSS cohort as a reasonable single 'tumor' summary.
    preference_order = {
        "crc": ["TCGA_RASWT_MSS", "TCGA_RASMut_MSS", "TCGA_Tumor"],
        "nsclc": ["TCGA_LUAD", "TCGA_LUSC", "TCGA_Tumor"],
    }.get(disease.lower(), ["TCGA_Tumor"])
    for cohort in preference_order:
        if cohort in medians:
            return medians[cohort]
    return None


def _select_normal_median(medians: Dict[str, float]) -> Optional[float]:
    """Pick the adjacent-normal median; fall back to GTEx if absent."""
    for cohort in ("TCGA_Adjacent", "GTEx_Colon", "GTEx_Lung"):
        if cohort in medians:
            return medians[cohort]
    return None


def run_scholareval(
    gene: str,
    disease: str,
    output_dir: Path,
    verbose: bool = False
) -> ScholarEvalResult:
    """
    Run deterministic ScholarEval scoring.

    1. Parse Step 1 and Step 2 outputs
    2. Extract structured evidence
    3. Call scoring engine
    4. Export results with audit trail
    """
    # Define expected input files (Step 1 risk assessment is single-named)
    risk_file = output_dir / f"{gene}_risk_assessment_{disease}.md"

    # Step 2 outputs (ai-sci naming).
    idas_file = _resolve_step2_input(output_dir, gene, disease, "idas")
    report_file = _resolve_step2_input(output_dir, gene, disease, "report")
    stats_file = _resolve_step2_input(output_dir, gene, disease, "tcga_stats")
    suitability_file = _resolve_step2_input(output_dir, gene, disease, "suitability")

    # Check required files exist.
    missing = []
    if not risk_file.exists():
        missing.append(str(risk_file))
    if idas_file is None:
        missing.append(f"{output_dir}/{gene}_analysis-bulk-rna-{disease}_idas.yaml")
    if report_file is None:
        missing.append(f"{output_dir}/{gene}_analysis-bulk-rna-{disease}_report.md")

    if missing:
        print(f"ERROR: Missing required input files:")
        for f in missing:
            print(f"  - {f}")
        print("\nStep 1 and Step 2 must be completed before running ScholarEval.")
        sys.exit(1)

    print(f"=== ScholarEval Deterministic Scoring ===")
    print(f"Gene: {gene}")
    print(f"Disease: {disease}")
    print(f"Output: {output_dir}")
    print()

    # Parse evidence from input files
    print("Extracting evidence...")
    lit_evidence = parse_risk_assessment(risk_file)
    omics_evidence = parse_idas_yaml(idas_file)
    report_evidence = parse_comprehensive_report(report_file)

    # Merge report-derived log2FC only if the iDAS YAML did not already supply it.
    if "tumor_vs_adjacent_fc" in report_evidence and \
            omics_evidence["rna_expression"].get("tumor_vs_adjacent_fc", 1.0) == 1.0:
        omics_evidence["rna_expression"]["tumor_vs_adjacent_fc"] = report_evidence["tumor_vs_adjacent_fc"]

    # Pull tumor and normal medians from the structured stats CSV. This
    # replaces the previous markdown-regex extraction which mistakenly
    # parsed n-count columns as expression values.
    if stats_file is not None:
        medians = parse_tcga_stats_csv(stats_file)
        tumor_median = _select_tumor_median(medians, disease)
        normal_median = _select_normal_median(medians)
        if tumor_median is not None:
            omics_evidence["rna_expression"]["tumor_median_log2tpm"] = tumor_median
        if normal_median is not None:
            omics_evidence["rna_expression"]["normal_median_log2tpm"] = normal_median

    # Extract evidence for previously-placeholder dimensions (P1 fix).
    # Each parser returns a small dict; the engine accepts these structured
    # fields and uses them in place of the 3.0 placeholder fallback.
    lit_evidence["pathway_relevance"] = parse_pathway_relevance(risk_file)
    lit_evidence["disease_association"] = parse_disease_association(
        risk_file, suitability_file,
        bio_validation=lit_evidence.get("biological_validation"),
    )
    lit_evidence["biomarker_potential"] = parse_biomarker_potential(
        risk_file, idas_file,
    )

    if verbose:
        print("\nLiterature Evidence:")
        print(yaml.dump(lit_evidence, default_flow_style=False))
        print("\nOmics Evidence:")
        print(yaml.dump(omics_evidence, default_flow_style=False))

    # Initialize scoring engine
    print("Running deterministic scoring engine...")
    engine = ScoringEngine()

    # Run evaluation
    result = engine.evaluate_target(
        gene=gene,
        disease=disease.upper(),
        literature_evidence=lit_evidence,
        omics_evidence=omics_evidence
    )

    # Export results
    output_yaml = output_dir / f"{gene}_scholareval.yaml"
    output_audit = output_dir / f"{gene}_audit_trail.json"

    engine.export_result(result, output_yaml)
    engine.export_audit_trail(output_audit)

    # Print summary
    print()
    print(f"{'='*60}")
    print(f"ScholarEval Result: {result.gene} in {result.disease}")
    print(f"{'='*60}")
    print(f"Total Score: {result.total_score}/5.0")
    print(f"Assessment: {result.assessment}")
    print(f"Recommendation: {result.recommendation}")
    print(f"High Risk Categories: {result.high_risk_count}")
    print(f"Input Hash: {result.input_hash}")
    print()
    print("Dimension Scores:")
    for dim, score in result.dimension_scores.items():
        print(f"  {dim}: {score.score}/5 ({score.risk_level})")
    print()
    print(f"Results exported to:")
    print(f"  - {output_yaml}")
    print(f"  - {output_audit}")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Run deterministic ScholarEval scoring",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python run_scholareval.py --gene CDCP1 --disease nsclc --output-dir ./results
    python run_scholareval.py --gene TNFRSF12A --disease crc --output-dir ./results -v
        """
    )
    parser.add_argument("--gene", required=True, help="Gene symbol (e.g., CDCP1)")
    parser.add_argument("--disease", required=True, choices=["crc", "nsclc"], help="Disease indication")
    parser.add_argument("--output-dir", required=True, help="Output directory with Step 1 and 2 outputs")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print extracted evidence")

    args = parser.parse_args()

    output_dir = Path(args.output_dir).expanduser().resolve()

    run_scholareval(
        gene=args.gene,
        disease=args.disease,
        output_dir=output_dir,
        verbose=args.verbose
    )


if __name__ == "__main__":
    main()
