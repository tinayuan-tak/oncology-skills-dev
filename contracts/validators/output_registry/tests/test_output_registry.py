"""Tests for the output-registry generator + the framework_health signal merge.

CI-safe: no sibling repos, no S3, no network. The exploratory tier (which reads S3) is
exercised only via the empty-run-list path; the byte-stability + additive-signal guarantees
are the load-bearing claims and are tested against local fixtures.

Run: pytest validators/output_registry/tests/ -q
"""

from __future__ import annotations

import json
from pathlib import Path

from validators.framework_health import probe
from validators.output_registry import build_output_registry as R


def _write_pkg(root: Path, target: str, ind: str, cards: list[tuple[str, str | None]]) -> Path:
    d = root / target / ind / f"ep-{target.lower()}-{ind.lower()}-unpinned-latest_approved-001"
    d.mkdir(parents=True)
    pkg = {
        "package_id": d.name,
        "context": {"target": {"symbol": target}, "indication": {"oncotree_code": ind}},
        "cards": [{"card_id": c, "validation_state": s} for c, s in cards],
    }
    (d / "evidence_package.json").write_text(json.dumps(pkg))
    return d


# --- generator: governed firing index mirrors the probe's pass-state semantics ---------
def test_governed_firings_only_counts_fired_states(tmp_path):
    _write_pkg(
        tmp_path,
        "BRAF",
        "SKCM",
        [("a", "pass"), ("b", "passed_with_warnings"), ("c", "fail"), ("d", None), ("e", "passed")],
    )
    gov = R._governed_card_firings(str(tmp_path))
    assert set(gov) == {"a", "b", "e"}
    assert gov["a"] == ["ep-braf-skcm-unpinned-latest_approved-001"]


def test_card_firings_governed_only_without_runs(tmp_path):
    _write_pkg(tmp_path, "BRAF", "SKCM", [("a", "pass"), ("b", "pass")])
    cf = R._card_firings(str(tmp_path), [])  # empty run list => no S3 harvest
    assert cf["fired_card_ids_governed"] == ["a", "b"]
    assert cf["fired_card_ids_any"] == ["a", "b"]
    assert cf["n_exploratory_only"] == 0


# --- the safety guarantee: registry governed subset == probe.fired_card_ids glob -------
def test_registry_governed_equals_probe_glob(tmp_path):
    _write_pkg(tmp_path, "BRAF", "SKCM", [("a", "pass"), ("b", "fail")])
    _write_pkg(tmp_path, "KRAS", "COADREAD", [("a", "passed_with_warnings"), ("c", "pass")])
    glob = probe.fired_card_ids(tmp_path)
    gov = set(R._governed_card_firings(str(tmp_path)))
    assert gov == glob == {"a", "c"}


# --- probe seam: absent registry degrades to the glob; present registry is authoritative
def test_fired_any_absent_registry_degrades_to_glob(tmp_path):
    _write_pkg(tmp_path, "BRAF", "SKCM", [("a", "pass"), ("b", "pass")])
    assert not (tmp_path / "catalog.json").exists()
    assert probe.fired_card_ids_any(tmp_path) == probe.fired_card_ids(tmp_path) == {"a", "b"}


def test_fired_any_uses_registry_superset(tmp_path):
    _write_pkg(tmp_path, "BRAF", "SKCM", [("a", "pass")])
    (tmp_path / "catalog.json").write_text(
        json.dumps({"card_firings": {"fired_card_ids_governed": ["a"], "fired_card_ids_any": ["a", "z"]}})
    )
    assert probe.fired_card_ids(tmp_path) == {"a"}  # governed glob unchanged
    assert probe.fired_card_ids_any(tmp_path) == {"a", "z"}  # exploratory-lit 'z' added


def test_registry_card_firings_none_when_malformed(tmp_path):
    (tmp_path / "catalog.json").write_text("{ not json")
    assert probe.registry_card_firings(tmp_path) is None
    # and fired_card_ids_any still works via fallback
    assert probe.fired_card_ids_any(tmp_path) == set()


# --- probe_card: fires_in_any_run is additive; fires_in_real_package stays governed ----
def test_probe_card_fires_in_any_run_additive(tmp_path):
    # 'z' fired only in an exploratory run (in fired_any_ids, not in fired_ids)
    card = probe.probe_card("z", tmp_path, tmp_path, live_ids=set(), fired_ids={"a"}, fired_any_ids={"a", "z"})
    assert card["fires_in_real_package"] is False  # not in a governed package
    assert card["fires_in_any_run"] is True  # but fired in a real run


