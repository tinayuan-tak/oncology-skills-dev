"""functional-requirement wires the SM-vs-degrader discriminator into the composed modality_fit: a
STRONGLY paralog-buffered target → degrader-preferred, SM caveated (mirrors the
strong-paralog-buffering-degrader-preferred rule). Previously paralog-buffering reached no modality
channel. Pure over synthetic cards."""
from __future__ import annotations
import sys
import importlib.util as u
from pathlib import Path

RUN = Path(__file__).resolve().parent.parent / "scripts" / "run.py"
sys.path.insert(0, str(RUN.parents[2]))
_spec = u.spec_from_file_location("run_fr_test", RUN)
m = u.module_from_spec(_spec); sys.modules["run_fr_test"] = m; _spec.loader.exec_module(m)


def _cards(cls):
    return [{"card_id": "paralog-buffering", "summary": {"paralog_buffering_class": cls}}]


def test_strong_buffering_prefers_degrader_caveats_sm():
    assert m._dep_modality_scope(_cards("strong")) == {
        "_refinements": {"degrader": "favorable", "small_molecule": "conditional"}}


def test_non_strong_buffering_is_silent():
    assert m._dep_modality_scope(_cards("partial")) is None
    assert m._dep_modality_scope(_cards("data_unavailable")) is None
    assert m._dep_modality_scope([]) is None


def test_claim_record_carries_the_degrader_scope():
    rec = m._claim_record(_cards("strong"), fired=[], verdict_pair=("lineage_selective", None))
    assert rec["modality_scope"]["_refinements"]["degrader"] == "favorable"
