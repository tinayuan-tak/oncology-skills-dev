"""PubMed search via NCBI E-utilities.

Stage 0 of the v1.4.0 facts.yaml extractor: turn a (gene, disease) pair
into structured per-category abstract lists, ready for LLM extraction
in Stage 1.

No LLM dependency — pure HTTP. Uses the public NCBI E-utilities API.

Robustness (PR-1, 2026-09-08):
  - abstract parsing is XML-based (retmode=xml + ElementTree) — structured
    ArticleTitle / AbstractText (labeled sections joined in order) / PubDate,
    replacing the fragile regex text parser (kept as a fallback). The old
    "longest text block" heuristic dropped RESULTS/limitations sections of
    structured abstracts, exactly where escalating findings live.
  - honours NCBI_API_KEY (10 req/s vs the anonymous <3 req/s) + NCBI_TOOL /
    NCBI_EMAIL identification per NCBI's usage policy.
  - bounded exponential backoff on HTTP 429/5xx (a transient blip previously
    yielded [] → a dimension silently went not_assessed).
  - OPTIONAL content-addressed corpus cache: set LITRISK_CACHE_DIR to memoize
    esearch/efetch response bodies on disk keyed by the request (api_key/tool/
    email stripped from the key) — the reproducibility pin that defeats
    PubMed's run-to-run relevance re-ranking. Best-effort: any cache error is
    swallowed and retrieval proceeds live.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# NCBI courtesy identification + throughput. An API key raises the rate ceiling from ~3 to 10 req/s
# and stabilizes throughput; tool+email identify the client per NCBI's E-utilities usage policy.
NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "").strip()
NCBI_TOOL = os.environ.get("NCBI_TOOL", "onc-compbio-litrisk").strip()
NCBI_EMAIL = os.environ.get("NCBI_EMAIL", "").strip()
# 10 req/s with a key (0.1s), else stay comfortably under the anonymous 3 req/s ceiling (0.34s).
DEFAULT_REQUEST_DELAY_S = 0.1 if NCBI_API_KEY else 0.34

# Optional on-disk corpus cache (see module docstring). Env-driven for PR-1 (a --cache-dir CLI flag
# lands with the run.py retrieval unification in PR-2).
_CACHE_DIR_ENV = "LITRISK_CACHE_DIR"
# HTTP status codes worth retrying with backoff (transient server / rate-limit).
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


def _eutils_params(params: dict) -> dict:
    """Augment an E-utilities param dict with NCBI courtesy identification (api_key/tool/email) when
    configured. Pure: returns a new dict, leaves the caller's dict untouched."""
    out = dict(params)
    if NCBI_API_KEY:
        out["api_key"] = NCBI_API_KEY
    if NCBI_TOOL:
        out["tool"] = NCBI_TOOL
    if NCBI_EMAIL:
        out["email"] = NCBI_EMAIL
    return out


# ---------------------------------------------------------------------------
# Optional content-addressed cache (best-effort; no-op unless LITRISK_CACHE_DIR set)
# ---------------------------------------------------------------------------


def _cache_dir() -> Path | None:
    d = os.environ.get(_CACHE_DIR_ENV, "").strip()
    return Path(d) if d else None


def _cache_key(url: str) -> str:
    """sha256 of the URL with the identity params (api_key/tool/email) stripped, so the SAME logical
    request (query + dates + retmode) caches identically regardless of who issued it."""
    parts = urllib.parse.urlsplit(url)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query) if k not in ("api_key", "tool", "email")]
    canon = urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(sorted(q)), ""))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _cache_read(url: str) -> str | None:
    d = _cache_dir()
    if not d:
        return None
    try:
        f = d / f"{_cache_key(url)}.txt"
        return f.read_text(encoding="utf-8") if f.exists() else None
    except Exception:  # noqa: BLE001 — cache is best-effort; fall through to a live fetch
        return None


def _cache_write(url: str, body: str) -> None:
    d = _cache_dir()
    if not d:
        return
    try:
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{_cache_key(url)}.txt").write_text(body, encoding="utf-8")
    except Exception:  # noqa: BLE001 — a write failure must never break retrieval
        return


