"""Guards for the L4 liabilities-vs-contradictions facet builder (epic #1986, C0c #2006).

Liabilities and contradictions are DISTINCT products (docs §"The six core L4 products" #3): a liability
is an adverse claim (cites its own claim ref); a contradiction is a two-claim evidence RELATIONSHIP
(``{between:[ref,ref], note}``) — never a low score, never folded into liabilities. These tests pin the
facet's real EPCAM/COADREAD flagship output, its determinism, its claim-ID traceability (mutation teeth),
the honest absence path (no upstream L3d -> None, never fabricated), and the disjointness invariant
(a contradiction never doubles as a liability entry and vice versa).
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2]  # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.l4_synthesis import (  # noqa: E402
    assemble_target_synthesis,
    resolve_ref,
    unresolved_refs,
)
from _skills_common.l4_synthesis import (
    facet_liabilities_contradictions as FLC,
)
from _skills_common.l4_synthesis import schema as S  # noqa: E402
from _skills_common.l4_synthesis.assembler import L4TraceabilityError  # noqa: E402
from _skills_common.l4_synthesis.context import POOLED, read_context  # noqa: E402

GOLDEN = SKILLS / "tumor-presence" / "tests" / "fixtures" / "epcam_coadread_decision.json"


def _golden():
    return json.loads(GOLDEN.read_text())


# ── registration ─────────────────────────────────────────────────────────────────────────────────
def test_module_is_built_and_registered():
    assert FLC.BUILT is True
    from _skills_common.l4_synthesis import assembler as A

    names_to_modules = dict(A.FACET_BUILDERS)
    assert names_to_modules[S.FACET_LIABILITIES_CONTRADICTIONS] is FLC


# ── flagship end-to-end (EPCAM) ──────────────────────────────────────────────────────────────────
def test_liabilities_contradictions_emits_for_epcam_flagship():
    syn = assemble_target_synthesis(_golden())
    assert S.FACET_LIABILITIES_CONTRADICTIONS in syn["facets"]
    fr = syn["facets"][S.FACET_LIABILITIES_CONTRADICTIONS]
    assert fr["facet"] == S.FACET_LIABILITIES_CONTRADICTIONS
    assert fr["layer"] == "L4"

    # the abundance chapter carries the golden's one caveat -> exactly one liability, citing it.
    assert len(fr["liabilities"]) == 1
    lia = fr["liabilities"][0]
    assert lia["domain"] == "tumor_presence"
    assert lia["aspect"] == "abundance"
    assert "MS-protein" in lia["liability"]
    assert lia["claim_ids"] == [{"claim_id": "abundance_concordance", "vector": POOLED, "domain": "tumor_presence"}]

    # central node (concordant) vs abundance chapter (a directional split, not "_concordant") -> one contradiction.
    assert len(fr["contradictions"]) == 1
    con = fr["contradictions"][0]
    assert con["between"] == [
        {"claim_id": "tumor_presence_concordance", "vector": POOLED, "domain": "tumor_presence"},
        {"claim_id": "abundance_concordance", "vector": POOLED, "domain": "tumor_presence"},
    ]
    assert "directional split" in con["note"]


def test_liabilities_and_contradictions_stay_distinct_products():
    """The load-bearing rule: a contradiction entry never appears in the liabilities list (by shape or by
    claim-ref set) and vice versa — conflating them is the known failure mode this facet must not repeat."""
    syn = assemble_target_synthesis(_golden())
    fr = syn["facets"][S.FACET_LIABILITIES_CONTRADICTIONS]
    for lia in fr["liabilities"]:
        assert "between" not in lia  # a liability is never shaped like a contradiction
        assert "note" not in lia
    for con in fr["contradictions"]:
        assert "liability" not in con  # a contradiction is never shaped like a liability
        assert "between" in con and "note" in con
        assert len(con["between"]) == 2  # a relationship always names exactly two claims

    liability_ref_sets = {tuple(sorted(r["claim_id"] for r in lia["claim_ids"])) for lia in fr["liabilities"]}
    contradiction_ref_sets = {tuple(sorted(r["claim_id"] for r in con["between"])) for con in fr["contradictions"]}
    assert liability_ref_sets.isdisjoint(contradiction_ref_sets)


# ── determinism ──────────────────────────────────────────────────────────────────────────────────
def test_deterministic_byte_stable():
    a = assemble_target_synthesis(_golden())
    b = assemble_target_synthesis(_golden())
    assert json.dumps(a["facets"][S.FACET_LIABILITIES_CONTRADICTIONS], sort_keys=True) == json.dumps(
        b["facets"][S.FACET_LIABILITIES_CONTRADICTIONS], sort_keys=True
    )


def test_build_does_not_mutate_context_or_decision():
    d = _golden()
    before = json.dumps(d, sort_keys=True)
    ctx = read_context(d)
    FLC.build(ctx)
    assert json.dumps(d, sort_keys=True) == before


# ── claim-ID traceability ────────────────────────────────────────────────────────────────────────
def test_every_statement_and_entry_traces_to_a_resolvable_claim_id():
    d = _golden()
    ctx = read_context(d)
    syn = assemble_target_synthesis(d)
    assert unresolved_refs(ctx, syn) == []  # full envelope-level traceability (all facets)

    fr = syn["facets"][S.FACET_LIABILITIES_CONTRADICTIONS]
    for lia in fr["liabilities"]:
        for ref in lia["claim_ids"]:
            assert resolve_ref(ctx, ref)
    for con in fr["contradictions"]:
        for ref in con["between"]:
            assert resolve_ref(ctx, ref)


def test_broken_claim_id_in_a_liability_red_fails_the_assemble(monkeypatch):
    """MUTATION TEETH: a liability citing an unresolvable claim ID must red-fail the assemble."""
    real_build = FLC.build

    def poisoned(ctx):
        fr = copy.deepcopy(real_build(ctx))
        fr["liabilities"].append(
            {
                "domain": "tumor_presence",
                "aspect": "fabricated",
                "liability": "fabricated liability",
                "claim_ids": [S.claim_ref("NOT_A_REAL_CLAIM_ID", vector=POOLED)],
            }
        )
        fr["statements"].append(
            S.statement("fabricated liability", [S.claim_ref("NOT_A_REAL_CLAIM_ID", vector=POOLED)])
        )
        return fr

    monkeypatch.setattr(FLC, "build", poisoned)
    with pytest.raises(L4TraceabilityError):
        assemble_target_synthesis(_golden())


def test_broken_claim_id_in_a_contradiction_red_fails_the_assemble(monkeypatch):
    """MUTATION TEETH: a contradiction's `between` ref must also resolve, or the assemble red-fails."""
    real_build = FLC.build

    def poisoned(ctx):
        fr = copy.deepcopy(real_build(ctx))
        bogus_ref = S.claim_ref("NOT_A_REAL_CLAIM_ID", vector=POOLED)
        real_ref = fr["contradictions"][0]["between"][0]
        fr["contradictions"].append({"between": [real_ref, bogus_ref], "note": "fabricated contradiction"})
        fr["statements"].append(S.statement("fabricated contradiction", [real_ref, bogus_ref]))
        return fr

    monkeypatch.setattr(FLC, "build", poisoned)
    with pytest.raises(L4TraceabilityError):
        assemble_target_synthesis(_golden())


