"""progeny_pathway_activity — hermetic tests (synthetic per-(pathway x indication) frame, no S3).

Pins the relative-class thresholds (cross-indication z), the composite-indication pooling
(COADREAD = COAD+READ sample-weighted), and the data_unavailable path. The live scoring + biology
(COADREAD Hypoxia-high etc.) is verified in the build micro-benchmark, not here (hermetic = no network)."""

from __future__ import annotations

from onc_methods.progeny_pathway_activity import read as prog_read


def _fake_product():
    import pandas as pd

    # two member studies for COADREAD + a standalone; z already precomputed for the test
    return pd.DataFrame(
        [
            {
                "indication": "COAD",
                "pathway": "WNT",
                "n_samples": 300,
                "median_activity": 2.0,
                "p25_activity": 1.0,
                "p75_activity": 3.0,
                "activity_z_across_indications": 1.5,
            },
            {
                "indication": "READ",
                "pathway": "WNT",
                "n_samples": 100,
                "median_activity": 2.0,
                "p25_activity": 1.0,
                "p75_activity": 3.0,
                "activity_z_across_indications": 1.5,
            },
            {
                "indication": "COAD",
                "pathway": "p53",
                "n_samples": 300,
                "median_activity": -3.0,
                "p25_activity": -4.0,
                "p75_activity": -2.0,
                "activity_z_across_indications": -1.4,
            },
            {
                "indication": "READ",
                "pathway": "p53",
                "n_samples": 100,
                "median_activity": -3.0,
                "p25_activity": -4.0,
                "p75_activity": -2.0,
                "activity_z_across_indications": -1.4,
            },
            {
                "indication": "COAD",
                "pathway": "MAPK",
                "n_samples": 300,
                "median_activity": 0.3,
                "p25_activity": -0.5,
                "p75_activity": 1.0,
                "activity_z_across_indications": 0.1,
            },
            {
                "indication": "READ",
                "pathway": "MAPK",
                "n_samples": 100,
                "median_activity": 0.3,
                "p25_activity": -0.5,
                "p75_activity": 1.0,
                "activity_z_across_indications": 0.1,
            },
        ]
    )


def test_relative_class_thresholds(monkeypatch):
    monkeypatch.setattr(prog_read, "_load_product", _fake_product)
    monkeypatch.setattr(
        prog_read._cli,
        "_load_model",
        lambda top_n=100: __import__("pandas").DataFrame({"source": ["WNT"], "target": ["ZZZ"], "weight": [1.0]}),
    )
    out = prog_read.read_progeny_pathway_activity(target="ZZZ", indication="COADREAD")
    assert "WNT" in out["relatively_high_pathways"]  # z 1.5 >= +1
    assert "p53" in out["relatively_low_pathways"]  # z -1.4 <= -1
    assert "MAPK" not in out["relatively_high_pathways"]  # z 0.1 → average
    assert out["pooled_from"] == ["COAD", "READ"]  # composite pooling
    assert out["n_pathways_profiled"] == 3


def test_target_pathway_membership(monkeypatch):
    import pandas as pd

    monkeypatch.setattr(prog_read, "_load_product", _fake_product)
    monkeypatch.setattr(
        prog_read._cli,
        "_load_model",
        lambda top_n=100: pd.DataFrame({"source": ["MAPK", "WNT"], "target": ["EGFR", "MYC"], "weight": [5.0, 3.0]}),
    )
    out = prog_read.read_progeny_pathway_activity(target="EGFR", indication="COAD")
    assert out["target_pathway_membership"] == ["MAPK"]  # EGFR is a MAPK responsive gene in the fake model


def test_unmapped_indication_is_data_unavailable(monkeypatch):
    monkeypatch.setattr(prog_read, "_load_product", _fake_product)
    out = prog_read.read_progeny_pathway_activity(indication="ZZZ_NOT_A_CANCER")
    assert out["pathway_activity_class"] == "data_unavailable"


def test_missing_indication_is_data_unavailable():
    out = prog_read.read_progeny_pathway_activity(indication=None)
    assert out["pathway_activity_class"] == "data_unavailable"


# --- resolver seam (all 3 hard-coded S3 URIs now resolve via catalog_query.s3_uri_for) --------------


def _patch_resolver(monkeypatch, mapping):
    """Replace catalog_query.read.s3_uri_for with a dict lookup (hermetic — no manifest files)."""
    import onc_methods.catalog_query.read as cq

    monkeypatch.setattr(cq, "s3_uri_for", lambda mid, **kw: mapping[mid])


def test_derived_uri_resolves_via_manifest(monkeypatch):
    _patch_resolver(
        monkeypatch,
        {
            "progeny-pathway-activity-per-indication-v1": "s3://bucket/data-catalog/derived/progeny-pathway-activity-per-indication-v1/progeny_activity_per_indication.parquet"
        },
    )
    assert prog_read._resolve_derived_uri().endswith("/progeny_activity_per_indication.parquet")
    assert prog_read.DERIVED_MANIFEST_ID == "progeny-pathway-activity-per-indication-v1"


def test_expr_uri_resolves_via_manifest(monkeypatch):
    from onc_methods.progeny_pathway_activity import cli as prog_cli

    _patch_resolver(
        monkeypatch,
        {
            "tcga-tumor-tpm-recount3-long-v1": "s3://bucket/data-catalog/derived/tcga-tumor-tpm-recount3-long-v1/tcga_tpm_long.parquet"
        },
    )
    assert prog_cli._resolve_expr_uri().endswith("/tcga_tpm_long.parquet")


def test_model_uri_appends_filename_to_source_directory(monkeypatch):
    """The source manifest s3_uri is a DIRECTORY (trailing slash); the helper appends the filename."""
    from onc_methods.progeny_pathway_activity import cli as prog_cli

    _patch_resolver(
        monkeypatch,
        {
            "progeny-saezlab-snapshot-2026-08-10": "s3://bucket/data-catalog/sources/progeny-saezlab/snapshot-2026-08-10/"
        },
    )
    uri = prog_cli._resolve_model_uri()
    assert uri == "s3://bucket/data-catalog/sources/progeny-saezlab/snapshot-2026-08-10/progeny_model_human.parquet"
    assert "//progeny_model_human" not in uri.replace("s3://", "")  # no double slash from the join


def test_resolver_import_is_call_time_not_import_time(monkeypatch):
    """read/test paths must not require the resolver at import — the read tests above already pass
    without patching s3_uri_for because _load_product is monkeypatched. This asserts the seam is a
    function (deferred import), so a missing manifest fails at call, not at module import."""
    import inspect

    src = inspect.getsource(prog_read._resolve_derived_uri)
    assert "from onc_methods.catalog_query.read import s3_uri_for" in src  # imported INSIDE the function
