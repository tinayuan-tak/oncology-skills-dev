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
def test_placeholder_only_type_is_registered_but_not_live(monkeypatch):
    """The NO_LIVE classification path: a type that IS registered but whose every provider is a
    {source: placeholder} resolves to registered_no_live_provider. Anchored on a SYNTHETIC provider
    set (not a live registry type) so it stays valid as types graduate placeholder→live — every
    registered type is now live (fusion_rearrangement graduated to tcga-fusion-consensus-v1, see
    test_placeholder_graduation_is_live below), so there is no longer a real placeholder type to
    point at. This guards the classification LOGIC, which is still load-bearing for the next
    not-yet-wired type someone registers."""
    monkeypatch.setattr(mt, "registered_types", lambda: {"synthetic_placeholder_type"})
    monkeypatch.setattr(mt, "_providers",
                        lambda t: [{"kind": "dataset", "source": "placeholder"}]
                        if t == "synthetic_placeholder_type" else [])
    r = mt.resolve_pull("synthetic_placeholder_type")
    assert r.status == mt.STATUS_NO_LIVE
    assert r.is_registered


@pytest.mark.skipif(not _REGISTRY_REACHABLE, reason="measurement_types.yaml not reachable")
def test_placeholder_graduation_is_live():
    """REGRESSION (2026-08-09): fusion_rearrangement was the framework's canonical placeholder-only
    type; it has since graduated to a live dataset provider (tcga-fusion-consensus-v1, EML4-ALK
    verified). Pin that it now resolves live_provider off that dataset, so a future edit that reverts
    the provider to a placeholder fails loudly. (This replaced the stale assertion that fusion was
    registered_no_live_provider.)"""
    r = mt.resolve_pull("fusion_rearrangement")
    assert r.status == mt.STATUS_LIVE
    assert r.is_registered
    assert "tcga-fusion-consensus-v1" in r.provider_sources


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
def test_registered_no_live_provider_is_a_surfaceable_state(monkeypatch):
    """A registered_no_live_provider pull is a legitimate VISIBLE-GAP state — the resolver must
    surface it (not hide it or crash), so a renderer can show the gap honestly. Historically anchored
    on fusion_rearrangement / surface_confirmation while they were placeholders; both have since
    graduated to live datasets, and NO registered type is placeholder-only today (the framework fully
    wired its pull-intents). So we drive the visible-gap path through a synthetic placeholder rather
    than a live type, keeping the guarantee under test independent of registry graduation."""
    monkeypatch.setattr(mt, "registered_types", lambda: {"gap_type", "live_type"})
    monkeypatch.setattr(mt, "_providers", lambda t: {
        "gap_type": [{"kind": "dataset", "source": "placeholder"}],
        "live_type": [{"kind": "dataset", "source": "some-real-product-v1"}],
    }.get(t, []))
    res = mt.resolve_pulled_types(["gap_type", "live_type"])
    by_type = {r.measurement_type: r for r in res}
    # the gap is surfaced (classified, registered, not dropped) alongside the live one — both visible
    assert by_type["gap_type"].status == mt.STATUS_NO_LIVE
    assert by_type["gap_type"].is_registered
    assert by_type["live_type"].status == mt.STATUS_LIVE


@pytest.mark.skipif(not _REGISTRY_REACHABLE, reason="measurement_types.yaml not reachable")
def test_no_gate_pulls_an_unregistered_type_via_resolutions():
    """Live-registry companion to the synthetic gap test: every type any wired gate actually pulls
    resolves to a REGISTERED status (live_provider or registered_no_live_provider — never unregistered).
    Complements test_every_pulled_type_is_registered by exercising the resolver end-to-end."""
    pulls = _gate_pulls()
    unregistered = {t for pulled in pulls.values() for t in pulled
                    if not mt.resolve_pull(t).is_registered}
    assert not unregistered, f"wired gates pull unregistered types: {sorted(unregistered)}"
