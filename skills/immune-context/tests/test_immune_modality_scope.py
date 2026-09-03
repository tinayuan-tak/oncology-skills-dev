"""immune-context wires the CD8 effector context into the composed modality_fit bite_tce channel
(modality-coverage: the TCE effector arm was previously unwired — immune-context had no _claim_record).
immune_cold = conditional (efficacy risk, NOT a veto — CIBERSORT is a relative, non-spatial screen).
Pure over the verdict; no S3/LLM."""
from __future__ import annotations
import sys
import importlib.util as u
from pathlib import Path

RUN = Path(__file__).resolve().parent.parent / "scripts" / "run.py"
SKILLS = RUN.parents[2]
sys.path.insert(0, str(SKILLS))
_spec = u.spec_from_file_location("run_ic_test", RUN)
m = u.module_from_spec(_spec); sys.modules["run_ic_test"] = m; _spec.loader.exec_module(m)


def test_bite_tce_only_and_immune_cold_is_conditional_not_veto():
    assert m._immune_modality_scope("immune_hot") == {"_refinements": {"bite_tce": "favorable"}}
    assert m._immune_modality_scope("immune_intermediate") == {"_refinements": {"bite_tce": "conditional"}}
    # cold = effector-absence efficacy RISK but NOT a veto → conditional (keeps TCE viable, caveated)
    assert m._immune_modality_scope("immune_cold") == {"_refinements": {"bite_tce": "conditional"}}
    # insufficient / unknown → silent (na), never fabricated
    assert m._immune_modality_scope("insufficient") is None
    assert m._immune_modality_scope(None) is None
    # informs ONLY the effector arm — never any other channel
    for v in ("immune_hot", "immune_intermediate", "immune_cold"):
        assert set(m._immune_modality_scope(v)["_refinements"]) == {"bite_tce"}


def test_claim_record_carries_the_scope_and_valid_enums():
    r = m._claim_record([], fired=[], verdict_pair=("immune_hot", None))
    assert r["axis"] == "immune_context"
    assert r["modality_scope"] == {"_refinements": {"bite_tce": "favorable"}}
    # availability/direction must be schema-valid (assemble_claim_record validates them)
    assert r["finding"]["availability"] == "measured_positive"
    assert r["finding"]["direction"] == "supports"
    cold = m._claim_record([], fired=[], verdict_pair=("immune_cold", None))
    assert cold["finding"]["availability"] == "measured_negative" and cold["finding"]["direction"] == "opposes"
