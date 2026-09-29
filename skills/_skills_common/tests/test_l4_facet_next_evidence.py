"""Guards for the L4 next_evidence facet builder (epic #1986, C0f #2009).

next_evidence is the value-of-information product: what additional evidence would most change or
resolve the assessment. It is derived DETERMINISTICALLY from the sibling ``facet_critical_unknowns``
builder (called as a pure function over the shared ``ctx``, never edited) plus the NOT_ASSESSED /
weakly-resolved domains it already names -- no new measurement, no LLM authorship, no invented assays.

Flagship reality (mirrors test_l4_facet_critical_unknowns.py): only tumor_presence is exported to L3d
today, and ONLY on the EPCAM/COADREAD golden. KRAS carries no L3d anywhere in the corpus yet. This suite
verifies the facet against BOTH flagship realities: EPCAM (one domain KNOWN, six honestly NOT_ASSESSED ->
exactly six "export an L3d story" next-evidence entries) and KRAS (nothing assessed at all -> the facet
has nothing resolvable to derive from, so it degrades to the same honest omission its critical_unknowns
upstream uses -- never a fabricated wishlist).
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
    facet_critical_unknowns,
    facet_next_evidence,
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


# ── registry ─────────────────────────────────────────────────────────────────────────────────────
def test_module_declares_built_and_uniform_contract():
    assert facet_next_evidence.BUILT is True
    assert callable(facet_next_evidence.build)


# ── EPCAM flagship: one KNOWN domain (no ask) + six NOT_ASSESSED -> six export asks ────────────────
def test_epcam_flagship_emits_one_entry_per_not_assessed_domain():
    syn = assemble_target_synthesis(_epcam())
    assert syn is not None
    fr = syn["facets"][S.FACET_NEXT_EVIDENCE]
    entries = fr["next_evidence"]

    domains_asked = {e["resolves"][0]["domain"] for e in entries}
    assert domains_asked == set(S.KNOWN_DOMAINS) - {"tumor_presence"}
    assert "tumor_presence" not in domains_asked  # already KNOWN -> nothing to ask for

    for e in entries:
        assert e["resolves"][0]["status"] == "NOT_ASSESSED"
        assert "export an L3d story for the" in e["evidence"]
        assert e["claim_ids"]  # cites the resolvable presence evidence, never empty


def test_every_next_evidence_entry_names_the_domain_it_resolves():
    syn = assemble_target_synthesis(_epcam())
    fr = syn["facets"][S.FACET_NEXT_EVIDENCE]
    for e in fr["next_evidence"]:
        resolved = e["resolves"][0]
        assert resolved["domain"] in S.KNOWN_DOMAINS
        assert isinstance(resolved["question"], str) and resolved["question"]


# ── every entry resolves >=1 REAL unknown from the sibling facet (teeth: not a free-floating ask) ──
def test_every_entry_resolves_a_real_critical_unknown():
    d = _epcam()
    ctx = read_context(d)
    cu = facet_critical_unknowns.build(ctx)
    by_domain = dict(zip(S.KNOWN_DOMAINS, cu["critical_unknowns"]))

    fr = facet_next_evidence.build(ctx)
    for e in fr["next_evidence"]:
        dom = e["resolves"][0]["domain"]
        assert dom in by_domain
        assert e["resolves"][0]["status"] == by_domain[dom]["status"]
        assert e["resolves"][0]["question"] == by_domain[dom]["question"]
        # the entry cites exactly the claim refs the real unknown carries -- no invented ref.
        assert e["claim_ids"] == by_domain[dom]["claim_ids"]


# ── KRAS flagship: nothing assessed anywhere -> honest omission, never fabricated ──────────────────
def test_kras_flagship_has_no_l3d_and_yields_no_synthesis():
    d = _kras()
    ctx = read_context(d)
    assert ctx.l3d_domains == {}


def test_kras_flagship_next_evidence_omits_rather_than_fabricates():
    d = _kras()
    ctx = read_context(d)
    fr = facet_next_evidence.build(ctx)
    assert fr is None  # critical_unknowns itself resolves nothing -> nothing to derive an ask from
    assert assemble_target_synthesis(d) is None


# ── all-KNOWN synthetic envelope -> honest-empty (no further evidence needed), never fabricated ────
def _synthetic_decision(coherence: str, *, domain: str = "dependency", claim_id: str = "dep::synthetic"):
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


def test_unknown_coherence_yields_a_strengthen_ask():
    d = _synthetic_decision("single_source_read", domain="surface_modality")
    ctx = read_context(d)
    fr = facet_next_evidence.build(ctx)
    surface_entries = [e for e in fr["next_evidence"] if e["resolves"][0]["domain"] == "surface_modality"]
    assert len(surface_entries) == 1
    assert "strengthen cross-source corroboration" in surface_entries[0]["evidence"]
    assert surface_entries[0]["resolves"][0]["status"] == "UNKNOWN"


def test_discordant_coherence_yields_a_reconcile_ask():
    d = _synthetic_decision("cross_source_discordant", domain="dependency")
    ctx = read_context(d)
    fr = facet_next_evidence.build(ctx)
    dep_entries = [e for e in fr["next_evidence"] if e["resolves"][0]["domain"] == "dependency"]
    assert len(dep_entries) == 1
    assert "reconcile the discordant cross-source read" in dep_entries[0]["evidence"]
    assert dep_entries[0]["resolves"][0]["status"] == "CONTRADICTED"


# ── determinism + traceability + non-mutation ───────────────────────────────────────────────────────
def test_deterministic_byte_stable_on_epcam():
    a = assemble_target_synthesis(_epcam())
    b = assemble_target_synthesis(_epcam())
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_every_statement_traces_to_a_resolvable_claim_id_on_epcam():
    d = _epcam()
    ctx = read_context(d)
    syn = assemble_target_synthesis(d)
    fr = syn["facets"][S.FACET_NEXT_EVIDENCE]
    for st in S.iter_statements(fr):
        assert st["claim_ids"]
        for ref in st["claim_ids"]:
            assert resolve_ref(ctx, ref)
    assert unresolved_refs(ctx, syn) == []


def test_broken_claim_id_on_next_evidence_red_fails_the_assemble(monkeypatch):
    """MUTATION TEETH: a next_evidence statement citing an unresolvable claim ID must red-fail the
    assemble, exactly like the sibling facets' own teeth."""
    real_build = facet_next_evidence.build

    def poisoned(ctx):
        fr = real_build(ctx)
        assert fr is not None
        fr = copy.deepcopy(fr)
        fr["statements"].append(S.statement("fabricated claim", [S.claim_ref("NOT_A_REAL_CLAIM_ID", vector=POOLED)]))
        return fr

    monkeypatch.setattr(facet_next_evidence, "build", poisoned)
    with pytest.raises(L4TraceabilityError):
        assemble_target_synthesis(_epcam())


def test_empty_claim_ids_on_next_evidence_also_red_fails(monkeypatch):
    real_build = facet_next_evidence.build

    def poisoned(ctx):
        fr = copy.deepcopy(real_build(ctx))
        fr["statements"].append(S.statement("un-cited claim", []))
        return fr

    monkeypatch.setattr(facet_next_evidence, "build", poisoned)
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
