"""Layer 1 — Input parsers for the integrated report generator.

Each parser is a pure function: file path in, dataclass out. No formatting,
no template logic. Independently testable with fixtures.

Order of complexity (simplest → hardest):
  1. load_scholareval    — YAML, fully deterministic schema
  2. load_idas           — YAML, deterministic but nested
  3. load_suitability    — CSV, simple columns
  4. load_comparisons    — CSV, simple columns
  5. parse_risk_assessment — hand-written markdown, regex-based extraction
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ============================================================================
# Dataclasses (return types)
# ============================================================================

@dataclass(frozen=True)
class ScholarEvalDimension:
    name: str
    score: int
    risk_level: str
    rationale: str
    rule_applied: str


@dataclass(frozen=True)
class ScholarEvalResult:
    gene: str
    disease: str
    total_score: float
    assessment: str          # 'Strong' / 'Moderate' / 'Weak'
    recommendation: str      # 'GO' / 'NO-GO' / 'CONDITIONAL'
    high_risk_count: int
    input_hash: str
    dimensions: dict[str, ScholarEvalDimension]


@dataclass(frozen=True)
class IDASWhitespace:
    label: str               # human-readable, e.g. "1L/2L KRAS Mutant"
    expression_log2tpm: float
    alignment: str           # 'Strong' / 'Moderate' / 'Weak'
    n_samples: int
    source: str              # 'TCGA' / 'Tempus' / 'TCGA+Tempus'
    # v1.2.0+ Phase 3 dispatcher fields (None if pre-v1.2.0 yaml)
    tox_penalty: int | None = None
    adjusted_score: int | None = None
    recommendation: str | None = None
    rule_applied: str | None = None
    rationale: str | None = None
    toxicity_risk: str | None = None


@dataclass(frozen=True)
class IDASAssessment:
    gene: str
    overall_alignment: str
    recommendation: str
    on_target_tox_risk: str       # 'Low' / 'Medium' / 'High'
    on_target_tox_log2fc: float
    luad_log2fc: float | None
    lusc_log2fc: float | None
    whitespaces: dict[str, IDASWhitespace]
    modality: str = ''
    # Empty string means "not set in idas.yaml" — context.py will resolve
    # via ModalityRegistry from the CLI/raw modality string instead of
    # silently anchoring to antibody_naked.
    modality_class: str = ''


@dataclass(frozen=True)
class SubgroupRow:
    subgroup: str
    category: str            # 'tcga_analysis' / 'tempus_mutation' / 'idas_whitespace'
    key_metric: str
    score: int
    recommendation: str


@dataclass(frozen=True)
class PairwiseComparison:
    tumor_cohort: str
    normal_group: str
    tumor_n: int
    normal_n: int
    tumor_median: float
    normal_median: float
    log2fc: float
    p_value: float
    p_adjusted: float
    significant: bool


@dataclass(frozen=True)
class RiskCategory:
    name: str                # e.g. "Biological"
    level: str               # 'LOW' / 'MEDIUM' / 'HIGH' / 'LOW-MEDIUM' etc.
    key_driver: str
    evidence_pmids: list[str] = field(default_factory=list)
    raw_considerations: str = ''   # full text from the table cell


@dataclass(frozen=True)
class RiskAssessment:
    gene: str
    disease: str
    overall_risk_profile: str       # 'LOW' / 'MEDIUM' / 'HIGH' / compound
    categories: dict[str, RiskCategory]   # keyed by category name
    strengths: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    mitigations: list[tuple[str, str, str]] = field(default_factory=list)  # (risk, level, strategy)
    recommendation: str = ''        # 'GO — MEDIUM-HIGH PRIORITY' etc.
    idas_alignments: dict[str, str] = field(default_factory=dict)   # whitespace → 'Strong'/'Moderate'/'Weak'
    modality_candidates: list[str] = field(default_factory=list)


# ============================================================================
# 1. ScholarEval YAML
# ============================================================================

def load_scholareval(path: Path) -> ScholarEvalResult:
    """Load and validate {GENE}_scholareval.yaml output from Step 3."""
    with open(path) as f:
        data = yaml.safe_load(f)

    dimensions = {}
    for name, cfg in (data.get('dimension_scores') or {}).items():
        dimensions[name] = ScholarEvalDimension(
            name=name,
            score=int(cfg.get('score', 0)),
            risk_level=str(cfg.get('risk_level', 'UNKNOWN')),
            rationale=str(cfg.get('rationale', '')),
            rule_applied=str(cfg.get('rule_applied', '')),
        )

    return ScholarEvalResult(
        gene=str(data.get('gene', '')),
        disease=str(data.get('disease', '')),
        total_score=float(data.get('total_score', 0.0)),
        assessment=str(data.get('assessment', 'Unknown')),
        recommendation=str(data.get('recommendation', 'TBD')),
        high_risk_count=int(data.get('high_risk_count', 0)),
        input_hash=str(data.get('input_hash', '')),
        dimensions=dimensions,
    )


# ============================================================================
# 2. iDAS YAML
# ============================================================================

# Map iDAS YAML keys to human-readable labels (drives §3.2 / §3.4).
_IDAS_LABELS = {
    # CRC
    'chemorefractory_3lplus': 'Chemorefractory 3L+',
    'ras_mutant_frontline': 'RAS Mutant Frontline',
    'ras_mutant_refractory': 'RAS Mutant Refractory (3L+)',
    'resectable': 'Resectable (Neo/Adjuvant)',
    # NSCLC
    '2L_NonAGA': '2L Non-AGA',
    '2L_EGFR': '2L EGFR Mutant (post-TKI)',
    '1L2L_KRAS': '1L/2L KRAS Mutant',
}


def load_idas(path: Path) -> IDASAssessment:
    """Load {GENE}_analysis-bulk-rna-{disease}_idas.yaml from Step 2."""
    with open(path) as f:
        data = yaml.safe_load(f)

    tox = data.get('on_target_toxicity', {}) or {}

    whitespaces: dict[str, IDASWhitespace] = {}
    ws_alignment = data.get('whitespace_alignment', {}) or {}
    sub_idas = ((data.get('subgroup_analysis', {}) or {})
                .get('idas_whitespace', {}) or {})

    for key, ws in ws_alignment.items():
        # Expression field name varies (expression / expression_3lplus /
        # tcga_expression / tempus_expression). Take the first present.
        expr = (ws.get('expression') or ws.get('expression_3lplus')
                or ws.get('tempus_expression') or ws.get('tcga_expression') or 0.0)
        sub = sub_idas.get(key, {})
        whitespaces[key] = IDASWhitespace(
            label=ws.get('label') or _IDAS_LABELS.get(key, key),
            expression_log2tpm=float(expr),
            alignment=str(ws.get('alignment', 'Unknown')),
            n_samples=int(ws.get('n_samples') or 0),
            source=str(ws.get('source', '')),
            tox_penalty=sub.get('tox_penalty'),
            adjusted_score=sub.get('adjusted_score'),
            recommendation=sub.get('recommendation'),
            rule_applied=sub.get('rule_applied'),
            rationale=sub.get('rationale'),
            toxicity_risk=sub.get('toxicity_risk'),
        )

    return IDASAssessment(
        gene=str(data.get('gene', '')),
        overall_alignment=str(data.get('overall_alignment', 'Unknown')),
        recommendation=str(data.get('recommendation', '')),
        on_target_tox_risk=str(tox.get('risk_level', 'Unknown')),
        on_target_tox_log2fc=float(tox.get('tumor_vs_adjacent_log2FC', 0.0)),
        luad_log2fc=tox.get('luad_vs_luad_adjacent_log2FC'),
        lusc_log2fc=tox.get('lusc_vs_lusc_adjacent_log2FC'),
        whitespaces=whitespaces,
        modality=str((data.get('subgroup_analysis', {}) or {}).get('modality', '')),
        modality_class=str((data.get('subgroup_analysis', {}) or {}).get('modality_class', '')),
    )


# ============================================================================
# 3 & 4. Suitability + Comparisons CSVs
# ============================================================================

def load_suitability(path: Path) -> list[SubgroupRow]:
    """Load {GENE}_analysis-bulk-rna-{disease}_suitability.csv from Step 2.

    Returns rows in file order (already sorted by score descending in the
    auto-generated CSV).
    """
    rows: list[SubgroupRow] = []
    with open(path) as f:
        for r in csv.DictReader(f):
            rows.append(SubgroupRow(
                subgroup=r['subgroup'],
                category=r['category'],
                key_metric=r['key_metric'],
                # int(float(...)): the suitability CSV 'score' column is often
                # written as a decimal string (e.g. "4.0"); run_scholareval reads
                # the same column as float(). Bare int("4.0") raises ValueError and
                # aborts integrated-report generation. Parse via float, keep the
                # int contract this dataclass declares.
                score=int(float(r['score'])),
                recommendation=r['recommendation'],
            ))
    return rows


def load_comparisons(path: Path) -> list[PairwiseComparison]:
    """Load {GENE}_analysis-bulk-rna-{disease}_comparisons.csv from Step 2."""
    rows: list[PairwiseComparison] = []
    with open(path) as f:
        for r in csv.DictReader(f):
            rows.append(PairwiseComparison(
                tumor_cohort=r['Tumor_Cohort'],
                normal_group=r['Normal_Group'],
                tumor_n=int(r['Tumor_N']),
                normal_n=int(r['Normal_N']),
                tumor_median=float(r['Tumor_Median']),
                normal_median=float(r['Normal_Median']),
                log2fc=float(r['Log2FC']),
                p_value=float(r['p_value']),
                p_adjusted=float(r['p_adjusted']),
                significant=str(r['significant']).lower() == 'true',
            ))
    return rows


# ============================================================================
# 5. Risk Assessment Markdown (the hard one — hand-written)
# ============================================================================

# Canonical 6 categories from the risk-assessment template.
RISK_CATEGORIES = [
    'Biological', 'Druggability', 'Translational',
    'Clinical', 'Safety', 'Commercial',
]


def parse_risk_assessment(path: Path) -> RiskAssessment:
    """Parse {GENE}_risk_assessment_{disease}.md from Step 1.

    The risk-assessment markdown follows
    `reference/risk_assessment_template_{disease}.md` structure:
      - "Executive Risk Summary" table (6 rows: category | level | considerations)
      - per-category sections: ## 1. Biological, ## 2. Druggability, etc.
      - "Key Strengths" / "Key Risks" / "Risk Mitigation Strategies"
      - "Recommendation" section

    Hand-written content varies in formatting; this parser is tolerant of
    bold markers, em-dashes, and compound risk levels (LOW-MEDIUM, etc.).
    """
    with open(path) as f:
        content = f.read()

    # --- Header metadata: gene, disease, modality candidates ----------------
    gene_match = re.search(r'^#\s+([A-Z][A-Z0-9]*)\s+', content, re.MULTILINE)
    gene = gene_match.group(1) if gene_match else ''

    disease_match = re.search(r'\*\*Disease:\*\*\s*([^\n]+)', content)
    disease = disease_match.group(1).strip() if disease_match else ''

    modality_candidates: list[str] = []
    mod_match = re.search(r'\*\*Modality candidates:\*\*\s*([^\n]+)', content, re.IGNORECASE)
    if mod_match:
        modality_candidates = [
            m.strip() for m in re.split(r'[,;]', mod_match.group(1))
            if m.strip()
        ]

    # --- Executive Risk Summary table ---------------------------------------
    # Match the table that follows "## Executive Risk Summary".
    categories: dict[str, RiskCategory] = {}
    summary_match = re.search(
        r'##\s+Executive Risk Summary[^\n]*\n(.*?)(?=^##\s|\Z)',
        content, re.DOTALL | re.MULTILINE,
    )
    if summary_match:
        for line in summary_match.group(1).split('\n'):
            if not line.strip().startswith('|'):
                continue
            cells = [c.strip() for c in line.strip('|').split('|')]
            if len(cells) < 3:
                continue
            cat_name = _strip_bold(cells[0])
            if cat_name not in RISK_CATEGORIES:
                continue
            level = _normalize_risk_level(_strip_bold(cells[1]))
            considerations = _strip_bold(cells[2])
            pmids = re.findall(r'PMID:?\s*(\d{6,9})', considerations)
            # Hand-written templates often put PMIDs in per-category
            # detail sections (## 1. Biological, ## 2. Druggability, etc.)
            # rather than the summary table cell. Pull PMIDs from there too.
            cat_section_match = re.search(
                rf'##\s+\d+\.\s+{re.escape(cat_name)}[^\n]*\n(.*?)(?=^##\s|\Z)',
                content, re.DOTALL | re.MULTILINE,
            )
            if cat_section_match:
                section_pmids = re.findall(
                    r'PMID:?\s*(\d{6,9})', cat_section_match.group(1)
                )
                for p in section_pmids:
                    if p not in pmids:
                        pmids.append(p)
            # Key driver = first sentence (split on period followed by
            # whitespace, to avoid truncating decimals like "+1.05").
            sentences = re.split(r'\.\s+', considerations, maxsplit=1)
            key_driver = sentences[0].rstrip('.').strip()
            if len(key_driver) > 200:
                key_driver = key_driver[:197] + '...'
            categories[cat_name] = RiskCategory(
                name=cat_name,
                level=level,
                key_driver=key_driver,
                evidence_pmids=pmids,
                raw_considerations=considerations,
            )

    # NOTE: parser is intentionally STRICT. If the Executive Risk Summary
    # table is missing or malformed, `categories` will be empty and the
    # generator will refuse to render. Use lint_risk_assessment.py to
    # validate inputs upstream rather than adding fallback paths here.
    # See memory: "No hand-writing in workflow" — schema enforcement at
    # every boundary, not parser tolerance.

    # --- Overall risk profile -----------------------------------------------
    overall_match = re.search(
        r'(?:###\s+)?Overall Target Risk Profile:\s*\*?\*?([A-Z][A-Z\-–—]*)',
        content, re.IGNORECASE,
    )
    if not overall_match:
        overall_match = re.search(
            r'\*\*Overall Risk Profile:\s*([A-Z][A-Z\-–—]*)',
            content, re.IGNORECASE,
        )
    overall = ''
    if overall_match:
        overall = _normalize_risk_level(overall_match.group(1))

    # --- Strengths / Risks / Mitigations ------------------------------------
    strengths = _extract_numbered_list_after(content, r'(?:##|###)\s*Key Strengths')
    risks = _extract_numbered_list_after(content, r'(?:##|###)\s*Key Risks(?:/Challenges)?')
    mitigations = _extract_mitigation_table(content)

    # --- Recommendation -----------------------------------------------------
    # Section heading is "## Recommendation" or "## Recommendations"; the
    # actual recommendation phrase is typically under "### Overall:" inside.
    rec_section = re.search(
        r'^##\s+Recommendations?\s*$(.*?)(?=^##\s|\Z)',
        content, re.DOTALL | re.MULTILINE,
    )
    recommendation = ''
    if rec_section:
        body = rec_section.group(1)
        # Look for any bold phrase containing GO/NO-GO/CONDITIONAL.
        rec_phrase = re.search(
            r'\*\*((?:CONDITIONAL\s+NO-GO|GO|NO-GO|CONDITIONAL)[^*]*)\*\*',
            body, re.IGNORECASE,
        )
        if rec_phrase:
            recommendation = rec_phrase.group(1).strip()

    # --- iDAS whitespace alignments -----------------------------------------
    # Whitespace alignment lives in a "## iDAS Strategic Alignment Assessment"
    # section. May be in table form `| Whitespace | Alignment | Rationale |`
    # or in checkbox form `- [x] 2L Non-AGA  [x] 2L EGFR ...`.
    idas_alignments: dict[str, str] = {}
    idas_section = re.search(
        r'^##\s+iDAS(?:\s+Strategic)?(?:\s+Alignment)?(?:\s+Assessment)?[^\n]*\n(.*?)(?=^##\s|\Z)',
        content, re.DOTALL | re.MULTILINE | re.IGNORECASE,
    )
    if idas_section:
        body = idas_section.group(1)
        # Format A: table rows. The first column has the whitespace label,
        # second has alignment.
        for line in body.split('\n'):
            if not line.strip().startswith('|'):
                continue
            cells = [_strip_bold(c) for c in line.strip('|').split('|')]
            if len(cells) < 2:
                continue
            label = cells[0].strip()
            alignment_cell = cells[1].strip()
            # Match Strong/Moderate/Weak/None inside the alignment cell.
            align_match = re.search(
                r'\b(Strong|Moderate|Weak|None)\b', alignment_cell, re.IGNORECASE,
            )
            if align_match and label and label.lower() not in (
                'priority whitespace', '---', 'whitespace', '------',
            ):
                idas_alignments[label] = align_match.group(1).capitalize()

    return RiskAssessment(
        gene=gene,
        disease=disease,
        overall_risk_profile=overall,
        categories=categories,
        strengths=strengths,
        risks=risks,
        mitigations=mitigations,
        recommendation=recommendation,
        idas_alignments=idas_alignments,
        modality_candidates=modality_candidates,
    )


# ----------------------------------------------------------------------------
# Helpers for the risk-assessment parser
# ----------------------------------------------------------------------------

def _strip_bold(s: str) -> str:
    """Remove **bold** and *italic* markers from a string."""
    return re.sub(r'\*+([^*]+)\*+', r'\1', s).strip()


def _normalize_risk_level(level: str) -> str:
    """Normalize risk-level strings: trim, uppercase, normalize dashes."""
    normalized = level.strip().upper()
    normalized = normalized.replace('–', '-').replace('—', '-')
    # Strip trailing punctuation.
    normalized = re.sub(r'[^A-Z\-]+$', '', normalized)
    return normalized


def _extract_numbered_list_after(content: str, heading_pattern: str) -> list[str]:
    """Pull numbered-list items following a markdown heading."""
    section = re.search(
        rf'{heading_pattern}[^\n]*\n(.*?)(?=^##\s|^###\s|^---|\Z)',
        content, re.DOTALL | re.MULTILINE | re.IGNORECASE,
    )
    if not section:
        return []
    items = []
    for line in section.group(1).split('\n'):
        m = re.match(r'^\s*(?:\d+\.|-)\s+(.+?)\s*$', line)
        if m:
            text = _strip_bold(m.group(1))
            items.append(text)
    return items


def _extract_mitigation_table(content: str) -> list[tuple[str, str, str]]:
    """Pull (risk, level, strategy) tuples from the Risk Mitigation section.

    Handles two formats:
      A. Markdown table: | Risk | Risk Level | Mitigation Strategy |
      B. Numbered list: "1. **Risk title** — strategy text"
         (level is inferred from the considerations or defaults to MEDIUM)
    """
    section = re.search(
        r'(?:##\s+|###\s+)?Risk Mitigation(?:\s+Strategies)?[^\n]*\n(.*?)(?=^##\s|^---|\Z)',
        content, re.DOTALL | re.MULTILINE | re.IGNORECASE,
    )
    if not section:
        return []
    body = section.group(1)
    rows: list[tuple[str, str, str]] = []

    # Format A: table.
    for line in body.split('\n'):
        if not line.strip().startswith('|'):
            continue
        cells = [_strip_bold(c) for c in line.strip('|').split('|')]
        if len(cells) < 3:
            continue
        risk = cells[0].strip()
        if not risk or risk.lower() in ('risk', '---', '------', '-------'):
            continue
        if all(set(c.strip()) <= {'-', ':'} or c.strip() == '' for c in cells):
            continue
        level = _normalize_risk_level(cells[1]) if len(cells) >= 3 else 'MEDIUM'
        strategy = cells[2].strip() if len(cells) >= 3 else cells[-1].strip()
        rows.append((risk, level, strategy))

    if rows:
        return rows

    # Format B: numbered list "N. **Title** — strategy text".
    for m in re.finditer(
        r'^\s*\d+\.\s+\*\*([^*]+)\*\*\s*[—\-–]\s*(.+?)(?=^\s*\d+\.\s+\*\*|^##|^---|\Z)',
        body, re.DOTALL | re.MULTILINE,
    ):
        title = m.group(1).strip()
        strategy = re.sub(r'\s+', ' ', m.group(2)).strip()
        # Level isn't explicit in numbered-list format; default to MEDIUM.
        rows.append((title, 'MEDIUM', strategy))

    return rows


# ============================================================================
# Optional: audit_trail.json (for §3.3 footer reference)
# ============================================================================

def load_audit_trail(path: Path) -> list[dict[str, Any]] | dict[str, Any]:
    """Load {GENE}_audit_trail.json.

    The scoring engine emits a JSON list of per-step audit records;
    older versions emitted a dict. Return whatever the file contains —
    consumers only use it for the input_hash citation in §3.3 footer
    (which lives in the scholareval YAML, not the audit trail).
    """
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)
