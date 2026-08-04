#!/usr/bin/env python3
"""
Deterministic Scoring Engine for Target Evaluation
Version: 1.0.0

NO LLM interpretation in scoring - pure rule-based computation.
LLM extracts FACTS → Scoring engine applies RULES → Output scores with audit trail.
"""

import yaml
import json
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import hashlib


@dataclass
class ScoringResult:
    """Result from a single dimension scoring."""
    dimension: str
    score: float  # 1-5 scale
    risk_level: str  # LOW, MEDIUM, HIGH
    evidence_weight: float
    rationale: str
    source_data: Dict[str, Any]
    rule_applied: str


@dataclass
class AuditEntry:
    """Audit trail entry for traceability."""
    timestamp: str
    dimension: str
    input_data: Dict[str, Any]
    rule_path: str
    calculated_value: float
    output_score: float
    checksum: str


@dataclass
class ScholarEvalResult:
    """Complete ScholarEval scoring result with audit trail."""
    gene: str
    disease: str
    timestamp: str
    dimension_scores: Dict[str, ScoringResult]
    total_score: float
    assessment: str
    recommendation: str
    high_risk_count: int
    audit_trail: List[AuditEntry]
    input_hash: str  # Hash of all inputs for reproducibility


class ScoringEngine:
    """
    Deterministic scoring engine for target evaluation.

    Applies rules from scoring_rules.yaml to structured evidence
    without any LLM interpretation in the scoring process.
    """

    def __init__(self, rules_path: Optional[Path] = None):
        """Initialize with scoring rules."""
        if rules_path is None:
            rules_path = Path(__file__).parent.parent / "configs" / "scoring_rules.yaml"

        with open(rules_path, 'r') as f:
            self.rules = yaml.safe_load(f)

        self.audit_trail: List[AuditEntry] = []

    def _create_audit_entry(
        self,
        dimension: str,
        input_data: Dict[str, Any],
        rule_path: str,
        calculated_value: float,
        output_score: float
    ) -> AuditEntry:
        """Create an audit trail entry."""
        data_str = json.dumps(input_data, sort_keys=True)
        checksum = hashlib.md5(data_str.encode()).hexdigest()[:8]

        return AuditEntry(
            timestamp=datetime.now().isoformat(),
            dimension=dimension,
            input_data=input_data,
            rule_path=rule_path,
            calculated_value=calculated_value,
            output_score=output_score,
            checksum=checksum
        )

    def _apply_threshold_score(
        self,
        value: float,
        thresholds: List[Dict],
        value_key: str = "min_weight"
    ) -> Tuple[float, str]:
        """Apply threshold-based scoring rules."""
        for threshold in thresholds:
            min_val = threshold.get(value_key, threshold.get("min_fc", threshold.get("min_phase", 0)))
            if value >= min_val:
                return threshold["score"], f"{value_key}>={min_val}"
        return 1.0, "default"

    def _determine_risk_level(
        self,
        value: float,
        risk_thresholds: Dict
    ) -> str:
        """Determine risk level based on thresholds."""
        if "LOW" in risk_thresholds:
            low = risk_thresholds["LOW"]
            if "min_weight" in low and value >= low["min_weight"]:
                return "LOW"
            if "min_phase" in low and value >= low["min_phase"]:
                return "LOW"
            if "min_fc" in low and value >= low["min_fc"]:
                return "LOW"

        if "MEDIUM" in risk_thresholds:
            med = risk_thresholds["MEDIUM"]
            min_val = med.get("min_weight", med.get("min_phase", med.get("min_fc", 0)))
            max_val = med.get("max_weight", med.get("max_phase", med.get("max_fc", float('inf'))))
            if min_val <= value <= max_val:
                return "MEDIUM"

        return "HIGH"

    # =========================================================================
    # LITERATURE EVIDENCE SCORING
    # =========================================================================

    def score_biological_validation(
        self,
        n_crispr: int = 0,
        n_rnai: int = 0,
        n_animal: int = 0,
        n_genetic: int = 0,
        n_overexpression: int = 0
    ) -> ScoringResult:
        """Score biological validation evidence."""
        rules = self.rules["literature_scoring"]["biological_validation"]
        weights = rules["evidence_weights"]

        # Calculate total evidence weight
        total_weight = (
            n_crispr * weights["crispr_knockout"] +
            n_rnai * weights["rnai_knockdown"] +
            n_animal * weights["animal_model_efficacy"] +
            n_genetic * weights["human_genetic_association"] +
            n_overexpression * weights["overexpression_study"]
        )

        # Apply score mapping
        score, rule = self._apply_threshold_score(
            total_weight,
            rules["score_mapping"],
            "min_weight"
        )

        # Determine risk level
        risk = self._determine_risk_level(total_weight, rules["risk_thresholds"])

        input_data = {
            "n_crispr": n_crispr,
            "n_rnai": n_rnai,
            "n_animal": n_animal,
            "n_genetic": n_genetic,
            "n_overexpression": n_overexpression
        }

        # Create audit entry
        self.audit_trail.append(self._create_audit_entry(
            dimension="biological_validation",
            input_data=input_data,
            rule_path="literature_scoring.biological_validation",
            calculated_value=total_weight,
            output_score=score
        ))

        return ScoringResult(
            dimension="biological_validation",
            score=score,
            risk_level=risk,
            evidence_weight=total_weight,
            rationale=f"Total evidence weight: {total_weight} (CRISPR:{n_crispr}, RNAi:{n_rnai}, Animal:{n_animal}, Genetic:{n_genetic})",
            source_data=input_data,
            rule_applied=rule
        )

    def score_clinical_validation(
        self,
        highest_phase: int = 0,
        n_trials: int = 0,
        indication_specific: bool = False
    ) -> ScoringResult:
        """Score clinical validation evidence."""
        rules = self.rules["literature_scoring"]["clinical_validation"]

        # Apply score mapping based on phase
        score, rule = self._apply_threshold_score(
            highest_phase,
            rules["score_mapping"],
            "min_phase"
        )

        # Determine risk level
        risk = self._determine_risk_level(highest_phase, rules["risk_thresholds"])

        input_data = {
            "highest_phase": highest_phase,
            "n_trials": n_trials,
            "indication_specific": indication_specific
        }

        self.audit_trail.append(self._create_audit_entry(
            dimension="clinical_validation",
            input_data=input_data,
            rule_path="literature_scoring.clinical_validation",
            calculated_value=highest_phase,
            output_score=score
        ))

        return ScoringResult(
            dimension="clinical_validation",
            score=score,
            risk_level=risk,
            evidence_weight=highest_phase,
            rationale=f"Highest phase: {highest_phase}, Trials: {n_trials}, Indication-specific: {indication_specific}",
            source_data=input_data,
            rule_applied=rule
        )

    def score_druggability(
        self,
        has_approved_drug: bool = False,
        has_clinical_compound: bool = False,
        has_tool_compound: bool = False,
        best_ic50_nm: Optional[float] = None,
        has_structure: bool = False,
        has_binding_pocket: bool = False
    ) -> ScoringResult:
        """Score druggability evidence."""
        rules = self.rules["literature_scoring"]["druggability"]
        weights = rules["evidence_weights"]

        # Calculate total weight.
        #
        # DESIGN NOTE (intentional mixed model — do NOT "fix" to pure-additive):
        # The compound tier is a SUBSUMPTION ladder (elif): an approved drug
        # strictly dominates a clinical compound, which dominates a tool
        # compound — they are levels of the same evidence, so we credit only the
        # highest and never sum across tiers. Structure and binding-pocket are
        # INDEPENDENT structural signals, so they add (if/if). This deliberately
        # differs from score_biological_validation, which is fully additive
        # because CRISPR/RNAi/animal/genetic are independent corroborating lines
        # of evidence, not tiers of one thing.
        total_weight = 0
        if has_approved_drug:
            total_weight += weights["approved_drug_exists"]
        elif has_clinical_compound:
            total_weight += weights["clinical_compound_exists"]
        elif has_tool_compound:
            if best_ic50_nm is not None and best_ic50_nm < 100:
                total_weight += weights["tool_compound_ic50_lt_100nm"]
            elif best_ic50_nm is not None and best_ic50_nm < 1000:
                total_weight += weights["tool_compound_ic50_lt_1um"]

        if has_binding_pocket:
            total_weight += weights["binding_pocket_identified"]
        if has_structure:
            total_weight += weights["structure_available"]

        # Apply score mapping
        score, rule = self._apply_threshold_score(
            total_weight,
            rules["score_mapping"],
            "min_weight"
        )

        risk = self._determine_risk_level(total_weight, rules["risk_thresholds"])

        input_data = {
            "has_approved_drug": has_approved_drug,
            "has_clinical_compound": has_clinical_compound,
            "has_tool_compound": has_tool_compound,
            "best_ic50_nm": best_ic50_nm,
            "has_structure": has_structure,
            "has_binding_pocket": has_binding_pocket
        }

        self.audit_trail.append(self._create_audit_entry(
            dimension="druggability",
            input_data=input_data,
            rule_path="literature_scoring.druggability",
            calculated_value=total_weight,
            output_score=score
        ))

        return ScoringResult(
            dimension="druggability",
            score=score,
            risk_level=risk,
            evidence_weight=total_weight,
            rationale=f"Druggability weight: {total_weight}",
            source_data=input_data,
            rule_applied=rule
        )

    # =========================================================================
    # OMICS EVIDENCE SCORING
    # =========================================================================

    def score_differential_expression(
        self,
        tumor_vs_adjacent_fc: float,
        tumor_median_log2tpm: Optional[float] = None,
        normal_median_log2tpm: Optional[float] = None
    ) -> ScoringResult:
        """Score differential expression from omics data."""
        rules = self.rules["omics_scoring"]["differential_expression"]

        # Apply threshold scoring
        score = 1.0
        risk = "HIGH"
        rule = "default"

        for threshold in rules["thresholds"]:
            if tumor_vs_adjacent_fc >= threshold["min_fc"]:
                score = threshold["score"]
                risk = threshold["risk"]
                rule = threshold["description"]
                break

        input_data = {
            "tumor_vs_adjacent_fc": tumor_vs_adjacent_fc,
            "tumor_median_log2tpm": tumor_median_log2tpm,
            "normal_median_log2tpm": normal_median_log2tpm
        }

        self.audit_trail.append(self._create_audit_entry(
            dimension="differential_expression",
            input_data=input_data,
            rule_path="omics_scoring.differential_expression",
            calculated_value=tumor_vs_adjacent_fc,
            output_score=score
        ))

        return ScoringResult(
            dimension="differential_expression",
            score=score,
            risk_level=risk,
            evidence_weight=tumor_vs_adjacent_fc,
            rationale=f"Tumor vs Adjacent FC: {tumor_vs_adjacent_fc:.2f}x - {rule}",
            source_data=input_data,
            rule_applied=rule
        )

    def score_safety_profile(
        self,
        tumor_vs_adjacent_fc: float,
        normal_expr_log2tpm: float
    ) -> ScoringResult:
        """Score safety profile based on expression patterns."""
        rules = self.rules["omics_scoring"]["safety_profile"]

        # Evaluate conditions — floor values (YAML's lowest tier) so a
        # parse-miss doesn't silently return a mid-range score.
        score = 1
        risk = "HIGH"
        rule = "default"

        for threshold in rules["thresholds"]:
            condition = threshold["condition"]
            # Parse and evaluate condition
            if self._evaluate_safety_condition(condition, tumor_vs_adjacent_fc, normal_expr_log2tpm):
                score = threshold["score"]
                risk = threshold["risk"]
                rule = threshold["description"]
                break

        input_data = {
            "tumor_vs_adjacent_fc": tumor_vs_adjacent_fc,
            "normal_expr_log2tpm": normal_expr_log2tpm
        }

        self.audit_trail.append(self._create_audit_entry(
            dimension="safety_profile",
            input_data=input_data,
            rule_path="omics_scoring.safety_profile",
            calculated_value=tumor_vs_adjacent_fc,
            output_score=score
        ))

        return ScoringResult(
            dimension="safety_profile",
            score=score,
            risk_level=risk,
            evidence_weight=tumor_vs_adjacent_fc,
            rationale=f"FC: {tumor_vs_adjacent_fc:.2f}x, Normal: {normal_expr_log2tpm:.2f} log2TPM - {rule}",
            source_data=input_data,
            rule_applied=rule
        )

    def _evaluate_safety_condition(
        self,
        condition: str,
        fc: float,
        normal_expr: float
    ) -> bool:
        """Evaluate safety condition string."""
        # Replace variables
        cond = condition.replace("fc", str(fc)).replace("normal_expr", str(normal_expr))

        # Handle AND/OR
        if " AND " in cond:
            parts = cond.split(" AND ")
            return all(self._eval_simple_condition(p.strip()) for p in parts)
        elif " OR " in cond:
            parts = cond.split(" OR ")
            return any(self._eval_simple_condition(p.strip()) for p in parts)
        else:
            return self._eval_simple_condition(cond)

    _COMPARATORS = {
        ">=": (lambda a, b: a >= b),
        "<=": (lambda a, b: a <= b),
        "==": (lambda a, b: a == b),
        "!=": (lambda a, b: a != b),
        ">":  (lambda a, b: a > b),
        "<":  (lambda a, b: a < b),
    }

    def _eval_simple_condition(self, cond: str) -> bool:
        """Evaluate a simple comparison like '2.0 >= 2.0' safely.

        Replaces a previous `eval(cond)` that could execute arbitrary Python
        if a malformed condition string ever entered scoring_rules.yaml.
        Supports the comparators >=, <=, ==, !=, >, < with numeric operands.
        Returns False on any parse failure (preserves previous bare-except
        behavior, but only swallows real grammar mismatches).
        """
        if not cond or not isinstance(cond, str):
            return False
        # Match the longest comparator first (>= before >, etc.).
        for op in ("<=", ">=", "==", "!=", "<", ">"):
            if op in cond:
                left, _, right = cond.partition(op)
                try:
                    a = float(left.strip())
                    b = float(right.strip())
                except ValueError:
                    return False
                return self._COMPARATORS[op](a, b)
        return False

    def score_idas_alignment(
        self,
        expression_log2tpm: float,
        whitespace_name: str = ""
    ) -> ScoringResult:
        """Score iDAS whitespace alignment."""
        rules = self.rules["omics_scoring"]["idas_alignment"]

        score = 1.0
        alignment = "Weak"

        for threshold in rules["thresholds"]:
            if expression_log2tpm >= threshold["min_expr"]:
                score = threshold["score"]
                alignment = threshold["alignment"]
                break

        risk = "LOW" if alignment == "Strong" else ("MEDIUM" if alignment == "Moderate" else "HIGH")

        input_data = {
            "expression_log2tpm": expression_log2tpm,
            "whitespace_name": whitespace_name
        }

        self.audit_trail.append(self._create_audit_entry(
            dimension="idas_alignment",
            input_data=input_data,
            rule_path="omics_scoring.idas_alignment",
            calculated_value=expression_log2tpm,
            output_score=score
        ))

        return ScoringResult(
            dimension="idas_alignment",
            score=score,
            risk_level=risk,
            evidence_weight=expression_log2tpm,
            rationale=f"{whitespace_name}: {expression_log2tpm:.2f} log2TPM - {alignment} alignment",
            source_data=input_data,
            rule_applied=f"min_expr>={expression_log2tpm}"
        )

    # =========================================================================
    # SCHOLAREVAL COMPUTATION
    # =========================================================================

    def compute_scholareval(
        self,
        gene: str,
        disease: str,
        dimension_scores: Dict[str, ScoringResult]
    ) -> ScholarEvalResult:
        """
        Compute weighted ScholarEval total score.

        Args:
            gene: Gene symbol
            disease: Disease indication (crc, nsclc)
            dimension_scores: Dictionary of dimension name -> ScoringResult

        Returns:
            ScholarEvalResult with total score, assessment, and recommendation
        """
        weights = self.rules["scholareval"]["dimensions"]
        thresholds = self.rules["scholareval"]["assessment_thresholds"]

        # Calculate weighted total
        total_score = 0.0
        for dim_name, weight_info in weights.items():
            if dim_name in dimension_scores:
                weighted = dimension_scores[dim_name].score * weight_info["weight"]
                total_score += weighted

        # Determine assessment label from score thresholds
        assessment = "Poor"
        for threshold in thresholds:
            if total_score >= threshold["min_score"]:
                assessment = threshold["label"]
                break

        # Count high-risk categories
        high_risk_count = sum(
            1 for s in dimension_scores.values()
            if s.risk_level == "HIGH"
        )

        # Recommendation comes solely from _apply_recommendation_rules, which
        # supersedes the threshold table's recommendation field. The threshold
        # table is authoritative only for the assessment label.
        recommendation = self._apply_recommendation_rules(
            total_score,
            high_risk_count,
            dimension_scores
        )

        # Create input hash for reproducibility
        input_hash = self._compute_input_hash(dimension_scores)

        return ScholarEvalResult(
            gene=gene,
            disease=disease,
            timestamp=datetime.now().isoformat(),
            dimension_scores=dimension_scores,
            total_score=round(total_score, 2),
            assessment=assessment,
            recommendation=recommendation,
            high_risk_count=high_risk_count,
            audit_trail=self.audit_trail.copy(),
            input_hash=input_hash
        )

    def _apply_recommendation_rules(
        self,
        total_score: float,
        high_risk_count: int,
        dimension_scores: Dict[str, ScoringResult]
    ) -> str:
        """Apply rule-based recommendation logic."""
        rules = self.rules["recommendation_rules"]

        # Get safety and differential expression scores
        safety_risk = dimension_scores.get("safety_profile", ScoringResult(
            dimension="safety_profile", score=1, risk_level="HIGH",
            evidence_weight=0, rationale="", source_data={}, rule_applied=""
        )).risk_level

        diff_expr_score = dimension_scores.get("differential_expression", ScoringResult(
            dimension="differential_expression", score=1, risk_level="HIGH",
            evidence_weight=0, rationale="", source_data={}, rule_applied=""
        )).score

        # Check NO_GO first (most restrictive)
        if total_score < 3.0:
            return "NO-GO"
        if safety_risk == "HIGH" and diff_expr_score < 3:
            return "NO-GO"
        if high_risk_count >= 3:
            return "NO-GO"

        # Check GO_PRIORITY
        if total_score >= 4.5 and high_risk_count == 0 and diff_expr_score >= 4:
            return "GO-PRIORITY"

        # Check GO
        if total_score >= 4.0 and high_risk_count <= 1 and safety_risk != "HIGH":
            return "GO"

        # Check GO_CONDITIONAL
        if total_score >= 3.5 and high_risk_count <= 1 and safety_risk != "HIGH":
            return "GO-CONDITIONAL"

        # Check CONDITIONAL
        if total_score >= 3.0 and high_risk_count <= 2:
            return "CONDITIONAL"

        return "NO-GO"

    def _compute_input_hash(self, dimension_scores: Dict[str, ScoringResult]) -> str:
        """Compute hash of all inputs for reproducibility verification."""
        data = {
            dim: {
                "score": s.score,
                "source_data": s.source_data
            }
            for dim, s in dimension_scores.items()
        }
        data_str = json.dumps(data, sort_keys=True)
        return hashlib.sha256(data_str.encode()).hexdigest()[:16]

    # =========================================================================
    # CONVENIENCE METHOD: FULL EVALUATION
    # =========================================================================

    def evaluate_target(
        self,
        gene: str,
        disease: str,
        literature_evidence: Dict[str, Any],
        omics_evidence: Dict[str, Any]
    ) -> ScholarEvalResult:
        """
        Run full target evaluation with all evidence.

        Args:
            gene: Gene symbol
            disease: Disease indication
            literature_evidence: Structured literature evidence (from extraction schema)
            omics_evidence: Structured omics evidence (from bulk RNA analysis)

        Returns:
            Complete ScholarEvalResult
        """
        self.audit_trail = []  # Reset audit trail

        dimension_scores = {}

        # Score literature dimensions
        if "biological_validation" in literature_evidence:
            bv = literature_evidence["biological_validation"]
            dimension_scores["genetic_validation"] = self.score_biological_validation(
                n_crispr=bv.get("n_crispr_studies", 0),
                n_rnai=bv.get("n_rnai_studies", 0),
                n_animal=bv.get("n_animal_models", 0),
                n_genetic=bv.get("n_human_genetic", 0),
                n_overexpression=bv.get("n_overexpression", 0)
            )

        if "clinical_validation" in literature_evidence:
            cv = literature_evidence["clinical_validation"]
            dimension_scores["clinical_validation"] = self.score_clinical_validation(
                highest_phase=cv.get("highest_phase", 0),
                n_trials=cv.get("n_trials", 0),
                indication_specific=cv.get("indication_specific", False)
            )

        if "druggability" in literature_evidence:
            dr = literature_evidence["druggability"]
            dimension_scores["druggability"] = self.score_druggability(
                has_approved_drug=dr.get("has_approved_drug", False),
                has_clinical_compound=dr.get("has_clinical_compound", False),
                has_tool_compound=dr.get("has_tool_compound", False),
                best_ic50_nm=dr.get("best_ic50_nm"),
                has_structure=dr.get("has_structure", False),
                has_binding_pocket=dr.get("has_binding_pocket", False)
            )

        # Score omics dimensions
        if "rna_expression" in omics_evidence:
            rna = omics_evidence["rna_expression"]

            dimension_scores["differential_expression"] = self.score_differential_expression(
                tumor_vs_adjacent_fc=rna.get("tumor_vs_adjacent_fc", 1.0),
                tumor_median_log2tpm=rna.get("tumor_median_log2tpm"),
                normal_median_log2tpm=rna.get("normal_median_log2tpm")
            )

            dimension_scores["safety_profile"] = self.score_safety_profile(
                tumor_vs_adjacent_fc=rna.get("tumor_vs_adjacent_fc", 1.0),
                normal_expr_log2tpm=rna.get("normal_median_log2tpm", 5.0)
            )

        # Score pathway relevance, disease association, and biomarker potential
        # from extracted evidence. If a parser did not provide structured
        # evidence, fall back to a 3.0 placeholder (was previously hardcoded).
        if "pathway_relevance" in literature_evidence:
            dimension_scores["pathway_relevance"] = self._score_pathway_relevance(
                literature_evidence["pathway_relevance"]
            )

        if "disease_association" in literature_evidence:
            dimension_scores["disease_association"] = self._score_disease_association(
                literature_evidence["disease_association"]
            )

        if "biomarker_potential" in literature_evidence:
            dimension_scores["biomarker_potential"] = self._score_biomarker_potential(
                literature_evidence["biomarker_potential"]
            )

        # Fallback: any dimension still missing gets a neutral 3.0 placeholder.
        placeholder_dims = ["pathway_relevance", "disease_association", "biomarker_potential"]
        for dim in placeholder_dims:
            if dim not in dimension_scores:
                dimension_scores[dim] = ScoringResult(
                    dimension=dim,
                    score=3.0,  # Neutral score
                    risk_level="MEDIUM",
                    evidence_weight=0,
                    rationale="Placeholder - no structured evidence extracted",
                    source_data={},
                    rule_applied="placeholder"
                )

        return self.compute_scholareval(gene, disease, dimension_scores)

    def _score_pathway_relevance(self, evidence: Dict[str, Any]) -> "ScoringResult":
        """Score pathway relevance from structured parser output."""
        score = int(evidence.get("pathway_score", 3))
        count = int(evidence.get("pathway_evidence_count", 0))
        risk = "LOW" if score >= 4 else "MEDIUM" if score >= 3 else "HIGH"
        self.audit_trail.append(self._create_audit_entry(
            dimension="pathway_relevance",
            input_data=evidence,
            rule_path="literature_scoring.pathway_relevance",
            calculated_value=count,
            output_score=score,
        ))
        return ScoringResult(
            dimension="pathway_relevance",
            score=score,
            risk_level=risk,
            evidence_weight=count,
            rationale=f"{count} pathway/mechanism term categories detected",
            source_data=evidence,
            rule_applied="pathway_term_count",
        )

    def _score_disease_association(self, evidence: Dict[str, Any]) -> "ScoringResult":
        """Score disease association from combined literature + omics evidence."""
        score = int(evidence.get("disease_assoc_score", 3))
        lit = evidence.get("literature_signal", 0)
        omics = evidence.get("omics_signal")
        risk = "LOW" if score >= 4 else "MEDIUM" if score >= 3 else "HIGH"
        rationale = (
            f"Literature signal: {lit}/5"
            + (f", omics avg suitability: {omics:.1f}/5" if omics is not None else ", omics: n/a")
        )
        self.audit_trail.append(self._create_audit_entry(
            dimension="disease_association",
            input_data=evidence,
            rule_path="literature_scoring.disease_association",
            calculated_value=score,
            output_score=score,
        ))
        return ScoringResult(
            dimension="disease_association",
            score=score,
            risk_level=risk,
            evidence_weight=lit,
            rationale=rationale,
            source_data=evidence,
            rule_applied="literature+omics_average",
        )

    def _score_biomarker_potential(self, evidence: Dict[str, Any]) -> "ScoringResult":
        """Score biomarker potential from clinical-grade availability + detection rate."""
        score = int(evidence.get("biomarker_score", 3))
        has_cdx = evidence.get("has_clinical_grade_biomarker", False)
        det = evidence.get("detection_rate_pct")
        risk = "LOW" if score >= 4 else "MEDIUM" if score >= 3 else "HIGH"
        rationale = (
            f"Clinical-grade biomarker: {has_cdx}"
            + (f", detection rate: {det:.0f}%" if det is not None else ", detection rate: n/a")
        )
        self.audit_trail.append(self._create_audit_entry(
            dimension="biomarker_potential",
            input_data=evidence,
            rule_path="literature_scoring.biomarker_potential",
            calculated_value=score,
            output_score=score,
        ))
        return ScoringResult(
            dimension="biomarker_potential",
            score=score,
            risk_level=risk,
            evidence_weight=int(has_cdx) + int(det is not None),
            rationale=rationale,
            source_data=evidence,
            rule_applied="biomarker_grade_x_detection_rate",
        )

    def export_audit_trail(self, output_path: Path) -> None:
        """Export audit trail to JSON file."""
        audit_data = [asdict(entry) for entry in self.audit_trail]
        with open(output_path, 'w') as f:
            json.dump(audit_data, f, indent=2)

    def export_result(self, result: ScholarEvalResult, output_path: Path) -> None:
        """Export ScholarEvalResult to YAML file."""
        output = {
            "gene": result.gene,
            "disease": result.disease,
            "timestamp": result.timestamp,
            "total_score": result.total_score,
            "assessment": result.assessment,
            "recommendation": result.recommendation,
            "high_risk_count": result.high_risk_count,
            "input_hash": result.input_hash,
            "dimension_scores": {
                dim: {
                    "score": s.score,
                    "risk_level": s.risk_level,
                    "rationale": s.rationale,
                    "rule_applied": s.rule_applied
                }
                for dim, s in result.dimension_scores.items()
            }
        }
        with open(output_path, 'w') as f:
            yaml.dump(output, f, default_flow_style=False, sort_keys=False)