# Six risk categories matching the workflow + the search-pattern column
# of risk_assessment_template_{disease}.md. The {gene} and {disease}
# placeholders get filled in at search time.
SEARCH_PATTERNS_BY_CATEGORY = {
    "biological": (
        "({gene}) AND ({disease}) AND (validation OR knockdown OR knockout OR CRISPR OR genetic association)"
    ),
    "druggability": ("({gene}) AND (drug target OR inhibitor OR antibody OR small molecule OR crystal structure)"),
    "translational": ("({gene}) AND ({disease}) AND (biomarker OR PDX OR organoid OR animal model)"),
    "clinical": ("({gene}) AND ({disease}) AND (clinical trial OR patient OR phase I OR phase II)"),
    "safety": ("({gene}) AND (toxicity OR adverse OR normal tissue OR knockout mouse)"),
    "commercial": ("({gene}) AND ({disease}) AND (therapeutic OR drug development OR competitive)"),
}

# Disease search-term expansions for PubMed.
DISEASE_TERMS = {
    "crc": "CRC OR colorectal cancer OR colon cancer OR rectal cancer",
    "nsclc": "NSCLC OR lung cancer OR lung adenocarcinoma OR LUAD OR LUSC",
}


def gene_search_term(gene: str) -> str:
    """Disambiguated PubMed term for a gene symbol. A BARE symbol ('{gene}') is free-text and matches
    any abstract that merely MENTIONS the token — catastrophic for short/ambiguous symbols (e.g. "AR"
    pulls transglutaminase/TGM2 papers that say "AR transcriptional repression"). We require the paper
    to be either NCBI-gene-annotated to this gene ([Gene], entity-resolved) OR to name the symbol in its
    TITLE (a title mention is about the gene, not incidental) — precise without collapsing recall to the
    subset PubMed has gene-tagged. Precision matters more than recall for this verdict-inert CONTEXT
    read: a wrong-gene abstract is worse than a missed one."""
    g = (gene or "").strip()
    if not g:
        return g
    return f'({g}[Gene] OR "{g}"[Title])'


@dataclass(frozen=True)
class PubMedAbstract:
    """One abstract record from PubMed efetch."""

    pmid: str
    title: str
    abstract: str
    journal: str
    year: int | None
    category: str  # which of the 6 risk categories returned this PMID


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
    request_delay_s: float = DEFAULT_REQUEST_DELAY_S,
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
        raise ValueError(f"disease must be one of {sorted(DISEASE_TERMS)}; got {disease!r}")

    disease_terms = DISEASE_TERMS[disease]
    abstracts_by_cat: dict[str, list[PubMedAbstract]] = {}

    gene_term = gene_search_term(gene)  # entity/title-qualified — never a bare ambiguous symbol
    for category, pattern in SEARCH_PATTERNS_BY_CATEGORY.items():
        query = pattern.format(gene=gene_term, disease=disease_terms)
        # esearch → list of PMIDs
        pmids = _esearch(query, retmax=abstracts_per_category, timeout_s=timeout_s, mindate=mindate, maxdate=maxdate)
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
        gene=gene,
        disease=disease,
        abstracts_by_category=abstracts_by_cat,
    )


# ---------------------------------------------------------------------------
# Internal: E-utilities calls
# ---------------------------------------------------------------------------


def _esearch(
    query: str, *, retmax: int, timeout_s: float, mindate: str | None = None, maxdate: str | None = None
) -> list[str]:
    """Return up to `retmax` PMIDs for a query. When mindate/maxdate are given, bounds the
    publication-date window (datetype=pdat) so the corpus is pinnable/reproducible — the fix
    for the unbounded-corpus reproducibility gap (RISK_ASSESSMENT_INTEGRATION.md)."""
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": str(retmax),
        "retmode": "json",
        "sort": "relevance",
    }
    if mindate and maxdate:
        params["datetype"] = "pdat"
        params["mindate"] = str(mindate)
        params["maxdate"] = str(maxdate)
    url = f"{EUTILS_BASE}/esearch.fcgi?" + urllib.parse.urlencode(_eutils_params(params))
    raw = _http_get(url, timeout_s=timeout_s)
    data = json.loads(raw)
    return list(data.get("esearchresult", {}).get("idlist", []))


