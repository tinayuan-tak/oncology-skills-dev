"""Snapshot/unit tests for the PDF report markdown extractors.

These guard against the failure modes we hit in May 2026:
  - Recommendation parser hallucinating "GO - PRIORITY" when the markdown
    actually said "GO — MEDIUM PRIORITY" or "CONDITIONAL".
  - `_build_slide_data` silently producing empty toxicity/iDAS/subgroup
    rows when section/table parsing drifts.
  - Risk-profile parsing dropping compound levels like "LOW-MEDIUM".

Run with: `uv run pytest tests/` from the skill directory, or
`pixi run pytest tests/`.
"""
from __future__ import annotations

import os
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

# scripts/ is not a package; inject it for import.
SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import generate_target_report_pdf as gpr  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures: minimal markdown bodies that exercise each parser path.
# ---------------------------------------------------------------------------

EXEC_SUMMARY_TEMPLATE = textwrap.dedent("""
    # {gene} Target Evaluation Report

    ## Executive Summary

    | Metric | Value |
    |--------|-------|
    | **Target** | {gene} ({aliases}) |
    | **ScholarEval Score** | **{score}/5.0 ({assessment})** |
    | **Overall Risk Profile** | **{risk}** |
    | **Recommendation** | **{recommendation}** |

    ### Key Findings at a Glance
    - **Modality**: {modality}
    - First takeaway about the target.
    - Second takeaway with **bolded** phrase.

    ## 3. Expression Analysis

    ### 3.2 On-Target Toxicity Risk

    | Comparison | Tumor (log2 TPM) | Normal (log2 TPM) | Fold Change | Risk Level |
    |------------|------------------|-------------------|-------------|------------|
    | TCGA RASMut MSS vs Adjacent | 4.19 | 4.61 | 0.7× | LOW |
    | TCGA RASWT MSS vs Adjacent | 4.32 | 4.61 | 0.8× | LOW |
    | TCGA RASMut MSS vs GTEx Colon | 4.19 | 4.80 | 0.7× | LOW |

    | Whitespace | Expression | Alignment | Source | n |
    |------------|------------|-----------|--------|---|
    | RAS mutant frontline | 4.19 | Strong | TCGA+Tempus | 920 |
    | Chemorefractory 3L+ | 4.43 | Strong | Tempus | 426 |
    | Resectable | 4.09 | Strong | TCGA | 136 |

    ## 6. Strategic Recommendations

    ### 6.3 Subgroup Suitability

    | Population | Recommendation | Rationale |
    |------------|----------------|-----------|
    | RAS-mutant 1L/2L | **PURSUE** | Strong iDAS alignment |
    | Chemorefractory 3L+ | **PURSUE** | High whitespace fit |
    | MSI-H | **DEFER** | Limited cohort size |
""").strip()


def _write_report(tmp_path: Path, gene: str, body: str, disease: str = "crc") -> Path:
    """Write the markdown to the path that integrated_report_path() expects."""
    target = Path(gpr.integrated_report_path(str(tmp_path), gene))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)
    return target


# ---------------------------------------------------------------------------
# parse_integrated_report: recommendation parsing matrix
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rec_in, rec_expected", [
    ("GO — HIGH PRIORITY", "GO — HIGH PRIORITY"),
    ("GO — MEDIUM-HIGH PRIORITY", "GO — MEDIUM-HIGH PRIORITY"),
    ("GO — MEDIUM PRIORITY", "GO — MEDIUM PRIORITY"),
    ("GO — LOW PRIORITY", "GO — LOW PRIORITY"),
    ("GO — Strong target with clear path", "GO"),
    ("CONDITIONAL — Conditional on biomarker validation", "CONDITIONAL"),
    ("CONDITIONAL NO-GO — Insufficient evidence", "CONDITIONAL NO-GO"),
    ("NO-GO — Excluded due to safety concerns", "NO-GO"),
])
def test_recommendation_parser_preserves_priority(tmp_path, rec_in, rec_expected):
    body = EXEC_SUMMARY_TEMPLATE.format(
        gene="TESTGENE", aliases="ALIAS1, ALIAS2", score="3.5",
        assessment="Moderate", risk="MEDIUM", recommendation=rec_in,
        modality="Antibody",
    )
    report = _write_report(tmp_path, "TESTGENE", body)
    data = gpr.parse_integrated_report(str(report))
    assert data["recommendation"] == rec_expected, (
        f"input={rec_in!r} expected={rec_expected!r} got={data['recommendation']!r}"
    )


def test_compound_risk_level_preserves_hyphen(tmp_path):
    body = EXEC_SUMMARY_TEMPLATE.format(
        gene="TG", aliases="A", score="3.0", assessment="Moderate",
        risk="LOW-MEDIUM", recommendation="CONDITIONAL — needs work",
        modality="Selective",
    )
    report = _write_report(tmp_path, "TG", body)
    data = gpr.parse_integrated_report(str(report))
    assert data["risk_profile"] == "LOW-MEDIUM"


