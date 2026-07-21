"""measurement_types PULL resolver + framework-wide pull-consistency (DATA_TO_SKILL_CONTRACT step 5).

Two things:
  1. the resolver classifies a pulled type as live_provider / registered_no_live_provider /
     unregistered against the registry;
  2. EVERY gate-view's composition.measurement_types_pulled resolves to a REGISTERED type — the
     framework-wide guard that a gate can't pull a claim no provider could satisfy (a typo or a type
     someone forgot to register). This is the pull half of the pull/push decoupling made honest.

Cross-repo: reads target-contracts. Graceful-skips the registry-dependent assertions when
target-contracts isn't checked out alongside (isolated CI), mirroring the other cross-repo checks.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

COMMON = Path(__file__).resolve().parent.parent
SKILLS_DIR = COMMON.parent


def _load_resolver():
    # Register in sys.modules BEFORE exec so @dataclass introspection (which looks the module up in
    # sys.modules) works under spec_from_file_location.
    sys.path.insert(0, str(SKILLS_DIR))
    spec = importlib.util.spec_from_file_location(
        "mt_resolver_under_test", COMMON / "measurement_types.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["mt_resolver_under_test"] = m
    spec.loader.exec_module(m)
    return m


mt = _load_resolver()
_REGISTRY_REACHABLE = mt.registered_types() is not None


# ---------- resolver classification ----------

@pytest.mark.skipif(not _REGISTRY_REACHABLE, reason="measurement_types.yaml not reachable")
def test_live_type_resolves_to_providers():
    r = mt.resolve_pull("surface_confirmation")
    assert r.status == mt.STATUS_LIVE
    assert r.provider_sources                       # non-empty
    assert "cspa-bausch-fluck-2015" in r.provider_sources   # the resolved orphan


@pytest.mark.skipif(not _REGISTRY_REACHABLE, reason="measurement_types.yaml not reachable")
def test_placeholder_only_type_is_registered_but_not_live():
    # fusion_rearrangement has a single {source: placeholder} provider
    r = mt.resolve_pull("fusion_rearrangement")
    assert r.status == mt.STATUS_NO_LIVE
    assert r.is_registered


@pytest.mark.skipif(not _REGISTRY_REACHABLE, reason="measurement_types.yaml not reachable")
def test_unregistered_type_is_flagged():
    r = mt.resolve_pull("definitely_not_a_real_type")
    assert r.status == mt.STATUS_UNREGISTERED
    assert not r.is_registered


@pytest.mark.skipif(not _REGISTRY_REACHABLE, reason="measurement_types.yaml not reachable")
def test_derived_type_live_iff_inputs_live():
    # adc_tce_modality_fit derives from surface_topology + surfaceome_family + structure_druggability,
    # all of which are live dataset providers → the derived type is live.
    assert mt.resolve_pull("adc_tce_modality_fit").status == mt.STATUS_LIVE


# ---------- framework-wide pull consistency ----------

def _gate_pulls() -> dict:
    """Map skill_dir -> measurement_types_pulled, for every SKILL.md that declares one."""
    out = {}
    for md in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        text = md.read_text()
        for chunk in text.split("---")[1:]:
            try:
                doc = yaml.safe_load(chunk)
            except yaml.YAMLError:
                continue
            if isinstance(doc, dict) and isinstance(doc.get("composition"), dict):
                pulled = doc["composition"].get("measurement_types_pulled")
                if pulled:
                    out[md.parent.name] = pulled
                break
    return out


def test_at_least_the_wired_gates_declare_pulls():
    pulls = _gate_pulls()
    # the wired biology gate-views that should each declare a pull now
    expected = {"functional-requirement", "genomic-alteration-profile", "mechanism-and-pharmacology",
                "on-target-safety-liability", "tractability-small-molecule", "tumor-presence",
                "tumor-selectivity", "differentiation-landscape", "surface-modality-fit"}
    missing = expected - set(pulls)
    assert not missing, f"these gate-views do not declare measurement_types_pulled: {sorted(missing)}"


@pytest.mark.skipif(not _REGISTRY_REACHABLE, reason="measurement_types.yaml not reachable")
def test_every_pulled_type_is_registered():
    """The framework-wide invariant: no gate pulls a claim that isn't a registered measurement_type."""
    registered = mt.registered_types()
    offenders = {}
    for skill, pulled in _gate_pulls().items():
        bad = [t for t in pulled if t not in registered]
        if bad:
            offenders[skill] = bad
    assert not offenders, f"gate-views pulling unregistered types: {offenders}"


@pytest.mark.skipif(not _REGISTRY_REACHABLE, reason="measurement_types.yaml not reachable")
def test_pulled_but_not_live_types_are_surfaced_not_hidden():
    """Pulls that resolve to registered_no_live_provider are legitimate visible-gap states (e.g.
    fusion_rearrangement, surface_confirmation pre-CSPA-reader). This test doesn't forbid them — it
    documents/pins that the resolver CAN see them, so a renderer can show the gap honestly."""
    pulls = _gate_pulls()
    resolutions = {t: mt.resolve_pull(t).status
                   for pulled in pulls.values() for t in pulled}
    # at least one known data-blocked pull is present and correctly classed (guards the visible-gap path)
    assert resolutions.get("fusion_rearrangement") == mt.STATUS_NO_LIVE
