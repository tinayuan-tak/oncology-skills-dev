"""Dependency resolver exhaustiveness/provenance rung (Gate-C gap 3, 2026-07-21).

Before v1.1.0, a MEASURED `data_unavailable` / partially-assayed call on a dependency card
fell through to `default: insufficient` with driving_rule_id=None — indistinguishable, in
provenance, from "no dependency rule fired at all" (the card never ran). v1.1.0 adds a
bottom rung (above default) mapping those data-unavailable rule_ids to `insufficient` WITH a
naming provenance anchor.

These tests pin the fix WITHOUT the 2^20 golden-snapshot explosion that adding the 5 new
rule_ids to the exhaustive table would cause (they are a strict, low-precedence addition):
  1. each data-unavailable rule, fired alone, → ('insufficient', <that rule_id>) — named, not null;
  2. the bare default (NO rule fired) still → ('insufficient', None) — the honest "nothing ran";
  3. the new rung NEVER outranks a real signal (a positive/veto co-firing wins);
  4. the frozen golden snapshot (the 15 pre-existing rule_ids) is unaffected — proven by the
     sibling test_resolver_golden_snapshots test; here we just assert the new rule_ids are
     absent from that frozen table's dimension (so no silent table drift).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SKILLS = Path("/home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills/skills")
CONTRACTS = Path("/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")

if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))


def _load(mod_name, path):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = m
    spec.loader.exec_module(m)
    return m


_resolver = _load("resolver_prov_ut", SKILLS / "_skills_common" / "resolver.py")
_SPEC = _resolver.load_resolver("dependency", contracts_repo=CONTRACTS)

_DATA_UNAVAILABLE_RULES = [
    "data-unavailable-insufficient",
    "concordance-partially-assayed-insufficient",
    "concordance-data-unavailable-insufficient",
    "rnai-data-unavailable-insufficient",
    "lineage-selectivity-data-unavailable-insufficient",
]


def test_spec_loads():
    assert _SPEC is not None and _SPEC["gate"] == "dependency"


def test_each_data_unavailable_rule_gets_named_provenance():
    """Fired alone, a data-unavailable rule → insufficient WITH its own rule_id as provenance
    (not the null-provenance default)."""
    for rid in _DATA_UNAVAILABLE_RULES:
        v, drv = _resolver.resolve_verdict([{"rule_id": rid}], _SPEC)
        assert v == "insufficient", f"{rid} → {v}, expected insufficient"
        assert drv == rid, f"{rid} → driving_rule {drv!r}, expected the rule itself (named provenance)"


def test_bare_default_still_null_provenance():
    """The honest 'no dependency rule fired at all' state stays ('insufficient', None) — this is
    the distinction the rung creates: null=nothing-ran vs named=a-coverage-gap-was-reported."""
    v, drv = _resolver.resolve_verdict([], _SPEC)
    assert v == "insufficient" and drv is None
    # an unrelated (non-dependency) fired rule that no rung matches also falls to bare default
    v2, drv2 = _resolver.resolve_verdict([{"rule_id": "some-unrelated-rule"}], _SPEC)
    assert v2 == "insufficient" and drv2 is None


def test_data_unavailable_rung_never_outranks_a_real_signal():
    """First-match-wins + bottom placement: a real positive or veto co-firing with a
    data-unavailable rule always wins (the rung is a strict, low-precedence addition)."""
    # CRISPR data-unavailable + a concordant-dependent positive → the positive wins
    v, drv = _resolver.resolve_verdict(
        [{"rule_id": "data-unavailable-insufficient"},
         {"rule_id": "concordant-dependent-supportive-dominant"}], _SPEC)
    assert v == "concordant_dependent"
    # rnai data-unavailable + a non-dependent veto → the veto wins
    v2, _ = _resolver.resolve_verdict(
        [{"rule_id": "rnai-data-unavailable-insufficient"},
         {"rule_id": "non-dependent-killer"}], _SPEC)
    assert v2 == "non_dependent"


def test_new_rule_ids_absent_from_frozen_golden_table_dimension():
    """The 5 new rule_ids must NOT be in the frozen golden snapshot's dependency rule_ids
    (that is what keeps the 32,768-combo table valid + unchanged — the new rungs are a strict
    addition that never fires on the old 15). Guards against someone regenerating the snapshot
    to 2^20 unnecessarily."""
    golden = json.loads((SKILLS / "_skills_common" / "tests" /
                         "resolver_golden_snapshots.json").read_text())
    frozen_ids = set(golden["dependency"]["rule_ids"])
    for rid in _DATA_UNAVAILABLE_RULES:
        assert rid not in frozen_ids, (
            f"{rid} leaked into the frozen golden dimension — the table would need 2^20 combos")
