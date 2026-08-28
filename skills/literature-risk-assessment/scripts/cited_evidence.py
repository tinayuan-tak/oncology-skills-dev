"""cited_evidence — verdict-INERT gene×indication CITED-LITERATURE card.

Composes the two pinned, catalogued literature products into a single "what does the literature say
about {target} in {indication}, with citations" card:

  - opentargets_europepmc_evidence (opentargets-europepmc-evidence-per-target-v1): OT co-occurrence
    literature VOLUME + RECENCY + the top cited statements (pmid/pmc/year/section/sentence).
  - pubtator3_gene_disease_relations (pubtator3-gene-disease-relations-per-gene-v1): PubTator BioREx
    typed relation DIRECTION (associate / cause / positive_correlate / negative_correlate / …) + PMIDs.

Both readers are best-effort (analysis-methods absent / product missing / creds → that lane is just
absent). The card carries NO verdict and can change NO verdict/gate/sub-verdict — it is descriptive
CONTEXT/CONFIDENCE only (tier: context), exactly like the risk-assessment layer. Extraction stays in
the reader/product; this card only assembles + trims for display.
"""
from __future__ import annotations

from typing import Optional

CARD_VERSION = "0.2.0"
DEFAULT_TOP_CITED = 8


def _looks_english(sentence) -> bool:
    """Heuristic: is the text-mined sentence English (Latin-script)? True when >=90% of its alphabetic
    characters are ASCII. Used to prefer English sentences for DISPLAY (the OT europepmc corpus carries
    multilingual sentences; the top-by-co-occurrence sentence is sometimes non-English)."""
    s = str(sentence or "")
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return True   # no alphabetic content (e.g. all-numeric) — don't penalize
    return sum(1 for c in letters if ord(c) < 128) / len(letters) >= 0.9


def _prefer_english(papers: list, k: int) -> list:
    """Stable top-k that surfaces English-looking sentences FIRST (each group keeps its incoming
    co-occurrence order), so the displayed citations are readable without dropping the ranking."""
    eng = [p for p in papers if _looks_english(p.get("sentence"))]
    other = [p for p in papers if not _looks_english(p.get("sentence"))]
    return (eng + other)[:k]


def build_cited_evidence_card(target: str, indication: str, epmc: Optional[dict],
                              relations: Optional[dict], *, top_cited: int = DEFAULT_TOP_CITED) -> dict:
    """PURE (offline-testable): assemble the two reader outputs into the verdict-inert card. Either
    reader dict may be None (lane unavailable) or carry a non-'ok' status (absence/insufficient) — in
    which case that half is None and its note is recorded. NEVER raises on shape."""
    card = {"target": target, "indication": indication, "card_version": CARD_VERSION,
            "verdict": None, "verdict_inert": True, "sources": {}, "notes": []}

    # --- OT europepmc cited evidence (co-occurrence; volume + recency + cited sentences)
    if isinstance(epmc, dict) and epmc.get("status") == "ok":
        card["literature_evidence"] = {
            "indication_scope": epmc.get("europepmc_scope") or epmc.get("indication_scope"),
            # NOTE: these are SUMMED over the indication's disease subtypes — a paper co-occurring with
            # N subtypes counts N times. They are paper×disease MENTIONS, NOT distinct papers (the
            # product carries per-(gene,disease) counts, so a distinct-across-subtypes count isn't
            # available). n_diseases is surfaced so the inflation is visible.
            "paper_disease_mentions": epmc.get("total_papers"),
            "recent_mentions": epmc.get("n_papers_recent"),
            "n_diseases": epmc.get("n_diseases"),
            "earliest_year": epmc.get("earliest_year"),
            "latest_year": epmc.get("latest_year"),
            "top_cited": _prefer_english(list(epmc.get("top_papers") or []), top_cited),
            "_metric_note": "paper_disease_mentions/recent_mentions are summed over disease subtypes "
                            "(mentions, not distinct papers); see n_diseases",
        }
        card["sources"]["europepmc_evidence"] = epmc.get("source")
    else:
        card["literature_evidence"] = None
        if isinstance(epmc, dict):
            card["notes"].append(f"europepmc: {epmc.get('_note') or epmc.get('status') or 'unavailable'}")
        else:
            card["notes"].append("europepmc: reader unavailable")

    # --- PubTator typed-relation DIRECTION
    if isinstance(relations, dict) and relations.get("status") == "ok":
        card["relation_direction"] = {
            "indication_scope": relations.get("relation_scope") or relations.get("indication_scope"),
            "mesh_id_source": relations.get("mesh_id_source"),
            "total_publications": relations.get("total_publications"),
            "relations": relations.get("relations"),   # per-type {relation_type, n_publications, pmids}
        }
        card["sources"]["pubtator_relations"] = relations.get("source")
    else:
        card["relation_direction"] = None
        if isinstance(relations, dict):
            card["notes"].append(f"pubtator: {relations.get('_note') or relations.get('status') or 'unavailable'}")
        else:
            card["notes"].append("pubtator: reader unavailable")

    if card["literature_evidence"] or card["relation_direction"]:
        card["status"] = "ok"
    else:
        # distinguish a bad/unresolvable input ('insufficient' from a reader) from a genuine coverage
        # gap ('no_evidence'): if the gene didn't resolve, BOTH readers report 'insufficient'.
        reader_statuses = {d.get("status") for d in (epmc, relations) if isinstance(d, dict)}
        card["status"] = "insufficient" if "insufficient" in reader_statuses else "no_evidence"
    return card


def cited_evidence(target: str, indication: str, *, top_cited: int = DEFAULT_TOP_CITED) -> dict:
    """LIVE: best-effort compose the two analysis-methods readers into the verdict-inert card.
    Each reader is imported + called defensively; an unavailable lane simply contributes None."""
    epmc = relations = None
    try:
        from methods.opentargets_europepmc_evidence.read import read_europepmc_evidence
        epmc = read_europepmc_evidence(target, indication)
    except Exception:  # noqa: BLE001 — best-effort; missing method/product must not break the card
        epmc = None
    try:
        from methods.pubtator3_gene_disease_relations.read import read_gene_disease_relations
        relations = read_gene_disease_relations(target, indication)
    except Exception:  # noqa: BLE001
        relations = None
    return build_cited_evidence_card(target, indication, epmc, relations, top_cited=top_cited)


def _main(argv=None):
    import argparse, json
    ap = argparse.ArgumentParser(description="Verdict-inert gene×indication cited-literature card.")
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--top-cited", type=int, default=DEFAULT_TOP_CITED)
    args = ap.parse_args(argv)
    print(json.dumps(cited_evidence(args.target, args.indication, top_cited=args.top_cited),
                     indent=2, default=str))


if __name__ == "__main__":
    _main()