def test_em_dash_normalized_in_risk(tmp_path):
    body = EXEC_SUMMARY_TEMPLATE.format(
        gene="TG", aliases="A", score="3.0", assessment="Moderate",
        risk="LOW–MEDIUM", recommendation="GO", modality="Selective",
    )
    report = _write_report(tmp_path, "TG", body)
    data = gpr.parse_integrated_report(str(report))
    assert data["risk_profile"] == "LOW-MEDIUM"


def test_score_and_assessment_extraction(tmp_path):
    body = EXEC_SUMMARY_TEMPLATE.format(
        gene="TG", aliases="A", score="4.25", assessment="Strong",
        risk="LOW", recommendation="GO", modality="Selective",
    )
    report = _write_report(tmp_path, "TG", body)
    data = gpr.parse_integrated_report(str(report))
    assert data["score"] == "4.25/5.0"
    assert data["assessment"] == "Strong"


# ---------------------------------------------------------------------------
# _extract_markdown_section_n / _extract_markdown_table_rows
# ---------------------------------------------------------------------------

SECTION_FIXTURE = textwrap.dedent("""
    ## 3. Expression Analysis

    ### 3.2 Toxicity

    | Comparison | Tumor | Normal | Fold Change | Risk Level |
    |------------|-------|--------|-------------|------------|
    | A vs B | 4.0 | 5.0 | 0.5× | LOW |
    | C vs D | 3.0 | 6.0 | 0.25× | MEDIUM |

    ## 4. Next section
""").strip()


def test_extract_section_n_returns_body():
    body = gpr._extract_markdown_section_n(SECTION_FIXTURE, 3)
    assert "### 3.2 Toxicity" in body
    assert "## 4." not in body


def test_extract_section_n_missing_returns_empty():
    assert gpr._extract_markdown_section_n(SECTION_FIXTURE, 99) == ""


def test_extract_table_rows_picks_matching_table():
    body = gpr._extract_markdown_section_n(SECTION_FIXTURE, 3)
    headers, rows = gpr._extract_markdown_table_rows(
        body, header_keywords=["Tumor", "Normal"]
    )
    assert headers[0] == "Comparison"
    assert len(rows) == 2
    assert rows[0][-1] == "LOW"


def test_extract_table_rows_no_match_returns_empty():
    body = gpr._extract_markdown_section_n(SECTION_FIXTURE, 3)
    headers, rows = gpr._extract_markdown_table_rows(
        body, header_keywords=["Doesnotexist"]
    )
    assert headers == [] and rows == []


# ---------------------------------------------------------------------------
# _build_slide_data: end-to-end (portrait page 1 + landscape both rely on it)
# ---------------------------------------------------------------------------

def test_build_slide_data_extracts_all_sections(tmp_path):
    body = EXEC_SUMMARY_TEMPLATE.format(
        gene="CRBN", aliases="MGC13452", score="3.35", assessment="Conditional",
        risk="LOW-MEDIUM", recommendation="CONDITIONAL — biomarker dependent",
        modality="Molecular Glue",
    )
    _write_report(tmp_path, "CRBN", body)
    sd = gpr._build_slide_data(str(tmp_path), "CRBN")

    assert sd["aliases"] == "MGC13452"
    assert sd["modality"].startswith("Molecular Glue")

    assert len(sd["toxicity_data"]) >= 1, "toxicity table should not be empty"
    assert all("subtype" in r and "fold_change" in r and "risk" in r
               for r in sd["toxicity_data"])
    # GTEx rows are intentionally filtered out of the slide.
    assert all("GTEx" not in r["subtype"] for r in sd["toxicity_data"])

    assert len(sd["idas_data"]) == 3
    assert sd["idas_data"][0]["alignment"] == "Strong"

    assert len(sd["subgroup_data"]) >= 2
    assert sd["subgroup_data"][0]["recommendation"] == "PURSUE"

    assert len(sd["takeaways"]) >= 1
    assert all("**" not in t for t in sd["takeaways"]), \
        "bold markdown should be stripped from takeaways"


def test_build_slide_data_missing_report_returns_empty(tmp_path):
    sd = gpr._build_slide_data(str(tmp_path), "MISSING")
    assert sd["toxicity_data"] == []
    assert sd["idas_data"] == []
    assert sd["subgroup_data"] == []
    assert sd["takeaways"] == []


def test_build_slide_data_falls_back_to_section7_takeaways(tmp_path):
    # Strip the "Key Findings at a Glance" block so the fallback path runs.
    body = EXEC_SUMMARY_TEMPLATE.format(
        gene="TG", aliases="A", score="4.0", assessment="Strong",
        risk="LOW", recommendation="GO", modality="Selective",
    )
    body = body.replace("### Key Findings at a Glance", "### Other Heading")
    body += textwrap.dedent("""

        ## 7. Final Recommendation

        1. **First** numbered takeaway from section 7.
        2. **Second** numbered takeaway from section 7.
    """)
    _write_report(tmp_path, "TG", body)
    sd = gpr._build_slide_data(str(tmp_path), "TG")
    assert len(sd["takeaways"]) >= 1
    assert "First" in sd["takeaways"][0]
