"""Hermetic tests for the v1.1.0 cited-evidence confidence surface (literature-and-claims arc, 2nd
NON-standard skill after target-archetype).

Covers the VERDICT-INERT enrichment added over the literature-native cited-literature-evidence skill:
  - cited_evidence_confidence_caveat  (3 tiers + false-demote guard + precedence + None path)
  - stale_literature_note             (recency; fires on old latest_year / no recent mentions)
  - cited_evidence_provenance         (quorum fields; empty→None; carries the card's OWN pmids)
  - _headline surfaces the primary caveat into key_signals.caveat (deterministic)
  - _SYNTHESIS_FACET_KEYS carries the caveats to the composed profile
  - the LITERATURE_CONTEXT lens (registry, descriptive, 3 axis_labels, tokenless) + the deliberate
    NO-literature_fn decision (SKIP the redundant/circular --literature lane)

Pure caveat/provenance tests use synthetic headline dicts (no S3 / no card / no LLM). SET literals, not
2-string tuples (reference-drift guard). Asserts the calibration the DETERMINISTIC panel shows live."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent

from _skills_common.narrator_lenses import LENSES, LITERATURE_CONTEXT  # noqa: E402


def _run_module():
    spec = importlib.util.spec_from_file_location("lc_run_caveats", SKILL_DIR / "scripts" / "run.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def M():
    return _run_module()


# ── synthetic headline builder (only the fields the caveats read) ───────────────────────────────────
def _hl(
    status="ok",
    volume=200,
    recent=40,
    n_diseases=3,
    latest_year=2025,
    earliest_year=1998,
    relation_types=("associate", "cause", "positive_correlate"),
    total_rel_pubs=80,
    top_cited=({"pmid": "18946061"},),
):
    return {
        "cited_evidence_status": status,
        "literature_scope": "indication",
        "paper_disease_mentions": volume,
        "recent_mentions": recent,
        "n_diseases": n_diseases,
        "earliest_year": earliest_year,
        "latest_year": latest_year,
        "relation_types": list(relation_types) if relation_types is not None else None,
        "total_relation_publications": total_rel_pubs,
        "top_cited": list(top_cited) if top_cited is not None else None,
    }


# ── TIER (iii) MILDER — validated_established_relationship false-demote guard ────────────────────────
@pytest.mark.parametrize(
    "target,indication", [("KRAS", "COADREAD"), ("ERBB2", "BRCA"), ("EGFR", "LUAD"), ("VHL", "KIRC")]
)
def test_validated_established_relationship_guard_fires(M, target, indication):
    c = M._cited_evidence_confidence_caveat(_hl(volume=12000, n_diseases=7), target=target, indication=indication)
    assert c["reason"] == "validated_established_relationship"
    assert c["tier"] == "milder" and c["false_demote_guarded"] is True


def test_guard_indication_alias(M):
    # leaf/synonym codes normalise into the crosswalk (COAD/READ→COADREAD, LUSC/NSCLC→LUAD, RCC→KIRC).
    for ind in ("COAD", "READ"):
        assert (
            M._cited_evidence_confidence_caveat(_hl(), target="KRAS", indication=ind)["reason"]
            == "validated_established_relationship"
        )
    assert (
        M._cited_evidence_confidence_caveat(_hl(), target="EGFR", indication="NSCLC")["reason"]
        == "validated_established_relationship"
    )
    assert (
        M._cited_evidence_confidence_caveat(_hl(), target="VHL", indication="RCC")["reason"]
        == "validated_established_relationship"
    )


def test_guard_wins_over_conflicting_relation(M):
    # A canonical pair with a (spurious) conflicting relation set: the MILDER guard still wins (a validated
    # relationship is not demoted for an automated-extraction artifact) — precedence check.
    c = M._cited_evidence_confidence_caveat(
        _hl(relation_types=("inhibit", "stimulate", "associate")), target="ERBB2", indication="BRCA"
    )
    assert c["reason"] == "validated_established_relationship"


# ── TIER (ii) SHARP — relation_direction_automated_or_conflicting ────────────────────────────────────
def test_conflicting_relation_direction_fires_sharp(M):
    c = M._cited_evidence_confidence_caveat(
        _hl(relation_types=("inhibit", "stimulate", "associate"), total_rel_pubs=15), target="FOO", indication="BAR"
    )
    assert c["reason"] == "relation_direction_automated_or_conflicting"
    assert c["tier"] == "sharp" and c["false_demote_guarded"] is False


def test_single_paper_relation_fires_sharp(M):
    c = M._cited_evidence_confidence_caveat(
        _hl(relation_types=("cause",), total_rel_pubs=1, volume=30), target="FOO", indication="BAR"
    )
    assert c["reason"] == "relation_direction_automated_or_conflicting"


def test_two_paper_relation_is_thin(M):
    # boundary: total_relation_publications == _SINGLE_PAPER_MAX (2) is still thin.
    assert M._SINGLE_PAPER_MAX == 2
    c = M._cited_evidence_confidence_caveat(
        _hl(relation_types=("cause",), total_rel_pubs=2, volume=30), target="FOO", indication="BAR"
    )
    assert c["reason"] == "relation_direction_automated_or_conflicting"


# ── TIER (i) SHARP — volume_without_validated_relation (catch-all incl. pleiotropy) ──────────────────
def test_volume_without_validated_relation_default(M):
    # high volume, consistent-but-not-conflicting relation, NOT canonical, well-supported → default over-call.
    c = M._cited_evidence_confidence_caveat(
        _hl(volume=5000, n_diseases=4, relation_types=("associate",), total_rel_pubs=50), target="FOO", indication="BAR"
    )
    assert c["reason"] == "volume_without_validated_relation"
    assert c["tier"] == "sharp"


def test_pleiotropy_inflation_annotated(M):
    # the TP53 pattern: high volume across MANY diseases → volume_without_validated_relation + pleiotropy note.
    c = M._cited_evidence_confidence_caveat(
        _hl(volume=50000, n_diseases=30, relation_types=("associate",), total_rel_pubs=40),
        target="TP53",
        indication="BRCA",
    )
    assert c["reason"] == "volume_without_validated_relation"
    assert "n_diseases" in c["detail"] and "pleiotropic" in c["detail"]


# ── None path (no positive substrate) → byte-stable ─────────────────────────────────────────────────
@pytest.mark.parametrize("status", ["no_evidence", "insufficient", "data_unavailable", None])
def test_no_positive_substrate_returns_none(M, status):
    assert (
        M._cited_evidence_confidence_caveat(
            _hl(status=status, volume=0, total_rel_pubs=0, relation_types=None, top_cited=None),
            target="KRAS",
            indication="COADREAD",
        )
        is None
    )


def test_ok_but_empty_returns_none(M):
    # status ok but no volume AND no relation → not positive substrate.
    assert (
        M._cited_evidence_confidence_caveat(
            _hl(volume=0, total_rel_pubs=0, relation_types=None), target="FOO", indication="BAR"
        )
        is None
    )


# ── stale_literature_note ───────────────────────────────────────────────────────────────────────────
def test_stale_note_old_latest_year(M):
    n = M._stale_literature_note(_hl(latest_year=2010))
    assert n and n["reason"] == "stale_literature" and "2010" in n["detail"]


def test_stale_note_zero_recent_with_volume(M):
    n = M._stale_literature_note(_hl(recent=0, volume=120, latest_year=2025))
    assert n and n["reason"] == "stale_literature"


def test_stale_note_none_when_current(M):
    assert M._stale_literature_note(_hl(latest_year=2025, recent=40, volume=120)) is None


def test_stale_note_none_without_substrate(M):
    assert M._stale_literature_note(_hl(status="no_evidence", volume=0, total_rel_pubs=0)) is None


# ── cited_evidence_provenance QUORUM ────────────────────────────────────────────────────────────────
def test_provenance_quorum_fields(M):
    p = M._cited_evidence_provenance(
        _hl(
            volume=12000,
            n_diseases=7,
            relation_types=("inhibit", "stimulate", "associate"),
            total_rel_pubs=120,
            top_cited=({"pmid": "18946061"}, {"pmid": "18316791"}),
        ),
        target="KRAS",
        indication="COADREAD",
    )
    assert p["validated_established_relationship_flag"] is True
    assert p["relation_direction_conflict"] is True
    assert p["n_relation_types"] == 3
    assert p["top_cited_pmids"] == ["18946061", "18316791"]
    assert "co-occurrence" in p["provenance_note"].lower() or "CO-OCCURRENCE" in p["provenance_note"]


def test_provenance_pleiotropy_and_stale_flags(M):
    p = M._cited_evidence_provenance(_hl(n_diseases=30, latest_year=2010), target="TP53", indication="BRCA")
    assert p["pleiotropic_flag"] is True and p["stale_flag"] is True
    assert p["validated_established_relationship_flag"] is False


def test_provenance_none_on_empty(M):
    assert M._cited_evidence_provenance({}, target="X", indication="Y") is None


# ── _headline wiring: primary caveat → key_signals.caveat; None path leaves it byte-stable ──────────
def test_headline_surfaces_caveat_into_key_signals(M):
    # Build cards shaped so get_card_field reads the fields _hl carries. The card list is what the composer
    # passes; we mimic a resolved cited-literature-evidence card row.
    card = {
        "card_id": "cited-literature-evidence",
        "summary": _card_fields(volume=50000, n_diseases=30, relation_types=["associate"], total_rel_pubs=40),
    }
    hl = M._headline([card], [], (None, None), target="TP53", indication="BRCA")
    cc = hl.get("cited_evidence_confidence_caveat")
    assert cc and cc["reason"] == "volume_without_validated_relation"
    assert hl["key_signals"]["caveat"] == cc["detail"]
    # provenance + facet keys present
    assert hl.get("cited_evidence_provenance") is not None


def test_headline_none_path_leaves_key_signals_caveat_untouched(M):
    card = {
        "card_id": "cited-literature-evidence",
        "summary": _card_fields(status="no_evidence", volume=0, total_rel_pubs=0, relation_types=[], top_cited=[]),
    }
    hl = M._headline([card], [], (None, None), target="KRAS", indication="COADREAD")
    assert hl.get("cited_evidence_confidence_caveat") is None
    # base key_signals may set a "thin corpus" caveat on the critical VOLUME axis, but our enrichment must
    # NOT have overwritten it with a confidence-caveat detail (byte-stable where the caveat is absent).
    ks_caveat = (hl.get("key_signals") or {}).get("caveat")
    assert ks_caveat is None or "thin cited-literature corpus" in ks_caveat


# ── lens contract ───────────────────────────────────────────────────────────────────────────────────
def test_lens_registered_descriptive_tokenless():
    assert "literature-context" in LENSES
    assert LENSES["literature-context"] is LITERATURE_CONTEXT
    assert LITERATURE_CONTEXT.mode == "descriptive"
    assert LITERATURE_CONTEXT.verdict_key is None  # tokenless (no collapsed verdict)
    assert set(LITERATURE_CONTEXT.axis_labels) == {"VOLUME", "RECENCY", "RELATION"}
    assert len(LENSES) >= 16


def test_synthesis_facet_carries_caveats(M):
    for k in ("cited_evidence_confidence_caveat", "stale_literature_note", "cited_evidence_provenance"):
        assert k in M._SYNTHESIS_FACET_KEYS


def test_no_literature_fn_wired(M):
    # the deliberate SKIP: run.py wires synthesize_fn but NOT literature_fn (redundant/circular lane).
    src = (SKILL_DIR / "scripts" / "run.py").read_text()
    assert "synthesize_fn=make_synthesize_fn" in src
    assert "literature_fn=" not in src


# ── reference-drift guard: the polarity/crosswalk containers are SETs/dicts, not 2-string tuples ────
def test_reference_containers_are_sets_or_dicts(M):
    assert isinstance(M._REL_UP, set) and isinstance(M._REL_DOWN, set)
    assert isinstance(M._VALIDATED_ESTABLISHED_RELATIONSHIP, dict)
    assert ("KRAS", "COADREAD") in M._VALIDATED_ESTABLISHED_RELATIONSHIP


# ── helper: build a cited-literature-evidence card row get_card_field can read ──────────────────────
def _card_fields(
    status="ok",
    volume=200,
    recent=40,
    n_diseases=3,
    latest_year=2025,
    earliest_year=1998,
    relation_types=("associate", "cause", "positive_correlate"),
    total_rel_pubs=80,
    top_cited=({"pmid": "18946061"},),
    literature_scope="indication",
):
    return {
        "cited_evidence_status": status,
        "literature_scope": literature_scope,
        "paper_disease_mentions": volume,
        "recent_mentions": recent,
        "n_diseases": n_diseases,
        "earliest_year": earliest_year,
        "latest_year": latest_year,
        "relation_types": list(relation_types) if relation_types is not None else None,
        "total_relation_publications": total_rel_pubs,
        "top_cited": list(top_cited) if top_cited is not None else None,
    }
