"""T2 (2026-08-11 engineering review): every shipped dashboard_spec must validate against
dashboard_spec.schema.json.

Before this guard, `intracellular-intrinsic-base.dashboard_spec.yaml` declared 26 required_cards
against a schema cap of `maxItems: 20` — it did NOT validate against its own schema, and nothing
caught it because dashboard_spec INSTANCES were never schema-validated (only card specs were, in
contracts-validate.yml). The cap has been raised to 60; this test pins that every dashboard_spec
on disk validates, so cap-drift (or any other schema violation) fails a PR forever after.

Companion: the CI wiring adds this test's directory to the workflow.
"""

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

REPO = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((REPO / "schemas" / "dashboard_spec.schema.json").read_text())
DASHBOARD_SPECS = sorted((REPO / "dashboards").glob("*.dashboard_spec.yaml"))


def test_dashboard_specs_present():
    """Guard against a glob that silently matches nothing (which would make the param test
    vacuously pass)."""
    assert DASHBOARD_SPECS, "no *.dashboard_spec.yaml found under dashboards/"


@pytest.mark.parametrize("spec_path", DASHBOARD_SPECS, ids=lambda p: p.name)
def test_dashboard_spec_validates(spec_path):
    spec = yaml.safe_load(spec_path.read_text())
    errors = sorted(
        f"[{'.'.join(str(p) for p in e.absolute_path) or '<root>'}] {e.message}"
        for e in Draft202012Validator(SCHEMA).iter_errors(spec)
    )
    assert errors == [], f"{spec_path.name} failed dashboard_spec.schema validation:\n" + "\n".join(errors)


def test_largest_spec_exceeds_old_cap():
    """Regression anchor: at least one shipped spec has >20 required_cards (the old cap),
    proving the raised cap is load-bearing and this test would have caught the original bug."""
    max_required = max(len(yaml.safe_load(p.read_text()).get("required_cards", [])) for p in DASHBOARD_SPECS)
    assert max_required > 20, (
        "no spec exceeds the old cap of 20 — if specs shrank, this anchor can be removed; "
        f"observed max required_cards = {max_required}"
    )
