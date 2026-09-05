"""Enrichment-layer robustness guards (production-readiness sweep, 2026-08-21).

Two coupled failure modes on the VERDICT-INERT enrichment layer, neither covered before:

  H1 — `presence_key_signals` formatted the tumor-rna-vs-adjacent `q_value` with `:.0e` behind an
       isinstance guard on `log2_fc` ONLY. DESeq2 emits a null padj (independent-filtered / Cook's-
       cutoff rows) alongside a finite log2FoldChange, so a present-but-`None` `q_value` reached
       `f"{None:.0e}"` and raised `TypeError`. Coupled: a genuine `0.0` protein BH q-value was folded
       to `1.0` by `or 1`, dropping the "protein-confirmed" bit for the STRONGEST signals (L4).

  H2 — that raise propagated through `_headline` (the enrichment ran UNWRAPPED, after the spine was
       already built) → `run_wired_skill` → the whole run aborted with NO decision.json, violating the
       skill's "malformed/partial card = coverage gap, not crash" contract. The enrichment projections
       are now best-effort: a fault degrades that one projection to None + records `_enrichment_errors`,
       and the presence spine (verdict + per-modality matrix) is ALWAYS emitted.

All three helpers are verdict-INERT, so these guards never touch the collapsed spine.
"""
from __future__ import annotations

from pathlib import Path

from _skills_common.presence_claims import presence_key_signals
from _test_support import load_run_py

SKILL_DIR = Path(__file__).resolve().parent.parent

tp = load_run_py(SKILL_DIR, "tp_run_enrich")


# ── H1: null / zero q-values must not crash and must not be silently mis-handled ────────────────
def test_key_signals_null_dge_q_value_no_crash_drops_q_clause():
    """The reproduced crash: a strong_up DGE arm with a finite log2FC but a NULL q_value. Before the
    fix `f"{None:.0e}"` raised TypeError; now the q clause is dropped (not fabricated as `q=0e+00`)."""
    cards = [{"card_id": "tumor-rna-vs-adjacent",
              "summary": {"expression_call_class": "strong_up", "log2_fc": 1.5, "q_value": None}}]
    ks = presence_key_signals({}, cards)   # must NOT raise
    b = next((s for s in ks["supports"] if "vs adjacent" in s), None)
    assert b is not None and "log2FC 1.5" in b
    assert ", q=" not in b, f"null q_value should drop the q clause, not fabricate one: {b!r}"


def test_key_signals_numeric_dge_q_value_is_kept():
    """A real numeric q_value is still rendered (byte-stable happy path)."""
    cards = [{"card_id": "tumor-rna-vs-adjacent",
              "summary": {"expression_call_class": "strong_up", "log2_fc": 1.5, "q_value": 1e-6}}]
    ks = presence_key_signals({}, cards)
    b = next((s for s in ks["supports"] if "vs adjacent" in s), None)
    assert b is not None and "q=1e-06" in b


def test_key_signals_keeps_protein_confirmed_at_zero_q_value():
    """L4: a maximally-significant protein BH q-value of exactly 0.0 must KEEP the protein-confirmed
    bit (the old `(x or 1) < 0.05` folded 0.0 -> 1.0 and dropped it for the strongest evidence)."""
    cards = [
        {"card_id": "tumor-rna-vs-adjacent",
         "summary": {"expression_call_class": "strong_up", "log2_fc": 1.5, "q_value": 1e-6}},
        {"card_id": "tumor-protein-abundance-cptac",
         "summary": {"protein_expression_class": "strong_up", "protein_effect_size": 0.5,
                     "protein_bh_q_value": 0.0}},
    ]
    ks = presence_key_signals({}, cards)
    b = next(s for s in ks["supports"] if "[DGE + CPTAC]" in s)
    assert "protein-confirmed" in b and "q=0e+00" in b, b


# ── H2: an enrichment fault degrades that projection, never the spine ───────────────────────────
def test_headline_degrades_when_an_enrichment_projection_raises(monkeypatch):
    """Containment guard: if any verdict-inert enrichment projection raises, `_headline` must still
    return the fully-built presence spine, degrade the failing projection to None, and record the
    fault under `_enrichment_errors` — instead of aborting the run with no decision.json."""
    cards = [{"card_id": cid, "summary": {}} for cid in tp.CARDS]

    def _boom(*_a, **_k):
        raise ValueError("simulated enrichment fault")

    # run.py's _enrich resolves the projection function from its module globals at call time.
    monkeypatch.setattr(tp, "presence_question_table", _boom)
    hl = tp._headline(cards, [], ("insufficient", None))

    # spine survives intact
    assert hl["presence_verdict"] == "insufficient"
    assert "presence_verdict_by_modality" in hl
    # the failing projection degraded to None and was recorded (not raised)
    assert hl["question_table"] is None
    assert hl["_enrichment_errors"]["question_table"].startswith("ValueError")
    # the other projections are unaffected
    assert "claim_vector" in hl and "key_signals" in hl


def test_headline_happy_path_has_no_enrichment_errors_key():
    """Byte-stability floor: on a clean run no `_enrichment_errors` key is added, so the golden-spine
    and replay fixtures are unaffected by the best-effort wrapper."""
    cards = [{"card_id": cid, "summary": {}} for cid in tp.CARDS]
    hl = tp._headline(cards, [], ("insufficient", None))
    assert "_enrichment_errors" not in hl
