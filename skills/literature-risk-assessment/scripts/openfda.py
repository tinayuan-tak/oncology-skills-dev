#!/usr/bin/env python3
"""openfda — FAERS post-market adverse-event + label boxed-warning pharmacovigilance (PR-7).

An escalate-only, CONTEXT-TIER safety annotation for the literature-risk 6-dim agent, sourced from the
public openFDA API (no key for moderate volume). openFDA is keyed by DRUG, not gene target, so the caller
supplies the target's drugs (run.py resolves them from the evidence-package's clinical-precedent /
competitor-landscape cards — the target→drug hop, no new cross-repo dependency).

Two signals per drug:
  - FAERS reaction counts (drug/event, aggregated by MedDRA preferred term) — real post-market AE volume.
  - label boxed warning (drug/label `boxed_warning`) — the regulator's most severe labelled risk.

GOVERNANCE: FAERS is a LIVING database (counts drift daily) and openFDA is a live source, so the
annotation records an `as_of` date and `source: openfda`; it inherits the skill's context-tier,
non-citable-in-nominations stance and is ESCALATE-ONLY (it can raise a safety flag, never lower one).
Best-effort throughout: any API/parse failure yields None/[] and never raises into the caller.

The parse helpers (`_parse_faers_counts`, `_parse_label_boxed`) are PURE and unit-tested offline; the two
thin HTTP wrappers mirror pubmed_search's style (stdlib urllib, courtesy throttle, bounded backoff).
"""

from __future__ import annotations

import datetime as _dt
import json
import time
import urllib.error
import urllib.parse
import urllib.request

_EVENT_URL = "https://api.fda.gov/drug/event.json"
_LABEL_URL = "https://api.fda.gov/drug/label.json"
_UA = {"User-Agent": "oncology-skills/1.7 (literature-risk pharmacovigilance)"}
_TIMEOUT = 20.0
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_BOXED_WARNING_CHARS = 600  # cap the labelled boxed-warning text carried into the annotation


# ------------------------------------------------------------------ network -----
def _get_json(url: str, *, timeout_s: float = _TIMEOUT, max_retries: int = 2):
    """Best-effort GET → parsed JSON with bounded exponential backoff on transient 429/5xx. openFDA
    returns HTTP 404 with a NOT_FOUND body for a query with zero matches — that is a legitimate empty
    result (not an error), so we return the parsed body and let the caller see empty `results`."""
    delay = 1.0
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=timeout_s) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:  # openFDA "no matches" — a valid empty result, not a transient failure
                return None
            if e.code not in _RETRYABLE_STATUS or attempt >= max_retries:
                return None
        except Exception:  # noqa: BLE001 — connection/JSON error: bounded retry, then degrade to None
            if attempt >= max_retries:
                return None
        time.sleep(delay)
        delay *= 2
    return None


# --------------------------------------------------------------------- pure -----
def _drug_search_clause(drug: str, *, label: bool = False) -> str:
    """PURE: an openFDA search clause matching a drug across name fields (generic / substance, plus brand
    for the label endpoint). Quoted phrase → matches multi-token names like 'mirvetuximab soravtansine'."""
    d = (drug or "").strip().strip('"')
    if not d:
        return ""
    if label:
        fields = ("openfda.generic_name", "openfda.brand_name", "openfda.substance_name")
    else:
        fields = ("patient.drug.openfda.generic_name", "patient.drug.openfda.substance_name")
    return "(" + " OR ".join(f'{f}:"{d}"' for f in fields) + ")"


def _parse_faers_counts(data: dict, *, limit: int) -> list:
    """PURE: openFDA drug/event count response → [{term, count}] (top `limit`, order preserved)."""
    out = []
    for r in (data or {}).get("results") or []:
        term, count = r.get("term"), r.get("count")
        if term and isinstance(count, int):
            out.append({"term": term, "count": count})
        if len(out) >= limit:
            break
    return out


def _parse_label_boxed(data: dict) -> dict | None:
    """PURE: openFDA drug/label response → boxed-warning summary, or None when no label/boxed warning."""
    results = (data or {}).get("results") or []
    if not results:
        return None
    bw = results[0].get("boxed_warning")
    text = " ".join(bw).strip() if isinstance(bw, list) else (bw or "")
    if not text:
        return None
    return {"has_boxed_warning": True, "boxed_warning": text[:_BOXED_WARNING_CHARS]}


# ---------------------------------------------------------------- high level -----
def faers_top_reactions(drug: str, *, limit: int = 8, timeout_s: float = _TIMEOUT) -> list:
    """Top MedDRA reaction terms + report counts for a drug (FAERS). Best-effort → []."""
    clause = _drug_search_clause(drug)
    if not clause:
        return []
    url = f"{_EVENT_URL}?" + urllib.parse.urlencode(
        {"search": clause, "count": "patient.reaction.reactionmeddrapt.exact", "limit": str(limit)}
    )
    return _parse_faers_counts(_get_json(url, timeout_s=timeout_s), limit=limit)


def label_boxed_warning(drug: str, *, timeout_s: float = _TIMEOUT) -> dict | None:
    """The drug's labelled boxed warning (openFDA drug/label). Best-effort → None."""
    clause = _drug_search_clause(drug, label=True)
    if not clause:
        return None
    url = f"{_LABEL_URL}?" + urllib.parse.urlencode({"search": clause, "limit": "1"})
    return _parse_label_boxed(_get_json(url, timeout_s=timeout_s))


def pharmacovigilance(drugs, *, per_drug_reactions: int = 6, max_drugs: int = 6, timeout_s: float = _TIMEOUT):
    """Aggregate FAERS reactions + label boxed warnings across a target's drugs into one escalate-only
    safety annotation. `drugs` is the caller-resolved drug list (target→drug hop). Returns None when no
    drug yields any openFDA signal (nothing to escalate). Records an `as_of` date — FAERS is a living DB."""
    seen, ordered = set(), []
    for d in drugs or []:
        key = (d or "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            ordered.append(d.strip())
        if len(ordered) >= max_drugs:
            break
    if not ordered:
        return None

    reactions, boxed = [], []
    for d in ordered:
        for rx in faers_top_reactions(d, limit=per_drug_reactions, timeout_s=timeout_s):
            reactions.append({**rx, "drug": d})
        bw = label_boxed_warning(d, timeout_s=timeout_s)
        if bw:
            boxed.append({"drug": d, "boxed_warning": bw["boxed_warning"]})

    if not reactions and not boxed:
        return None
    reactions.sort(key=lambda r: r["count"], reverse=True)
    return {
        "source": "openfda",
        "as_of": _dt.date.today().isoformat(),  # FAERS is a living DB — annotation is as-of-date context
        "escalate_only": True,
        "drugs_queried": ordered,
        "boxed_warning_drugs": boxed,
        "top_reactions": reactions[: per_drug_reactions * 2],
    }
