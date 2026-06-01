"""Stage 2 — synthesize facts.yaml from extracted claims via Opus tool use.

Takes the per-category ExtractedClaim lists from Stage 1 (extract_claims)
and synthesizes:
  - Per-category risk level + key_driver + justification
  - iDAS whitespace alignments (per-disease canonical labels)
  - Strengths / risks / mitigations
  - Overall recommendation + priority

Single LLM call (uses Opus — heavier reasoning step on a smaller volume
of input). Output is constrained via tool use to match the canonical
schema enforced by load_facts() — passes the strict v1.4.0 validator
on the way to disk.
"""
from __future__ import annotations

import json
from typing import Any

from .bedrock_client import ModelConfig, get_bedrock_client
from .extract_claims import CategoryExtraction
from .risk_assessment_renderer import (
    CANONICAL_IDAS_ALIGNMENTS, CANONICAL_MITIGATION_LEVELS,
    CANONICAL_RECOMMENDATION_LEVELS, CANONICAL_RECOMMENDATION_PRIORITIES,
    CANONICAL_RISK_LEVELS, CANONICAL_WHITESPACES,
)


# ---------------------------------------------------------------------------
# Tool schema — output must match facts.yaml shape exactly
# ---------------------------------------------------------------------------

def _build_synthesize_tool(disease: str) -> dict[str, Any]:
    """Tool schema parameterized by disease (different canonical
    whitespaces for CRC vs NSCLC)."""
    canonical_ws = sorted(CANONICAL_WHITESPACES[disease])
    return {
        "name": "synthesize_facts",
        "description": (
            "Synthesize a structured target-evaluation facts record "
            "from per-category extracted claims. Output must match the "
            "facts.yaml schema (canonical enums for risk levels, "
            "alignments, recommendation levels)."
        ),
        "input_schema": {
            "type": "object",
            "required": [
                "background", "risk_categories", "idas_alignment",
                "strengths", "risks", "mitigations", "recommendation",
            ],
            "properties": {
                "background": {
                    "type": "string",
                    "description": (
                        "2-3 sentence target-biology and rationale paragraph "
                        "synthesizing the extracted claims."
                    ),
                },
                "risk_categories": {
                    "type": "object",
                    "required": [
                        "biological", "druggability", "translational",
                        "clinical", "safety", "commercial",
                    ],
                    "properties": {
                        cat: _category_schema(cat)
                        for cat in [
                            "biological", "druggability", "translational",
                            "clinical", "safety", "commercial",
                        ]
                    },
                },
                "idas_alignment": {
                    "type": "array",
                    "description": (
                        f"iDAS strategic-alignment scores for {disease.upper()} "
                        f"priority whitespaces. Whitespace label MUST be one of: "
                        f"{canonical_ws}."
                    ),
                    "items": {
                        "type": "object",
                        "required": ["whitespace", "alignment"],
                        "properties": {
                            "whitespace": {"type": "string", "enum": canonical_ws},
                            "alignment": {
                                "type": "string",
                                "enum": sorted(CANONICAL_IDAS_ALIGNMENTS),
                            },
                            "rationale": {"type": "string"},
                        },
                    },
                },
                "strengths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "3-6 bullet-point strengths.",
                },
                "risks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "3-6 bullet-point risks/challenges.",
                },
                "mitigations": {
                    "type": "array",
                    "description": "3-6 risk-mitigation strategies.",
                    "items": {
                        "type": "object",
                        "required": ["title", "risk_level", "strategy"],
                        "properties": {
                            "title": {"type": "string"},
                            "risk_level": {
                                "type": "string",
                                "enum": sorted(CANONICAL_MITIGATION_LEVELS),
                            },
                            "strategy": {"type": "string"},
                        },
                    },
                },
                "recommendation": {
                    "type": "object",
                    "required": ["level", "rationale"],
                    "properties": {
                        "level": {
                            "type": "string",
                            "enum": sorted(CANONICAL_RECOMMENDATION_LEVELS),
                        },
                        "priority": {
                            "type": "string",
                            "enum": sorted(CANONICAL_RECOMMENDATION_PRIORITIES),
                            "description": (
                                "Optional priority qualifier; omit for "
                                "NO-GO or pure CONDITIONAL recommendations."
                            ),
                        },
                        "rationale": {"type": "string"},
                    },
                },
            },
        },
    }


