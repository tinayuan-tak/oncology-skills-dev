"""Phase-1c: the subgroup-stratified-mutation-frequency dispatcher must PARTITION
strata by data-source axis — molecular → TCGA shard + tcga_mc3; LOT_* → GENIE-BPC
shard + genie_registry — and MERGE the per_subgroup_metrics.

Before this, LOT strata were routed to the TCGA shard + MC3 MAF (wrong sample universe →
subgroup_n=0). These tests mock the panorama builder to capture the (subgroups, manifest,
maf_source) each arm is called with — no S3.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # skills/ — _live_readers in _skills_common

from _skills_common import _live_readers as L  # noqa: E402


class _FakeHotspot:
    """Records each build_mutation_frequency_panorama call + returns one row per stratum."""
    def __init__(self):
        self.calls = []

    def build_mutation_frequency_panorama(self, *, target, indication, subgroups,
                                          subgroup_assignments_manifest, maf_source="tcga_mc3", **kw):
        self.calls.append({"subgroups": list(subgroups),
                           "manifest": subgroup_assignments_manifest,
                           "maf_source": maf_source})
        cohort = "GENIE-registry" if maf_source == "genie_registry" else "TCGA-MC3"
        return {"per_subgroup_metrics": [
            {"stratum": s, "source_cohort": cohort, "evidence_state": "measured"} for s in subgroups]}


def _patch(monkeypatch):
    fake = _FakeHotspot()
    monkeypatch.setattr(L, "_import_method", lambda name: fake)
    return fake


def test_mixed_strata_partition_two_calls(monkeypatch):
    fake = _patch(monkeypatch)
    out = L._dispatch_subgroup_stratified_mutation_frequency(
        "KRAS", "COADREAD",
        subgroups=["MSS", "LOT_1L_only", "LOT_2L"],
        subgroup_assignments_manifest="tcga-subgroup-assignments-coadread-v1")
    # two arms called
    assert len(fake.calls) == 2
    mol = next(c for c in fake.calls if c["maf_source"] == "tcga_mc3")
    lot = next(c for c in fake.calls if c["maf_source"] == "genie_registry")
    assert mol["subgroups"] == ["MSS"]
    assert mol["manifest"] == "tcga-subgroup-assignments-coadread-v1"
    assert set(lot["subgroups"]) == {"LOT_1L_only", "LOT_2L"}
    assert lot["manifest"] == "genie-bpc-subgroup-assignments-coadread-v1"
    # merged rows carry correct source_cohort
    rows = {r["stratum"]: r["source_cohort"] for r in out["per_subgroup_metrics"]}
    assert rows == {"MSS": "TCGA-MC3", "LOT_1L_only": "GENIE-registry", "LOT_2L": "GENIE-registry"}


def test_molecular_only_single_arm_no_merge_wrapper(monkeypatch):
    fake = _patch(monkeypatch)
    out = L._dispatch_subgroup_stratified_mutation_frequency(
        "KRAS", "COADREAD", subgroups=["MSI_H", "MSS"],
        subgroup_assignments_manifest="tcga-subgroup-assignments-coadread-v1")
    assert len(fake.calls) == 1
    assert fake.calls[0]["maf_source"] == "tcga_mc3"
    # single arm returned verbatim (byte-stable — no LOT regression on molecular-only runs)
    assert [r["stratum"] for r in out["per_subgroup_metrics"]] == ["MSI_H", "MSS"]


def test_lot_only_routes_to_genie(monkeypatch):
    fake = _patch(monkeypatch)
    out = L._dispatch_subgroup_stratified_mutation_frequency(
        "KRAS", "COADREAD", subgroups=["LOT_3Lplus"],
        subgroup_assignments_manifest="tcga-subgroup-assignments-coadread-v1")
    assert len(fake.calls) == 1
    assert fake.calls[0]["maf_source"] == "genie_registry"
    assert fake.calls[0]["manifest"] == "genie-bpc-subgroup-assignments-coadread-v1"
    assert out["per_subgroup_metrics"][0]["source_cohort"] == "GENIE-registry"


def test_lot_without_shard_emits_note_not_crash(monkeypatch):
    fake = _patch(monkeypatch)
    # STAD has no LOT shard in the map → LOT arm degrades to a data-note, molecular arm still runs.
    # (NSCLC/COADREAD now HAVE LOT shards, so an unsharded indication is used here.)
    out = L._dispatch_subgroup_stratified_mutation_frequency(
        "KRAS", "STAD", subgroups=["MSS", "LOT_1L_only"],
        subgroup_assignments_manifest="tcga-subgroup-assignments-stad-v1")
    # only the molecular arm actually calls the builder; LOT arm is a note
    assert any(c["maf_source"] == "tcga_mc3" for c in fake.calls)
    assert "_data_note" in out and "LOT" in out["_data_note"]


# --- read_live_summary must NOT prematurely bail for an indication that
#     has ONLY a GENIE-BPC LOT shard (e.g. NSCLC). The outer gate keyed on the molecular-only
#     manifest map, so the NSCLC LOT panorama was unreachable + emitted a factually-wrong note. ---

def test_nsclc_lot_reaches_dispatcher_not_premature_bail(monkeypatch):
    fake = _patch(monkeypatch)
    out = L.read_live_summary(
        "subgroup-stratified-mutation-frequency", "KRAS", "NSCLC",
        subgroup_context={"resolved_strata_ids": ["LOT_1L_only", "LOT_2L"],
                          "catalog_status": "resolved_active"})
    # did NOT short-circuit with the (wrong) "no subgroup-assignments shard for NSCLC" note
    assert "no subgroup-assignments shard" not in (out.get("_data_note") or "")
    # the LOT arm ran against the NSCLC GENIE-BPC shard
    assert len(fake.calls) == 1
    assert fake.calls[0]["maf_source"] == "genie_registry"
    assert fake.calls[0]["manifest"] == "genie-bpc-subgroup-assignments-nsclc-v1"
    assert {r["stratum"] for r in out["per_subgroup_metrics"]} == {"LOT_1L_only", "LOT_2L"}


def test_nsclc_molecular_strata_get_data_note_not_crash(monkeypatch):
    # A molecular stratum requested for NSCLC (no molecular shard): the dispatcher is still reached
    # (LOT shard exists), the molecular arm emits an honest data-note, and nothing crashes.
    fake = _patch(monkeypatch)
    out = L.read_live_summary(
        "subgroup-stratified-mutation-frequency", "KRAS", "NSCLC",
        subgroup_context={"resolved_strata_ids": ["MSS"], "catalog_status": "resolved_active"})
    assert fake.calls == []                                   # builder NOT called with a null manifest
    assert "no molecular subgroup-assignments shard" in (out.get("_data_note") or "")
