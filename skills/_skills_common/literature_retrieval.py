"""literature_retrieval — Europe PMC grounding + PMID verification for the literature lane.

Two best-effort, stdlib-only (urllib) helpers wired into `literature_synthesis`:

  * ``europe_pmc_retrieve(target, indication, lens)`` — query the public Europe PMC REST API for the most
    relevant papers on the (target, indication) and return a compact GROUNDING CORPUS string (PMID +
    citation + truncated abstract per paper). Injected into the synthesis prompt so the model cites REAL
    papers present in the corpus (and may mark those ``verified=true``).

  * ``verify_citations(result)`` — after synthesis, reconcile every citation's ``verified`` flag against
    GROUND TRUTH: a PMID is ``verified=true`` iff Europe PMC actually returns that identifier. This makes
    ``verified`` trustworthy regardless of what the model claimed (a hallucinated PMID flips to false), and
    records a ``_verification`` summary on the result.

BEST-EFFORT / NEVER-BREAK: every network path has a short timeout and degrades on ANY failure
(no network, DNS, non-200, parse error) — retrieval returns None (→ internal-knowledge mode), verification
leaves the model's flags and marks ``_verification: {"status": "unavailable"}``. The literature lane itself
is already optional + verdict-inert, so a retrieval/verification outage can never touch the spine.
"""
from __future__ import annotations
import json
import urllib.parse
import urllib.request
from typing import Optional

_EPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_UA = {"User-Agent": "onc-compbio-skills-literature-lane/1.0 (mailto:noreply@takeda.com)"}

# Minimal OncoTree-ish code → readable phrase for the query (best-effort; unknown codes fall back to the
# raw code + "cancer", which Europe PMC free-text still ranks usefully). Kept tiny + local on purpose —
# this is a query hint, not a canonical vocabulary.
_INDICATION_PHRASE = {
    "COADREAD": "colorectal cancer", "COAD": "colon cancer", "READ": "rectal cancer",
    "LUAD": "lung adenocarcinoma", "LUSC": "lung squamous carcinoma", "NSCLC": "non-small cell lung cancer",
    "BRCA": "breast cancer", "PAAD": "pancreatic cancer", "PDAC": "pancreatic ductal adenocarcinoma",
    "STAD": "gastric cancer", "OV": "ovarian cancer", "PRAD": "prostate cancer", "UCEC": "endometrial cancer",
    "SCLC": "small cell lung cancer", "HNSC": "head and neck squamous carcinoma", "SKCM": "melanoma",
    "GBM": "glioblastoma", "AML": "acute myeloid leukemia", "BLCA": "bladder cancer",
}


def _indication_phrase(indication: Optional[str]) -> str:
    if not indication:
        return "cancer"
    return _INDICATION_PHRASE.get(indication.upper(), f"{indication} cancer")


def _http_get_json(url: str, timeout: float) -> Optional[dict]:
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if getattr(r, "status", 200) != 200:
                return None
            return json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 — best-effort; ANY failure → degrade to None
        return None


def _search(query: str, *, page_size: int, result_type: str, timeout: float) -> Optional[dict]:
    params = urllib.parse.urlencode({"query": query, "format": "json",
                                     "resultType": result_type, "pageSize": page_size})
    return _http_get_json(f"{_EPMC_SEARCH}?{params}", timeout)


def europe_pmc_retrieve(target, indication, lens=None, *, max_results: int = 8,
                        abstract_chars: int = 420, timeout: float = 8.0) -> Optional[str]:
    """Return a compact grounding corpus (str) of the top Europe PMC hits for (target, indication), or None
    on any failure / no hits. `lens` is accepted for the retrieve_fn signature but not required."""
    if not target:
        return None
    phrase = _indication_phrase(indication)
    # bias toward reviews + primary papers with abstracts; free-text is robust to the OncoTree code.
    query = f'("{target}") AND ("{phrase}") AND (HAS_ABSTRACT:Y)'
    data = _search(query, page_size=max_results, result_type="core", timeout=timeout)
    results = ((data or {}).get("resultList") or {}).get("result") or []
    lines = []
    for r in results:
        pmid = r.get("pmid")           # ONLY a real PMID — never fall back to `id` (a PPR/preprint id is
        if not pmid:                   # not PMID-verifiable and must not be mislabelled [PMID:...]).
            continue
        auth = (r.get("authorString") or "").split(",")[0].strip() or "?"
        cite = f"{auth} {r.get('pubYear', '?')}, {r.get('journalTitle') or r.get('source') or '?'}"
        title = (r.get("title") or "").strip().rstrip(".")
        abstract = (r.get("abstractText") or "").replace("\n", " ").strip()
        if len(abstract) > abstract_chars:
            abstract = abstract[:abstract_chars].rsplit(" ", 1)[0] + "…"
        lines.append(f"[PMID:{pmid}] {cite} — {title}. {abstract}".strip())
    if not lines:
        return None
    header = (f"Top Europe PMC results for {target} in {phrase} (cite these PMIDs; you MAY mark verified=true "
              f"only for identifiers listed here):")
    return header + "\n" + "\n".join(f"  {ln}" for ln in lines)


def _pmid_exists(pmid: str, timeout: float) -> Optional[bool]:
    """True/False if Europe PMC does/doesn't return the id; None if the check itself could not run."""
    data = _search(f"EXT_ID:{pmid} AND SRC:MED", page_size=1, result_type="idlist", timeout=timeout)
    if data is None:
        return None
    return int(data.get("hitCount") or 0) >= 1


def verify_citations(result: dict, *, timeout: float = 8.0) -> dict:
    """Reconcile every citation.verified against Europe PMC ground truth (in place) + stamp a
    `_verification` summary. Best-effort: if the checks cannot run, leave flags and mark status
    'unavailable'. A citation with no PMID stays verified=false (identifier not checkable here)."""
    if not isinstance(result, dict):
        return result
    cites = []
    for ax in (result.get("axes") or []):
        if isinstance(ax, dict):
            cites += [c for c in (ax.get("citations") or []) if isinstance(c, dict)]
    for bs in (result.get("blind_spots") or []):
        if isinstance(bs, dict):
            cites += [c for c in (bs.get("citations") or []) if isinstance(c, dict)]
    checked = verified = flipped = 0
    ran = False
    seen: dict[str, Optional[bool]] = {}
    for c in cites:
        pmid = str(c.get("pmid") or "").strip()
        if not pmid:
            c["verified"] = False              # no identifier → not verifiable here
            continue
        if pmid not in seen:
            seen[pmid] = _pmid_exists(pmid, timeout)
        exists = seen[pmid]
        if exists is None:                     # the check could not run — leave the model's flag
            continue
        ran = True
        checked += 1
        was = bool(c.get("verified"))
        c["verified"] = exists
        verified += 1 if exists else 0
        flipped += 1 if was != exists else 0
    result["_verification"] = ({"status": "unavailable",
                                "note": "Europe PMC PMID verification could not run (no network / API error); "
                                        "citation.verified reflects the model's self-report, treat as unconfirmed."}
                               if (cites and not ran) else
                               {"status": "checked", "source": "europe_pmc",
                                "n_pmid_checked": checked, "n_verified": verified, "n_flipped": flipped})
    return result
