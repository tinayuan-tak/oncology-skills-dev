"""Dry-run tests for scripts/emit_subgroup_assignments.py + run_subgroup_emit_batch.sh.

Verifies the Phase 2b/c emission-driver architecture without requiring
AWS credentials, S3 access, or source-data cache-population.

Test structure:
  1. ShardSpec derives correct paths + IDs across all 20 shards in the matrix
  2. Dry-run driver invocation prints the expected plan (subprocess-argv,
     S3 URIs, derived-manifest paths)
  3. Batch driver iterates over the shard-matrix TSV correctly
"""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARDS_TSV = REPO_ROOT / "scripts" / "subgroup_emit_shards.tsv"


# ---------- ShardSpec derivation ----------


def test_shardspec_coadread_marker_paper():
    """COADREAD × tcga_marker_paper: paths + IDs derive correctly."""
    from scripts.emit_subgroup_assignments import ShardSpec

    shard = ShardSpec(
        source="tcga_marker_paper",
        indication="COADREAD",
        release_pin="2026-Q2",
        catalog_repo=Path("/tmp/data-catalog"),
        run_dir=Path("/tmp/run"),
    )
    assert shard.derived_manifest_id == "tcga-marker-paper-subgroup-assignments-coadread-v1"
    assert shard.s3_uri_base == (
        "s3://onc-compbio/data-catalog/derived/subgroup-assignments/coadread/tcga_marker_paper/2026-q2"
    )
    assert shard.out_dir == Path("/tmp/run/COADREAD/tcga_marker_paper")


def test_shardspec_sclc_classifier():
    """SCLC × depmap_expression: classifier-config required."""
    from scripts.emit_subgroup_assignments import ShardSpec

    shard = ShardSpec(
        source="depmap_expression",
        indication="SCLC",
        release_pin="2026-Q3",
        catalog_repo=Path("/tmp/data-catalog"),
        run_dir=Path("/tmp/run"),
        classifier_config=Path("/tmp/sclc-napy-config.yaml"),
    )
    assert shard.derived_manifest_id == "depmap-expression-subgroup-assignments-sclc-v1"
    assert shard.classifier_config == Path("/tmp/sclc-napy-config.yaml")


def test_shardspec_aml_multi_cohort():
    """AML has 4 source keys (tcga_marker_paper, tcga_maf, beataml_maf,
    target_aml_maf) — each produces a distinct derived-manifest id."""
    from scripts.emit_subgroup_assignments import ShardSpec

    ids = set()
    for source in ["tcga_marker_paper", "tcga_maf", "beataml_maf", "target_aml_maf"]:
        shard = ShardSpec(
            source=source,
            indication="AML",
            release_pin="2026-Q3",
            catalog_repo=Path("/tmp/data-catalog"),
            run_dir=Path("/tmp/run"),
        )
        ids.add(shard.derived_manifest_id)
    assert len(ids) == 4  # All four manifest ids distinct
    assert "beataml-maf-subgroup-assignments-aml-v1" in ids
    assert "target-aml-maf-subgroup-assignments-aml-v1" in ids


# ---------- Source → assigner mapping ----------


def test_all_seven_sources_have_assigner_mapping():
    """SOURCE_TO_ASSIGNER covers all shard-matrix source keys."""
    from scripts.emit_subgroup_assignments import SOURCE_TO_ASSIGNER

    expected = {
        "tcga_marker_paper",
        "tcga_maf",
        "depmap_omics_inferred",
        "depmap_somatic",
        "depmap_expression",
        "beataml_maf",
        "target_aml_maf",
    }
    assert set(SOURCE_TO_ASSIGNER.keys()) == expected


def test_source_maps_to_correct_assigner():
    """Directly-tagged sources → subgroup_assigner_directly_tagged;
    MAF sources → subgroup_assigner_maf_filter;
    expression source → subgroup_assigner_classifier."""
    from scripts.emit_subgroup_assignments import SOURCE_TO_ASSIGNER

    assert SOURCE_TO_ASSIGNER["tcga_marker_paper"][0] == "subgroup_assigner_directly_tagged"
    assert SOURCE_TO_ASSIGNER["depmap_omics_inferred"][0] == "subgroup_assigner_directly_tagged"
    assert SOURCE_TO_ASSIGNER["tcga_maf"][0] == "subgroup_assigner_maf_filter"
    assert SOURCE_TO_ASSIGNER["depmap_somatic"][0] == "subgroup_assigner_maf_filter"
    assert SOURCE_TO_ASSIGNER["beataml_maf"][0] == "subgroup_assigner_maf_filter"
    assert SOURCE_TO_ASSIGNER["target_aml_maf"][0] == "subgroup_assigner_maf_filter"
    assert SOURCE_TO_ASSIGNER["depmap_expression"][0] == "subgroup_assigner_classifier"


