#!/usr/bin/env python3
"""
Workflow Validation Script
Verifies all required outputs exist before marking workflow complete.

Usage:
    python validate_workflow.py --gene CDCP1 --disease nsclc --output-dir /path/to/output
"""

import argparse
import sys
from pathlib import Path


def validate_workflow(gene: str, disease: str, output_dir: Path) -> bool:
    """
    Validate that all required workflow outputs exist.

    Returns True if all files present, False otherwise.
    """
    required_files = {
        "Step 1": [
            f"{gene}_risk_assessment_{disease}.md",
        ],
        "Step 2": [
            f"{gene}_comprehensive_report.md",
            f"{gene}_idas_assessment.yaml",
            f"{gene}_subgroup_suitability.csv",
            f"{gene}_tcga_statistics.csv",
        ],
        "Step 3": [
            f"{gene}_scholareval.yaml",
            f"{gene}_audit_trail.json",
        ],
        "Step 4": [
            f"{gene}_integrated_target_report.md",
        ],
    }

    print(f"=== Workflow Validation ===")
    print(f"Gene: {gene}")
    print(f"Disease: {disease}")
    print(f"Output Dir: {output_dir}")
    print()

    all_present = True
    missing_by_step = {}

    for step, files in required_files.items():
        missing = []
        for f in files:
            filepath = output_dir / f
            if not filepath.exists():
                missing.append(f)
                all_present = False

        if missing:
            missing_by_step[step] = missing
            print(f"{step}: INCOMPLETE")
            for f in missing:
                print(f"  MISSING: {f}")
        else:
            print(f"{step}: OK ({len(files)} files)")

    print()

    if all_present:
        print("VALIDATION PASSED: All required outputs present.")
        print("Workflow can be marked as complete.")
        return True
    else:
        print("VALIDATION FAILED: Missing required outputs.")
        print("DO NOT mark workflow as complete until all files are generated.")
        print()
        print("Missing files by step:")
        for step, files in missing_by_step.items():
            print(f"  {step}:")
            for f in files:
                print(f"    - {f}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Validate target evaluation workflow outputs"
    )
    parser.add_argument("--gene", required=True, help="Gene symbol")
    parser.add_argument("--disease", required=True, choices=["crc", "nsclc"], help="Disease")
    parser.add_argument("--output-dir", required=True, help="Output directory")

    args = parser.parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()

    success = validate_workflow(args.gene, args.disease, output_dir)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
