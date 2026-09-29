"""Portability + dry-run-validity tests for the two batch shell drivers.

Covers scripts/run_indication_batch.sh and scripts/run_subgroup_emit_batch.sh together, because
the second one's header says it "Mirrors the run_indication_batch.sh pattern (PR #23)" — and a
copied driver copies its defects. Both were measured before this file was written; both carried
the same two:

  1. run_indication_batch.sh anchored its data-catalog root at $HOME. It is the LAST of the four
     spellings of that bug in this repo (AM#631/632/634/635 fixed the others). It matters most
     here, because the driver passes --catalog-repo on EVERY indication and so OVERRIDES the
     portable default inside methods/dge_deseq2/cli.py — the batch path is how all 19 actually run.

  2. BOTH drivers' dry-run branches wrote status `ok` unconditionally, without touching a single
     input. A check that cannot fail is not a check. `DRY_RUN=1 ... && echo safe` reported every
     shard green against a catalog root that did not exist.

Two things this file is deliberately built to avoid:

  * A LOCAL RUN CANNOT FALSIFY A $HOME-ANCHORED DEFAULT. On a dev box $HOME and the checkout
    parent are the same directory, so the wrong answer and the right answer are the same string.
    Every portability test here therefore passes a FAKE HOME, and pairs the negative assertion
    with a POSITIVE CONTROL that makes the resolved root MOVE — an invariant path is otherwise
    indistinguishable from a driver that never reached the line under test.

  * A GUARD THAT REDS ON A CORRECT CHECKOUT IS WORSE THAN NO GUARD. The stub roots below stage
    exactly what each consumer reads, verified against the real sibling checkout first:
    resolve_config() searches indication-configs/{IND}.yaml then manifests/sources/{IND}.yaml
    (19/19 of the driver's indications resolve via the first); catalog_path() reads
    subgroup-catalogs/{IND}/ (20/20 shards resolve).
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INDICATION_DRIVER = REPO_ROOT / "scripts" / "run_indication_batch.sh"
SUBGROUP_DRIVER = REPO_ROOT / "scripts" / "run_subgroup_emit_batch.sh"
DATA_CATALOG_SIBLING = REPO_ROOT.parent / "rnd-computational-biology-oncology-data-catalog"

BASE_PATH = "/opt/conda/bin:/usr/bin:/bin"


@pytest.fixture
def no_aws(tmp_path):
    """A stub `aws` that always exits non-zero, PREPENDED to PATH.

    run_indication_batch.sh calls `aws s3api head-object` as its resume gate BEFORE the dry-run
    branch (unlike run_subgroup_emit_batch.sh, which skips the S3 check under DRY_RUN). With real
    credentials on this box that gate can legitimately answer "cached", which writes status
    `skipped-cached` and RETURNS EARLY — so the dry-run input check under test would never run and
    the test would pass without evaluating anything. Forcing the gate to say "not cached" is what
    makes these assertions reachable. It also keeps the suite hermetic: no network, no creds.

    PREPEND, never replace: a replaced PATH drops the tools the driver needs and manufactures
    failures that read like defects.
    """
    stub_dir = tmp_path / "stub-bin"
    stub_dir.mkdir()
    aws = stub_dir / "aws"
    aws.write_text("#!/usr/bin/env bash\nexit 1\n")
    aws.chmod(0o755)
    return f"{stub_dir}:{BASE_PATH}"


def _stub_indication_catalog(root: Path, indications) -> Path:
    """Minimal valid catalog root for run_indication_batch.sh.

    Mirrors resolve_config()'s FIRST candidate only (methods/dge_deseq2/cli.py). Staging the
    second as well would not test anything the driver decides.
    """
    configs = root / "indication-configs"
    configs.mkdir(parents=True, exist_ok=True)
    for ind in indications:
        (configs / f"{ind}.yaml").write_text("# stub\n")
    return root


def _stub_subgroup_catalog(root: Path, indications) -> Path:
    """Minimal valid catalog root for run_subgroup_emit_batch.sh.

    Directories only, no per-quarter YAML: catalog_path() IGNORES the shard TSV's release_pin
    column and derives the quarter itself (COADREAD -> 2026-Q2, else 2026-Q3). Staging the exact
    file would copy that rule into a third place and would start failing the day it changed.
    """
    for ind in indications:
        (root / "subgroup-catalogs" / ind).mkdir(parents=True, exist_ok=True)
    return root


def _run(driver: Path, *args, env_extra=None, path=BASE_PATH, home="/tmp", timeout=90):
    env = {"PATH": path, "HOME": home, "DRY_RUN": "1", "PARALLEL": "1"}
    env.update(env_extra or {})
    result = subprocess.run([str(driver), *args], capture_output=True, text=True, timeout=timeout, env=env)
    return result, result.stdout + result.stderr


# ---------- (1) the last $HOME-anchored root: run_indication_batch.sh ----------


def test_indication_driver_derives_catalog_repo_when_env_is_unset(no_aws, tmp_path):
    """With CATALOG_REPO and DATA_CATALOG_ROOT both unset, the resolved root is the SIBLING
    CHECKOUT, not $HOME/... — asserted under a fake HOME, which is the only condition that can
    tell the two apart on a dev box.

    The exit code is deliberately NOT asserted: whether the sibling checkout is populated varies
    by environment, and the claim under test is which ROOT is resolved. The banner is logged
    before the preflight and before any indication runs, so it is on the record either way.
    """
    fake_home = str(tmp_path / "not-the-checkout-parent")
    _, combined = _run(
        INDICATION_DRIVER,
        "COAD",
        path=no_aws,
        home=fake_home,
        # CATALOG_REPO / DATA_CATALOG_ROOT unset on purpose: exercise the derivation.
    )
    catalog_lines = [ln for ln in combined.splitlines() if "catalog-repo:" in ln]
    assert len(catalog_lines) == 1, f"expected exactly one catalog-repo banner, got {catalog_lines}"
    assert str(DATA_CATALOG_SIBLING) in catalog_lines[0], (
        f"driver resolved an unexpected catalog root:\n{combined[:2000]}"
    )
    # Scoped to the catalog-repo line, NOT the whole output: RUN_DIR is $HOME-anchored on purpose.
    # A scratch/output directory under $HOME is correct and portable — only REPO roots must derive
    # from the checkout — so asserting the fake home is absent everywhere would fail a correct run.
    assert fake_home not in catalog_lines[0], f"$HOME leaked into the catalog root: {catalog_lines[0]}"


def test_indication_driver_honours_data_catalog_root(no_aws, tmp_path):
    """POSITIVE CONTROL for the test above: the resolved root must MOVE when DATA_CATALOG_ROOT
    names one. Without this, a driver that hardcoded the sibling path — or never evaluated the
    line at all — would pass the test above just as happily."""
    named = str(tmp_path / "env-named-root")
    _, combined = _run(INDICATION_DRIVER, "COAD", path=no_aws, env_extra={"DATA_CATALOG_ROOT": named})
    assert f"catalog-repo: {named}" in combined, f"DATA_CATALOG_ROOT not honoured:\n{combined[:2000]}"


def test_indication_driver_catalog_repo_beats_data_catalog_root(no_aws, tmp_path):
    """Precedence matches the Python side and the sibling driver: explicit CATALOG_REPO wins."""
    _, combined = _run(
        INDICATION_DRIVER,
        "COAD",
        path=no_aws,
        env_extra={
            "CATALOG_REPO": str(tmp_path / "explicit"),
            "DATA_CATALOG_ROOT": str(tmp_path / "fallback"),
        },
    )
    assert f"catalog-repo: {tmp_path / 'explicit'}" in combined
    assert str(tmp_path / "fallback") not in combined


def test_indication_driver_is_executable():
    assert INDICATION_DRIVER.exists()
    assert os.access(INDICATION_DRIVER, os.X_OK), "run_indication_batch.sh must be executable"


# ---------- (2) the dry run must be able to FAIL ----------


@pytest.mark.parametrize("driver", [INDICATION_DRIVER, SUBGROUP_DRIVER], ids=["indication", "subgroup"])
def test_dry_run_fails_on_a_nonexistent_catalog_root(driver, no_aws, tmp_path):
    """THE HEADLINE REGRESSION TEST. Before the fix both drivers reported every unit `ok` and
    exited 0 against a catalog root that does not exist — the state the old
    test_batch_script_parses_shard_matrix asserted as correct behaviour.

    Exit 2, not 1: both drivers document 2 as "one or more units failed", and a root that cannot
    serve anything is that outcome rather than a usage error.
    """
    missing = tmp_path / "definitely-not-a-catalog-root"
    assert not missing.exists()
    result, combined = _run(driver, "COADREAD", path=no_aws, env_extra={"CATALOG_REPO": str(missing)})
    assert result.returncode == 2, (
        f"a missing catalog root must fail the batch, got exit {result.returncode}:\n{combined[:2000]}"
    )
    assert "PREFLIGHT-FAIL" in combined
    assert str(missing) in combined, "the failure must NAME the root it rejected"
    # The banner precedes the preflight on purpose: the resolved root stays auditable even when it
    # is what got rejected. A guard that fails without disclosing the value it tested is a guess.
    assert "catalog-repo:" in combined


@pytest.mark.parametrize("driver", [INDICATION_DRIVER, SUBGROUP_DRIVER], ids=["indication", "subgroup"])
def test_dry_run_fails_when_root_exists_but_is_not_a_catalog_checkout(driver, no_aws, tmp_path):
    """An existing-but-wrong directory is the likelier real-world mistake (a typo'd sibling, a
    partial clone, a bare $HOME), and `-d` alone cannot see it."""
    empty = tmp_path / "exists-but-empty"
    empty.mkdir()
    result, combined = _run(driver, "COADREAD", path=no_aws, env_extra={"CATALOG_REPO": str(empty)})
    assert result.returncode == 2, f"got exit {result.returncode}:\n{combined[:2000]}"
    assert "PREFLIGHT-FAIL" in combined
    assert "not a data-catalog checkout" in combined


def test_indication_dry_run_passes_on_a_valid_stub_root(no_aws, tmp_path):
    """THE OTHER HALF: the guard must NOT red on a correct checkout. Staged from what
    resolve_config() actually searches, so `ok` is now a claim rather than a formality."""
    catalog = _stub_indication_catalog(tmp_path / "data-catalog", ["COAD", "READ"])
    result, combined = _run(INDICATION_DRIVER, "COAD", "READ", path=no_aws, env_extra={"CATALOG_REPO": str(catalog)})
    assert result.returncode == 0, f"valid stub root must pass:\n{combined[:3000]}"
    assert "ok=2" in combined
    assert "DRY-FAIL" not in combined
    assert "PREFLIGHT-FAIL" not in combined


def test_subgroup_dry_run_passes_on_a_valid_stub_root(tmp_path):
    """Same positive control for the shard driver (no aws stub needed: it skips the S3 gate
    under DRY_RUN)."""
    catalog = _stub_subgroup_catalog(tmp_path / "data-catalog", ["COADREAD"])
    result, combined = _run(SUBGROUP_DRIVER, "COADREAD", env_extra={"CATALOG_REPO": str(catalog)})
    assert result.returncode == 0, f"valid stub root must pass:\n{combined[:3000]}"
    assert "ok=3" in combined
    assert "DRY-FAIL" not in combined


# ---------- (3) per-unit granularity: a partial root fails only the units it cannot serve ----------


def test_indication_dry_run_fails_only_the_unresolvable_indication(no_aws, tmp_path):
    """A whole-batch verdict would be nearly as useless as no verdict. The point of checking
    per-indication is that the report NAMES which one cannot run."""
    catalog = _stub_indication_catalog(tmp_path / "data-catalog", ["COAD"])  # LGG deliberately absent
    result, combined = _run(INDICATION_DRIVER, "COAD", "LGG", path=no_aws, env_extra={"CATALOG_REPO": str(catalog)})
    assert result.returncode == 2, f"got exit {result.returncode}:\n{combined[:3000]}"
    assert "DRY-FAIL LGG" in combined
    assert "DRY-FAIL COAD" not in combined
    assert "ok=1" in combined and "failed=1" in combined
    # Both resolution candidates must appear: a message naming only one would send the reader to
    # create a file in a location the code would not have consulted second.
    assert "indication-configs/LGG.yaml" in combined
    assert "manifests/sources/LGG.yaml" in combined


def test_subgroup_dry_run_fails_only_the_unresolvable_shards(tmp_path):
    """COADREAD staged, NSCLC not: 3 shards resolve, NSCLC's 3 do not."""
    catalog = _stub_subgroup_catalog(tmp_path / "data-catalog", ["COADREAD"])
    result, combined = _run(SUBGROUP_DRIVER, "COADREAD", "NSCLC", env_extra={"CATALOG_REPO": str(catalog)})
    assert result.returncode == 2, f"got exit {result.returncode}:\n{combined[:3000]}"
    assert "ok=3" in combined and "failed=3" in combined
    assert "subgroup-catalogs/NSCLC/" in combined
    assert "DRY-FAIL" in combined and "COADREAD" not in combined.split("DRY-FAIL")[1].splitlines()[0]


