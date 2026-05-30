"""Stage 1 — per-abstract claim extraction via Sonnet tool use.

Takes the per-category abstract lists from pubmed_search.py and
returns structured `ExtractedClaim` records. The LLM is constrained
via Anthropic's tool-use feature: it returns structured JSON matching
a fixed schema, not free-form prose.

Single API call per category (not per abstract) — abstracts for one
category are batched into one prompt. Saves 6× the round-trips and
lets the LLM see claim-level redundancy across abstracts.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .bedrock_client import ModelConfig, get_bedrock_client
from .pubmed_search import PubMedAbstract, PubMedSearchResult


@dataclass(frozen=True)
class ExtractedClaim:
    """One structured claim extracted from one abstract.

    Maps 1:1 onto an `evidence[]` entry in the facts.yaml schema.
    """
    pmid: str
    claim: str          # ≤200 char summary of the claim
    study_type: str     # e.g. "in vivo", "preclinical antibody"
    category: str       # one of the 6 risk categories


@dataclass(frozen=True)
class CategoryExtraction:
    """Per-category extraction output."""
    category: str
    claims: list[ExtractedClaim] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Tool schema — the structured output contract the LLM must produce
# ---------------------------------------------------------------------------

EXTRACT_CLAIMS_TOOL = {
    "name": "extract_claims",
    "description": (
        "Extract structured therapeutic-target claims from PubMed "
        "abstracts. Each claim should be a single-sentence summary of "
        "evidence relevant to the requested risk category, with the "
        "PMID it came from."
    ),
    "input_schema": {
        "type": "object",
        "required": ["claims"],
        "properties": {
            "claims": {
                "type": "array",
                "description": (
                    "List of extracted claims. Aim for 1-3 claims per "
                    "abstract; skip abstracts that don't substantively "
                    "address the risk category."
                ),
                "items": {
                    "type": "object",
                    "required": ["pmid", "claim", "study_type"],
                    "properties": {
                        "pmid": {
                            "type": "string",
                            "description": "PubMed ID of the source abstract.",
                        },
                        "claim": {
                            "type": "string",
                            "description": (
                                "Single-sentence summary of the evidence, "
                                "≤200 characters. Specific and verifiable."
                            ),
                        },
                        "study_type": {
                            "type": "string",
                            "description": (
                                "Brief study-type tag, e.g. 'in vivo', "
                                "'preclinical antibody', 'prognostic cohort', "
                                "'mechanistic', 'biomarker development'."
                            ),
                        },
                    },
                },
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Per-category prompts
# ---------------------------------------------------------------------------

CATEGORY_FOCUS = {
    'biological': (
        "biological-validation evidence: in vivo / in vitro studies, "
        "knockout/knockdown phenotypes, mechanism of action, genetic "
        "association, prognostic relevance, and disease-driver evidence"
    ),
    'druggability': (
        "druggability evidence: tool compounds, antibodies, ADCs, "
        "small-molecule chemistry, structural biology, modality "
        "feasibility, and CMC"
    ),
    'translational': (
        "translational evidence: animal models (PDX/organoid/GEMM), "
        "target-engagement biomarkers, pharmacodynamic biomarkers, and "
        "imaging assays for clinical translation"
    ),
    'clinical': (
        "clinical evidence: clinical trial results, patient stratification, "
        "biomarker-defined populations, line-of-therapy fit, and trial "
        "feasibility for the indication"
    ),
    'safety': (
        "safety evidence: on-target toxicity, normal-tissue expression, "
        "knockout-mouse phenotype, off-target risks, class effects, "
        "and premonitory safety biomarkers"
    ),
    'commercial': (
        "commercial / competitive evidence: market size, unmet need, "
        "competitive landscape, pipeline activity, differentiation "
        "potential, and cross-indication portfolio fit"
    ),
}


def _build_extraction_prompt(
    gene: str, disease: str, category: str,
    abstracts: list[PubMedAbstract],
) -> str:
    """Compose the extraction prompt for one category's abstracts."""
    focus = CATEGORY_FOCUS[category]
    abstract_blocks = []
    for a in abstracts:
        abstract_blocks.append(
            f"PMID: {a.pmid}\n"
            f"Title: {a.title}\n"
            f"Journal: {a.journal} ({a.year or 'n.d.'})\n"
            f"Abstract: {a.abstract}\n"
        )
    abstracts_text = '\n---\n'.join(abstract_blocks)
    return (
        f"You are reviewing PubMed abstracts to populate a structured "
        f"target-evaluation facts file for **{gene}** in **{disease.upper()}**.\n\n"
        f"Risk category: **{category}** — focus on {focus}.\n\n"
        f"For each abstract below, extract 1-3 specific claims relevant "
        f"to this risk category. Skip abstracts that don't substantively "
        f"address {category}. Each claim should be a single sentence "
        f"(≤200 chars), specific enough to be verifiable, and tagged "
        f"with the PMID and a brief study_type label.\n\n"
        f"Use the `extract_claims` tool to return the structured output.\n\n"
        f"=== ABSTRACTS ===\n\n{abstracts_text}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_claims_for_category(
    *, gene: str, disease: str, category: str,
    abstracts: list[PubMedAbstract],
    client=None, model_config: ModelConfig | None = None,
) -> CategoryExtraction:
    """Run Sonnet structured extraction on one category's abstracts.

    If `abstracts` is empty, returns a `CategoryExtraction` with no
    claims (no LLM call made).
    """
    if not abstracts:
        return CategoryExtraction(category=category, claims=[])

    client = client or get_bedrock_client()
    cfg = model_config or ModelConfig.from_env()

    prompt = _build_extraction_prompt(gene, disease, category, abstracts)
    response = client.messages.create(
        model=cfg.extraction_model,
        max_tokens=cfg.max_output_tokens,
        tools=[EXTRACT_CLAIMS_TOOL],
        tool_choice={"type": "tool", "name": "extract_claims"},
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_tool_response(response, category=category)


def extract_claims(
    search_result: PubMedSearchResult,
    *, client=None, model_config: ModelConfig | None = None,
) -> dict[str, CategoryExtraction]:
    """Run extraction across all 6 categories of a search result.

    Returns:
        Dict keyed by category name → CategoryExtraction.
    """
    client = client or get_bedrock_client()
    cfg = model_config or ModelConfig.from_env()
    out: dict[str, CategoryExtraction] = {}
    for category, abstracts in search_result.abstracts_by_category.items():
        out[category] = extract_claims_for_category(
            gene=search_result.gene, disease=search_result.disease,
            category=category, abstracts=abstracts,
            client=client, model_config=cfg,
        )
    return out


# ---------------------------------------------------------------------------
# Internal: parse Anthropic tool-use response
# ---------------------------------------------------------------------------

def _parse_tool_response(response: Any, *, category: str) -> CategoryExtraction:
    """Pull the structured output out of an Anthropic tool-use response."""
    # Find the tool_use content block.
    tool_use_block = None
    for block in getattr(response, 'content', []):
        # Anthropic SDK returns content blocks with type attribute.
        block_type = getattr(block, 'type', None)
        if block_type == 'tool_use':
            tool_use_block = block
            break
    if tool_use_block is None:
        # Defensive: model didn't call the tool. Return empty.
        return CategoryExtraction(category=category, claims=[])

    tool_input = getattr(tool_use_block, 'input', None)
    if isinstance(tool_input, str):
        # SDK sometimes returns input as JSON string; decode.
        tool_input = json.loads(tool_input)
    if not isinstance(tool_input, dict):
        return CategoryExtraction(category=category, claims=[])

    raw_claims = tool_input.get('claims', []) or []
    claims = []
    for c in raw_claims:
        if not isinstance(c, dict):
            continue
        pmid = str(c.get('pmid', '')).strip()
        claim_text = str(c.get('claim', '')).strip()
        study_type = str(c.get('study_type', '')).strip()
        if not (pmid and claim_text):
            continue
        # Truncate over-long claims to the schema's 200-char target.
        if len(claim_text) > 200:
            claim_text = claim_text[:197] + '...'
        claims.append(ExtractedClaim(
            pmid=pmid, claim=claim_text, study_type=study_type,
            category=category,
        ))
    return CategoryExtraction(category=category, claims=claims)
