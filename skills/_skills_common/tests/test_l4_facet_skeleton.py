"""Guards for the L4 target-synthesis skeleton + schema + thesis/archetype facet (epic #1986, C0a #1995).

The L4 layer is a DETERMINISTIC, verdict-INERT, facet-based VIEW over the already-emitted L2b/L3d/L3f
evidence. These tests pin the properties C0a's acceptance requires:

  * SCHEMA + REGISTRY — one module per facet builder; thesis_archetype BUILT, the rest declared stubs.
  * FLAGSHIP END-TO-END — thesis+archetype emits for EPCAM/COADREAD, traces to claim IDs, is deterministic.
  * BYTE-STABLE / VERDICT-INERT — the assembler NEVER mutates the decision it reads (existing goldens
    byte-unchanged); it is not wired into emission.
  * CLAIM-ID TRACEABILITY TEETH — every emitted statement's claim IDs resolve into the envelope; a broken
    claim ID RED-fails the assemble (mutation teeth).
  * COLLISION-FREE FAN-OUT — flipping a stub on (returning a facet) is picked up with no assembler edit.
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
    facet_thesis_archetype,
    resolve_ref,
    unresolved_refs,
)
from _skills_common.l4_synthesis import assembler as A  # noqa: E402
from _skills_common.l4_synthesis import (
    schema as S,
)
from _skills_common.l4_synthesis.assembler import L4TraceabilityError  # noqa: E402
from _skills_common.l4_synthesis.context import POOLED, read_context  # noqa: E402

GOLDEN = SKILLS / "tumor-presence" / "tests" / "fixtures" / "epcam_coadread_decision.json"


def _golden():
    return json.loads(GOLDEN.read_text())


# ── schema + registry ────────────────────────────────────────────────────────────────────────────
def test_layer_ordinal_reads_the_shared_ladder_without_owning_it():
    # L4 rides ClaimType.SYNTHESIS (layer 4) — imported, not redefined; C0a modifies no shared ladder.
    assert S.L4_LAYER == "L4"
    assert S.L4_CLAIM_TYPE == "synthesis"
    assert S.L4_LAYER_ORDINAL == 4


def test_schema_vocabularies_are_closed_and_sane():
    assert S.ARCHETYPE_UNDETERMINED == "undetermined"
    assert S.ARCHETYPE_UNDETERMINED not in S.ARCHETYPES  # sentinel is distinct from the definitive tokens
    assert "surface-antigen-opportunity" in S.ARCHETYPES
    assert set(S.UNKNOWN_STATUS) == {"KNOWN", "UNKNOWN", "CONTRADICTED", "NOT_ASSESSED"}
    assert "tumor_presence" in S.KNOWN_DOMAINS


def test_one_module_per_facet_builder_registered():
    """The module boundary is the deliverable: exactly one builder module per declared facet, thesis
    built, the rest stubs — so C0b–C0f fan out collision-free."""
    names = [n for n, _ in A.FACET_BUILDERS]
    assert names == list(S.FACET_NAMES)  # every facet declared, in order, no dupes
    for name, module in A.FACET_BUILDERS:
        assert hasattr(module, "build") and hasattr(module, "BUILT")
    built = {n: m for n, m in A.FACET_BUILDERS if m.BUILT}
    assert set(built) == {S.FACET_THESIS_ARCHETYPE}  # only C0a is built
    assert facet_thesis_archetype.BUILT is True


def test_stub_builders_return_none():
    ctx = read_context(_golden())
    for name, module in A.FACET_BUILDERS:
        if not module.BUILT:
            assert module.build(ctx) is None, f"stub {name} must return None until built"


# ── flagship end-to-end ──────────────────────────────────────────────────────────────────────────
def test_thesis_archetype_emits_for_epcam_flagship():
    syn = assemble_target_synthesis(_golden())
    assert syn is not None
    assert syn["layer"] == "L4"
    assert syn["target"] == "EPCAM"
    assert "tumor_presence" in syn["assessed_domains"]
    # thesis derived from the presence L3d coherence (cross_source_corroborated -> supported).
    thesis = syn["thesis"]
    assert thesis["state"] in S.THESIS_STATES
    assert thesis["state"] == "supported"
    assert thesis["primary_coherence"] == "cross_source_corroborated"
    assert thesis["supported_by"]  # cites the L3d chapter claim refs
    # thesis+archetype facet present; the others are absent (stubs) — honest, not fabricated.
    assert set(syn["facets"]) == {S.FACET_THESIS_ARCHETYPE}


def test_archetype_is_honestly_undetermined_when_only_presence_assessed():
    """Only tumor_presence is exported to L3d, so the cross-domain opportunity KIND cannot be classified
    without laundering one domain — the honest token is UNDETERMINED, and the defining domains are named
    as NOT_ASSESSED."""
    syn = assemble_target_synthesis(_golden())
    assert syn["archetype"] == S.ARCHETYPE_UNDETERMINED
    unassessed = set(syn["unassessed_domains"])
    assert {"dependency", "on_target_safety", "surface_modality"} <= unassessed
    promote = set(syn["facets"][S.FACET_THESIS_ARCHETYPE]["archetype_promote_when"])
    assert {"dependency", "surface_modality", "on_target_safety"} <= promote


def test_synthesis_is_deterministic_byte_stable():
    a = assemble_target_synthesis(_golden())
    b = assemble_target_synthesis(_golden())
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a["integration_method"] == "deterministic_facet_assembly"


# ── byte-stability / verdict-inert (does NOT mutate the object it reads) ────────────────────────────
def test_assembler_never_mutates_the_decision():
    d = _golden()
    before = json.dumps(d, sort_keys=True)
    assemble_target_synthesis(d)
    assert json.dumps(d, sort_keys=True) == before, "L4 assembler must not touch the decision it reads"


def test_assembler_writes_no_l4_key_into_the_committed_golden():
    """C0a is a pure read-over: the L4 object is NEW and separate — it is NOT spliced into the decision,
    so the committed golden carries no l4/target_synthesis key (envelope-emission wiring is deferred to
    C1 #1996). This pins that C0a stays byte-inert to every emitted field."""
    d = _golden()
    assert "l4" not in d and "target_synthesis" not in d
    assert "l4" not in d.get("headline", {}) and "target_synthesis" not in d.get("headline", {})


# ── claim-ID traceability teeth ─────────────────────────────────────────────────────────────────
def test_every_emitted_statement_traces_to_a_resolvable_claim_id():
    d = _golden()
    ctx = read_context(d)
    syn = assemble_target_synthesis(d)
    assert unresolved_refs(ctx, syn) == []  # no statement cites an unresolvable id
    # and every cited id is a real key on the vector it names.
    for fr in syn["facets"].values():
        for st in S.iter_statements(fr):
            assert st["claim_ids"]  # a statement with no ref is itself a violation
            for ref in st["claim_ids"]:
                assert resolve_ref(ctx, ref)
                if ref.get("vector") == POOLED:
                    assert ref["claim_id"] in d["headline"]["claim_vector"]


def test_provenance_union_is_all_resolvable():
    d = _golden()
    ctx = read_context(d)
    syn = assemble_target_synthesis(d)
    refs = syn["provenance"]["claim_ids"]
    assert refs and all(resolve_ref(ctx, r) for r in refs)


def test_broken_claim_id_red_fails_the_assemble(monkeypatch):
    """MUTATION TEETH: if a facet emits a statement citing a claim ID that does not drill back into the
    envelope, the assemble RED-fails. (If this passed, traceability would be cosmetic.)"""
    real_build = facet_thesis_archetype.build

    def poisoned(ctx):
        fr = real_build(ctx)
        assert fr is not None
        fr = copy.deepcopy(fr)
        fr["statements"].append(S.statement("fabricated claim", [S.claim_ref("NOT_A_REAL_CLAIM_ID", vector=POOLED)]))
        return fr

    monkeypatch.setattr(facet_thesis_archetype, "build", poisoned)
    with pytest.raises(L4TraceabilityError):
        assemble_target_synthesis(_golden())


def test_empty_claim_ids_also_red_fails(monkeypatch):
    """A statement that cites NOTHING is untraceable and must be rejected too (not just wrong ids)."""
    real_build = facet_thesis_archetype.build

    def poisoned(ctx):
        fr = copy.deepcopy(real_build(ctx))
        fr["statements"].append(S.statement("un-cited claim", []))
        return fr

    monkeypatch.setattr(facet_thesis_archetype, "build", poisoned)
    with pytest.raises(L4TraceabilityError):
        assemble_target_synthesis(_golden())


# ── honest omission + collision-free fan-out ───────────────────────────────────────────────────────
def test_no_l3d_yields_no_synthesis():
    """No L3d story resolves -> no facet -> None (byte-stable omission), never a fabricated synthesis."""
    assert assemble_target_synthesis({"target": "X", "indication": "Y", "headline": {}}) is None


def test_flipping_a_stub_on_is_picked_up_without_assembler_edits(monkeypatch):
    """A child builds a facet by implementing build() in ITS module only — the assembler picks it up with
    no edit to FACET_BUILDERS. Simulated by turning one stub into a real (traceable) facet."""
    real_presence_build = facet_thesis_archetype.build

    def a_real_next_evidence(ctx):
        # cite a ref the presence thesis already proves resolvable, so it stays traceable.
        base = real_presence_build(ctx)
        ref = base["thesis"]["supported_by"][0]
        return {
            "facet": S.FACET_NEXT_EVIDENCE,
            "layer": S.L4_LAYER,
            "statements": [S.statement("a next-evidence item", [ref])],
        }

    from _skills_common.l4_synthesis import facet_next_evidence

    monkeypatch.setattr(facet_next_evidence, "build", a_real_next_evidence)
    syn = assemble_target_synthesis(_golden())
    assert S.FACET_NEXT_EVIDENCE in syn["facets"]  # appeared with zero assembler changes
    assert unresolved_refs(read_context(_golden()), syn) == []  # still fully traceable
