#!/usr/bin/env python3
"""field_role_classifier.py — OFFLINE, data-driven field-role proposer (P5, issue #1509).

WHY
---
Field roles in `skills/<skill>/field_disposition.yaml` were originally auto-DRAFTED by a name-shape
heuristic whose own fallback was unconditionally `display` — a draft, never a decision (the ledger's
`_meta` says so). This tool replaces that heuristic with a DATA-DRIVEN proposal:

    role  ≈  descriptor-prior  ×  census reach  ×  value-shape fallback

over the DECLARED field set of a card, so a human reviewing a row reads a proposal grounded in what
actually reads the field, not in its name.

THE PREDICATE (the load-bearing rule)
-------------------------------------
    propose `signal`  ⇔  the field has EXACT, census-visible, SIGNAL-BEARING reach.

`exact` = a literal card id AND a literal field name at one read site (`name_only` over-credits every
card declaring the name, so it never proposes signal). SIGNAL-BEARING excludes:

  * `capsule` reach — a capsule surfaces both decisive calls (`isoform_expression_class`) and context
    inputs (`distribution_pattern`, `coefficient_of_variation`) identically, so capsule-ONLY reach
    cannot separate the two. Such fields are surfaced as REVIEW candidates, never auto-promoted.
  * POWER / qualifier salience slots (`n_field`, `strata_array`, `omnibus_field`) — the ruler reads
    them for support, not as a call, so a bare `n_cell_lines_evaluated` must not promote on that reach
    (see `field_disposition.salience_signal_readers`).
  * cross-repo reads — the census scrapes the SKILLS tree only (`field_disposition.py`), so a field
    whose only interpreter is the analysis-methods property resolver (`distribution_pattern`,
    `coefficient_of_variation`, the `fraction_*`/lineage inputs) is census-invisible here and surfaces
    as a REVIEW candidate. Teaching the census to read the analysis-methods tree is a separate,
    AM-sibling-gated follow-up (a review candidate is the correct disposition until then).

So this tool never writes the ledger; it proposes and, for anything it cannot decide from reach, hands
the human a REVIEW candidate with the exact reach it found. A capsule-only or cross-repo-input field is
a review candidate BY DESIGN, not a bug — that is the P5 disposition the author confirmed for Card 1.

NOT A CI TEST. Re-runnable for the fleet phase (G3.2): `python3 field_role_classifier.py [--card ID]`.
READ-ONLY.

USAGE
    python3 field_role_classifier.py                 # every card that has SALIENCE/reach, vs the ledger
    python3 field_role_classifier.py --card cellline-rna-distribution
    python3 field_role_classifier.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# make `_skills_common` importable whether run from the repo or a worktree
_SKILLS_ROOT = Path(__file__).resolve().parents[1]  # .../skills

from _skills_common import field_descriptor as fdesc  # noqa: E402
from _skills_common import field_disposition as fd  # noqa: E402
from _skills_common import field_disposition_contract as fdc  # noqa: E402
from _skills_common import field_disposition_ledger as fdl  # noqa: E402

_CARD1 = "cellline-rna-distribution"

# ── the reach taxonomy ─────────────────────────────────────────────────────────────────────────────
# Census reader kinds whose EXACT evidence, on its own, is a decisive read into a claim/verdict/gate.
# salience is handled separately (slot-aware, via salience_signal_readers) — a salience pair here is
# credited only when it is read through a SIGNAL-BEARING slot.
AUTO_SIGNAL_KINDS = frozenset({"gating_rule", "claim_passthrough", "question_table", "skill_code"})
# Kinds that reach a field but do NOT, alone, decide signal-vs-context: capsule (surfaces both) and
# display_rule (a display projection). A field whose only exact reach is one of these is a REVIEW
# candidate.
AMBIGUOUS_KINDS = frozenset({"capsule", "display_rule"})

# descriptor role -> the disposition to FALL BACK to when reach does not decide it.
_DESCRIPTOR_FALLBACK = {
    fdesc.ROLE_N: "context",
    fdesc.ROLE_STRATA: "display",
    fdesc.ROLE_LABEL: "context",
    fdesc.ROLE_ENVELOPE: "provenance",
}
# descriptor roles that DESCRIBE a decisive call — an unread one is a should-be-signal to REVIEW.
_DECISIVE_DESCRIPTOR_ROLES = frozenset(
    {
        fdesc.ROLE_EFFECT,
        fdesc.ROLE_SIGNIFICANCE,
        fdesc.ROLE_FRAME_VALUE,
        fdesc.ROLE_CATEGORICAL,
        fdesc.ROLE_EXTRA_SCALAR,
    }
)


def _card_to_measurement_type() -> dict:
    """`{card_id: measurement_type}` inverted from the census helper (first mt wins on the rare tie)."""
    out: dict[str, str] = {}
    for mt, cards in fd._card_measurement_types().items():
        for cid in cards or ():
            out.setdefault(cid, mt)
    return out


def classify_card(card_id: str, cen: dict, sig_salience: set, card_mt: dict) -> list[dict]:
    """One proposal row per declared field of `card_id`. Pure function of the prebuilt census."""
    declared = fd.declared_fields().get(card_id) or []
    mt = card_mt.get(card_id)
    rows = []
    for field in declared:
        readers = cen.get((card_id, field)) or {"exact": set(), "name_only": set()}
        exact = set(readers.get("exact") or ())
        auto = exact & AUTO_SIGNAL_KINDS
        cross = exact & set(fd.CROSS_REPO_KINDS)
        sig_sal = (card_id, field) in sig_salience
        signal_reach = sorted(auto) + (["salience(signal-slot)"] if sig_sal else [])
        descriptor_role = fdesc.classify_field(field, mt)
        reach_axis = fdc.interpretation_reach_for(readers)

        if signal_reach:
            proposal, review = "signal", False
            basis = "exact signal-bearing reach: " + ", ".join(signal_reach)
        elif cross:
            # CROSS-REPO resolver input (issue #1525). The field IS consumed — by the analysis-methods
            # property resolver — so it is NEITHER an orphan NOR a review candidate; it earns cross-repo
            # interpretation_reach. But the raw measurement is a context INPUT, not itself a signal: the
            # signal attaches to the RESOLVED property (`expression_properties`), never to the raw skills
            # field. So propose `context`, decided (review=False). This replaces the old REVIEW-candidate
            # fallback that a cross-repo-only field previously fell into.
            proposal, review = "context", False
            basis = (
                f"cross-repo reach via {sorted(cross)} (analysis-methods property resolver) — the raw "
                "measurement is a context input; the signal attaches to the resolved property, so "
                "role=context, NOT signal"
            )
        elif exact:
            # reached, but only by kinds that cannot decide signal-vs-context on their own.
            proposal = _DESCRIPTOR_FALLBACK.get(descriptor_role, "context")
            review = True
            why = []
            if exact & AMBIGUOUS_KINDS:
                why.append(
                    "capsule/display reach cannot separate a decisive call from a context input"
                    if "capsule" in exact
                    else "display-rule reach is a projection, not a call"
                )
            if "salience" in exact and not sig_sal:
                why.append("salience reach is through a POWER/qualifier slot (n/strata/omnibus), not a call")
            basis = f"reach via {sorted(exact)} only — " + "; ".join(why or ["ambiguous reach"]) + " → hand-review"
        else:
            # no exact reach at all — fall back to the descriptor prior / value shape.
            review = descriptor_role in _DECISIVE_DESCRIPTOR_ROLES
            proposal = _DESCRIPTOR_FALLBACK.get(descriptor_role, "context")
            if review:
                basis = (
                    f"NO census reach; descriptor role={descriptor_role} describes a decisive call — an "
                    "unread should-be-signal → hand-review (wire a reader, or waive naming the consumer)"
                )
            else:
                basis = f"NO census reach; descriptor role={descriptor_role} → {proposal} by prior"
        rows.append(
            {
                "card": card_id,
                "field": field,
                "exact_reach": sorted(exact),
                "name_only_reach": sorted(readers.get("name_only") or ()),
                "descriptor_role": descriptor_role,
                "proposed": proposal,
                "interpretation_reach": reach_axis,
                "review_candidate": review,
                "basis": basis,
            }
        )
    return rows


def diff_against_ledger(rows: list[dict], ledger_doc: dict) -> list[dict]:
    """Attach the current ledger role/reviewed to each proposal and flag where they disagree."""
    out = []
    for r in rows:
        cur = (ledger_doc.get(r["card"]) or {}).get(r["field"]) or {}
        r = {
            **r,
            "current_role": cur.get("role"),
            "current_reviewed": bool(cur.get("reviewed")),
            "agrees": cur.get("role") == r["proposed"],
        }
        out.append(r)
    return out


def _cards_with_reach(cen: dict) -> list[str]:
    return sorted({c for (c, _f), r in cen.items() if r["exact"] or r["name_only"]})


def _ledger_for(card_id: str) -> dict:
    """The discovered ledger doc that contains `card_id` (empty dict if none)."""
    for _skill, path in fdl.discover_ledgers(_SKILLS_ROOT).items():
        doc = fdl.load_ledger(path)
        if card_id in doc:
            return doc
    return {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--card", default=None, help="one card id (default: every card with reach)")
    ap.add_argument("--json", action="store_true", help="emit the proposal rows as JSON")
    ap.add_argument("--only-diffs", action="store_true", help="print only rows where proposal != current role")
    args = ap.parse_args(argv)

    cen = fd.census(_SKILLS_ROOT)
    sig_salience = fd.salience_signal_readers()
    card_mt = _card_to_measurement_type()

    cards = [args.card] if args.card else _cards_with_reach(cen)
    all_rows: list[dict] = []
    for cid in cards:
        rows = classify_card(cid, cen, sig_salience, card_mt)
        all_rows += diff_against_ledger(rows, _ledger_for(cid))

    if args.only_diffs:
        all_rows = [r for r in all_rows if not r["agrees"]]

    if args.json:
        print(json.dumps(all_rows, indent=2, sort_keys=True))
        return 0

    for cid in cards:
        crows = [r for r in all_rows if r["card"] == cid]
        if not crows:
            continue
        print(f"\n=== {cid} ===")
        print(f"{'field':32} {'proposed':10} {'current':10} {'rev?':4} basis")
        for r in crows:
            flag = "R" if r["review_candidate"] else ("=" if r["agrees"] else "Δ")
            print(f"{r['field']:32} {r['proposed']:10} {str(r['current_role']):10} {flag:4} {r['basis']}")
    n_sig = sum(1 for r in all_rows if r["proposed"] == "signal")
    n_rev = sum(1 for r in all_rows if r["review_candidate"])
    n_diff = sum(1 for r in all_rows if not r["agrees"])
    print(
        f"\n{len(all_rows)} fields over {len(cards)} card(s): {n_sig} proposed signal, "
        f"{n_rev} review candidates, {n_diff} disagree with the current ledger role."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