def test_subgroup_dry_run_fails_on_a_missing_classifier_config(tmp_path):
    """The classifier-config path is assembled BY THE DRIVER ($CLASSIFIER_CONFIG_DIR/$file), so a
    wrong one is this driver's defect, not the method's. SCLC is the only shard that uses one."""
    catalog = _stub_subgroup_catalog(tmp_path / "data-catalog", ["SCLC"])
    result, combined = _run(
        SUBGROUP_DRIVER,
        "SCLC",
        env_extra={
            "CATALOG_REPO": str(catalog),
            "CLASSIFIER_CONFIG_DIR": str(tmp_path / "no-configs-here"),
        },
    )
    assert result.returncode == 2, f"got exit {result.returncode}:\n{combined[:3000]}"
    assert "classifier config missing" in combined
    assert "sclc-napy-2026-q3.yaml" in combined


def test_subgroup_dry_run_passes_with_the_real_classifier_config_dir(tmp_path):
    """POSITIVE CONTROL for the test above, and the check that the guard stays green on a correct
    checkout: the config the TSV names is present in the repo's example-configs/ today."""
    catalog = _stub_subgroup_catalog(tmp_path / "data-catalog", ["SCLC"])
    result, combined = _run(SUBGROUP_DRIVER, "SCLC", env_extra={"CATALOG_REPO": str(catalog)})
    assert result.returncode == 0, f"real classifier-config dir must pass:\n{combined[:3000]}"
    assert "classifier config missing" not in combined


