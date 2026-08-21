"""opentargets_target_prioritisation — the P5 Slice-1 walking-skeleton reader.

No S3: opentargets_common.read_entity + symbol_to_ensembl are monkeypatched to synthetic
values so the band arithmetic + data_unavailable paths are pinned deterministically. Asserts
the card presents OT-normalized scores as CONTEXT (bands + raw), never as raw facts, and is
data_unavailable-safe on both an unresolvable symbol and an absent entity.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

r = importlib.import_module("methods.opentargets_target_prioritisation.read")


def _patch(monkeypatch, *, ensg, df):
    monkeypatch.setattr(r, "symbol_to_ensembl", lambda t: ensg)
    monkeypatch.setattr(r, "read_entity", lambda entity, columns=None, **_kw: df)


def _row(ensg, **scores):
    base = {c: None for c in r._ALL_FIELDS}
    base["targetId"] = ensg
    base.update(scores)
    return pd.DataFrame([base])


def test_scored_bands_and_raw_scores(monkeypatch):
    df = _row("ENSG_KRAS", geneticConstraint=-0.9, mouseKOScore=-0.98, hasSafetyEvent=None,
              isInMembrane=0.0)
    _patch(monkeypatch, ensg="ENSG_KRAS", df=df)
    out = r.read_target_prioritisation("KRAS", "COADREAD")
    assert out["prioritisation_status"] == "scored"
    # negative OT score -> unfavorable band; None -> not_scored
    assert out["genetic_constraint_band"] == "unfavorable"
    assert out["mouse_ko_score_band"] == "unfavorable"
    assert out["has_safety_event_band"] == "not_scored"
    # raw score surfaced (context, full precision rounded)
    assert out["ot_scores"]["geneticConstraint"] == -0.9
    assert out["ot_scores"]["hasSafetyEvent"] is None
    # the card must flag its values are OT priors, not raw facts
    assert "OT-normalized" in out["_encoding_note"]


def test_favorable_and_intermediate_bands(monkeypatch):
    df = _row("ENSG_X", geneticConstraint=0.7, mouseKOScore=0.1, hasSafetyEvent=-1.0)
    _patch(monkeypatch, ensg="ENSG_X", df=df)
    out = r.read_target_prioritisation("X")
    assert out["genetic_constraint_band"] == "favorable"      # >= 0.5
    assert out["mouse_ko_score_band"] == "intermediate"       # -0.5 < v < 0.5
    assert out["has_safety_event_band"] == "unfavorable"      # <= -0.5


def test_unresolvable_symbol_is_data_unavailable(monkeypatch):
    _patch(monkeypatch, ensg=None, df=pd.DataFrame())
    out = r.read_target_prioritisation("NOTAGENE")
    assert out["prioritisation_status"] == "data_unavailable"
    assert out["ensembl_gene_id"] is None


def test_resolved_but_absent_from_table(monkeypatch):
    _patch(monkeypatch, ensg="ENSG_ORPHAN", df=_row("ENSG_OTHER", geneticConstraint=0.2))
    out = r.read_target_prioritisation("ORPHAN")
    assert out["prioritisation_status"] == "not_in_prioritisation_table"


def test_entity_unavailable_is_data_unavailable(monkeypatch):
    _patch(monkeypatch, ensg="ENSG_KRAS", df=pd.DataFrame())
    out = r.read_target_prioritisation("KRAS")
    assert out["prioritisation_status"] == "data_unavailable"
