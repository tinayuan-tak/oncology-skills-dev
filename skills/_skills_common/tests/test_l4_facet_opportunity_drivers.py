"""Guards for the L4 opportunity_drivers facet builder (epic #1986, C0b #2005).

opportunity_drivers = the claims that make the target INTERESTING, each driver citing the L2/L3 claim
ref(s) it rests on. Built by walking every assessed domain's L3d chapters and selecting the ones whose
OWN concordance_class is a corroborated positive read — structural over the shared L3d chapter shape, not
tumor_presence-specific. These tests pin the properties #2005's acceptance requires:

  * FLAGSHIP END-TO-END (EPCAM) — the facet resolves real drivers from the tumor_presence L3d story, each
    traceable to a resolvable claim ref, and rides under assemble_target_synthesis's ``facets`` alongside
    the thesis_archetype floor.
  * ABSENCE PATH (KRAS) — no tumor_presence L3d story exists anywhere in the KRAS decision fixtures
    shipped by this repo's other skills; the facet must degrade to None (never fabricate a driver from
    nothing), and so must the whole assembly if nothing else resolves either.
  * DETERMINISM / BYTE-STABILITY — two builds over the same golden are byte-identical; the assembler still
    never mutates the decision it reads.
  * CLAIM-ID TRACEABILITY TEETH — a broken or empty claim ref on a driver statement RED-fails the
    assemble (mutation teeth), and a discordant / low-corroboration / caveat-only synthetic chapter is
    correctly excluded from the driver set (never laundered into an "interesting" claim).
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
    facet_opportunity_drivers,
    resolve_ref,
    unresolved_refs,
)
from _skills_common.l4_synthesis import schema as S  # noqa: E402
from _skills_common.l4_synthesis.assembler import L4TraceabilityError  # noqa: E402
from _skills_common.l4_synthesis.context import POOLED, L4Context, read_context  # noqa: E402

EPCAM_GOLDEN = SKILLS / "tumor-presence" / "tests" / "fixtures" / "epcam_coadread_decision.json"
# No tumor-presence L3d story exists for KRAS anywhere in the repo (C0a report point 3) — any KRAS
# decision fixture from a sibling skill is an honest "no L3d resolved" flagship read for this facet.
KRAS_DECISION = SKILLS / "genomic-alteration-profile" / "tests" / "fixtures" / "kras_coadread_decision.json"


def _epcam():
    return json.loads(EPCAM_GOLDEN.read_text())


def _kras():
    return json.loads(KRAS_DECISION.read_text())


# ── registry ─────────────────────────────────────────────────────────────────────────────────────
def test_opportunity_drivers_is_built():
    assert facet_opportunity_drivers.BUILT is True


# ── flagship end-to-end: EPCAM ──────────────────────────────────────────────────────────────────
def test_opportunity_drivers_emits_real_drivers_for_epcam_flagship():
    ctx = read_context(_epcam())
    fr = facet_opportunity_drivers.build(ctx)
    assert fr is not None
    assert fr["facet"] == S.FACET_OPPORTUNITY_DRIVERS
    assert fr["layer"] == S.L4_LAYER
    drivers = fr["drivers"]
    assert drivers  # at least one corroborated-positive chapter resolved
    # every driver names the domain + aspect it came from and cites a resolvable ref
    for d in drivers:
        assert d["domain"] == "tumor_presence"
        assert d["aspect"]
        assert d["claim_ids"]
        for ref in d["claim_ids"]:
            assert resolve_ref(ctx, ref)
    # the tumor-presence chapter itself (multi-source corroborated presence) is always a driver
    aspects = {d["aspect"] for d in drivers}
    assert "tumor_presence" in aspects
    assert "coverage" in aspects
    assert "protein_presence" in aspects


def test_opportunity_drivers_rides_the_assembled_synthesis_alongside_the_thesis_floor():
    syn = assemble_target_synthesis(_epcam())
    assert syn is not None
    assert S.FACET_THESIS_ARCHETYPE in syn["facets"]  # the permanent C0a floor
    assert S.FACET_OPPORTUNITY_DRIVERS in syn["facets"]  # this facet resolves too
    fr = syn["facets"][S.FACET_OPPORTUNITY_DRIVERS]
    assert fr["drivers"]
    # every statement in the assembled synthesis (across all facets) stays fully traceable
    ctx = read_context(_epcam())
    assert unresolved_refs(ctx, syn) == []


def test_a_caveated_but_positive_chapter_still_counts_as_a_driver():
    """The EPCAM abundance chapter is corroborated (RNA + MS-protein both detect the target) but carries a
    caveat (protein ranks below RNA). It is STILL a driver — the caveat is a distinct evidence
    relationship for the sibling liabilities_contradictions facet (C0c #2006), not a veto on this one."""
    ctx = read_context(_epcam())
    fr = facet_opportunity_drivers.build(ctx)
    abundance = [d for d in fr["drivers"] if d["aspect"] == "abundance"]
    assert abundance, "the caveated-but-corroborated abundance chapter must still surface as a driver"


# ── absence path: KRAS (no tumor_presence L3d anywhere in this fixture) ─────────────────────────
def test_opportunity_drivers_is_none_when_no_l3d_domain_resolves():
    ctx = read_context(_kras())
    assert ctx.l3d_domains == {}
    assert facet_opportunity_drivers.build(ctx) is None


def test_kras_flagship_yields_no_synthesis_at_all():
    """Honest absence, never fabricated: with no L3d domain anywhere in the object, the WHOLE assembly
    (not just this facet) is None — missing != negative."""
    assert assemble_target_synthesis(_kras()) is None


def test_no_positive_chapter_yields_no_drivers():
    """A resolved L3d story whose every chapter is discordant / low-corroboration yields no drivers —
    never a fabricated one — even though the domain itself resolved."""
    ctx = L4Context(
        decision={},
        l3d_domains={
            "tumor_presence": {
                "layer": "L3d",
                "domain": "tumor_presence",
                "coherence": "cross_source_discordant",
                "chapters": [
                    {
                        "aspect": "tumor_presence",
                        "claim_id": "tumor_presence_concordance",
                        "reconstructable_from": POOLED,
                        "concordance_class": "tumor_presence_discordant",
                        "corroboration": "high",
                        "reads": "sources disagree",
                    },
                    {
                        "aspect": "coverage",
                        "claim_id": "bulk_vs_singlecell_coverage_concordance",
                        "reconstructable_from": POOLED,
                        "concordance_class": "coverage_concordant",
                        "corroboration": "low",
                        "reads": "weak single read",
                    },
                ],
            }
        },
        l3f_frames={},
        claim_vectors={
            POOLED: {
                "tumor_presence_concordance": {},
                "bulk_vs_singlecell_coverage_concordance": {},
            }
        },
    )
    assert facet_opportunity_drivers.build(ctx) is None


# ── determinism / byte-stability ─────────────────────────────────────────────────────────────────
def test_opportunity_drivers_is_deterministic():
    ctx = read_context(_epcam())
    a = facet_opportunity_drivers.build(ctx)
    b = facet_opportunity_drivers.build(ctx)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_synthesis_with_opportunity_drivers_stays_byte_stable_to_the_decision():
    d = _epcam()
    before = json.dumps(d, sort_keys=True)
    assemble_target_synthesis(d)
    assert json.dumps(d, sort_keys=True) == before


# ── claim-ID traceability teeth ──────────────────────────────────────────────────────────────────
def test_broken_claim_id_on_a_driver_red_fails_the_assemble(monkeypatch):
    real_build = facet_opportunity_drivers.build

    def poisoned(ctx):
        fr = real_build(ctx)
        assert fr is not None
        fr = copy.deepcopy(fr)
        fr["statements"].append(
            S.statement("fabricated opportunity driver", [S.claim_ref("NOT_A_REAL_CLAIM_ID", vector=POOLED)])
        )
        return fr

    monkeypatch.setattr(facet_opportunity_drivers, "build", poisoned)
    with pytest.raises(L4TraceabilityError):
        assemble_target_synthesis(_epcam())


def test_empty_claim_ids_on_a_driver_red_fails_the_assemble(monkeypatch):
    real_build = facet_opportunity_drivers.build

    def poisoned(ctx):
        fr = copy.deepcopy(real_build(ctx))
        fr["statements"].append(S.statement("un-cited driver", []))
        return fr

    monkeypatch.setattr(facet_opportunity_drivers, "build", poisoned)
    with pytest.raises(L4TraceabilityError):
        assemble_target_synthesis(_epcam())
