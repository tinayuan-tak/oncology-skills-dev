"""C0f facet builder — next_evidence / value-of-information (epic #1986, #2009). BUILT.

next_evidence is the sixth core L4 product (docs §"The six core L4 products" #6): what additional
evidence would most change or resolve the assessment — ``{evidence, resolves}`` — the step that makes L4
more than reporting. It is derived DETERMINISTICALLY from the sibling ``facet_critical_unknowns`` builder
(called here as a pure function over the SAME ``ctx`` — no edit to that module, per the cross-facet rule:
import + call a sibling's pure ``build``, never edit it) plus the NOT_ASSESSED / weakly-resolved domains
it already names. No new measurement, no LLM authorship, no invented assays: every entry's specificity is
bounded by what the cited unknown itself already states — "export an L3d story for domain X" or
"strengthen/reconcile domain X's L3d story" — never a speculative assay or wishlist item.

Deterministic evidence-ask per unknown status (the ONLY vocabulary this module uses — a closed,
structural map over ``schema.UNKNOWN_STATUS``, never free text authored per-target):
  * NOT_ASSESSED  -> "export an L3d story for the {domain} domain" (the honest value-of-information read
                      for a domain the framework knows how to assess but has not yet exported — this IS
                      what the KRAS flagship's degraded-honestly read looks like: every NOT_ASSESSED
                      domain yields exactly one such entry, never fabricated science).
  * UNKNOWN       -> "strengthen cross-source corroboration for the {domain} domain's L3d story" (the
                      domain WAS assessed but its central question did not resolve cleanly).
  * CONTRADICTED  -> "reconcile the discordant cross-source read for the {domain} domain's L3d story".
  * KNOWN         -> nothing to ask for; contributes no entry (the domain already resolved cleanly).

Each entry's ``resolves`` list names the unknown(s) it would resolve BY REFERENCE (domain + question +
status, mirroring the critical_unknowns entry verbatim) and its ``claim_ids`` are the SAME resolvable
refs the critical_unknowns entry already cites (the presence evidence backing a NOT_ASSESSED call, or the
assessed domain's own story refs for UNKNOWN/CONTRADICTED) — so every statement here traces back exactly
as the sibling facet's does; this module invents no new ref.

Absence path ("missing != negative", never fabricated):
  * When ``facet_critical_unknowns.build(ctx)`` itself returns None (nothing anywhere to cite — the KRAS
    flagship reality), this facet also returns None: there is no resolvable unknown to derive a
    value-of-information entry from.
  * When critical_unknowns DOES resolve but every domain is KNOWN (nothing left to ask for), this facet
    returns None as well — an honest-empty "no further evidence needed" is the same None-omission the
    sibling facets use, never an empty placeholder object.

Uniform facet-builder contract: ``build(ctx) -> Optional[dict]``. See schema.py / assembler.FACET_BUILDERS.
"""

from __future__ import annotations

from typing import Optional

from _skills_common.l4_synthesis import facet_critical_unknowns
from _skills_common.l4_synthesis import schema as S
from _skills_common.l4_synthesis.context import L4Context

BUILT = True

# Closed, structural vocabulary — the ONLY evidence-ask text this module authors, keyed off the unknown's
# own status. Deliberately generic over "domain" (never a speculative assay or invented measurement type)
# so the specificity never exceeds what the cited unknown itself already states.
_EVIDENCE_ASK = {
    "NOT_ASSESSED": "export an L3d story for the {domain} domain",
    "UNKNOWN": "strengthen cross-source corroboration for the {domain} domain's L3d story",
    "CONTRADICTED": "reconcile the discordant cross-source read for the {domain} domain's L3d story",
}


def build(ctx: L4Context) -> Optional[dict]:
    cu = facet_critical_unknowns.build(ctx)
    if cu is None:
        return None  # nothing resolvable anywhere to derive a value-of-information entry from

    unknowns = cu.get("critical_unknowns") or []
    # facet_critical_unknowns.build emits exactly one entry per S.KNOWN_DOMAINS, in that fixed order (its
    # own test helper -- _by_domain -- relies on this same positional zip); recovering the domain name
    # this way keeps this module independent of the entry's internal shape (no bare ``domain`` field is
    # guaranteed on every claim ref -- an assessed domain's own provenance refs carry only ``vector``).
    domains_in_order = list(S.KNOWN_DOMAINS[: len(unknowns)])

    entries: list = []
    statements: list = []
    for entry_domain, unknown in zip(domains_in_order, unknowns):
        status = unknown.get("status")
        ask = _EVIDENCE_ASK.get(status)
        if ask is None:
            continue  # KNOWN (or an unrecognized status) -> nothing to ask for -> no entry
        refs = unknown.get("claim_ids") or []
        evidence = ask.format(domain=entry_domain)
        resolves = [
            {
                "domain": entry_domain,
                "question": unknown.get("question"),
                "status": status,
            }
        ]
        entries.append({"evidence": evidence, "resolves": resolves, "claim_ids": list(refs)})
        statements.append(S.statement(f"{evidence} -> resolves: {entry_domain} ({status})", refs))

    if not entries:
        return None  # every domain already KNOWN -> no further evidence to ask for -> honest omission

    return {
        "facet": S.FACET_NEXT_EVIDENCE,
        "layer": S.L4_LAYER,
        "built_by": "C0f #2009",
        "next_evidence": entries,
        "statements": statements,
        "integration_method": S.INTEGRATION_METHOD,
        "_disclaimer": (
            "L4 next_evidence (C0f #2009) — DETERMINISTIC value-of-information facet derived from the "
            "critical_unknowns facet (a sibling module called as a pure function, never edited), "
            "verdict-INERT (reads no verdict, feeds no rule/veto/resolver, moves no emitted field), no "
            "new measurement, no LLM-authored wishlist. Each entry's evidence-ask is bounded by what the "
            "cited unknown already states (export a missing L3d domain / strengthen or reconcile a "
            "weakly-resolved one) — never a speculative assay. Every statement drills back to the cited "
            "L2/L3 claim IDs."
        ),
    }