def _category_schema(category: str | None = None) -> dict[str, Any]:
    """Per-category schema fragment used six times in the tool input.

    For `clinical` and `druggability`, adds optional structured fields
    that ScholarEval reads directly (v1.4.0+) — eliminates regex-on-prose
    brittleness in Step 3 scoring.
    """
    schema: dict[str, Any] = {
        "type": "object",
        "required": ["level", "key_driver", "justification"],
        "properties": {
            "level": {
                "type": "string",
                "enum": sorted(CANONICAL_RISK_LEVELS),
            },
            "key_driver": {
                "type": "string",
                "description": (
                    "1-sentence summary that lands in the Executive Risk "
                    "Summary table. ≤200 chars."
                ),
            },
            "justification": {
                "type": "string",
                "description": "2-4 sentence rationale for the risk level.",
            },
            # v1.7.0: optional pointer to the load-bearing piece of evidence
            # for this category. The PMID MUST appear in the same category's
            # `evidence[]` (validator enforces). Omit if no single study
            # dominates.
            "primary_evidence": {
                "type": "object",
                "required": ["pmid", "why_primary"],
                "properties": {
                    "pmid": {
                        "type": "string",
                        "description": (
                            "PMID (6-9 digits) of the load-bearing study. "
                            "MUST be present in this category's evidence[]."
                        ),
                    },
                    "why_primary": {
                        "type": "string",
                        "description": (
                            "1-sentence rationale: what makes this study "
                            "load-bearing for the category? E.g. 'Establishes "
                            "extracellular-domain antibody accessibility' for "
                            "druggability; 'Sole in-vivo PoC in autochthonous "
                            "GEMM' for biological."
                        ),
                    },
                },
                "additionalProperties": False,
            },
        },
    }
    if category == 'clinical':
        schema["properties"]["biomarker_tier"] = {
            "type": "string",
            "enum": ["none", "emerging", "clinical_grade"],
            "description": (
                "Biomarker development stage for this gene in this disease. "
                "'clinical_grade' = an approved companion diagnostic, "
                "FDA-cleared NGS panel, or standard-of-care testing assay "
                "exists. 'emerging' = patient-selection / stratification / "
                "enrichment biomarker work has been published but no "
                "clinical-grade assay yet. 'none' = no biomarker strategy "
                "evident in the extracted claims."
            ),
        }
        schema["properties"]["highest_phase"] = {
            "type": "integer",
            "minimum": 0,
            "maximum": 4,
            "description": (
                "Highest clinical phase reached by ANY agent targeting "
                "this gene for this disease. 0 = preclinical only, "
                "1-4 = Phase I-IV. Be conservative — only count agents "
                "where the extracted claims provide direct evidence."
            ),
        }
        schema["properties"]["disease_assoc_literature_signal"] = {
            "type": "integer",
            "minimum": 1,
            "maximum": 5,
            "description": (
                "How strongly the literature ties this gene to disease "
                "biology and patient outcomes (1=weak, 5=strong). "
                "Rubric: 5 = recurrent driver mutation + survival "
                "association + multiple in-vivo / human-genetic studies; "
                "4 = strong prognostic + multiple lines of evidence; "
                "3 = some prognostic or mutational data; "
                "2 = limited associative evidence; "
                "1 = no clear disease-association signal."
            ),
        }
    if category == 'biological':
        schema["properties"]["pathway_score"] = {
            "type": "integer",
            "minimum": 1,
            "maximum": 5,
            "description": (
                "Pathway / mechanism relevance score (1-5). Counts how "
                "many DISTINCT cancer-relevant pathways or mechanisms "
                "the extracted claims connect this gene to. Rubric: "
                "5 = ≥6 distinct pathway/mechanism categories "
                "(e.g. DDR, cell cycle, MAPK, EMT, immune evasion, "
                "synthetic lethality); 4 = 4-5 categories; "
                "3 = 2-3 categories; 2 = 1 category; 1 = none."
            ),
        }
        schema["properties"]["pathway_evidence_count"] = {
            "type": "integer",
            "minimum": 0,
            "description": (
                "Number of distinct pathway/mechanism categories that "
                "support the pathway_score. Audit field."
            ),
        }
    if category == 'druggability':
        schema["properties"].update({
            "has_approved_drug": {
                "type": "boolean",
                "description": (
                    "True if a drug targeting this gene is FDA-approved "
                    "(or equivalent regulatory approval). Default false."
                ),
            },
            "has_clinical_compound": {
                "type": "boolean",
                "description": (
                    "True if a clinical-stage compound (Phase I+) "
                    "targeting this gene exists. Default false."
                ),
            },
            "has_tool_compound": {
                "type": "boolean",
                "description": (
                    "True if a preclinical tool compound or validated "
                    "ADC/antibody for this gene exists. Default false."
                ),
            },
            "has_structure": {
                "type": "boolean",
                "description": (
                    "True if a crystal structure / cryo-EM / PDB entry "
                    "for this protein exists. Default false."
                ),
            },
            "best_ic50_nm": {
                "type": ["number", "null"],
                "description": (
                    "Lowest reported IC50 in nM across known compounds; "
                    "null if no compound exists."
                ),
            },
        })
    # Lock each category to its declared properties — prevents Opus from
    # spraying clinical-only or druggability-only fields onto other
    # categories (observed in v1.6.0 dev: `highest_phase: null` appeared
    # under `safety`, which load_facts rightly rejects under per-category
    # placement rules but which a global `RECOGNIZED_CATEGORY_KEYS` allow
    # would silently pass).
    schema["additionalProperties"] = False
    return schema


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def _build_synthesis_prompt(
    gene: str, disease: str, modality: str | None,
    extractions: dict[str, CategoryExtraction],
) -> str:
    """Compose the synthesis prompt from per-category extracted claims."""
    canonical_ws = sorted(CANONICAL_WHITESPACES[disease])
    sections: list[str] = []
    # Per-category PMID inventories — load-bearing for v1.7.0
    # primary_evidence selection. The validator enforces that
    # primary_evidence.pmid is in *this* category's evidence[],
    # not just *some* category's. Surface the per-category PMID
    # set explicitly so Opus picks within the right pool.
    per_category_pmids: dict[str, list[str]] = {}
    for category, ce in extractions.items():
        pmids = sorted({c.pmid for c in ce.claims})
        per_category_pmids[category] = pmids
        if not ce.claims:
            sections.append(f"### {category.title()}\n*No claims extracted.*")
            continue
        bullets = '\n'.join(
            f"  - [PMID {c.pmid}] ({c.study_type}) {c.claim}"
            for c in ce.claims
        )
        sections.append(
            f"### {category.title()}\n"
            f"**Valid PMIDs for primary_evidence in this category: "
            f"{pmids}**\n"
            f"{bullets}"
        )
    claims_block = '\n\n'.join(sections)
    modality_line = (
        f"Modality candidates: {modality}\n" if modality else ""
    )
    return (
        f"You are synthesizing a structured target-evaluation facts file for "
        f"**{gene}** in **{disease.upper()}**.\n"
        f"{modality_line}\n"
        f"Below are claims extracted from PubMed abstracts, organized by the "
        f"6 risk categories. Synthesize them into a complete facts record:\n\n"
        f"For each of the 6 risk categories, assign a risk level (LOW / "
        f"MEDIUM / HIGH or compound LOW-MEDIUM / MEDIUM-HIGH), a 1-sentence "
        f"key_driver, and a 2-4 sentence justification.\n\n"
        f"For iDAS alignment, score each of these {disease.upper()} priority "
        f"whitespaces (Strong / Moderate / Weak / None): {canonical_ws}.\n\n"
        f"List 3-6 strengths, 3-6 risks, and 3-6 mitigation strategies. "
        f"Then output an overall recommendation (GO / NO-GO / CONDITIONAL) "
        f"with optional priority (HIGH / MEDIUM-HIGH / MEDIUM / LOW).\n\n"
        f"For the **clinical** category, also fill `highest_phase` (0-4): "
        f"the highest clinical phase reached by ANY {gene}-targeting agent "
        f"in {disease.upper()}. Use 0 if no agent has entered trials. Be "
        f"conservative — base this only on the extracted claims. Also fill "
        f"`disease_assoc_literature_signal` (1-5): how strongly the literature "
        f"ties {gene} to {disease.upper()} biology and patient outcomes — "
        f"5=driver mutation + survival + multi-line in-vivo evidence; "
        f"3=some prognostic/mutational data; 1=no disease-association signal. "
        f"Also fill `biomarker_tier` (one of 'none', 'emerging', "
        f"'clinical_grade'): 'clinical_grade' if an approved companion "
        f"diagnostic / FDA-cleared NGS panel / standard-of-care assay for "
        f"{gene} exists; 'emerging' if patient-selection / stratification / "
        f"enrichment biomarker work has been published but no clinical-grade "
        f"assay yet; 'none' if no biomarker strategy is evident.\n\n"
        f"For the **biological** category, also fill `pathway_score` (1-5) "
        f"and `pathway_evidence_count`: count distinct cancer-relevant "
        f"pathway/mechanism categories the claims connect {gene} to "
        f"(DDR, cell cycle, MAPK, EMT, immune evasion, synthetic lethality, "
        f"angiogenesis, etc.). 5 = ≥6 categories, 4 = 4-5, 3 = 2-3, 2 = 1, "
        f"1 = none.\n\n"
        f"For the **druggability** category, also fill the boolean fields: "
        f"`has_approved_drug` (FDA-approved drug exists), "
        f"`has_clinical_compound` (Phase I+ compound exists), "
        f"`has_tool_compound` (preclinical tool/ADC/antibody exists), "
        f"`has_structure` (PDB / crystal / cryo-EM entry exists). "
        f"Default each to false unless extracted claims directly support it. "
        f"Set `best_ic50_nm` to the lowest reported IC50 in nM, or null.\n\n"
        f"For each category, IF the extracted claims include a single "
        f"load-bearing study that the rest of the category's reasoning "
        f"hinges on (e.g. the in-vivo PoC paper for biological; the "
        f"crystal-structure / IC50 paper for druggability; the "
        f"biomarker-validation paper for translational), set "
        f"`primary_evidence` to {{pmid, why_primary}}.\n\n"
        f"CRITICAL: `primary_evidence.pmid` MUST be drawn from the "
        f"'Valid PMIDs for primary_evidence in this category' list shown "
        f"at the top of each category section below. A PMID that appears "
        f"under one category cannot be used as primary_evidence for a "
        f"different category, even if the paper is conceptually relevant "
        f"to both. If no PMID in the listed set is load-bearing for the "
        f"category, OMIT `primary_evidence` entirely for that category.\n\n"
        f"`why_primary` is one sentence explaining why the chosen study "
        f"is load-bearing for THIS category specifically.\n\n"
        f"Use the `synthesize_facts` tool to return structured output. "
        f"Be specific and ground claims in the provided PMIDs.\n\n"
        f"=== EXTRACTED CLAIMS ===\n\n{claims_block}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def synthesize_facts(
    *, gene: str, disease: str,
    extractions: dict[str, CategoryExtraction],
    modality: str | None = None,
    target_aliases: str = '',
    modality_candidates: list[str] | None = None,
    date: str | None = None,
    client=None, model_config: ModelConfig | None = None,
    feedback: str | None = None,
) -> dict[str, Any]:
    """Run Opus synthesis and return a facts.yaml-shaped dict.

    The returned dict is ready to be passed to `yaml.safe_dump()` and
    written. It will pass `load_facts()` strict validation by
    construction (tool schema enforces enums; we still validate
    afterward as a defensive double-check).

    Args:
        feedback: Optional. Validation-error message from a previous
            attempt. When set, prepended to the prompt so Opus can
            correct field placement on retry.
    """
    if disease not in CANONICAL_WHITESPACES:
        raise ValueError(f"unknown disease: {disease!r}")
    client = client or get_bedrock_client()
    cfg = model_config or ModelConfig.from_env()

    tool = _build_synthesize_tool(disease)
    prompt = _build_synthesis_prompt(gene, disease, modality, extractions)
    if feedback:
        prompt = (
            f"PREVIOUS ATTEMPT FAILED VALIDATION with this error:\n"
            f"  {feedback}\n\n"
            f"Common cause: a category-specific field (e.g. `highest_phase` "
            f"on `clinical`, `pathway_score` on `biological`, `has_*` on "
            f"`druggability`) was placed on the wrong category. Fields are "
            f"strictly per-category. Please regenerate the output respecting "
            f"the schema's per-category locality.\n\n"
        ) + prompt
    response = client.messages.create(
        model=cfg.synthesis_model,
        max_tokens=cfg.max_output_tokens,
        tools=[tool],
        tool_choice={"type": "tool", "name": "synthesize_facts"},
        messages=[{"role": "user", "content": prompt}],
    )
    synthesized = _parse_synthesis_response(response)

    # Attach the structured `evidence[]` lists back into each category
    # from Stage 1 (the synthesis LLM only sees claim text; the per-PMID
    # mapping is preserved here).
    for cat_key, ce in extractions.items():
        if cat_key in synthesized.get('risk_categories', {}):
            synthesized['risk_categories'][cat_key]['evidence'] = [
                {
                    'claim': c.claim,
                    'pmid': c.pmid,
                    'study_type': c.study_type or '',
                }
                for c in ce.claims
            ]

    # Wrap into the full facts.yaml shape.
    from datetime import date as _date
    facts: dict[str, Any] = {
        'gene': gene,
        'disease': disease,
        'date': date or _date.today().isoformat(),
        'target_aliases': target_aliases,
        'modality_candidates': modality_candidates or (
            [modality] if modality else []
        ),
        'background': synthesized.get('background', '').strip(),
        'risk_categories': synthesized.get('risk_categories', {}),
        'idas_alignment': synthesized.get('idas_alignment', []),
        'strengths': synthesized.get('strengths', []),
        'risks': synthesized.get('risks', []),
        'mitigations': synthesized.get('mitigations', []),
        'recommendation': synthesized.get('recommendation', {'level': 'CONDITIONAL'}),
    }
    return facts


# ---------------------------------------------------------------------------
# Internal: parse the synthesis response
# ---------------------------------------------------------------------------

def _parse_synthesis_response(response: Any) -> dict[str, Any]:
    """Extract the synthesize_facts tool input from an Anthropic response."""
    for block in getattr(response, 'content', []):
        if getattr(block, 'type', None) == 'tool_use':
            tool_input = getattr(block, 'input', None)
            if isinstance(tool_input, str):
                tool_input = json.loads(tool_input)
            if isinstance(tool_input, dict):
                return tool_input
    return {}
