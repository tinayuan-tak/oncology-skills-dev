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
import yaml
import re
import sys
from pathlib import Path
from typing import Dict, Any, Optional

# Import scoring engine from same directory
from scoring_engine import ScoringEngine, ScholarEvalResult


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
    Parse comprehensive report markdown to extract additional evidence.
    """
    content = report_file.read_text()
    evidence = {}

    # Extract tumor vs adjacent FC from tables
    # Look for pattern like "log2FC: 0.72" or "log2FC = 1.01" or "| 0.44 |"
    # Try multiple patterns

    # Pattern 1: "On-Target Toxicity Risk** | Medium (log2FC: 0.72)"
    fc_match = re.search(r'log2FC[:\s]+([0-9.-]+)', content, re.IGNORECASE)
    if fc_match:
        log2fc = float(fc_match.group(1))
        evidence["tumor_vs_adjacent_log2fc"] = log2fc
        evidence["tumor_vs_adjacent_fc"] = 2 ** log2fc

    # Pattern 2: Look in TCGA pairwise comparisons table
    # "| TCGA_LUSC vs TCGA_LUSC_Adjacent | ... | 1.01 |"
    lusc_match = re.search(r'LUSC.*Adjacent.*\|\s*([0-9.-]+)\s*\|', content)
    luad_match = re.search(r'LUAD.*Adjacent.*\|\s*([0-9.-]+)\s*\|', content)

    if lusc_match and luad_match:
        lusc_fc = float(lusc_match.group(1))
        luad_fc = float(luad_match.group(1))
        avg_log2fc = (lusc_fc + luad_fc) / 2
        evidence["tumor_vs_adjacent_log2fc"] = avg_log2fc
        evidence["tumor_vs_adjacent_fc"] = 2 ** avg_log2fc
        evidence["lusc_log2fc"] = lusc_fc
        evidence["luad_log2fc"] = luad_fc

    # Extract normal tissue median from statistics table
    # "| TCGA_LUAD_Adjacent | 59 | 3.77 |"
    normal_match = re.search(r'Adjacent\s*\|\s*\d+\s*\|\s*([0-9.]+)', content)
    if normal_match:
        evidence["normal_median_log2tpm"] = float(normal_match.group(1))

    # Extract tumor median
    tumor_match = re.search(r'TCGA_LUAD\s*\|\s*\d+\s*\|\s*([0-9.]+)', content)
    if tumor_match:
        evidence["tumor_median_log2tpm"] = float(tumor_match.group(1))

    return evidence


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
    # Define expected input files
    risk_file = output_dir / f"{gene}_risk_assessment_{disease}.md"
    idas_file = output_dir / f"{gene}_idas_assessment.yaml"
    report_file = output_dir / f"{gene}_comprehensive_report.md"

    # Check required files exist
    missing = []
    if not risk_file.exists():
        missing.append(str(risk_file))
    if not idas_file.exists():
        missing.append(str(idas_file))
    if not report_file.exists():
        missing.append(str(report_file))

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

    # Merge report evidence into omics
    if "tumor_vs_adjacent_fc" in report_evidence:
        omics_evidence["rna_expression"]["tumor_vs_adjacent_fc"] = report_evidence["tumor_vs_adjacent_fc"]
    if "normal_median_log2tpm" in report_evidence:
        omics_evidence["rna_expression"]["normal_median_log2tpm"] = report_evidence["normal_median_log2tpm"]

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
