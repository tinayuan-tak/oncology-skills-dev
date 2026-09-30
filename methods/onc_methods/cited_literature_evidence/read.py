"""cited_literature_evidence.read — verdict-INERT gene×indication CITED-LITERATURE card (composing reader).

Single source of truth for "what does the literature SAY about {target} in {indication}, with
citations" — composes the two pinned, catalogued literature readers into ONE card. Lives in
analysis-methods (method-layer composition of two method-layer readers) so the target-contracts
card `cited-literature-evidence` can reference a SINGLE `methods:` entrypoint (the generic dispatcher
resolves only the first method), and the skills-side sibling
(`literature-risk-assessment/scripts/cited_evidence.py`) delegates here rather than duplicating the
compose logic.

Composes:
  - opentargets_europepmc_evidence (opentargets-europepmc-evidence-per-target-v1): OT co-occurrence
    literature VOLUME + RECENCY + the top cited statements (pmid/pmc/year/section/sentence).
  - pubtator3_gene_disease_relations (pubtator3-gene-disease-relations-per-gene-v1): PubTator BioREx
    typed relation DIRECTION (associate / cause / positive_correlate / negative_correlate / …) + PMIDs.

Both lanes are best-effort and NEVER raise, but they distinguish "we looked, nothing there" (a
genuine coverage gap → `no_evidence`) from "the lane never ran" (import missing / transient / creds /
broken-env, OR a re-raised infra fault the child reader deliberately propagated → `data_unavailable`).
An unavailable lane contributes an explicit `data_unavailable` sentinel (recorded in `notes`), NOT a
None that would collapse into `no_evidence` clean-zero. The card carries NO verdict and can change NO verdict/gate/sub-verdict — it
is descriptive CONTEXT/CONFIDENCE only, exactly like the risk-assessment layer. Extraction stays in the
underlying readers/products; this reader only assembles + trims for display, then FLATTENS the
display-relevant fields to top level (so a card's `outputs.summary_fields` can name emitted top-level
keys and the emission guard is satisfiable).
"""

from __future__ import annotations

from typing import Optional

METHOD_VERSION = "0.1.0"
CARD_VERSION = "0.2.0"  # preserved from the skills-side sibling this consolidates
DEFAULT_TOP_CITED = 8
SOURCE = "cited-literature-evidence"  # composite; provider manifests carried in `sources`


def _looks_english(sentence) -> bool:
    """Heuristic: is the text-mined sentence English (Latin-script)? True when >=90% of its alphabetic
    characters are ASCII. Used to prefer English sentences for DISPLAY (the OT europepmc corpus carries
    multilingual sentences; the top-by-co-occurrence sentence is sometimes non-English)."""
    s = str(sentence or "")
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return True  # no alphabetic content (e.g. all-numeric) — don't penalize
    return sum(1 for c in letters if ord(c) < 128) / len(letters) >= 0.9


def _prefer_english(papers: list, k: int) -> list:
    """Stable top-k that surfaces English-looking sentences FIRST (each group keeps its incoming
    co-occurrence order), so the displayed citations are readable without dropping the ranking."""
    eng = [p for p in papers if _looks_english(p.get("sentence"))]
    other = [p for p in papers if not _looks_english(p.get("sentence"))]
    return (eng + other)[:k]


def build_cited_evidence_card(
    target: str, indication: str, epmc: Optional[dict], relations: Optional[dict], *, top_cited: int = DEFAULT_TOP_CITED
) -> dict:
    """PURE (offline-testable): assemble the two reader outputs into the verdict-inert NESTED card.
    Either reader dict may be None (lane not provided) or carry a non-'ok' status
    (no_evidence/insufficient/data_unavailable) — in which case that half is None and its note is
    recorded. When neither lane emits evidence the overall status is data_unavailable (a lane could not
    run) > insufficient (target didn't resolve) > no_evidence (measured coverage gap). NEVER raises on
    shape.

    Contract preserved verbatim from the former skills-side sibling so its tests stay green when the
    sibling delegates here."""
    card = {
        "target": target,
        "indication": indication,
        "card_version": CARD_VERSION,
        "verdict": None,
        "verdict_inert": True,
        "sources": {},
        "notes": [],
    }

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
            "relations": relations.get("relations"),  # per-type {relation_type, n_publications, pmids}
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
        # Neither lane produced evidence. Distinguish, in precedence order:
        #   data_unavailable — at least one lane could NOT run (import missing / transient / creds /
        #     broken-env, surfaced by _compose_nested as a data_unavailable sentinel). We did not
        #     fully look, so this is NOT a measured zero — must not collapse to no_evidence.
        #   insufficient    — the target could not be resolved to an Ensembl gene id (BOTH readers
        #     report 'insufficient').
        #   no_evidence     — the target resolved and every lane returned a genuine coverage gap.
        reader_statuses = {d.get("status") for d in (epmc, relations) if isinstance(d, dict)}
        if "data_unavailable" in reader_statuses:
            card["status"] = "data_unavailable"
        elif "insufficient" in reader_statuses:
            card["status"] = "insufficient"
        else:
            card["status"] = "no_evidence"
    return card