# ---------- Shard-matrix TSV ----------


def test_shard_matrix_parses():
    """subgroup_emit_shards.tsv has expected shape + all rows use valid sources."""
    from scripts.emit_subgroup_assignments import SOURCE_TO_ASSIGNER

    lines = [line.strip() for line in SHARDS_TSV.read_text().splitlines() if line.strip() and not line.startswith("#")]
    assert len(lines) >= 15  # at least 15 non-comment rows

    valid_sources = set(SOURCE_TO_ASSIGNER.keys())
    valid_indications = {"COADREAD", "NSCLC", "SCLC", "HNSC", "STAD", "ESCA", "PAAD", "AML"}
    for line in lines:
        parts = line.split("\t")
        assert len(parts) == 4, f"Row must have 4 tab-separated fields: {line!r}"
        source, indication, release_pin, classifier_config = parts
        assert source in valid_sources, f"Unknown source in matrix: {source!r}"
        assert indication in valid_indications, f"Unknown indication: {indication!r}"
        assert release_pin in {"2026-Q2", "2026-Q3"}, f"Unexpected release_pin: {release_pin!r}"


def test_coadread_uses_2026_q2_release_pin():
    """COADREAD is the anchor catalog on 2026-Q2 (not 2026-Q3)."""
    lines = [line.strip() for line in SHARDS_TSV.read_text().splitlines() if line.strip() and not line.startswith("#")]
    for line in lines:
        parts = line.split("\t")
        source, indication, release_pin, _ = parts
        if indication == "COADREAD":
            assert release_pin == "2026-Q2", f"COADREAD row uses {release_pin} but should be 2026-Q2 (anchor catalog)"


def test_sclc_only_uses_classifier():
    """SCLC row uses depmap_expression + sclc-napy classifier config."""
    lines = [line.strip() for line in SHARDS_TSV.read_text().splitlines() if line.strip() and not line.startswith("#")]
    sclc_rows = [line.split("\t") for line in lines if line.split("\t")[1] == "SCLC"]
    assert len(sclc_rows) == 1
    source, indication, release_pin, classifier_config = sclc_rows[0]
    assert source == "depmap_expression"
    assert classifier_config == "sclc-napy-2026-q3.yaml"


# ---------- Product-identity guards (sweep2 fixes 1 + 2) ----------


def test_s3_uri_base_is_under_data_catalog_prefix():
    """Fix 1: uploads MUST live under s3://onc-compbio/data-catalog/derived/ (on-convention with
    the other 91 derived products) — NOT the off-convention s3://onc-compbio/derived/ that no
    catalog reader resolves."""
    from scripts.emit_subgroup_assignments import ShardSpec

    shard = ShardSpec(
        source="tcga_maf",
        indication="NSCLC",
        release_pin="2026-Q3",
        catalog_repo=Path("/tmp/data-catalog"),
        run_dir=Path("/tmp/run"),
    )
    assert shard.s3_uri_base.startswith("s3://onc-compbio/data-catalog/derived/")
    assert "onc-compbio/derived/" not in shard.s3_uri_base


@pytest.mark.parametrize("source", ["beataml_maf", "target_aml_maf"])
def test_aml_adjunct_sources_fail_loud(source, tmp_path):
    """Fix 2: beataml_maf / target_aml_maf have no distinct MAF loader; the assigner would load the
    SAME TCGA-AML MAF as tcga_maf and emit a duplicate-identity manifest. They must raise, not
    silently emit."""
    from scripts.emit_subgroup_assignments import ShardSpec, _invoke_assigner

    shard = ShardSpec(
        source=source,
        indication="AML",
        release_pin="2026-Q3",
        catalog_repo=tmp_path,
        run_dir=tmp_path / "run",
    )
    with pytest.raises(NotImplementedError) as exc:
        _invoke_assigner(shard, dry_run=True)
    assert "duplicate-identity" in str(exc.value)
    # The failing manifest id is named so the operator knows exactly which shard to remove/fix.
    assert shard.derived_manifest_id in str(exc.value)


