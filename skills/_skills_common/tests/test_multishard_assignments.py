"""Multi-shard assignment routing (2026-09-11, NSCLC/DepMap-CMS wiring).

Reality is MULTIPLE assignments shards per (indication, cohort), partitioned by derivation method.
`_route_strata_to_shards` sends each requested stratum to the shard that carries it, calls the builder
once per populated shard, merges the per_subgroup_metrics, and data-notes strata no shard carries.
These tests pin the routing with a STUB builder (no live data) + assert the registries match the
materialized shards.
"""

from __future__ import annotations

import _skills_common._live_readers as lr  # noqa: E402  (skills/ on sys.path via skills/conftest.py)


def _stub_builder(calls):
    """A build_*_panorama stand-in: records each (manifest, subgroups) call and returns one measured
    per_subgroup row per requested stratum, so the merge is observable."""

    def _b(*, target, indication, subgroups, subgroup_assignments_manifest, **kw):
        calls.append((subgroup_assignments_manifest, list(subgroups)))
        return {
            "per_subgroup_metrics": [
                {"stratum": s, "evidence_state": "measured", "median_chronos": -0.5} for s in subgroups
            ]
        }

    return _b


def test_routes_each_stratum_to_the_shard_that_carries_it():
    calls: list = []
    shards = [
        ("shard-A", {"MSI_H", "MSS"}),
        ("shard-B", {"CMS1_depmap", "CMS2_depmap"}),
    ]
    out = lr._route_strata_to_shards(
        _stub_builder(calls),
        target="X",
        indication="COADREAD",
        subgroups=["MSI_H", "CMS1_depmap", "MSS"],
        shards=shards,
        reducer_metric="median_chronos",
        reducer_label="dependency",
    )
    # one call per POPULATED shard, each with only the strata it carries (requested-order preserved)
    assert ("shard-A", ["MSI_H", "MSS"]) in calls
    assert ("shard-B", ["CMS1_depmap"]) in calls
    assert len(calls) == 2
    # merged rows cover every requested stratum
    strata = {r["stratum"] for r in out["per_subgroup_metrics"]}
    assert strata == {"MSI_H", "MSS", "CMS1_depmap"}
    assert "_data_note" not in out  # everything was covered


def test_uncovered_stratum_gets_a_data_note_never_a_row():
    calls: list = []
    out = lr._route_strata_to_shards(
        _stub_builder(calls),
        target="X",
        indication="NSCLC",
        subgroups=["histology_Adeno", "EGFR_mut_L858R"],  # only histology is in the depmap dep shard
        shards=[("depmap-subgroup-assignments-nsclc-v1", {"histology_Adeno", "histology_SCC"})],
        reducer_metric="median_chronos",
        reducer_label="dependency",
    )
    assert calls == [("depmap-subgroup-assignments-nsclc-v1", ["histology_Adeno"])]
    strata = {r["stratum"] for r in out["per_subgroup_metrics"]}
    assert strata == {"histology_Adeno"}  # EGFR is NOT fabricated as a row
    assert "EGFR_mut_L858R" in out["_data_note"]


def test_registries_wire_the_materialized_shards():
    # DepMap dependency: COADREAD MSI + CMScaller-CMS; NSCLC histology.
    dep = lr._DEPENDENCY_ASSIGNMENTS_SHARDS
    assert {m for m, _ in dep["COADREAD"]} == {
        "depmap-subgroup-assignments-coadread-v1",
        "depmap-subgroup-assignments-coadread-cms-v1",
    }
    cms_strata = next(s for m, s in dep["COADREAD"] if m.endswith("cms-v1"))
    assert cms_strata == {"CMS1_depmap", "CMS2_depmap", "CMS3_depmap", "CMS4_depmap"}
    assert dep["NSCLC"] == [("depmap-subgroup-assignments-nsclc-v1", {"histology_Adeno", "histology_SCC"})]
    # NSCLC mutation-freq: directly-tagged histology/fusion shard + MAF mutation-status shard (disjoint)
    mol = lr._MUTATION_MOLECULAR_ASSIGNMENTS_SHARDS["NSCLC"]
    a, b = mol[0][1], mol[1][1]
    assert not (a & b), "the two NSCLC molecular shards must carry DISJOINT strata"
    assert "histology_Adeno" in a and "EGFR_mut_L858R" in b
    # NSCLC dependency primary is registered so read_live_summary does not bail
    assert lr._DEPENDENCY_ASSIGNMENTS_MANIFEST["NSCLC"] == "depmap-subgroup-assignments-nsclc-v1"