def main():
    """Example usage of the scoring engine."""
    engine = ScoringEngine()

    # Example: TNFRSF12A in CRC
    literature_evidence = {
        "biological_validation": {
            "n_crispr_studies": 3,
            "n_rnai_studies": 5,
            "n_animal_models": 2,
            "n_human_genetic": 1,
            "n_overexpression": 2
        },
        "clinical_validation": {
            "highest_phase": 1,
            "n_trials": 3,
            "indication_specific": False
        },
        "druggability": {
            "has_approved_drug": False,
            "has_clinical_compound": True,
            "has_tool_compound": True,
            "best_ic50_nm": 50,
            "has_structure": True,
            "has_binding_pocket": True
        }
    }

    omics_evidence = {
        "rna_expression": {
            "tumor_vs_adjacent_fc": 7.8,
            "tumor_vs_adjacent_log2fc": 2.96,
            "tumor_median_log2tpm": 5.2,
            "normal_median_log2tpm": 2.3
        }
    }

    result = engine.evaluate_target(
        gene="TNFRSF12A",
        disease="CRC",
        literature_evidence=literature_evidence,
        omics_evidence=omics_evidence
    )

    print(f"\n{'='*60}")
    print(f"ScholarEval Result: {result.gene} in {result.disease}")
    print(f"{'='*60}")
    print(f"Total Score: {result.total_score}/5.0")
    print(f"Assessment: {result.assessment}")
    print(f"Recommendation: {result.recommendation}")
    print(f"High Risk Categories: {result.high_risk_count}")
    print(f"Input Hash: {result.input_hash}")
    print(f"\nDimension Scores:")
    for dim, score in result.dimension_scores.items():
        print(f"  {dim}: {score.score}/5 ({score.risk_level}) - {score.rationale}")

    # Export results
    output_dir = Path("./validation_output")
    output_dir.mkdir(exist_ok=True)

    engine.export_result(result, output_dir / f"{result.gene}_scholareval.yaml")
    engine.export_audit_trail(output_dir / f"{result.gene}_audit_trail.json")
    print(f"\nResults exported to {output_dir}/")


if __name__ == "__main__":
    main()