def test_aml_adjunct_sources_have_no_data_source_arg():
    """Fix 2: the SOURCE_TO_ASSIGNER data_source_arg for the adjunct sources is None (not 'tcga'),
    so the mapping itself no longer misrepresents them as loadable TCGA shards."""
    from scripts.emit_subgroup_assignments import (
        _SOURCES_WITHOUT_DISTINCT_LOADER,
        SOURCE_TO_ASSIGNER,
    )

    assert _SOURCES_WITHOUT_DISTINCT_LOADER == {"beataml_maf", "target_aml_maf"}
    for s in _SOURCES_WITHOUT_DISTINCT_LOADER:
        assert SOURCE_TO_ASSIGNER[s][1] is None


# ---------- CLI dry-run ----------


def test_cli_dry_run_prints_plan(monkeypatch, tmp_path):
    """DRY_RUN=1 invocation prints the plan without invoking assigner or S3."""
    # Fabricate a minimal catalog file for the shard's catalog_path check
    catalog_dir = tmp_path / "subgroup-catalogs" / "COADREAD"
    catalog_dir.mkdir(parents=True)
    catalog_path = catalog_dir / "2026-Q2.yaml"
    catalog_path.write_text("id: coadread-subgroups-2026-q2\nindication: COADREAD\n")

    env = dict(
        **{
            k: v
            for k, v in [
                ("PATH", "/opt/conda/bin:/usr/bin:/bin"),
                ("DRY_RUN", "1"),
                ("HOME", str(tmp_path)),
            ]
        }
    )

    result = subprocess.run(
        [
            "python",
            "-m",
            "scripts.emit_subgroup_assignments",
            "--source",
            "tcga_marker_paper",
            "--indication",
            "COADREAD",
            "--release-pin",
            "2026-Q2",
            "--catalog-repo",
            str(tmp_path),
            "--run-dir",
            str(tmp_path / "run"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, f"CLI failed:\n{result.stderr}"
    # Dry-run banner appears
    assert "DRY_RUN=1" in result.stderr
    # Shard identity printed
    assert "tcga_marker_paper × COADREAD" in result.stderr
    # Expected S3 URI
    assert (
        "s3://onc-compbio/data-catalog/derived/subgroup-assignments/coadread/tcga_marker_paper/2026-q2" in result.stderr
    )
    # Derived-manifest id
    assert "tcga-marker-paper-subgroup-assignments-coadread-v1" in result.stderr
    # Would-invoke assigner
    assert "subgroup_assigner_directly_tagged" in result.stderr


# ---------- --catalog-repo default portability ----------
#
# The option used to bake in a literal /home/sagemaker-user path. Nothing could observe it: the
# dry-run test below passes --catalog-repo explicitly, and a click decorator default is frozen at
# IMPORT time, so no monkeypatch.setenv could ever have reached it either.


DATA_CATALOG_SIBLING = REPO_ROOT.parent / "rnd-computational-biology-oncology-data-catalog"
NOT_THE_CHECKOUT_PARENT = "/tmp/emit-subgroup-fake-home-not-the-checkout-parent"


def test_catalog_repo_option_bakes_in_no_path():
    """click evaluates decorator defaults once, at import. Any path baked into the option is
    therefore frozen before a caller's environment exists — unreachable by a test and unaffected by
    DATA_CATALOG_ROOT being exported later. The option must carry None and resolve per run."""
    from scripts.emit_subgroup_assignments import main

    param = next(p for p in main.params if p.name == "catalog_repo")
    assert param.default is None, (
        f"--catalog-repo has a decorator default ({param.default!r}); resolve it per run in main() instead"
    )


def test_default_catalog_repo_is_derived_from_the_checkout_not_home(monkeypatch):
    """On a dev box $HOME and the checkout parent are the same directory, so only a faked $HOME can
    tell a home-anchored root from a checkout-derived one."""
    from scripts.emit_subgroup_assignments import _default_catalog_repo

    monkeypatch.delenv("DATA_CATALOG_ROOT", raising=False)
    monkeypatch.setenv("HOME", NOT_THE_CHECKOUT_PARENT)

    resolved = _default_catalog_repo()

    assert resolved == DATA_CATALOG_SIBLING
    assert NOT_THE_CHECKOUT_PARENT not in str(resolved)


def test_default_catalog_repo_honours_the_env_override(monkeypatch, tmp_path):
    """POSITIVE CONTROL: a path that does not move under a faked $HOME is indistinguishable from a
    function that was never called, so prove this resolution does move when the env names a root."""
    from scripts.emit_subgroup_assignments import _default_catalog_repo

    monkeypatch.setenv("DATA_CATALOG_ROOT", str(tmp_path))

    assert _default_catalog_repo() == tmp_path


def test_default_catalog_repo_falls_back_on_an_empty_env_value(monkeypatch):
    """DATA_CATALOG_ROOT="" must fall back, not yield Path("") — which is the CWD."""
    from scripts.emit_subgroup_assignments import _default_catalog_repo

    monkeypatch.setenv("DATA_CATALOG_ROOT", "")

    assert _default_catalog_repo() == DATA_CATALOG_SIBLING


def test_cli_resolves_catalog_repo_per_run_when_the_flag_is_omitted(tmp_path):
    """END-TO-END, in a real process with --catalog-repo OMITTED: the driver must resolve the root
    at run time and hand it to ShardSpec, with $HOME faked to a directory holding no catalog.

    THIS TEST PASSES AGAINST THE OLD CODE TOO, and that is worth stating so nobody mistakes it for
    the guard on the frozen-default defect. Steering it requires DATA_CATALOG_ROOT (the derived
    sibling is a real checkout, not this tmp_path), and a SUBPROCESS re-imports the module with that
    variable ALREADY SET — so the old import-time os.environ.get(...) default resolved correctly
    here. Click's freeze is only observable IN-PROCESS, where the environment changes after import.
    The actual guard on it is test_catalog_repo_option_bakes_in_no_path, which asserts on the
    parameter's structure rather than on behaviour. What this test does add: the resolved root
    reaches ShardSpec through a real invocation, and no $HOME fragment leaks into it."""
    catalog_repo = tmp_path / "data-catalog"
    catalog_dir = catalog_repo / "subgroup-catalogs" / "COADREAD"
    catalog_dir.mkdir(parents=True)
    catalog_yaml = catalog_dir / "2026-Q2.yaml"
    catalog_yaml.write_text("id: coadread-subgroups-2026-q2\nindication: COADREAD\n")
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()

    result = subprocess.run(
        [
            "python",
            "-m",
            "scripts.emit_subgroup_assignments",
            "--source",
            "tcga_marker_paper",
            "--indication",
            "COADREAD",
            "--release-pin",
            "2026-Q2",
            # no --catalog-repo: this is the branch a bare invocation takes
            "--run-dir",
            str(tmp_path / "run"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={
            "PATH": "/opt/conda/bin:/usr/bin:/bin",
            "DRY_RUN": "1",
            "HOME": str(fake_home),
            "DATA_CATALOG_ROOT": str(catalog_repo),
        },
    )
    assert result.returncode == 0, f"CLI failed:\n{result.stderr}"
    # The resolved root reached ShardSpec: the catalog it located is the one under the named root.
    assert str(catalog_yaml) in result.stderr
    assert str(fake_home) not in result.stderr


def test_batch_driver_derives_catalog_repo_when_env_is_unset():
    """The batch driver passes --catalog-repo on EVERY shard invocation, so its own default overrides
    the one inside emit_subgroup_assignments.py. A $HOME-anchored default here silently undoes the
    portable default for the batch path — which is how all 20 shards actually run.

    test_batch_script_parses_shard_matrix below exports CATALOG_REPO explicitly and so can never
    observe this default, the same blindness that let the default go wrong in the first place.

    The exit code is deliberately NOT asserted: whether the derived sibling checkout exists varies
    by environment, and the claim under test is which ROOT the driver resolves, not that it is
    populated. The banner is logged before any shard runs, so it is present either way.
    """
    fake_home = "/tmp/emit-batch-fake-home-not-the-checkout-parent"
    result = subprocess.run(
        [str(REPO_ROOT / "scripts" / "run_subgroup_emit_batch.sh"), "COADREAD"],
        capture_output=True,
        text=True,
        timeout=60,
        env={
            "PATH": "/opt/conda/bin:/usr/bin:/bin",
            "HOME": fake_home,  # NOT the checkout parent — the runner condition
            "DRY_RUN": "1",
            "PARALLEL": "1",
            # CATALOG_REPO and DATA_CATALOG_ROOT both unset on purpose: exercise the derivation.
        },
    )
    combined = result.stdout + result.stderr
    assert f"catalog-repo:  {DATA_CATALOG_SIBLING}" in combined, (
        f"batch driver resolved an unexpected catalog root:\n{combined[:2000]}"
    )
    # Scoped to the catalog-repo line, NOT the whole output: RUN_DIR is $HOME-anchored on purpose
    # (a scratch/output directory under $HOME is correct and portable — only REPO roots must derive
    # from the checkout), so asserting the fake home is absent everywhere would fail on a correct run.
    catalog_lines = [ln for ln in combined.splitlines() if "catalog-repo:" in ln]
    assert len(catalog_lines) == 1, f"expected exactly one catalog-repo banner, got {catalog_lines}"
    assert fake_home not in catalog_lines[0], f"$HOME leaked into the catalog root: {catalog_lines[0]}"


def test_batch_driver_honours_data_catalog_root():
    """POSITIVE CONTROL for the test above: prove the derivation is actually consulted by showing the
    resolved root MOVES when DATA_CATALOG_ROOT names one. An invariant path is otherwise
    indistinguishable from a driver that never reached this line."""
    result = subprocess.run(
        [str(REPO_ROOT / "scripts" / "run_subgroup_emit_batch.sh"), "COADREAD"],
        capture_output=True,
        text=True,
        timeout=60,
        env={
            "PATH": "/opt/conda/bin:/usr/bin:/bin",
            "HOME": "/tmp",
            "DRY_RUN": "1",
            "PARALLEL": "1",
            "DATA_CATALOG_ROOT": "/tmp/emit-batch-env-named-root",
        },
    )
    combined = result.stdout + result.stderr
    assert "catalog-repo:  /tmp/emit-batch-env-named-root" in combined, (
        f"DATA_CATALOG_ROOT was not honoured:\n{combined[:2000]}"
    )


def test_batch_script_exists_and_executable():
    """The batch bash driver exists + is executable."""
    batch_script = REPO_ROOT / "scripts" / "run_subgroup_emit_batch.sh"
    assert batch_script.exists()
    import os

    assert os.access(batch_script, os.X_OK), "run_subgroup_emit_batch.sh must be executable"


def test_batch_script_parses_shard_matrix():
    """The batch bash driver iterates over subgroup_emit_shards.tsv (dry-run).

    Filtered to COADREAD to keep the test tight — 3 shards vs 20. The
    filter also mirrors the recommended sequencing (vertical-slice first
    per user 2026-07-15 direction).
    """
    result = subprocess.run(
        [str(REPO_ROOT / "scripts" / "run_subgroup_emit_batch.sh"), "COADREAD"],
        capture_output=True,
        text=True,
        timeout=30,
        env={
            "PATH": "/opt/conda/bin:/usr/bin:/bin",
            "HOME": "/tmp",
            "DRY_RUN": "1",
            "PARALLEL": "1",
            "CATALOG_REPO": "/tmp/data-catalog",  # dry-run doesn't read files
        },
    )
    assert result.returncode == 0, f"Batch driver failed:\n{result.stderr}"
    # Batch script prints intro banner + shard-file discovery
    assert "batch RUN_DIR" in result.stderr
    assert "DRY_RUN=1" in result.stderr
    # Filter applied
    assert "filter:" in result.stderr and "COADREAD" in result.stderr
    # All 3 COADREAD shards launched
    assert "3 of 20 shards launched" in result.stderr
    # Report shows all 3 as ok
    combined = result.stdout + result.stderr
    assert "tcga_marker_paper × COADREAD" in combined
    assert "tcga_maf × COADREAD" in combined
    assert "depmap_omics_inferred × COADREAD" in combined
    assert "ok=3" in combined
