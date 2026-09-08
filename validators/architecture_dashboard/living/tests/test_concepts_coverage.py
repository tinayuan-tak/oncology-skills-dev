"""Every component type resolves a schema shape, a real example, and an inventory count."""

from pathlib import Path

import yaml
from _util import load_committed

_SPEC = Path(__file__).resolve().parent.parent / "concepts.yaml"


def test_all_declared_types_present():
    declared = {t["id"] for t in (yaml.safe_load(_SPEC.read_text()) or {}).get("types", [])}
    got = {c["id"] for c in load_committed().get("concepts", [])}
    assert declared == got, f"concept types mismatch: missing={declared - got} extra={got - declared}"


def test_each_concept_resolved():
    for c in load_committed().get("concepts", []):
        cid = c["id"]
        assert c.get("narration"), f"{cid}: no narration"
        assert not (c.get("schema") or {}).get("error"), f"{cid}: schema unresolved"
        di = c.get("defined_in") or {}
        assert di.get("count"), f"{cid}: inventory count missing/zero"
        # example should resolve to a real committed instance (best-effort but expected in-repo)
        assert (c.get("example") or {}).get("resolved") is not None