def test_probe_card_fires_in_any_defaults_to_governed(tmp_path):
    # no fired_any_ids passed => field mirrors fires_in_real_package (pre-merge behaviour)
    card = probe.probe_card("a", tmp_path, tmp_path, live_ids=set(), fired_ids={"a"})
    assert card["fires_in_real_package"] is True
    assert card["fires_in_any_run"] is True
    card2 = probe.probe_card("b", tmp_path, tmp_path, live_ids=set(), fired_ids={"a"})
    assert card2["fires_in_real_package"] is False
    assert card2["fires_in_any_run"] is False


# --- exploratory harvest: BOTH run shapes, and misses are counted -----------------------
#
# 2026-09-11: the harvest read only decision.json, which FOCUSED skills emit. COMPOSED
# (target-profile) runs emit evidence_package.json and no decision.json, so all 10 published
# composed runs contributed nothing and n_exploratory_only was 0 — which then made the
# framework-health drift feed report 8 cards as never-firing that those runs had proven live.
def _fake_s3(monkeypatch, files: dict[str, dict]):
    """Stub `aws s3 cp <uri>/<name> <dst>`: files maps "<run-leaf>/<name>" -> json payload."""

    class _R:
        def __init__(self, rc):
            self.returncode = rc

    def run(cmd, capture_output=True, text=True):
        src, dst = cmd[3], cmd[4]
        leaf, name = src.rstrip("/").rsplit("/", 2)[-2:]
        payload = files.get(f"{leaf}/{name}")
        if payload is None:
            return _R(1)
        Path(dst).write_text(json.dumps(payload))
        return _R(0)

    monkeypatch.setattr(R.subprocess, "run", run)


def _entry(leaf: str) -> dict:
    return {"s3_uri": f"s3://b/skill-runs/skill/T-I/{leaf}", "s3_key": f"skill-runs/skill/T-I/{leaf}"}


def test_exploratory_harvest_reads_focused_decision_json(monkeypatch):
    _fake_s3(monkeypatch, {"r1/decision.json": {"run_health": {"cards_fired": ["a", "b"]}}})
    fired, rep = R._exploratory_card_firings([_entry("r1")])
    assert set(fired) == {"a", "b"}
    assert rep["n_from_decision"] == 1 and rep["n_from_package"] == 0
    assert rep["unreadable_runs"] == []


def test_exploratory_harvest_falls_back_to_composed_evidence_package(monkeypatch):
    """The regression under test: no decision.json, so the card set must come from the package
    using the SAME fired-state predicate the governed side applies."""
    _fake_s3(
        monkeypatch,
        {
            "r1/evidence_package.json": {
                "cards": [
                    {"card_id": "immune-context", "validation_state": "pass"},
                    {"card_id": "x", "validation_state": "passed_with_warnings"},
                    {"card_id": "skipped", "validation_state": "fail"},
                    {"card_id": "none-state", "validation_state": None},
                ]
            }
        },
    )
    fired, rep = R._exploratory_card_firings([_entry("r1")])
    assert set(fired) == {"immune-context", "x"}, "fail/None states must not count as fired"
    assert rep["n_from_package"] == 1 and rep["n_from_decision"] == 0


def test_exploratory_harvest_counts_unreadable_runs(monkeypatch):
    """A blinded harvest must be VISIBLE. Silently contributing nothing is indistinguishable from
    'these cards never fired' — which is the very claim this index is used to make."""
    _fake_s3(monkeypatch, {})  # neither artifact fetchable (creds/layout change)
    fired, rep = R._exploratory_card_firings([_entry("r1"), _entry("r2")])
    assert fired == {}
    assert rep["n_runs"] == 2
    assert rep["unreadable_runs"] == ["r1", "r2"]


def test_card_firings_surfaces_the_harvest_report(monkeypatch, tmp_path):
    _write_pkg(tmp_path, "BRAF", "SKCM", [("gov-only", "pass")])
    _fake_s3(
        monkeypatch, {"r1/evidence_package.json": {"cards": [{"card_id": "exp-only", "validation_state": "pass"}]}}
    )
    cf = R._card_firings(str(tmp_path), [_entry("r1")])
    assert cf["fired_card_ids_governed"] == ["gov-only"]
    assert cf["fired_card_ids_any"] == ["exp-only", "gov-only"]
    assert cf["n_exploratory_only"] == 1
    assert cf["exploratory_harvest"]["n_from_package"] == 1
