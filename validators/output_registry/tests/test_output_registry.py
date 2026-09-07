"""Tests for the output-registry generator + the framework_health signal merge.

CI-safe: no sibling repos, no S3, no network. The exploratory tier (which reads S3) is
exercised only via the empty-run-list path; the byte-stability + additive-signal guarantees
are the load-bearing claims and are tested against local fixtures.

Run: pytest validators/output_registry/tests/ -q
"""

from __future__ import annotations

import json
from pathlib import Path

from validators.output_registry import build_output_registry as R
from validators.framework_health import probe


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
