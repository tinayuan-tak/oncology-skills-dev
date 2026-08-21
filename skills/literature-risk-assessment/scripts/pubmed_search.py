"""PubMed search via NCBI E-utilities.

Stage 0 of the v1.4.0 facts.yaml extractor: turn a (gene, disease) pair
into structured per-category abstract lists, ready for LLM extraction
in Stage 1.

No LLM dependency — pure HTTP. Uses the public NCBI E-utilities API
(no API key required for moderate usage).
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Iterable

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# Six risk categories matching the workflow + the search-pattern column
# of risk_assessment_template_{disease}.md. The {gene} and {disease}
# placeholders get filled in at search time.
SEARCH_PATTERNS_BY_CATEGORY = {
    'biological': (
        '({gene}) AND ({disease}) AND '
        '(validation OR knockdown OR knockout OR CRISPR OR genetic association)'
    ),
    'druggability': (
        '({gene}) AND '
        '(drug target OR inhibitor OR antibody OR small molecule OR crystal structure)'
    ),
    'translational': (
        '({gene}) AND ({disease}) AND '
        '(biomarker OR PDX OR organoid OR animal model)'
    ),
    'clinical': (
        '({gene}) AND ({disease}) AND '
        '(clinical trial OR patient OR phase I OR phase II)'
    ),
    'safety': (
        '({gene}) AND '
        '(toxicity OR adverse OR normal tissue OR knockout mouse)'
    ),
    'commercial': (
        '({gene}) AND ({disease}) AND '
        '(therapeutic OR drug development OR competitive)'
    ),
}

# Disease search-term expansions for PubMed.
DISEASE_TERMS = {
    'crc': 'CRC OR colorectal cancer OR colon cancer OR rectal cancer',
    'nsclc': 'NSCLC OR lung cancer OR lung adenocarcinoma OR LUAD OR LUSC',
}


@dataclass(frozen=True)
class PubMedAbstract:
    """One abstract record from PubMed efetch."""
    pmid: str
    title: str
    abstract: str
    journal: str
    year: int | None
    category: str   # which of the 6 risk categories returned this PMID


@dataclass(frozen=True)
class PubMedSearchResult:
    """Per-category search results for a single (gene, disease) query."""
    gene: str
    disease: str
    abstracts_by_category: dict[str, list[PubMedAbstract]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search_pubmed(
    gene: str,
    disease: str,
    *,
    abstracts_per_category: int = 10,
    request_delay_s: float = 0.34,
    timeout_s: float = 30.0,
    mindate: str | None = None,
    maxdate: str | None = None,
) -> PubMedSearchResult:
    """Run six per-category PubMed searches for (gene, disease).

    Args:
        gene: Gene symbol (e.g. "PCDH7"). Case-sensitive — NCBI is liberal.
        disease: One of {'crc', 'nsclc'} — lower-case canonical disease key.
        abstracts_per_category: Cap on number of abstracts per category.
        request_delay_s: Inter-request delay to stay under NCBI's 3 req/s limit.
        timeout_s: Per-request timeout.

    Returns:
        PubMedSearchResult with abstracts grouped by category. Categories
        with zero results are still present as empty lists (so the
        downstream LLM stage can render "no evidence found" cleanly).

    Raises:
        ValueError: if disease is not a canonical key.
        urllib.error.URLError: if the network is unreachable. Caller
            should surface a helpful message about VPN / connectivity.
    """
    disease = disease.strip().lower()
    if disease not in DISEASE_TERMS:
        raise ValueError(
            f"disease must be one of {sorted(DISEASE_TERMS)}; got {disease!r}"
        )

    disease_terms = DISEASE_TERMS[disease]
    result = PubMedSearchResult(gene=gene, disease=disease)
    abstracts_by_cat: dict[str, list[PubMedAbstract]] = {}

    for category, pattern in SEARCH_PATTERNS_BY_CATEGORY.items():
        query = pattern.format(gene=gene, disease=disease_terms)
        # esearch → list of PMIDs
        pmids = _esearch(query, retmax=abstracts_per_category, timeout_s=timeout_s,
                         mindate=mindate, maxdate=maxdate)
        time.sleep(request_delay_s)
        if not pmids:
            abstracts_by_cat[category] = []
            continue
        # efetch → abstract records
        abstracts = _efetch_abstracts(pmids, category=category, timeout_s=timeout_s)
        abstracts_by_cat[category] = abstracts
        time.sleep(request_delay_s)

    # `dataclass(frozen=True)` blocks attribute assignment, so build a
    # fresh instance with the populated dict.
    return PubMedSearchResult(
        gene=gene, disease=disease, abstracts_by_category=abstracts_by_cat,
    )


# ---------------------------------------------------------------------------
# Internal: E-utilities calls
# ---------------------------------------------------------------------------

def _esearch(query: str, *, retmax: int, timeout_s: float,
             mindate: str | None = None, maxdate: str | None = None) -> list[str]:
    """Return up to `retmax` PMIDs for a query. When mindate/maxdate are given, bounds the
    publication-date window (datetype=pdat) so the corpus is pinnable/reproducible — the fix
    for the unbounded-corpus reproducibility gap (RISK_ASSESSMENT_INTEGRATION.md)."""
    params = {
        'db': 'pubmed',
        'term': query,
        'retmax': str(retmax),
        'retmode': 'json',
        'sort': 'relevance',
    }
    if mindate and maxdate:
        params['datetype'] = 'pdat'
        params['mindate'] = str(mindate)
        params['maxdate'] = str(maxdate)
    url = f"{EUTILS_BASE}/esearch.fcgi?" + urllib.parse.urlencode(params)
    raw = _http_get(url, timeout_s=timeout_s)
    data = json.loads(raw)
    return list(data.get('esearchresult', {}).get('idlist', []))


def _efetch_abstracts(
    pmids: Iterable[str], *, category: str, timeout_s: float,
) -> list[PubMedAbstract]:
    """Fetch and parse abstract records for a list of PMIDs."""
    pmid_str = ','.join(pmids)
    params = {
        'db': 'pubmed',
        'id': pmid_str,
        'rettype': 'abstract',
        'retmode': 'text',
    }
    url = f"{EUTILS_BASE}/efetch.fcgi?" + urllib.parse.urlencode(params)
    raw = _http_get(url, timeout_s=timeout_s)
    return _parse_efetch_text(raw, category=category)


def _http_get(url: str, *, timeout_s: float) -> str:
    """GET with explicit timeout. Returns body as str."""
    req = urllib.request.Request(url, headers={'User-Agent': 'oncology-skills/1.4'})
    with urllib.request.urlopen(req, timeout=timeout_s) as fh:
        return fh.read().decode('utf-8', errors='replace')


# ---------------------------------------------------------------------------
# Internal: efetch text parser
# ---------------------------------------------------------------------------

# efetch returns abstracts as plain text, with each record having this
# structure:
#
#   1. Journal. YYYY Mon DD;VOL(ISSUE):PP-PP. doi: 10.xxxx/...
#
#   Title of the paper on its own line (may wrap to next line).
#
#   Author A(1), Author B(2)(3), ...
#
#   Author information:
#   (1)Affiliation 1
#   (2)Affiliation 2
#
#   [Erratum in / Comment in / etc. — optional]
#
#   Abstract paragraph 1 (or BACKGROUND: ...)
#
#   © YYYY Publisher.
#
#   DOI: 10.xxxx/...
#   PMCID: PMCxxxxxxx
#   PMID: NNNNNNNN

_PMID_RE = re.compile(r'^PMID:\s*(\d+)', re.MULTILINE)
_JOURNAL_LINE_RE = re.compile(
    # First line of record: "1. Journal. YYYY ..."
    r'^\d+\.\s+([^.]+?)\.\s+(\d{4})\b',
)


def _parse_efetch_text(text: str, *, category: str) -> list[PubMedAbstract]:
    """Parse the plain-text output of efetch into PubMedAbstract records."""
    # Records separated by blank-line-then-numbered-line boundary.
    records = re.split(r'\n\n(?=\d+\.\s+[A-Z])', text.strip())
    abstracts: list[PubMedAbstract] = []
    for rec in records:
        pmid_match = _PMID_RE.search(rec)
        if not pmid_match:
            continue
        pmid = pmid_match.group(1)

        # First-line journal + year — line starts with "N. Journal. YYYY".
        journal = ''
        year: int | None = None
        first_line_match = re.match(
            r'^(\d+\.\s+)?([^.\n]+?)\.\s+(\d{4})\b', rec,
        )
        if first_line_match:
            journal = first_line_match.group(2).strip()
            try:
                year = int(first_line_match.group(3))
            except ValueError:
                year = None

        title = _extract_title(rec)
        abstract = _extract_abstract_body(rec)
        abstracts.append(PubMedAbstract(
            pmid=pmid,
            title=title,
            abstract=abstract,
            journal=journal,
            year=year,
            category=category,
        ))
    return abstracts


def _extract_title(record_body: str) -> str:
    """Title is the first paragraph after the journal/DOI line.

    Strategy: split on blank lines, take the second block (first is
    journal/DOI line). The title may span multiple lines so we join
    them with a space.
    """
    # Drop the first numbered-line block (journal + DOI). Find first
    # blank line and start from there.
    blocks = re.split(r'\n\s*\n', record_body, maxsplit=2)
    if len(blocks) < 2:
        return ''
    title_block = blocks[1].strip()
    # Title can span multiple lines; collapse to one.
    return re.sub(r'\s+', ' ', title_block)


def _extract_abstract_body(record_body: str) -> str:
    """Pull the abstract prose out of an efetch record.

    The abstract sits after author info, after Erratum/Comment blocks,
    and before the © / DOI / PMID trailers. Strategy: split on blank
    lines, find the longest block that doesn't start with a known
    metadata marker (Author info, Erratum in, Comment in, ©, DOI:,
    Conflict of interest, Keywords:, etc.) and isn't the title.
    """
    blocks = re.split(r'\n\s*\n', record_body)
    # Discard blocks that are metadata.
    metadata_starts = (
        'Author information:', 'Erratum in', 'Comment in',
        '©', 'DOI:', 'PMCID:', 'PMID:', 'Conflict of interest',
        'Keywords:', 'Copyright',
    )
    # Skip the first 2 blocks (journal-DOI line, title).
    candidates = []
    for block in blocks[2:]:
        b = block.strip()
        if not b:
            continue
        if any(b.startswith(prefix) for prefix in metadata_starts):
            continue
        # Author lines start with "Lastname F" pattern; skip.
        if re.match(r'^[A-Z][a-z]+\s+[A-Z]', b) and '(' in b[:40]:
            continue
        candidates.append(b)
    if not candidates:
        return ''
    # Take the longest candidate — abstracts are usually longer than
    # contributor lists or short notes.
    longest = max(candidates, key=len)
    return re.sub(r'\s+', ' ', longest)
