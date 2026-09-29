"""Emitted data-product contract guard for tumor-presence.

The finalized data product is defined by skills/tumor-presence/DATA_PRODUCT.md; its EMITTED shape is
pinned by the SELF-CONTAINED, generated per-skill schema
`target-contracts/schemas/skills/tumor-presence.decision.schema.json` (embeds the shared spine +
envelope — no cross-file $ref, so validation needs no registry). Shared load/validate helpers live in
`_skills_common.data_product_contract`.

Two conformance targets:
  - the frozen static golden (this file), validated only when it is a FULL decision (some skills keep a
    trimmed golden — not a valid full-decision target); and
  - the FRESH replay emit (test_tumor_presence_replay.py::test_replay_conforms_to_data_product_schema),
    which runs the real run.py credential-less — the load-bearing check for LIVE emitted-shape drift.

CI-liveness: when the schema is unresolvable, this SKIPS locally but FAILS in CI (env CI set), so the
ratchet can never be a silent green no-op. The contracts schema PR must land before skills CI can
resolve the schema — that ordering is intentional.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import check_schema_wellformed, check_static_golden_conforms

SKILL = "tumor-presence"
GOLDEN = Path(__file__).resolve().parent / "fixtures" / "epcam_coadread_decision.json"


def test_schema_is_wellformed():
    check_schema_wellformed(SKILL)


def test_static_golden_conforms():
    check_static_golden_conforms(SKILL, GOLDEN)
