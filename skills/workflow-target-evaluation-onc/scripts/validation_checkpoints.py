#!/usr/bin/env python3
"""
Validation Checkpoints for Target Evaluation Workflow
Version: 1.0.0

Three checkpoints to ensure consistency:
1. Input Completeness - Verify all evidence collected before scoring
2. Scoring Determinism - Verify scores are reproducible
3. Report Consistency - Verify report matches computed scores
"""

import yaml
import json
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import hashlib


@dataclass
class ValidationResult:
    """Result of a validation checkpoint."""
    checkpoint: str
    passed: bool
    timestamp: str
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowState:
    """Current state of the target evaluation workflow."""
    gene: str
    disease: str
    step1_complete: bool = False
    step2_complete: bool = False
    step3_complete: bool = False
    step4_complete: bool = False
    literature_evidence_path: Optional[Path] = None
    omics_evidence_path: Optional[Path] = None
    scholareval_path: Optional[Path] = None
    report_path: Optional[Path] = None


def _step2_artifact_path(base_path: Path, gene: str, disease: str, kind: str) -> Path:
    """Return the canonical Step 2 artifact path (ai-sci naming).

    kind: 'report' | 'idas' | 'suitability' | 'tcga_stats'
    Caller is responsible for checking existence.
    """
    skill = f"analysis-bulk-rna-{disease}"
    catalog = {
        "report": f"{gene}_{skill}_report.md",
        "idas": f"{gene}_{skill}_idas.yaml",
        "suitability": f"{gene}_{skill}_suitability.csv",
        "tcga_stats": f"{gene}_{skill}_tcga-stats.csv",
    }
    return base_path / catalog[kind]


