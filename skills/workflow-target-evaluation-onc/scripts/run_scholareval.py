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
    """
    Resolve Step 2 output paths supporting both ai-sci and legacy naming.

    kind: 'idas' | 'report' | 'tcga_stats'
    Prefers the new ai-sci-style filenames, falls back to legacy names so
    older fixtures and pre-rename outputs remain compatible.
    """
    skill_name = f"analysis-bulk-rna-{disease}"
    candidates = {
        "idas": [
            f"{gene}_{skill_name}_idas.yaml",       # new ai-sci
            f"{gene}_idas_assessment.yaml",         # legacy
        ],
        "report": [
            f"{gene}_{skill_name}_report.md",       # new ai-sci
            f"{gene}_comprehensive_report.md",      # legacy
        ],
        "tcga_stats": [
            f"{gene}_{skill_name}_tcga-stats.csv",  # new ai-sci
            f"{gene}_tcga_statistics.csv",          # legacy
        ],
    }[kind]

    for name in candidates:
        path = output_dir / name
        if path.exists():
            return path
    return None


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

    # Parse biological validation
    # Look for "In vivo validation" mentions
    if re.search(r'in.?vivo.*validation.*PDX|PDX.*efficacy|animal.*model', content, re.IGNORECASE):
        evidence["biological_validation"]["n_animal_models"] = 2

    # Look for CRISPR/knockout mentions
    if re.search(r'CRISPR|knockout|KO mice', content, re.IGNORECASE):
        evidence["biological_validation"]["n_crispr_studies"] = 1

    # Look for RNAi/knockdown mentions
    if re.search(r'RNAi|knockdown|siRNA|shRNA', content, re.IGNORECASE):
        evidence["biological_validation"]["n_rnai_studies"] = 1

    # Parse clinical validation
    # Check for phase mentions
    phase_match = re.search(r'Phase\s*(\d+)', content, re.IGNORECASE)
    if phase_match:
        evidence["clinical_validation"]["highest_phase"] = int(phase_match.group(1))

    # Check for "no clinical trials" or similar
    if re.search(r'no.*clinical.*trial|no.*NSCLC.*trial|no.*CRC.*trial|preclinical only', content, re.IGNORECASE):
        evidence["clinical_validation"]["highest_phase"] = 0

    # Parse druggability
    if re.search(r'approved.*drug|FDA.*approved', content, re.IGNORECASE):
        evidence["druggability"]["has_approved_drug"] = True

    if re.search(r'clinical.*compound|phase.*compound|clinical.*PoC', content, re.IGNORECASE):
        evidence["druggability"]["has_clinical_compound"] = True

    if re.search(r'tool.*compound|antibody.*characterized|ADC.*validated|preclinical.*ADC', content, re.IGNORECASE):
        evidence["druggability"]["has_tool_compound"] = True

    if re.search(r'crystal.*structure|X-ray|cryo-EM', content, re.IGNORECASE):
        evidence["druggability"]["has_structure"] = True

    return evidence


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

    # Step 2 outputs may use ai-sci or legacy naming; resolve either.
    idas_file = _resolve_step2_input(output_dir, gene, disease, "idas")
    report_file = _resolve_step2_input(output_dir, gene, disease, "report")
    stats_file = _resolve_step2_input(output_dir, gene, disease, "tcga_stats")

    # Check required files exist
    missing = []
    if not risk_file.exists():
        missing.append(str(risk_file))
    if idas_file is None:
        missing.append(
            f"{output_dir}/{gene}_analysis-bulk-rna-{disease}_idas.yaml "
            f"(or legacy {gene}_idas_assessment.yaml)"
        )
    if report_file is None:
        missing.append(
            f"{output_dir}/{gene}_analysis-bulk-rna-{disease}_report.md "
            f"(or legacy {gene}_comprehensive_report.md)"
        )

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