def _efetch_abstracts(
    pmids: Iterable[str],
    *,
    category: str,
    timeout_s: float,
) -> list[PubMedAbstract]:
    """Fetch and parse abstract records for a list of PMIDs.

    Primary path is XML (retmode=xml): structured ArticleTitle + AbstractText (labeled sections joined
    in order) + PubDate — robust to structured/erratum/multi-section abstracts. The legacy plain-text
    parser is retained as a FALLBACK: it fires only if the XML fetch/parse raises OR yields zero records
    for a non-empty PMID list (an anomaly worth a second look), so a real "no records" answer costs no
    extra request."""
    pmid_list = [str(p) for p in pmids if str(p).strip()]
    if not pmid_list:
        return []
    pmid_str = ",".join(pmid_list)
    xml_url = f"{EUTILS_BASE}/efetch.fcgi?" + urllib.parse.urlencode(
        _eutils_params({"db": "pubmed", "id": pmid_str, "rettype": "abstract", "retmode": "xml"})
    )
    try:
        parsed = _parse_efetch_xml(_http_get(xml_url, timeout_s=timeout_s), category=category)
        if parsed:
            return parsed
    except Exception:  # noqa: BLE001 — degrade to the legacy text parser on any XML fetch/parse failure
        pass
    text_url = f"{EUTILS_BASE}/efetch.fcgi?" + urllib.parse.urlencode(
        _eutils_params({"db": "pubmed", "id": pmid_str, "rettype": "abstract", "retmode": "text"})
    )
    return _parse_efetch_text(_http_get(text_url, timeout_s=timeout_s), category=category)


def _http_get(url: str, *, timeout_s: float, max_retries: int = 3) -> str:
    """GET with explicit timeout, bounded exponential backoff on transient HTTP 429/5xx (and connection
    errors), and an optional content-addressed disk cache (LITRISK_CACHE_DIR). Returns body as str.

    Backoff: a transient rate-limit / server blip previously surfaced as an exception that callers turned
    into an empty result (a dimension silently → not_assessed). We retry _RETRYABLE_STATUS + URLErrors up
    to `max_retries` times with 1s→2s→4s sleeps before re-raising."""
    cached = _cache_read(url)
    if cached is not None:
        return cached
    delay, last_exc = 1.0, None
    for attempt in range(max_retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "oncology-skills/1.6"})
            with urllib.request.urlopen(req, timeout=timeout_s) as fh:
                body = fh.read().decode("utf-8", errors="replace")
            _cache_write(url, body)
            return body
        except urllib.error.HTTPError as e:  # status-bearing: retry only the transient ones
            last_exc = e
            if e.code not in _RETRYABLE_STATUS or attempt >= max_retries:
                raise
        except urllib.error.URLError as e:  # connection/DNS/timeout: transient, retry
            last_exc = e
            if attempt >= max_retries:
                raise
        time.sleep(delay)
        delay *= 2
    raise last_exc  # unreachable (loop re-raises), but keeps the type-checker honest


# ---------------------------------------------------------------------------
# Internal: efetch XML parser (primary)
# ---------------------------------------------------------------------------


def _xml_text(el) -> str:
    """All text within an element (itertext), whitespace-collapsed — so inline markup in a title/abstract
    (<i>, <sup>, <sub>, MathML) contributes its text rather than being dropped or splitting the string."""
    if el is None:
        return ""
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def _parse_efetch_xml(xml_text: str, *, category: str) -> list[PubMedAbstract]:
    """Parse retmode=xml efetch output into PubMedAbstract records. Joins ALL AbstractText sections in
    document order (prefixing a section's Label — BACKGROUND/METHODS/RESULTS/CONCLUSIONS — when present),
    so structured abstracts keep their RESULTS/limitations text. Raises xml.etree ParseError on malformed
    XML (caller falls back to the text parser)."""
    root = ET.fromstring(xml_text)
    out: list[PubMedAbstract] = []
    for art in root.iter("PubmedArticle"):
        pmid_el = art.find(".//MedlineCitation/PMID")
        pmid = (pmid_el.text or "").strip() if pmid_el is not None else ""
        if not pmid:
            continue
        title = _xml_text(art.find(".//Article/ArticleTitle"))
        parts: list[str] = []
        for at in art.findall(".//Article/Abstract/AbstractText"):
            seg = _xml_text(at)
            if not seg:
                continue
            label = at.get("Label")
            parts.append(f"{label}: {seg}" if label else seg)
        abstract = " ".join(parts).strip()
        journal = _xml_text(art.find(".//Article/Journal/Title")) or _xml_text(
            art.find(".//Article/Journal/ISOAbbreviation")
        )
        year: int | None = None
        y = art.find(".//Article/Journal/JournalIssue/PubDate/Year")
        if y is not None and (y.text or "").strip().isdigit():
            year = int(y.text.strip())
        else:  # MedlineDate fallback (e.g. "2019 Jan-Feb" → 2019)
            md = art.find(".//Article/Journal/JournalIssue/PubDate/MedlineDate")
            m = re.search(r"\d{4}", md.text) if (md is not None and md.text) else None
            year = int(m.group(0)) if m else None
        out.append(
            PubMedAbstract(pmid=pmid, title=title, abstract=abstract, journal=journal, year=year, category=category)
        )
    return out


