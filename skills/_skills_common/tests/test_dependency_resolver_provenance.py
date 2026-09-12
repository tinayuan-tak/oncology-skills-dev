"""Dependency resolver exhaustiveness/provenance rung (Gate-C gap 3, 2026-07-21).

Before v1.1.0, a MEASURED `data_unavailable` / partially-assayed call on a dependency card
fell through to `default: insufficient` with driving_rule_id=None — indistinguishable, in
provenance, from "no dependency rule fired at all" (the card never ran). v1.1.0 adds a
bottom rung (above default) mapping those data-unavailable rule_ids to `insufficient` WITH a
naming provenance anchor.

These tests pin the fix directly on the rungs (fast, readable, independent of the frozen table):
  1. each data-unavailable rule, fired alone, → ('insufficient', <that rule_id>) — named, not null;
  2. the bare default (NO rule fired) still → ('insufficient', None) — the honest "nothing ran";
  3. the new rung NEVER outranks a real signal (a positive/veto co-firing wins);
  4. the 5 rule_ids ARE carried in the golden snapshot's dependency dimension, so those rungs are
     actually exercised by the frozen table.

(4) was the OPPOSITE assertion until 2026-09-12 — it required the ids to be ABSENT, to dodge a
2**20 power-set explosion that the D5 co-emission migration had already eliminated. Keeping them
out left 5 of 18 rungs invisible to the oracle. See the inverted test's docstring and
test_resolver_golden_rule_id_coverage.py.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from _test_support import load_module

SKILLS = Path(__file__).resolve().parents[2]  # the skills/ dir (this test is skills/_skills_common/tests/)
CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
)

_resolver = load_module(SKILLS / "_skills_common" / "resolver.py", "resolver_prov_ut")
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
    """Lowest-`priority`-wins + bottom placement: a real positive or veto co-firing with a
    data-unavailable rule always wins (the rung is a strict, low-precedence addition). Note the
    resolver is NOT first-match-wins — precedence is the explicit `priority:` field, so rung order
    in the YAML is irrelevant."""
    # CRISPR data-unavailable + a concordant-dependent positive → the positive wins
    v, drv = _resolver.resolve_verdict(
        [{"rule_id": "data-unavailable-insufficient"}, {"rule_id": "concordant-dependent-supportive-dominant"}], _SPEC
    )
    assert v == "concordant_dependent"
    # rnai data-unavailable + a non-dependent veto → the veto wins
    v2, _ = _resolver.resolve_verdict(
        [{"rule_id": "rnai-data-unavailable-insufficient"}, {"rule_id": "non-dependent-killer"}], _SPEC
    )
    assert v2 == "non_dependent"


def test_new_rule_ids_are_in_the_frozen_golden_table_dimension():
    """INVERTED 2026-09-12. This test previously asserted the 5 data-unavailable rule_ids were
    ABSENT from the golden's dependency rule_ids, to avoid a 2**20 power-set explosion.

    Two things made that reasoning obsolete and then harmful:
      1. D5 (2026-08-09) replaced power-set enumeration with co-emission enumeration. The 5 ids
         cost 840 -> 8,640 rows (with the 2 partner-conditional ids), not 2**20. The explosion the
         exclusion was defending against no longer exists.
      2. The exclusion hardened into policy. It kept 5 of 18 rungs UNEXERCISED by the oracle, and
         the same reasoning left the 2 partner-conditional ids (Track PC, 2026-08-09) unlisted too
         — so `partner_conditional_dependent`, a shipped verdict and a `dominant` nomination-gate
         positive_signal, appeared on ZERO frozen rows. Resolver v1.4.0 raised those rungs above
         `discordant`: 4/840 rows moved in the committed table vs 374/8,640 with the ids listed.
         A verdict-moving precedence change read as near-inert.

    So the ids are now REQUIRED to be present, and the rung-behaviour tests above (which pin the
    same rungs directly, and do not depend on the table) remain as the fast, readable spec.
    See test_resolver_golden_rule_id_coverage.py for the general guard across all gates.
    """
    golden = json.loads((SKILLS / "_skills_common" / "tests" / "resolver_golden_snapshots.json").read_text())
    frozen_ids = set(golden["dependency"]["rule_ids"])
    missing = [rid for rid in _DATA_UNAVAILABLE_RULES if rid not in frozen_ids]
    assert not missing, (
        f"data-unavailable rule_ids missing from the golden dependency dimension: {missing} — "
        f"their rungs are unexercised by the frozen table; add them and re-run "
        f"regenerate_resolver_golden.py"
    )