# ── honest absence path ──────────────────────────────────────────────────────────────────────────
def test_no_l3d_domain_yields_none_never_fabricates():
    """No upstream L3d story at all (e.g. the KRAS flagship today — tumor-presence has never exported an
    L3d story for KRAS/COADREAD) -> the facet degrades to None, never invents a liability/contradiction."""
    ctx = read_context({"target": "KRAS", "indication": "COADREAD", "headline": {}})
    assert ctx.l3d_domains == {}
    assert FLC.build(ctx) is None
    assert assemble_target_synthesis({"target": "KRAS", "indication": "COADREAD", "headline": {}}) is None


def test_domain_with_story_but_no_caveat_or_split_emits_honest_empty_lists():
    """When a domain DOES resolve an L3d story but it carries no caveats and every chapter agrees with
    the central node, the facet still emits — with BOTH lists honestly empty ("checked, found nothing"),
    never omitted (omission would misread as "did not check")."""
    clean_story = {
        "layer": "L3d",
        "domain": "tumor_presence",
        "chapters": [
            {
                "aspect": "tumor_presence",
                "claim_id": "tumor_presence_concordance",
                "reconstructable_from": POOLED,
                "concordance_class": "tumor_presence_concordant",
                "caveat": None,
            },
            {
                "aspect": "coverage",
                "claim_id": "bulk_vs_singlecell_coverage_concordance",
                "reconstructable_from": POOLED,
                "concordance_class": "coverage_concordant",
                "caveat": None,
            },
        ],
        "caveats": [],
    }
    from _skills_common.l4_synthesis.context import L4Context

    ctx = L4Context(
        decision={},
        l3d_domains={"tumor_presence": clean_story},
        l3f_frames={},
        claim_vectors={
            POOLED: {
                "tumor_presence_concordance": {},
                "bulk_vs_singlecell_coverage_concordance": {},
            }
        },
        target="X",
        indication="Y",
    )
    fr = FLC.build(ctx)
    assert fr is not None
    assert fr["liabilities"] == []
    assert fr["contradictions"] == []
    assert fr["statements"] == []


def test_discordant_central_node_never_fabricates_a_between_pair():
    """When the central node itself is unresolved/discordant, this module's pairwise rule stays silent
    (that tension belongs to the thesis coherence facet, not a guessed 'between' pair off a bad anchor)."""
    from _skills_common.l4_synthesis.context import L4Context

    story = {
        "layer": "L3d",
        "domain": "tumor_presence",
        "chapters": [
            {
                "aspect": "tumor_presence",
                "claim_id": "tumor_presence_concordance",
                "reconstructable_from": POOLED,
                "concordance_class": "tumor_presence_discordant",
                "caveat": None,
            },
            {
                "aspect": "coverage",
                "claim_id": "bulk_vs_singlecell_coverage_concordance",
                "reconstructable_from": POOLED,
                "concordance_class": "coverage_split_something",
                "caveat": None,
            },
        ],
        "caveats": [],
    }
    ctx = L4Context(
        decision={},
        l3d_domains={"tumor_presence": story},
        l3f_frames={},
        claim_vectors={POOLED: {"tumor_presence_concordance": {}, "bulk_vs_singlecell_coverage_concordance": {}}},
        target="X",
        indication="Y",
    )
    fr = FLC.build(ctx)
    assert fr["contradictions"] == []


# ── collision-free (no edit anywhere else needed) ───────────────────────────────────────────────
def test_thesis_archetype_facet_unaffected():
    """C0c touches only its own module; thesis+archetype (C0a) keeps emitting unchanged."""
    syn = assemble_target_synthesis(_golden())
    assert S.FACET_THESIS_ARCHETYPE in syn["facets"]
    assert syn["thesis"]["state"] == "supported"
