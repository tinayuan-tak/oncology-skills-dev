"""Robustness guards (2026-08-20, VERDICT-INERT). Two additive legibility facets on the presence
headline, unit-tested on the pure helpers (they never touch the collapsed spine):

  * presence_headline_conflict (_headline_conflict) — Principle 1: the positive-over-negative collapse
    can bury a MEASURED presence-negative (e.g. RNA broadly_high but CPTAC protein not_detected) under
    the one-word headline. The flag re-surfaces it. It must fire ONLY when the collapsed verdict is a
    presence-positive AND some other bucket is a MEASURED negative — never on a neutral (e.g. CPTAC
    `ns`/present-not-elevated) and never when the collapsed verdict is itself a negative/gap.

  * abundance_floor_flag (_abundance_floor) — Principle 2 (breadth != level): a presence-positive whose
    absolute abundance LEVEL reads bottom-decile in >=1 lens. The contrast-rank cards (CPTAC,
    RNA-vs-adjacent) are deliberately excluded — a low contrast rank is not low abundance.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_run_guards", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tp = _load()


def _bucket(measurement, sample_context, verdict, evidence_state="measured"):
    return {"measurement": measurement, "sample_context": sample_context,
            "verdict": verdict, "driving_rule_id": None, "evidence_state": evidence_state}


# ── presence_headline_conflict ─────────────────────────────────────────────────────────────────
def test_conflict_fires_when_measured_protein_absence_buried_under_rna_positive():
    """The canonical dangerous shape: RNA broadly_high (positive headline) while CPTAC protein is a
    MEASURED not_detected. The collapse ranks the positive first, so the killer is invisible in the
    one-word verdict — the flag must fire and name the protein bucket."""
    pm = {
        "bulk_rna/cell_line": _bucket("bulk_rna", "cell_line", "broadly_high_expression"),
        "bulk_protein_ms/tumor": _bucket("bulk_protein_ms", "tumor", "protein_not_detected"),
    }
    conflict, note, buckets = tp._headline_conflict("broadly_high_expression", pm)
    assert conflict is True
    assert buckets == ["bulk_protein_ms/tumor"]
    assert note and "bulk_protein_ms/tumor" in note


def test_conflict_silent_on_neutral_cptac_not_a_negative():
    """EPCAM/COADREAD shape: CPTAC `protein_present_not_elevated` (a measured NEUTRAL, not a killer).
    No conflict — the flag must not cry wolf on present-but-flat protein."""
    pm = {
        "bulk_rna/tumor": _bucket("bulk_rna", "tumor", "tumor_broadly_expressed"),
        "bulk_protein_ms/tumor": _bucket("bulk_protein_ms", "tumor", "protein_present_not_elevated"),
    }
    conflict, note, buckets = tp._headline_conflict("tumor_broadly_expressed", pm)
    assert conflict is False and note is None and buckets == []


def test_conflict_silent_when_headline_itself_negative_or_gap():
    """When the collapsed verdict is itself a negative (or a gap / insufficient), there is no buried
    killer to surface — the flag is only about a POSITIVE headline hiding a negative."""
    pm = {"bulk_rna/cell_line": _bucket("bulk_rna", "cell_line", "broadly_low_expression")}
    for v in ("broadly_low_expression", "data_unavailable", "insufficient", "not_informative"):
        conflict, note, buckets = tp._headline_conflict(v, pm)
        assert conflict is False and buckets == []


def test_conflict_ignores_unmeasured_negative_lookalike():
    """A data_unavailable bucket is a coverage GAP, never a measured negative — it must not trip the
    conflict flag even under a positive headline."""
    pm = {
        "bulk_rna/tumor": _bucket("bulk_rna", "tumor", "tumor_broadly_expressed"),
        "bulk_protein_ms/tumor": _bucket("bulk_protein_ms", "tumor", "data_unavailable",
                                         evidence_state="data_unavailable"),
    }
    conflict, _, buckets = tp._headline_conflict("tumor_broadly_expressed", pm)
    assert conflict is False and buckets == []


# ── abundance_floor_flag ───────────────────────────────────────────────────────────────────────
def _cards(**pct_by_card):
    """Minimal cards list carrying only allgene_percentile_class for the level-anchor cards."""
    return [{"card_id": cid, "summary": {"allgene_percentile_class": klass}}
            for cid, klass in pct_by_card.items()]


def test_abundance_floor_fires_on_bottom_decile_level_lens():
    """EPCAM shape: presence-positive, but cell-line PROTEIN abundance level is bottom-decile (detected
    everywhere yet low absolute level). The flag must fire and name the low lens."""
    cards = _cards(**{"tumor-rna-distribution": "top_1pct",
                      "cellline-rna-distribution": "mid",
                      "cellline-protein-abundance": "bottom_decile"})
    flag, lenses = tp._abundance_floor(cards, "tumor_broadly_expressed")
    assert flag == "present_low_abundance"
    assert [x["card_id"] for x in lenses] == ["cellline-protein-abundance"]


def test_abundance_floor_adequate_when_no_bottom_decile_level():
    cards = _cards(**{"tumor-rna-distribution": "top_1pct",
                      "cellline-rna-distribution": "mid",
                      "cellline-protein-abundance": "mid"})
    flag, lenses = tp._abundance_floor(cards, "tumor_broadly_expressed")
    assert flag == "adequate_abundance" and lenses == []


def test_abundance_floor_none_when_not_positive():
    """A negative / gap / insufficient headline gets no abundance-floor read (nothing to qualify)."""
    cards = _cards(**{"tumor-rna-distribution": "bottom_decile",
                      "cellline-rna-distribution": "bottom_decile",
                      "cellline-protein-abundance": "bottom_decile"})
    for v in ("broadly_low_expression", "data_unavailable", "insufficient"):
        flag, lenses = tp._abundance_floor(cards, v)
        assert flag is None and lenses == []


def test_presence_positive_predicate_matches_partition():
    """_is_presence_positive must agree with the collapse's own positive tier (single source of truth):
    every rung _partition_measured calls a positive is presence-positive; every negative/gap is not."""
    pos, neg, gap = tp._partition_measured(tp._VERDICT_RANK)
    assert all(tp._is_presence_positive(v) for _, v in pos)
    assert all(not tp._is_presence_positive(v) for _, v in neg)
    assert all(not tp._is_presence_positive(v) for _, v in gap)
