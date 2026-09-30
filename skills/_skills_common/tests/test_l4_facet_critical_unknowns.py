"""Guards for the L4 critical_unknowns facet builder (epic #1986, C0d #2007).

critical_unknowns is a first-class L4 product: for every domain the framework knows how to assess
(``schema.KNOWN_DOMAINS``) it names KNOWN / UNKNOWN / CONTRADICTED / NOT_ASSESSED, flags which unknowns
are decision-critical (the archetype-defining domains), and cites the claim refs that back each call.
Deterministic, verdict-inert, no LLM authorship, no new measurement — see facet_critical_unknowns.py.

Flagship reality (C0a #1995 landing report point 3, reconfirmed here): only tumor_presence is exported
to L3d today, and ONLY on the EPCAM/COADREAD golden. KRAS carries no L3d anywhere in the corpus yet
(``kras_target_intrinsic_decision.json`` has no L3d-tagged object at all). This suite verifies the facet
against BOTH flagship realities: EPCAM (one domain KNOWN/assessed, the rest honestly NOT_ASSESSED) and
KRAS (nothing assessed at all -> the facet has nothing resolvable to cite, so it degrades to the same
honest omission ``facet_thesis_archetype`` uses -- never a NOT_ASSESSED list fabricated from nothing).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2]  # skills/

from _skills_common.l4_synthesis import (  # noqa: E402
    assemble_target_synthesis,
    facet_critical_unknowns,
    resolve_ref,
    unresolved_refs,
)
from _skills_common.l4_synthesis import schema as S  # noqa: E402
from _skills_common.l4_synthesis.assembler import L4TraceabilityError  # noqa: E402
from _skills_common.l4_synthesis.context import POOLED, read_context  # noqa: E402

EPCAM_GOLDEN = SKILLS / "tumor-presence" / "tests" / "fixtures" / "epcam_coadread_decision.json"
KRAS_INTRINSIC = SKILLS / "target-intrinsic" / "tests" / "fixtures" / "kras_target_intrinsic_decision.json"


def _epcam():
    return json.loads(EPCAM_GOLDEN.read_text())


def _kras():
    return json.loads(KRAS_INTRINSIC.read_text())


def _by_domain(fr):
    """Zip the emitted critical_unknowns list back onto S.KNOWN_DOMAINS (build() emits in that order)."""
    return dict(zip(S.KNOWN_DOMAINS, fr["critical_unknowns"]))


# ── registry ─────────────────────────────────────────────────────────────────────────────────────
def test_module_declares_built_and_uniform_contract():
    assert facet_critical_unknowns.BUILT is True
    assert callable(facet_critical_unknowns.build)


# ── EPCAM flagship: one KNOWN domain, six honest NOT_ASSESSED ──────────────────────────────────────
def test_epcam_flagship_emits_one_known_and_six_not_assessed():
    syn = assemble_target_synthesis(_epcam())
    assert syn is not None
    fr = syn["facets"][S.FACET_CRITICAL_UNKNOWNS]
    by_domain = _by_domain(fr)
    assert set(by_domain) == set(S.KNOWN_DOMAINS)

    assert by_domain["tumor_presence"]["status"] == "KNOWN"
    assert by_domain["tumor_presence"]["current_status"] == "cross_source_corroborated"
    assert by_domain["tumor_presence"]["decision_critical"] is False  # not archetype-defining

    not_assessed_domains = {d for d, u in by_domain.items() if d != "tumor_presence"}
    for d in not_assessed_domains:
        assert by_domain[d]["status"] == "NOT_ASSESSED"
        assert by_domain[d]["claim_ids"]  # cites the resolvable presence evidence, never empty


def test_epcam_archetype_defining_not_assessed_domains_are_decision_critical():
    syn = assemble_target_synthesis(_epcam())
    fr = syn["facets"][S.FACET_CRITICAL_UNKNOWNS]
    by_domain = _by_domain(fr)
    for d in ("dependency", "surface_modality", "on_target_safety"):
        assert by_domain[d]["status"] == "NOT_ASSESSED"
        assert by_domain[d]["decision_critical"] is True
        assert by_domain[d]["decision_importance"] == "high"
        assert by_domain[d]["affects"] == ["archetype"]
    # non-defining domains are never marked decision-critical even though also unassessed.
    for d in ("tumor_selectivity", "tractability", "genomic_alteration"):
        assert by_domain[d]["decision_critical"] is False
        assert by_domain[d]["affects"] == []


# ── KRAS flagship: nothing assessed anywhere -> honest omission, never fabricated ──────────────────
def test_kras_flagship_has_no_l3d_and_yields_no_synthesis():
    """Sanity on the corpus reality this suite pins: KRAS carries no L3d-tagged object at all today."""
    d = _kras()
    ctx = read_context(d)
    assert ctx.l3d_domains == {}


def test_kras_flagship_critical_unknowns_omits_rather_than_fabricates():
    d = _kras()
    ctx = read_context(d)
    fr = facet_critical_unknowns.build(ctx)
    assert fr is None  # nothing resolvable anywhere to cite -> honest omission, not a guessed list
    # and the top-level assembler agrees: no facet resolves -> no synthesis at all for KRAS today.
    assert assemble_target_synthesis(d) is None


# ── coherence -> status mapping (UNKNOWN / CONTRADICTED), exercised via synthetic envelopes ─────────
def _synthetic_decision(coherence: str, *, domain: str = "dependency", claim_id: str = "dep::synthetic"):
    """A minimal decision object with exactly one resolved L3d domain story, so the mapping from
    coherence -> critical-unknown status can be exercised without touching any pinned golden."""
    return {
        "target": "SYN",
        "indication": "SYNIND",
        "headline": {
            "claim_vector": {claim_id: {"value": "measured"}},
            "synthetic_story": {
                "layer": "L3d",
                "domain": domain,
                "coherence": coherence,
                "provenance": {"claim_ids": [{"claim_id": claim_id, "vector": POOLED}]},
            },
        },
    }


def test_discordant_coherence_maps_to_contradicted_and_is_decision_critical_for_a_defining_domain():
    d = _synthetic_decision("cross_source_discordant", domain="dependency")
    ctx = read_context(d)
    fr = facet_critical_unknowns.build(ctx)
    by_domain = _by_domain(fr)
    assert by_domain["dependency"]["status"] == "CONTRADICTED"
    assert by_domain["dependency"]["decision_critical"] is True  # CONTRADICTED != KNOWN, and defining
    assert unresolved_refs(ctx, {"facets": {S.FACET_CRITICAL_UNKNOWNS: fr}}) == []


@pytest.mark.parametrize(
    "coherence",
    ["single_source_read", "peripheral_islands_only", "central_node_unclassified", "no_resolved_island"],
)
def test_weak_coherence_classes_map_to_unknown_not_known_or_not_assessed(coherence):
    d = _synthetic_decision(coherence, domain="surface_modality")
    ctx = read_context(d)
    fr = facet_critical_unknowns.build(ctx)
    by_domain = _by_domain(fr)
    assert by_domain["surface_modality"]["status"] == "UNKNOWN"
    # an ASSESSED-but-unresolved domain is never conflated with an unassessed one.
    assert by_domain["surface_modality"]["current_status"] == coherence


def test_a_non_defining_domain_known_is_never_decision_critical():
    d = _synthetic_decision("cross_source_corroborated", domain="tractability")
    ctx = read_context(d)
    fr = facet_critical_unknowns.build(ctx)
    by_domain = _by_domain(fr)
    assert by_domain["tractability"]["status"] == "KNOWN"
    assert by_domain["tractability"]["decision_critical"] is False


# ── ASSESSED never renders NOT_ASSESSED and vice versa (mutation teeth on the branch itself) ───────
def test_assessed_domain_never_renders_not_assessed():
    d = _synthetic_decision("cross_source_corroborated", domain="on_target_safety")
    ctx = read_context(d)
    fr = facet_critical_unknowns.build(ctx)
    by_domain = _by_domain(fr)
    assert by_domain["on_target_safety"]["status"] != "NOT_ASSESSED"
    assert by_domain["on_target_safety"]["current_status"] == "cross_source_corroborated"


def test_unassessed_domain_never_renders_known_unknown_or_contradicted():
    d = _synthetic_decision("cross_source_corroborated", domain="on_target_safety")
    ctx = read_context(d)
    fr = facet_critical_unknowns.build(ctx)
    by_domain = _by_domain(fr)
    for domain, entry in by_domain.items():
        if domain == "on_target_safety":
            continue
        assert entry["status"] == "NOT_ASSESSED", f"{domain} must not be laundered into an assessed status"


# ── determinism + traceability + non-mutation ───────────────────────────────────────────────────────
def test_deterministic_byte_stable_on_epcam():
    a = assemble_target_synthesis(_epcam())
    b = assemble_target_synthesis(_epcam())
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_every_statement_traces_to_a_resolvable_claim_id_on_epcam():
    d = _epcam()
    ctx = read_context(d)
    syn = assemble_target_synthesis(d)
    fr = syn["facets"][S.FACET_CRITICAL_UNKNOWNS]
    for st in S.iter_statements(fr):
        assert st["claim_ids"]
        for ref in st["claim_ids"]:
            assert resolve_ref(ctx, ref)
    assert unresolved_refs(ctx, syn) == []


def test_broken_claim_id_on_critical_unknowns_red_fails_the_assemble(monkeypatch):
    """MUTATION TEETH: a critical_unknowns statement citing an unresolvable claim ID must red-fail the
    assemble, exactly like the thesis+archetype facet's own teeth (test_l4_facet_skeleton.py)."""
    real_build = facet_critical_unknowns.build

    def poisoned(ctx):
        fr = real_build(ctx)
        assert fr is not None
        fr = copy.deepcopy(fr)
        fr["statements"].append(S.statement("fabricated claim", [S.claim_ref("NOT_A_REAL_CLAIM_ID", vector=POOLED)]))
        return fr

    monkeypatch.setattr(facet_critical_unknowns, "build", poisoned)
    with pytest.raises(L4TraceabilityError):
        assemble_target_synthesis(_epcam())


def test_empty_claim_ids_on_critical_unknowns_also_red_fails(monkeypatch):
    real_build = facet_critical_unknowns.build

    def poisoned(ctx):
        fr = copy.deepcopy(real_build(ctx))
        fr["statements"].append(S.statement("un-cited claim", []))
        return fr

    monkeypatch.setattr(facet_critical_unknowns, "build", poisoned)
    with pytest.raises(L4TraceabilityError):
        assemble_target_synthesis(_epcam())


def test_assembler_never_mutates_the_decision_it_reads():
    d = _epcam()
    before = json.dumps(d, sort_keys=True)
    assemble_target_synthesis(d)
    assert json.dumps(d, sort_keys=True) == before


def test_no_l4_key_spliced_into_the_committed_epcam_golden():
    d = _epcam()
    assert "l4" not in d and "target_synthesis" not in d
    assert "l4" not in d.get("headline", {}) and "target_synthesis" not in d.get("headline", {})
