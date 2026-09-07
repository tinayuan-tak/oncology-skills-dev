#!/usr/bin/env python3
"""Entity-normalized literature retrieval via PubTator3 (companion to pubmed_search).

WHY THIS EXISTS — the keyword-collision failure mode:
  ground_axis previously retrieved ONLY via NCBI E-utilities keyword search. For a
  gene whose symbol collides with a common word/suffix, keyword search retrieves the
  WRONG ENTITY. Measured example: the query `(ME3) AND (toxicity OR normal tissue ...)`
  returned 10 papers, 9 of which were histone-trimethylation papers ("H3K9me3",
  "H3K27me3", DOT1L/KDM5B methylation biology) — NOT the gene ME3 (malic enzyme 3) —
  so the grounded read raised ZERO findings and silently rubber-stamped the
  deterministic safety verdict. (STAG1, MET, SET, CAD, ACE … share this hazard.)

  PubTator3 entity-links each mention to an NCBI Gene id, so `@GENE_<entrez>` retrieves
  the gene, not the string. This module resolves a symbol -> entity id (via PubTator's
  own autocomplete — no external resolver dependency) and searches by that entity.

Pure functions (`_pick_gene_entity`, `_numeric_pmids`, `entity_axis_query`) are unit
-tested offline; the two thin HTTP wrappers mirror pubmed_search's style (stdlib urllib,
courtesy throttle, no API key) and are best-effort — callers fall back to keyword search
if PubTator is unreachable.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

PUBTATOR_BASE = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api"
_UA = {"User-Agent": "oncology-skills/1.5 (grounded-substrate entity retrieval)"}
_TIMEOUT = 30.0
_DELAY = 0.34  # stay well under NCBI's 3 req/s


# ------------------------------------------------------------------ pure -----
def _pick_gene_entity(results: list[dict], symbol: str) -> str | None:
    """From PubTator autocomplete hits, pick the entity whose gene NAME matches the
    symbol exactly (case-insensitive) — avoids the synonym false-matches that caused
    the collision in the first place. Returns '@GENE_<entrez>' or None."""
    sym = symbol.strip().upper()
    for r in results or []:
        if str(r.get("name", "")).upper() == sym and r.get("db_id"):
            return f"@GENE_{r['db_id']}"
    return None


def _numeric_pmids(hits: list[dict], limit: int) -> list[str]:
    """Keep only real PubMed PMIDs (drop Europe-PMC preprint/other ids like PPR*/IND*
    that do not resolve via NCBI efetch), preserving PubTator's relevance order."""
    out: list[str] = []
    for h in hits or []:
        pmid = str(h.get("pmid") or h.get("_id") or "")
        if pmid.isdigit():
            out.append(pmid)
        if len(out) >= limit:
            break
    return out


def entity_axis_query(
    gene_clause: str, disease_terms: str, axis_terms: str, *, disease_scoped: bool, broad: bool
) -> str:
    """Build the PubTator query. `gene_clause` is the entity anchor ('@GENE_10873')
    or a fallback symbol clause ('(ME3)'). `broad` drops the axis-term conjunction
    (the soft-fallback used when the tight query starves)."""
    parts = [gene_clause]
    if disease_scoped and disease_terms:
        parts.append(f"({disease_terms})")
    if not broad and axis_terms:
        parts.append(f"({axis_terms})")
    return " AND ".join(parts)


# --------------------------------------------------------------- network -----
def resolve_gene_entity(symbol: str, *, timeout_s: float = _TIMEOUT) -> str | None:
    """symbol -> '@GENE_<entrez>' via PubTator autocomplete; None on miss/error."""
    try:
        q = urllib.parse.urlencode({"query": symbol, "concept": "gene", "limit": 10})
        req = urllib.request.Request(f"{PUBTATOR_BASE}/entity/autocomplete/?{q}", headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        time.sleep(_DELAY)
        return _pick_gene_entity(data if isinstance(data, list) else data.get("results", []), symbol)
    except Exception:  # noqa: BLE001 — best-effort; caller falls back to keyword search
        return None


def pubtator_pmids(query: str, *, retmax: int, timeout_s: float = _TIMEOUT) -> list[str]:
    """Entity-aware relevance search -> list of PubMed PMIDs (numeric only)."""
    try:
        q = urllib.parse.urlencode({"text": query})
        req = urllib.request.Request(f"{PUBTATOR_BASE}/search/?{q}", headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        time.sleep(_DELAY)
        return _numeric_pmids(data.get("results") or [], retmax)
    except Exception:  # noqa: BLE001
        return []