class CheckpointValidator:
    """
    Validates target evaluation workflow at critical checkpoints.

    Checkpoints:
    1. Pre-Step3: Input completeness (literature + omics evidence ready)
    2. Step3: Scoring determinism (same inputs = same scores)
    3. Pre-Step4: Report consistency (scores in report match computed)
    """

    # Required fields from evidence extraction schema. Only fields the parser
    # actually populates are required; aspirational fields (like
    # safety.knockout_phenotype) live in OPTIONAL_LITERATURE_FIELDS until the
    # parser is extended to extract them.
    REQUIRED_LITERATURE_FIELDS = [
        "biological_validation.n_crispr_studies",
        "biological_validation.n_animal_models",
        "clinical_validation.highest_phase",
        "druggability.has_tool_compound",
    ]

    OPTIONAL_LITERATURE_FIELDS = [
        # Awaiting structured-extraction support in run_scholareval.py:
        "safety.knockout_phenotype",
    ]

    REQUIRED_OMICS_FIELDS = [
        "rna_expression.tumor_vs_adjacent_fc",
        "rna_expression.tumor_median_log2tpm",
        "rna_expression.normal_median_log2tpm"
    ]

    def __init__(self, output_dir: Path):
        """Initialize validator with output directory."""
        self.output_dir = Path(output_dir)
        self.validation_log: List[ValidationResult] = []

    def _get_nested_value(self, data: Dict, path: str) -> Any:
        """Get value from nested dict using dot notation."""
        keys = path.split(".")
        value = data
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return None
        return value

    def _file_exists_and_valid(self, path: Path, required_keys: List[str] = None) -> Tuple[bool, List[str]]:
        """Check if file exists and contains required keys."""
        errors = []
        if not path.exists():
            errors.append(f"File not found: {path}")
            return False, errors

        try:
            with open(path, 'r') as f:
                if path.suffix == '.yaml':
                    data = yaml.safe_load(f)
                elif path.suffix == '.json':
                    data = json.load(f)
                else:
                    # Assume markdown - just check it exists and has content
                    content = f.read()
                    if len(content) < 100:
                        errors.append(f"File appears empty or minimal: {path}")
                        return False, errors
                    return True, errors

            if required_keys:
                for key in required_keys:
                    if self._get_nested_value(data, key) is None:
                        errors.append(f"Missing required field: {key}")

            return len(errors) == 0, errors

        except Exception as e:
            errors.append(f"Error reading {path}: {str(e)}")
            return False, errors

    # =========================================================================
    # CHECKPOINT 1: INPUT COMPLETENESS
    # =========================================================================

    def validate_input_completeness(
        self,
        gene: str,
        disease: str,
        literature_yaml_path: Optional[Path] = None,
        risk_assessment_path: Optional[Path] = None,
        comprehensive_report_path: Optional[Path] = None,
        idas_yaml_path: Optional[Path] = None
    ) -> ValidationResult:
        """
        Checkpoint 1: Validate all inputs are complete before Step 3.

        Checks:
        - Literature evidence extracted (structured YAML or risk assessment MD)
        - Omics analysis complete (comprehensive report + iDAS YAML)
        - Required fields present in each
        """
        errors = []
        warnings = []
        details = {}

        timestamp = datetime.now().isoformat()

        # Check literature evidence
        literature_complete = False
        if literature_yaml_path and literature_yaml_path.exists():
            valid, errs = self._file_exists_and_valid(
                literature_yaml_path,
                self.REQUIRED_LITERATURE_FIELDS
            )
            literature_complete = valid
            errors.extend(errs)
            details["literature_yaml"] = str(literature_yaml_path)
        elif risk_assessment_path and risk_assessment_path.exists():
            # Fallback: check risk assessment markdown exists and has content
            valid, errs = self._file_exists_and_valid(risk_assessment_path)
            if valid:
                # Parse markdown to verify risk categories present
                with open(risk_assessment_path, 'r') as f:
                    content = f.read()
                required_sections = ["Biological", "Druggability", "Safety", "Clinical"]
                missing = [s for s in required_sections if s.lower() not in content.lower()]
                if missing:
                    warnings.append(f"Risk assessment missing sections: {missing}")
                else:
                    literature_complete = True
            errors.extend(errs)
            details["risk_assessment"] = str(risk_assessment_path)
        else:
            errors.append("No literature evidence found (need structured YAML or risk assessment MD)")

        # Check omics evidence
        omics_complete = False
        if comprehensive_report_path and comprehensive_report_path.exists():
            valid, errs = self._file_exists_and_valid(comprehensive_report_path)
            if valid:
                # Check for key sections in comprehensive report
                with open(comprehensive_report_path, 'r') as f:
                    content = f.read()
                required_sections = ["On-Target Toxicity", "iDAS", "Expression"]
                missing = [s for s in required_sections if s.lower() not in content.lower()]
                if missing:
                    warnings.append(f"Comprehensive report missing sections: {missing}")
                else:
                    omics_complete = True
            errors.extend(errs)
            details["comprehensive_report"] = str(comprehensive_report_path)

        if idas_yaml_path and idas_yaml_path.exists():
            valid, errs = self._file_exists_and_valid(idas_yaml_path)
            if not valid:
                errors.extend(errs)
            details["idas_yaml"] = str(idas_yaml_path)
        else:
            warnings.append("iDAS YAML not found - will extract from comprehensive report")

        # Overall status
        passed = literature_complete and omics_complete
        if not passed:
            if not literature_complete:
                errors.append("BLOCKED: Literature evidence incomplete - cannot proceed to Step 3")
            if not omics_complete:
                errors.append("BLOCKED: Omics evidence incomplete - cannot proceed to Step 3")

        result = ValidationResult(
            checkpoint="input_completeness",
            passed=passed,
            timestamp=timestamp,
            errors=errors,
            warnings=warnings,
            details={
                "gene": gene,
                "disease": disease,
                "literature_complete": literature_complete,
                "omics_complete": omics_complete,
                **details
            }
        )

        self.validation_log.append(result)
        return result

    # =========================================================================
    # CHECKPOINT 2: SCORING DETERMINISM
    # =========================================================================

    def validate_scoring_determinism(
        self,
        scholareval_yaml_path: Path,
        literature_evidence: Dict[str, Any],
        omics_evidence: Dict[str, Any]
    ) -> ValidationResult:
        """
        Checkpoint 2: Validate scoring is deterministic.

        Re-runs scoring engine with same inputs and verifies identical output.
        """
        from scoring_engine import ScoringEngine

        errors = []
        warnings = []
        details = {}
        timestamp = datetime.now().isoformat()

        # Load existing ScholarEval result
        if not scholareval_yaml_path.exists():
            errors.append(f"ScholarEval YAML not found: {scholareval_yaml_path}")
            return ValidationResult(
                checkpoint="scoring_determinism",
                passed=False,
                timestamp=timestamp,
                errors=errors,
                warnings=warnings,
                details=details
            )

        with open(scholareval_yaml_path, 'r') as f:
            existing_result = yaml.safe_load(f)

        # Re-run scoring
        engine = ScoringEngine()
        recomputed = engine.evaluate_target(
            gene=existing_result["gene"],
            disease=existing_result["disease"],
            literature_evidence=literature_evidence,
            omics_evidence=omics_evidence
        )

        # Compare results
        details["existing_score"] = existing_result["total_score"]
        details["recomputed_score"] = recomputed.total_score
        details["existing_hash"] = existing_result.get("input_hash", "N/A")
        details["recomputed_hash"] = recomputed.input_hash

        # Score tolerance (should be exactly equal for deterministic)
        score_match = abs(existing_result["total_score"] - recomputed.total_score) < 0.001

        if not score_match:
            errors.append(
                f"Score mismatch: existing={existing_result['total_score']}, "
                f"recomputed={recomputed.total_score}"
            )

        # Check hash match (stronger check)
        hash_match = existing_result.get("input_hash") == recomputed.input_hash
        if not hash_match:
            warnings.append("Input hash mismatch - inputs may have changed")
            details["hash_mismatch"] = True

        # Check recommendation match
        rec_match = existing_result["recommendation"] == recomputed.recommendation
        if not rec_match:
            errors.append(
                f"Recommendation mismatch: existing={existing_result['recommendation']}, "
                f"recomputed={recomputed.recommendation}"
            )

        passed = score_match and rec_match

        result = ValidationResult(
            checkpoint="scoring_determinism",
            passed=passed,
            timestamp=timestamp,
            errors=errors,
            warnings=warnings,
            details=details
        )

        self.validation_log.append(result)
        return result

    # =========================================================================
    # CHECKPOINT 3: REPORT CONSISTENCY
    # =========================================================================

    def validate_report_consistency(
        self,
        report_path: Path,
        scholareval_yaml_path: Path
    ) -> ValidationResult:
        """
        Checkpoint 3: Validate report matches computed scores.

        Parses the integrated report and verifies ScholarEval table matches
        the structured YAML output.
        """
        errors = []
        warnings = []
        details = {}
        timestamp = datetime.now().isoformat()

        # Load ScholarEval YAML
        if not scholareval_yaml_path.exists():
            errors.append(f"ScholarEval YAML not found: {scholareval_yaml_path}")
            return ValidationResult(
                checkpoint="report_consistency",
                passed=False,
                timestamp=timestamp,
                errors=errors,
                warnings=warnings,
                details=details
            )

        with open(scholareval_yaml_path, 'r') as f:
            scholareval = yaml.safe_load(f)

        # Load and parse report
        if not report_path.exists():
            errors.append(f"Report not found: {report_path}")
            return ValidationResult(
                checkpoint="report_consistency",
                passed=False,
                timestamp=timestamp,
                errors=errors,
                warnings=warnings,
                details=details
            )

        with open(report_path, 'r') as f:
            report_content = f.read()

        # Extract ScholarEval table from report
        table_scores = self._extract_scholareval_table(report_content)
        details["extracted_scores"] = table_scores

        if not table_scores:
            errors.append("Could not find ScholarEval table in report")
            return ValidationResult(
                checkpoint="report_consistency",
                passed=False,
                timestamp=timestamp,
                errors=errors,
                warnings=warnings,
                details=details
            )

        # Compare scores
        yaml_scores = scholareval.get("dimension_scores", {})
        mismatches = []

        for dim, yaml_data in yaml_scores.items():
            yaml_score = yaml_data.get("score", 0)
            # Normalize dimension name for comparison
            dim_normalized = dim.replace("_", " ").title()

            # Find matching dimension in extracted table
            table_score = None
            for extracted_dim, extracted_score in table_scores.items():
                if self._dimensions_match(dim, extracted_dim):
                    table_score = extracted_score
                    break

            if table_score is not None:
                if abs(yaml_score - table_score) > 0.1:
                    mismatches.append({
                        "dimension": dim,
                        "yaml_score": yaml_score,
                        "report_score": table_score
                    })

        if mismatches:
            errors.append(f"Score mismatches found: {mismatches}")
            details["mismatches"] = mismatches

        # Check total score
        yaml_total = scholareval.get("total_score", 0)
        report_total = table_scores.get("TOTAL", table_scores.get("total", None))

        if report_total is not None:
            if abs(yaml_total - report_total) > 0.1:
                errors.append(f"Total score mismatch: YAML={yaml_total}, Report={report_total}")
                details["total_mismatch"] = {
                    "yaml": yaml_total,
                    "report": report_total
                }

        # Check recommendation
        yaml_rec = scholareval.get("recommendation", "")
        report_rec = self._extract_recommendation(report_content)
        details["yaml_recommendation"] = yaml_rec
        details["report_recommendation"] = report_rec

        if report_rec and yaml_rec.upper() != report_rec.upper():
            warnings.append(f"Recommendation may differ: YAML={yaml_rec}, Report={report_rec}")

        passed = len(errors) == 0

        result = ValidationResult(
            checkpoint="report_consistency",
            passed=passed,
            timestamp=timestamp,
            errors=errors,
            warnings=warnings,
            details=details
        )

        self.validation_log.append(result)
        return result

    def _dimensions_match(self, dim1: str, dim2: str) -> bool:
        """Check if two dimension names refer to the same dimension."""
        # Normalize both
        d1 = dim1.lower().replace("_", " ").replace("-", " ")
        d2 = dim2.lower().replace("_", " ").replace("-", " ")
        return d1 == d2 or d1 in d2 or d2 in d1

    def _extract_scholareval_table(self, report_content: str) -> Dict[str, float]:
        """Extract ScholarEval scores from markdown table in report."""
        scores = {}

        # Find table with Score column
        # Pattern: | Dimension | Weight | Score | Rationale |
        # Score format: digit/5
        table_pattern = r'\|[^|]+\|[^|]+\|[^|]*(\d)/5[^|]*\|'
        dimension_pattern = r'\|\s*([^|]+?)\s*\|\s*[\d.]+\s*\|\s*(\d)/5\s*\|'

        for match in re.finditer(dimension_pattern, report_content):
            dimension = match.group(1).strip()
            score = int(match.group(2))

            # Skip header row
            if dimension.lower() not in ["dimension", "---"]:
                scores[dimension] = float(score)

        # Also look for TOTAL row
        total_pattern = r'\*\*TOTAL\*\*.*?\*\*(\d+\.?\d*)/5\.0\*\*'
        total_match = re.search(total_pattern, report_content)
        if total_match:
            scores["TOTAL"] = float(total_match.group(1))

        return scores

    def _extract_recommendation(self, report_content: str) -> Optional[str]:
        """Extract recommendation from report."""
        # Look for recommendation patterns
        patterns = [
            r'Recommendation[:\s]+\*\*([A-Z-]+)\*\*',
            r'\*\*Recommendation[:\s]+([A-Z-]+)\*\*',
            r'(?:GO-PRIORITY|GO-CONDITIONAL|GO|NO-GO|CONDITIONAL)'
        ]

        for pattern in patterns:
            match = re.search(pattern, report_content)
            if match:
                return match.group(1) if match.lastindex else match.group(0)

        return None

    # =========================================================================
    # WORKFLOW STATE MANAGEMENT
    # =========================================================================

    def check_workflow_ready_for_step(
        self,
        step: int,
        gene: str,
        disease: str
    ) -> ValidationResult:
        """
        Check if workflow is ready to proceed to a given step.

        Step dependencies:
        - Step 1 & 2: Can run in parallel, no dependencies
        - Step 3: Requires Step 1 AND Step 2 complete
        - Step 4: Requires Step 3 complete
        """
        errors = []
        warnings = []
        details = {"target_step": step, "gene": gene, "disease": disease}
        timestamp = datetime.now().isoformat()

        base_path = self.output_dir / gene

        if step == 3:
            # Check Step 1 (Literature) complete
            risk_assessment = base_path / f"{gene}_risk_assessment_{disease}.md"
            literature_yaml = base_path / f"{gene}_literature_evidence.yaml"

            step1_complete = risk_assessment.exists() or literature_yaml.exists()
            details["step1_complete"] = step1_complete
            details["step1_files"] = {
                "risk_assessment": str(risk_assessment) if risk_assessment.exists() else None,
                "literature_yaml": str(literature_yaml) if literature_yaml.exists() else None
            }

            if not step1_complete:
                errors.append("Step 1 (Literature) not complete - missing risk assessment or literature YAML")

            # Check Step 2 (Omics) complete (ai-sci naming).
            comprehensive_report = _step2_artifact_path(base_path, gene, disease, "report")
            idas_yaml = _step2_artifact_path(base_path, gene, disease, "idas")

            step2_complete = comprehensive_report.exists()
            details["step2_complete"] = step2_complete
            details["step2_files"] = {
                "comprehensive_report": str(comprehensive_report) if comprehensive_report.exists() else None,
                "idas_yaml": str(idas_yaml) if idas_yaml.exists() else None,
            }

            if not step2_complete:
                errors.append(
                    f"Step 2 (Omics) not complete - missing {comprehensive_report.name}"
                )

        elif step == 4:
            # Check Step 3 (ScholarEval) complete
            scholareval = base_path / f"{gene}_scholareval.yaml"

            step3_complete = scholareval.exists()
            details["step3_complete"] = step3_complete
            details["step3_files"] = {
                "scholareval": str(scholareval) if scholareval.exists() else None
            }

            if not step3_complete:
                errors.append("Step 3 (ScholarEval) not complete - missing scholareval YAML")

        passed = len(errors) == 0

        result = ValidationResult(
            checkpoint=f"ready_for_step_{step}",
            passed=passed,
            timestamp=timestamp,
            errors=errors,
            warnings=warnings,
            details=details
        )

        self.validation_log.append(result)
        return result

    # =========================================================================
    # EXPORT AND REPORTING
    # =========================================================================

    def export_validation_log(self, output_path: Path) -> None:
        """Export all validation results to JSON."""
        log_data = []
        for result in self.validation_log:
            log_data.append({
                "checkpoint": result.checkpoint,
                "passed": result.passed,
                "timestamp": result.timestamp,
                "errors": result.errors,
                "warnings": result.warnings,
                "details": result.details
            })

        with open(output_path, 'w') as f:
            json.dump(log_data, f, indent=2)

    def generate_validation_report(self) -> str:
        """Generate human-readable validation report."""
        lines = [
            "# Target Evaluation Validation Report",
            f"Generated: {datetime.now().isoformat()}",
            "",
            "## Checkpoint Summary",
            ""
        ]

        all_passed = True
        for result in self.validation_log:
            status = "PASS" if result.passed else "FAIL"
            all_passed = all_passed and result.passed
            lines.append(f"### {result.checkpoint}: **{status}**")
            lines.append(f"Timestamp: {result.timestamp}")
            lines.append("")

            if result.errors:
                lines.append("**Errors:**")
                for err in result.errors:
                    lines.append(f"- {err}")
                lines.append("")

            if result.warnings:
                lines.append("**Warnings:**")
                for warn in result.warnings:
                    lines.append(f"- {warn}")
                lines.append("")

            if result.details:
                lines.append("**Details:**")
                for key, value in result.details.items():
                    lines.append(f"- {key}: {value}")
                lines.append("")

        lines.insert(4, f"**Overall Status: {'ALL PASSED' if all_passed else 'VALIDATION FAILED'}**")

        return "\n".join(lines)