# ---------------------------------------------------------------------------
# Internal: efetch text parser (fallback)
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

_PMID_RE = re.compile(r"^PMID:\s*(\d+)", re.MULTILINE)
_JOURNAL_LINE_RE = re.compile(
    # First line of record: "1. Journal. YYYY ..."
    r"^\d+\.\s+([^.]+?)\.\s+(\d{4})\b",
)


def _parse_efetch_text(text: str, *, category: str) -> list[PubMedAbstract]:
    """Parse the plain-text output of efetch into PubMedAbstract records."""
    # Records separated by blank-line-then-numbered-line boundary.
    records = re.split(r"\n\n(?=\d+\.\s+[A-Z])", text.strip())
    abstracts: list[PubMedAbstract] = []
    for rec in records:
        pmid_match = _PMID_RE.search(rec)
        if not pmid_match:
            continue
        pmid = pmid_match.group(1)

        # First-line journal + year — line starts with "N. Journal. YYYY".
        journal = ""
        year: int | None = None
        first_line_match = re.match(
            r"^(\d+\.\s+)?([^.\n]+?)\.\s+(\d{4})\b",
            rec,
        )
        if first_line_match:
            journal = first_line_match.group(2).strip()
            try:
                year = int(first_line_match.group(3))
            except ValueError:
                year = None

        title = _extract_title(rec)
        abstract = _extract_abstract_body(rec)
        abstracts.append(
            PubMedAbstract(
                pmid=pmid,
                title=title,
                abstract=abstract,
                journal=journal,
                year=year,
                category=category,
            )
        )
    return abstracts


def _extract_title(record_body: str) -> str:
    """Title is the first paragraph after the journal/DOI line.

    Strategy: split on blank lines, take the second block (first is
    journal/DOI line). The title may span multiple lines so we join
    them with a space.
    """
    # Drop the first numbered-line block (journal + DOI). Find first
    # blank line and start from there.
    blocks = re.split(r"\n\s*\n", record_body, maxsplit=2)
    if len(blocks) < 2:
        return ""
    title_block = blocks[1].strip()
    # Title can span multiple lines; collapse to one.
    return re.sub(r"\s+", " ", title_block)


def _extract_abstract_body(record_body: str) -> str:
    """Pull the abstract prose out of an efetch record.

    The abstract sits after author info, after Erratum/Comment blocks,
    and before the © / DOI / PMID trailers. Strategy: split on blank
    lines, find the longest block that doesn't start with a known
    metadata marker (Author info, Erratum in, Comment in, ©, DOI:,
    Conflict of interest, Keywords:, etc.) and isn't the title.
    """
    blocks = re.split(r"\n\s*\n", record_body)
    # Discard blocks that are metadata.
    metadata_starts = (
        "Author information:",
        "Erratum in",
        "Comment in",
        "©",
        "DOI:",
        "PMCID:",
        "PMID:",
        "Conflict of interest",
        "Keywords:",
        "Copyright",
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
        if re.match(r"^[A-Z][a-z]+\s+[A-Z]", b) and "(" in b[:40]:
            continue
        candidates.append(b)
    if not candidates:
        return ""
    # Take the longest candidate — abstracts are usually longer than
    # contributor lists or short notes.
    longest = max(candidates, key=len)
    return re.sub(r"\s+", " ", longest)