def _flatten_for_card(card: dict) -> dict:
    """Project the NESTED card into the flat top-level summary_fields the target-contracts card declares
    (the emission guard requires every declared summary_field to be emitted as a top-level key). The
    nested `literature_evidence` / `relation_direction` blocks are retained for the display/LLM layer."""
    lit = card.get("literature_evidence") or {}
    rel = card.get("relation_direction") or {}
    relations = rel.get("relations") or []
    return {
        "cited_evidence_status": card.get("status"),
        "literature_scope": lit.get("indication_scope"),
        "paper_disease_mentions": lit.get("paper_disease_mentions"),
        "recent_mentions": lit.get("recent_mentions"),
        "n_diseases": lit.get("n_diseases"),
        "earliest_year": lit.get("earliest_year"),
        "latest_year": lit.get("latest_year"),
        "top_cited": lit.get("top_cited") or [],
        # relation DIRECTION summary — the typed-relation labels present (associate/cause/…), ordered by
        # publication support, plus the total. NOT vocabulary-pinned (PubTator BioREx owns the labels).
        "relation_types": [r.get("relation_type") for r in relations],
        "total_relation_publications": rel.get("total_publications"),
    }


def read_cited_literature_evidence(
    target: str, indication: str, modality: Optional[str] = None, *, top_cited: int = DEFAULT_TOP_CITED
) -> dict:
    """CARD ENTRYPOINT (generic-dispatch signature fn(target=, indication=)): best-effort compose the
    two analysis-methods readers into the verdict-inert card, FLATTENED for the card contract. Each
    reader is imported + called defensively; an unavailable lane simply contributes None. `modality` is
    accepted for dispatch-signature parity (unused — literature context is modality-independent)."""
    card = _compose_nested(target, indication, top_cited=top_cited)
    flat = _flatten_for_card(card)
    return {
        "target": target,
        "indication": indication,
        "method_version": METHOD_VERSION,
        "source": SOURCE,
        "verdict": None,
        "verdict_inert": True,
        **flat,
        # retained detail (not summary_fields): the human/LLM display layer reads these
        "literature_evidence": card.get("literature_evidence"),
        "relation_direction": card.get("relation_direction"),
        "sources": card.get("sources") or {},
        "notes": card.get("notes") or [],
        "status": card.get("status"),
    }


def _unavailable_arm(lane: str, exc: Exception) -> dict:
    """A lane the composing reader could NOT run — import missing / transient / creds / broken-env, OR
    a re-raised infra fault from the child reader (both arm readers practice absence discipline: they
    return `[]`/a status dict on a DEFINITIVE absence and re-RAISE transient/infra faults). Return an
    explicit `data_unavailable` sentinel so the card status is the honest "a lane never ran", NOT the
    None that the former blanket swallow collapsed into `no_evidence` clean-zero (defeating the child
    readers' distinction — #774/#776/#770 fail-toward-absence seam-except family). A genuine
    NoSuchKey/404/FileNotFound never reaches here as an exception (the child converts it to a status
    dict), but is_definitively_absent is still consulted so the recorded note is cause-accurate."""
    from onc_methods.target_id_sidecar import is_definitively_absent

    kind = "absent" if is_definitively_absent(exc) or isinstance(exc, FileNotFoundError) else "unavailable"
    return {"status": "data_unavailable", "_note": f"{lane} reader {kind}: {type(exc).__name__}: {exc}"}


def _compose_nested(target: str, indication: str, *, top_cited: int = DEFAULT_TOP_CITED) -> dict:
    """LIVE: best-effort compose the two readers into the NESTED card (the human-readable standalone
    shape). Each reader is imported + called defensively; a lane that cannot run does not raise but
    contributes an explicit `data_unavailable` sentinel (see `_unavailable_arm`), so an infra fault is
    distinguishable from a genuine measured coverage gap instead of both collapsing to `no_evidence`."""
    epmc = relations = None
    try:
        from onc_methods.opentargets_europepmc_evidence.read import read_europepmc_evidence

        epmc = read_europepmc_evidence(target, indication)
    except Exception as e:  # noqa: BLE001 — best-effort verdict-inert card; surface as data_unavailable, not None
        epmc = _unavailable_arm("europepmc", e)
    try:
        from onc_methods.pubtator3_gene_disease_relations.read import read_gene_disease_relations

        relations = read_gene_disease_relations(target, indication)
    except Exception as e:  # noqa: BLE001
        relations = _unavailable_arm("pubtator", e)
    return build_cited_evidence_card(target, indication, epmc, relations, top_cited=top_cited)


# Back-compat alias for the standalone / risk-assessment sibling: the NESTED live card.
cited_evidence = _compose_nested


def _main(argv=None):
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Verdict-inert gene×indication cited-literature card (flattened).")
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--top-cited", type=int, default=DEFAULT_TOP_CITED)
    args = ap.parse_args(argv)
    print(
        json.dumps(
            read_cited_literature_evidence(args.target, args.indication, top_cited=args.top_cited),
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    _main()
