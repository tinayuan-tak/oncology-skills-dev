"""Guards for the L4 decision_dimensions (5R) facet builder (epic #1986, C0e #2008).

decision_dimensions = the 5R read (right_target / right_tissue / right_safety / right_patient /
right_drug) as VIEWS reorganizing the assessed L3d domain evidence — never a scalar N/5. These tests pin
the properties #2008 requires:

  * FLAGSHIP END-TO-END (EPCAM) — right_tissue resolves a real state from tumor_presence; every other
    dimension (none of whose relevant domains are assessed) reads NOT_ASSESSED, never fabricated.
  * ABSENCE PATH (KRAS) — no L3d domain anywhere -> the facet (and the whole assembly) is None.
  * DETERMINISM / BYTE-STABILITY.
  * CLAIM-ID TRACEABILITY TEETH.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2]  # skills/

from _skills_common.l4_synthesis import (  # noqa: E402
    assemble_target_synthesis,
    facet_decision_dimensions,
    resolve_ref,
    unresolved_refs,
)
from _skills_common.l4_synthesis import schema as S  # noqa: E402
from _skills_common.l4_synthesis.assembler import L4TraceabilityError  # noqa: E402
from _skills_common.l4_synthesis.context import read_context  # noqa: E402

EPCAM_GOLDEN = SKILLS / "tumor-presence" / "tests" / "fixtures" / "epcam_coadread_decision.json"
KRAS_DECISION = SKILLS / "genomic-alteration-profile" / "tests" / "fixtures" / "kras_coadread_decision.json"


def _epcam():
    return json.loads(EPCAM_GOLDEN.read_text())


def _kras():
    return json.loads(KRAS_DECISION.read_text())


def test_decision_dimensions_is_built():
    assert facet_decision_dimensions.BUILT is True


# ── flagship end-to-end: EPCAM ──────────────────────────────────────────────────────────────────
def test_decision_dimensions_emits_all_5r_for_epcam_flagship():
    ctx = read_context(_epcam())
    fr = facet_decision_dimensions.build(ctx)
    assert fr is not None
    assert fr["facet"] == S.FACET_DECISION_DIMENSIONS
    assert fr["layer"] == S.L4_LAYER
    dims = fr["decision_dimensions"]
    assert set(dims) == set(facet_decision_dimensions.DIMENSIONS)
    for entry in dims.values():
        assert entry["claim_ids"]
        for ref in entry["claim_ids"]:
            assert resolve_ref(ctx, ref)


def test_right_tissue_resolves_a_real_state_from_tumor_presence():
    ctx = read_context(_epcam())
    fr = facet_decision_dimensions.build(ctx)
    right_tissue = fr["decision_dimensions"][facet_decision_dimensions.RIGHT_TISSUE]
    assert right_tissue["assessed_domains"] == ["tumor_presence"]
    assert right_tissue["state"] != "NOT_ASSESSED"


def test_right_safety_and_right_target_are_honestly_not_assessed_for_epcam():
    """No dependency / genomic_alteration / on_target_safety L3d story exists in the EPCAM flagship —
    those dimensions must read NOT_ASSESSED, never guessed from the one assessed presence domain."""
    ctx = read_context(_epcam())
    fr = facet_decision_dimensions.build(ctx)
    dims = fr["decision_dimensions"]
    assert dims[facet_decision_dimensions.RIGHT_TARGET]["state"] == "NOT_ASSESSED"
    assert dims[facet_decision_dimensions.RIGHT_SAFETY]["state"] == "NOT_ASSESSED"


def test_decision_dimensions_rides_the_assembled_synthesis_alongside_the_thesis_floor():
    syn = assemble_target_synthesis(_epcam())
    assert syn is not None
    assert S.FACET_THESIS_ARCHETYPE in syn["facets"]
    assert S.FACET_DECISION_DIMENSIONS in syn["facets"]
    ctx = read_context(_epcam())
    assert unresolved_refs(ctx, syn) == []


# ── absence path: KRAS (no L3d domain anywhere) ─────────────────────────────────────────────────
def test_decision_dimensions_is_none_when_no_l3d_domain_resolves():
    ctx = read_context(_kras())
    assert ctx.l3d_domains == {}
    assert facet_decision_dimensions.build(ctx) is None


def test_kras_flagship_yields_no_synthesis_at_all():
    assert assemble_target_synthesis(_kras()) is None


# ── determinism / byte-stability ─────────────────────────────────────────────────────────────────
def test_decision_dimensions_is_deterministic():
    ctx = read_context(_epcam())
    a = facet_decision_dimensions.build(ctx)
    b = facet_decision_dimensions.build(ctx)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_synthesis_with_decision_dimensions_stays_byte_stable_to_the_decision():
    d = _epcam()
    before = json.dumps(d, sort_keys=True)
    assemble_target_synthesis(d)
    assert json.dumps(d, sort_keys=True) == before


# ── claim-ID traceability teeth ──────────────────────────────────────────────────────────────────
def test_broken_claim_id_on_a_dimension_statement_red_fails_the_assemble(monkeypatch):
    real_build = facet_decision_dimensions.build

    def poisoned(ctx):
        fr = real_build(ctx)
        assert fr is not None
        fr = copy.deepcopy(fr)
        fr["statements"].append(
            S.statement(
                "fabricated dimension statement",
                [S.claim_ref("NOT_A_REAL_CLAIM_ID", vector="pooled_claim_vector")],
            )
        )
        return fr

    monkeypatch.setattr(facet_decision_dimensions, "build", poisoned)
    with pytest.raises(L4TraceabilityError):
        assemble_target_synthesis(_epcam())


def test_empty_claim_ids_on_a_dimension_statement_red_fails_the_assemble(monkeypatch):
    real_build = facet_decision_dimensions.build

    def poisoned(ctx):
        fr = copy.deepcopy(real_build(ctx))
        fr["statements"].append(S.statement("un-cited dimension statement", []))
        return fr

    monkeypatch.setattr(facet_decision_dimensions, "build", poisoned)
    with pytest.raises(L4TraceabilityError):
        assemble_target_synthesis(_epcam())