def main():
    """Example usage of validation checkpoints."""
    from pathlib import Path

    # Example validation run
    output_dir = Path("./crc_analysis_results/TNFRSF12A")
    validator = CheckpointValidator(output_dir.parent)

    print("Running validation checkpoints...\n")

    # Checkpoint 1: Input completeness (ai-sci naming).
    result1 = validator.validate_input_completeness(
        gene="TNFRSF12A",
        disease="crc",
        risk_assessment_path=output_dir / "TNFRSF12A_risk_assessment_crc.md",
        comprehensive_report_path=_step2_artifact_path(output_dir, "TNFRSF12A", "crc", "report"),
        idas_yaml_path=_step2_artifact_path(output_dir, "TNFRSF12A", "crc", "idas"),
    )
    print(f"Checkpoint 1 (Input Completeness): {'PASS' if result1.passed else 'FAIL'}")
    if result1.errors:
        for err in result1.errors:
            print(f"  ERROR: {err}")

    # Checkpoint: Ready for Step 3
    result_ready = validator.check_workflow_ready_for_step(
        step=3,
        gene="TNFRSF12A",
        disease="crc"
    )
    print(f"\nReady for Step 3: {'PASS' if result_ready.passed else 'FAIL'}")
    if not result_ready.passed:
        for err in result_ready.errors:
            print(f"  BLOCKED: {err}")

    # Generate report
    print("\n" + "=" * 60)
    print(validator.generate_validation_report())


if __name__ == "__main__":
    main()
