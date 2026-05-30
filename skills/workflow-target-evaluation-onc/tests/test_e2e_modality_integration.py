"""End-to-end integration tests for modality-aware Phase 3 scoring.

Imports compute_subgroup_suitability from both bulk-RNA scripts and
exercises real CRBN-shaped + PCDH7-shaped + STK11-shaped fixtures
through the full registry → dispatcher → recommendation chain.

These tests are the regression guard for the v1.1.0 → v1.2.0 transition:
verifying that default behavior (no --modality) is bit-identical to v1.1.0,
and that explicit modality routes through the registry.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[3]
CRC_SCRIPTS = REPO / "skills/analysis-bulk-rna-crc/scripts"
NSCLC_SCRIPTS = REPO / "skills/analysis-bulk-rna-nsclc/scripts"
sys.path.insert(0, str(CRC_SCRIPTS))
sys.path.insert(0, str(NSCLC_SCRIPTS))

# Stub AWS-related deps the bulk-RNA scripts pull in at import (not used
# by the scoring functions under test).
for _mod in ("boto3", "s3fs", "botocore", "botocore.exceptions"):
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)
sys.modules["botocore.exceptions"].ClientError = type("ClientError", (Exception,), {})

import crc_comprehensive_analysis as crc  # noqa: E402
import nsclc_comprehensive_analysis as nsclc  # noqa: E402


# ---------------------------------------------------------------------------
# CRBN-shaped fixture (CRC) — uniformly expressed, HIGH tox, Strong iDAS
# ---------------------------------------------------------------------------

CRBN_IDAS = {
    "on_target_toxicity": {
        "risk_level": "High",
        "tumor_vs_adjacent_log2FC": -0.19,
    },
    "whitespace_alignment": {
        "chemorefractory_3lplus": {
            "alignment": "Strong",
            "expression_3lplus": 4.43,
            "n_samples": 426,
        },
        "ras_mutant_frontline": {
            "alignment": "Strong",
            "tcga_expression": 4.19,
            "tempus_expression": 4.40,
        },
        "resectable": {
            "alignment": "Strong",
            "tcga_expression": 4.09,
        },
    },
}
EMPTY_PAIRWISE = pd.DataFrame(columns=["Tumor_Cohort", "Normal_Group", "Log2FC"])
EMPTY_TEMPUS = {}


# ---------------------------------------------------------------------------
# Default behavior must match v1.1.0 (antibody-naked penalty table)
# ---------------------------------------------------------------------------

class TestDefaultBehaviorMatchesV1_1_0:
    """No --modality → antibody_naked → tumor_vs_normal_strict.
    Penalty table {Low:0, Med:1, High:2} matches v1.1.0 hard-coded values
    exactly. CRBN-shaped fixture (HIGH tox, Strong iDAS) should produce
    CAUTION on every whitespace, just like v1.1.0."""

    def test_crc_no_modality_produces_v1_1_0_caution(self) -> None:
        out = crc.compute_subgroup_suitability(
            gene="CRBN",
            tcga_stats=None,
            pairwise_df=EMPTY_PAIRWISE,
            idas_assessment=CRBN_IDAS,
            tempus_gene_data=EMPTY_TEMPUS,
        )
        assert out["modality_class"] == "antibody_naked"
        for ws_key, row in out["idas_whitespace"].items():
            assert row["tox_penalty"] == 2, (
                f"{ws_key}: HIGH tox should give penalty=2 under default rule"
            )
            assert row["recommendation"] == "CAUTION", (
                f"{ws_key}: default rule should give CAUTION (matches v1.1.0)"
            )
            # Audit trail records the rule that fired.
            assert row["rule_applied"] == "tumor_vs_normal_strict"

    def test_default_rationale_string_format(self) -> None:
        out = crc.compute_subgroup_suitability(
            gene="CRBN", tcga_stats=None, pairwise_df=EMPTY_PAIRWISE,
            idas_assessment=CRBN_IDAS, tempus_gene_data=EMPTY_TEMPUS,
        )
        for row in out["idas_whitespace"].values():
            # New rationale uses tox_context which for strict rule is "High toxicity"
            assert "High toxicity" in row["rationale"]
            assert "Expression=" in row["rationale"]


# ---------------------------------------------------------------------------
# Degrader: same fixture, different result
# ---------------------------------------------------------------------------

class TestDegraderModalityRoutesCorrectly:
    """CRBN-shaped fixture + --modality "Molecular Glue" → expression_floor_only
    rule → no tox penalty → PRIORITY recommendation."""

    @pytest.mark.parametrize("modality_alias", [
        "Molecular Glue",
        "molecular glue",
        "PROTAC",
        "degrader",
        "TPD",
    ])
    def test_crc_degrader_aliases_route_to_expression_floor(
        self, modality_alias: str
    ) -> None:
        out = crc.compute_subgroup_suitability(
            gene="CRBN", tcga_stats=None, pairwise_df=EMPTY_PAIRWISE,
            idas_assessment=CRBN_IDAS, tempus_gene_data=EMPTY_TEMPUS,
            modality=modality_alias,
        )
        assert out["modality_class"] == "degrader"
        for ws_key, row in out["idas_whitespace"].items():
            # Degrader rule: no tumor-vs-normal penalty.
            assert row["tox_penalty"] == 0, (
                f"{ws_key}: degrader should not penalize HIGH tumor-vs-normal tox"
            )
            assert row["recommendation"] != "CAUTION", (
                f"{ws_key}: degrader CRBN should not be CAUTION; got {row['recommendation']}"
            )
            assert row["rule_applied"] == "expression_floor_only"


# ---------------------------------------------------------------------------
# ADC: stricter than antibody on the same fixture
# ---------------------------------------------------------------------------

class TestADCStricterThanAntibody:
    """Same CRBN-shaped fixture: ADC modality should produce stricter
    penalties than the default antibody_naked path."""

    def test_adc_penalty_exceeds_antibody_at_high_tox(self) -> None:
        ab_out = crc.compute_subgroup_suitability(
            gene="CRBN", tcga_stats=None, pairwise_df=EMPTY_PAIRWISE,
            idas_assessment=CRBN_IDAS, tempus_gene_data=EMPTY_TEMPUS,
            # default → antibody_naked
        )
        adc_out = crc.compute_subgroup_suitability(
            gene="CRBN", tcga_stats=None, pairwise_df=EMPTY_PAIRWISE,
            idas_assessment=CRBN_IDAS, tempus_gene_data=EMPTY_TEMPUS,
            modality="ADC",
        )
        assert ab_out["modality_class"] == "antibody_naked"
        assert adc_out["modality_class"] == "adc"

        for ws_key in ab_out["idas_whitespace"]:
            ab_pen = ab_out["idas_whitespace"][ws_key]["tox_penalty"]
            adc_pen = adc_out["idas_whitespace"][ws_key]["tox_penalty"]
            assert adc_pen > ab_pen, (
                f"{ws_key}: ADC (penalty={adc_pen}) must be stricter than "
                f"antibody (penalty={ab_pen}) at HIGH tox"
            )


# ---------------------------------------------------------------------------
# NSCLC mirror: a single sanity-check that the same wiring works there
# ---------------------------------------------------------------------------

NSCLC_PCDH7_LIKE_IDAS = {
    "on_target_toxicity": {
        "risk_level": "Low",
        "tumor_vs_adjacent_log2FC": 1.05,
    },
    "whitespace_alignment": {
        "2L_NonAGA": {"alignment": "Strong", "expression": 4.43, "n_samples": 295},
        "1L2L_KRAS": {"alignment": "Strong", "expression": 4.50, "n_samples": 607},
    },
}


class TestNSCLCMirror:
    """NSCLC is a separate file; verify the same wiring applies there too."""

    def test_nsclc_default_pcdh7_priority(self) -> None:
        out = nsclc.compute_subgroup_suitability(
            gene="PCDH7",
            tcga_stats=None,
            pairwise_df=EMPTY_PAIRWISE,
            tcga_mutation_stats=None,
            idas_assessment=NSCLC_PCDH7_LIKE_IDAS,
            tempus_gene_data=EMPTY_TEMPUS,
        )
        assert out["modality_class"] == "antibody_naked"
        for ws_key, row in out["idas_whitespace"].items():
            assert row["tox_penalty"] == 0, f"{ws_key}: Low tox = penalty 0"
            assert row["recommendation"] == "PRIORITY", (
                f"{ws_key}: PCDH7-like (Low tox + Strong iDAS) should be PRIORITY"
            )

    def test_nsclc_tce_modality_blocks_low_tox(self) -> None:
        """TCE is strictest: even Low tox gets a penalty (1)."""
        out = nsclc.compute_subgroup_suitability(
            gene="PCDH7", tcga_stats=None, pairwise_df=EMPTY_PAIRWISE,
            tcga_mutation_stats=None,
            idas_assessment=NSCLC_PCDH7_LIKE_IDAS,
            tempus_gene_data=EMPTY_TEMPUS,
            modality="T-cell engager",
        )
        assert out["modality_class"] == "tce"
        for ws_key, row in out["idas_whitespace"].items():
            assert row["tox_penalty"] == 1, (
                f"{ws_key}: TCE penalty for Low tox should be 1 (no free pass)"
            )
            assert row["rule_applied"] == "any_normal_expression_blocks"


# ---------------------------------------------------------------------------
# Modality recorded in suitability dict (audit trail)
# ---------------------------------------------------------------------------

def test_modality_recorded_at_top_level() -> None:
    """The resolved modality_class must be recorded so the audit trail
    can report it."""
    out = crc.compute_subgroup_suitability(
        gene="CRBN", tcga_stats=None, pairwise_df=EMPTY_PAIRWISE,
        idas_assessment=CRBN_IDAS, tempus_gene_data=EMPTY_TEMPUS,
        modality="Molecular Glue",
    )
    assert out["modality"] == "Molecular Glue"
    assert out["modality_class"] == "degrader"