# ---------- (4) the report must survive to print, or the exit code is unreachable ----------


def test_indication_report_is_complete_and_not_truncated(no_aws, tmp_path):
    """REGRESSION TEST for a pre-existing `set -e` defect found while probing the fix.

    run_indication_batch.sh counted with `((n_ok++))`. Under `set -euo pipefail` that is not
    equivalent to `n_ok=$((n_ok+1))`: `((expr))` returns exit status 1 when the expression
    evaluates to 0, and POST-increment evaluates to the OLD value — so the first `ok` row (n_ok
    still 0) returned 1 and errexit killed the script mid-report. Measured on the pre-fix driver:
    the report header and exactly ONE row printed, then exit 1.

    Two reasons that is not cosmetic. First, the truncated report reads like a finished one if you
    look at the tail. Second, it made the documented `exit 2` UNREACHABLE — the script died before
    the `if (( n_fail + n_upfail > 0 ))` test — so a batch with failures could not report them,
    and every dry-run guard added above would have been silently un-actionable.

    So this asserts the SUMMARY LINE, not just absence of a failure: a log that stops early is
    consistent with both "clean" and "died before it could say otherwise".
    """
    inds = ["COAD", "READ", "COADREAD"]
    catalog = _stub_indication_catalog(tmp_path / "data-catalog", inds)
    result, combined = _run(INDICATION_DRIVER, *inds, path=no_aws, env_extra={"CATALOG_REPO": str(catalog)})
    assert result.returncode == 0, f"got exit {result.returncode}:\n{combined[:3000]}"
    rows = [ln for ln in combined.splitlines() if ln.startswith("  ") and ln.split()[1:2] == ["ok"]]
    assert len(rows) == len(inds), f"report truncated: {len(rows)} of {len(inds)} rows:\n{combined[:3000]}"
    assert "ok=3  skipped-cached=0  upload-failed=0  failed=0  total=3" in combined, (
        f"summary line absent — the report did not run to completion:\n{combined[:3000]}"
    )
