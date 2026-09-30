"""run_cms.R determinism gate — the CMS NTP permutation FDR must not move between identical runs.

WHY THIS EXISTS: run_cms.R called CMScaller() with no `seed`, under a header comment asserting
"NTP is deterministic given a fixed matrix + templates; no RNG seeding needed". The ASSIGNMENT
half of that is true — correlate each sample to each template, take the nearest. The p-value/FDR
half is not: CMScaller derives both from a PERMUTATION null (default nPerm = 1000), so an unseeded
run re-rolls them from a clock-seeded RNG. MEASURED on byte-identical DepMap input: 2 of 131 Bowel
models changed CMS class across three runs and the CMS3 count moved 20/19/20 — enough to make any
expected_n declared off a single run a flaky floor rather than a measurement.

TWO LEGS, on purpose:

1. `test_run_cms_seeds_the_permutation_null` — SOURCE-LEVEL, always runs. This is the leg that is
   load-bearing on CI: CMScaller is NOT in pixi.lock (setup.R installs it out-of-band from GitHub),
   so leg 2 skips on every runner. Without leg 1, this file would be green-by-skip in exactly the
   place a regression would land.

2. `test_cms_ntp_is_stable_across_runs` — BEHAVIORAL, opportunistic (a local compute session with
   CMScaller installed). Runs the real script twice on one fixture and compares the WHOLE frame.

WHY THE WHOLE FRAME, AND WHY THE FIXTURE IS TUNED THIS WAY — both traps here were measured, and
both make the obvious version of this test pass whether or not the bug is present:

  - Comparing only the `CMS` column is VACUOUS at fixture scale. Two unseeded replicates differ in
    0/40 class labels but 19/40 p_values and 39/40 FDRs. Class labels are the LEAST sensitive
    column, because a re-rolled null has to push a sample all the way across the FDR floor to
    relabel it. So this test compares p_value and FDR too.

  - A fixture whose samples are PERFECT class exemplars is ALSO vacuous. Lift each sample's
    template markers by a flat +4.0 and every p_value saturates at the permutation floor
    (1/nPerm = 0.001): no permutation ever beats the observed correlation, so the RNG has nothing
    left to move and the unseeded control STOPS FIRING. Making the fixture look more like real
    data made it unable to detect the bug.

So the fixture plants a GRADIENT of marker lift (0 -> MAX_MARKER_LIFT), which straddles the FDR
floor, and `_assert_fixture_can_discriminate` asserts that non-degeneracy BEFORE the equality
assertion. A fixture that later drifts into either degenerate regime then fails loudly instead of
passing for free.
"""

from __future__ import annotations

import io
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")

METHODS_REPO = Path(__file__).resolve().parents[3]
RUN_CMS_R = Path(__file__).resolve().parents[1] / "steps" / "run_cms.R"

# The claim this gate retired. Asserted ABSENT so the comment cannot rot back to the false version
# while the code stays right — the wrong comment is why the defect survived unexamined.
RETRACTED_CLAIM = "no RNG seeding needed"

N_SAMPLES = 40
N_BACKGROUND_GENES = 200
# MEASURED CEILING, not a taste call. At a flat lift this high every p_value pins to the
# permutation floor and the fixture goes blind (see module docstring). At <= 1.0 across a gradient,
# 21/40 samples classify and 22 distinct p_values appear — both branches live, null still mobile.
MAX_MARKER_LIFT = 1.0

# run_cms.R's own library() calls. All three must resolve or the script dies for an unrelated reason
# and the skip reason would misreport which dependency is missing.
R_PACKAGES = ("optparse", "arrow", "CMScaller")


def _resolve_rscript() -> str | None:
    """Rscript path, preferring the RUNNING INTERPRETER's env over PATH.

    Same resolution order (and same reason) as
    methods/dge_deseq2/tests/test_byte_identity_vs_legacy_coadread.py::_resolve_rscript: a /tmp
    worktree has no .pixi/ of its own, so anchoring only to METHODS_REPO resolves to nothing in
    exactly the case that matters, and a PATH-only lookup silently disarms the gate whenever
    pytest is driven by absolute interpreter path.
    """
    for candidate in (
        Path(sys.executable).parent / "Rscript",
        METHODS_REPO / ".pixi" / "envs" / "default" / "bin" / "Rscript",
    ):
        if candidate.exists():
            return str(candidate)
    return shutil.which("Rscript")


RSCRIPT = _resolve_rscript()


def _missing_r_packages(rscript: str | None) -> list[str]:
    """Names of R_PACKAGES that are not installed (all of them if R itself is unusable)."""
    if rscript is None:
        return list(R_PACKAGES)
    expr = "; ".join(f'if (!requireNamespace("{p}", quietly = TRUE)) cat("{p}\\n")' for p in R_PACKAGES)
    proc = subprocess.run([rscript, "-e", expr], capture_output=True, text=True)
    if proc.returncode != 0:
        return list(R_PACKAGES)
    return proc.stdout.split()


MISSING_R_PACKAGES = _missing_r_packages(RSCRIPT)


# --------------------------------------------------------------------------------------------
# Leg 1 — source-level. Always runs; the only leg CI can reach.
# --------------------------------------------------------------------------------------------
def test_run_cms_seeds_the_permutation_null():
    """The single CMScaller() call site must pass a seed bound to an integer literal.

    Asserting on the CALL rather than on file-wide presence of the token: a `seed` defined but
    never threaded through is the whole original defect in a new costume.
    """
    src = RUN_CMS_R.read_text()
    calls = [ln for ln in src.splitlines() if "CMScaller::CMScaller(" in ln and not ln.lstrip().startswith("#")]
    assert len(calls) == 1, f"expected exactly one CMScaller() call site in run_cms.R, found {len(calls)}: {calls}"
    (call,) = calls

    match = re.search(r"\bseed\s*=\s*([A-Za-z_.][\w.]*|\d+L?)", call)
    assert match, (
        "run_cms.R calls CMScaller() without `seed =`; the permutation FDR will be clock-seeded "
        f"and will move between identical runs. Call site: {call.strip()}"
    )

    # A seed is only a pin if it is a constant. A named argument is fine, but it has to be bound to
    # an integer literal in this same file — `seed = Sys.time()` would satisfy a token check.
    seed_arg = match.group(1)
    if not re.fullmatch(r"\d+L?", seed_arg):
        binding = re.search(rf"^\s*{re.escape(seed_arg)}\s*<-\s*\d+L?\s*(#.*)?$", src, re.MULTILINE)
        assert binding, (
            f"`seed = {seed_arg}` is not bound to an integer literal in run_cms.R, so the seed is "
            "not a reproducibility pin"
        )


def test_determinism_comment_states_the_permutation_null():
    """Documentation anti-rot: the header must name the permutation null and not re-assert the myth."""
    src = RUN_CMS_R.read_text()
    assert RETRACTED_CLAIM not in src, (
        f"run_cms.R again claims {RETRACTED_CLAIM!r}. The NTP assignment is deterministic but the "
        "p-value/FDR come from a permutation null; this claim is what kept the missing seed invisible."
    )
    assert "permutation" in src.lower(), (
        "run_cms.R no longer documents that its FDR comes from a permutation null, so the next "
        "reader has no reason to keep the seed"
    )


# --------------------------------------------------------------------------------------------
# Leg 2 — behavioral. Needs R + CMScaller, which CI does not have (setup.R installs it from GitHub).
# --------------------------------------------------------------------------------------------
def _cms_templates(rscript: str) -> pd.DataFrame:
    """CMScaller's CMS marker table (probe = Entrez id, class = CMS label).

    Read from the INSTALLED package rather than vendored into the repo: setup.R resolves
    CMSCALLER_REF (default `master`), so a vendored copy could silently describe a different
    template set than the one the run actually scores against.
    """
    proc = subprocess.run(
        [
            rscript,
            "-e",
            "suppressMessages(library(CMScaller)); "
            'write.csv(CMScaller::templates.CMS[, c("probe", "class")], stdout(), row.names = FALSE)',
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    templates = pd.read_csv(io.StringIO(proc.stdout), dtype={"probe": str})
    assert not templates.empty, "CMScaller::templates.CMS came back empty; cannot build a fixture"
    return templates


def _write_synthetic_emat(templates: pd.DataFrame, path: Path) -> None:
    """Write a genes x samples emat parquet in the shape run_cms.R reads (`entrez_id` + sample cols).

    Synthetic on purpose — no DepMap cache, so this leg is hermetic given R. Values are shaped like
    log2(count+1): a per-gene mean plus per-sample noise, then each sample's own CMS markers lifted
    by a per-sample amount drawn from a 0 -> MAX_MARKER_LIFT gradient so the cohort spans confident
    exemplars and samples sitting on the FDR floor.
    """
    rng = np.random.default_rng(0)
    probes = sorted(templates["probe"].unique())
    genes = probes + [str(900000 + i) for i in range(N_BACKGROUND_GENES)]
    row_of = {gene: i for i, gene in enumerate(genes)}

    matrix = rng.normal(6.0, 2.0, size=(len(genes), 1)) + rng.normal(0.0, 1.0, size=(len(genes), N_SAMPLES))
    classes = sorted(templates["class"].unique())
    lifts = np.linspace(0.0, MAX_MARKER_LIFT, N_SAMPLES)
    for column in range(N_SAMPLES):
        marker_rows = [row_of[p] for p in templates.loc[templates["class"] == classes[column % len(classes)], "probe"]]
        matrix[marker_rows, column] += lifts[column]

    frame = pd.DataFrame(np.clip(matrix, 0.0, None), columns=[f"S{i:03d}" for i in range(N_SAMPLES)])
    frame.insert(0, "entrez_id", genes)
    frame.to_parquet(path, index=False)


def _run_cms(rscript: str, emat: Path, out: Path) -> pd.DataFrame:
    proc = subprocess.run(
        [rscript, str(RUN_CMS_R), "--emat", str(emat), "--out", str(out), "--rnaseq", "TRUE", "--fdr", "0.05"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"run_cms.R exited {proc.returncode}\nSTDERR:\n{proc.stderr}"
    return pd.read_parquet(out).sort_values("sample_id").reset_index(drop=True)


def _assert_fixture_can_discriminate(frame: pd.DataFrame) -> None:
    """Fail loudly if the fixture landed in a regime where an unseeded run would pass anyway."""
    classified = int(frame["CMS"].notna().sum())
    assert 0 < classified < len(frame), (
        f"degenerate fixture: {classified}/{len(frame)} samples classified, so one of the two "
        "branches (classified / unclassifiable-below-FDR-floor) is never exercised"
    )
    assert frame["p_value"].nunique() > 1, (
        "degenerate fixture: every sample shares one p_value, so it is pinned at the permutation "
        f"floor where a re-rolled null cannot move it (p={sorted(frame['p_value'].unique())[:3]}). "
        "Lower MAX_MARKER_LIFT."
    )


@pytest.mark.skipif(
    bool(MISSING_R_PACKAGES),
    reason=f"R deps unavailable: {', '.join(MISSING_R_PACKAGES) or 'none'} "
    "(CMScaller is not in pixi.lock — setup.R installs it from GitHub, so CI always skips this leg)",
)
def test_cms_ntp_is_stable_across_runs(tmp_path):
    """Two runs of run_cms.R on one emat must agree on CMS, p_value AND FDR."""
    emat = tmp_path / "emat.parquet"
    _write_synthetic_emat(_cms_templates(RSCRIPT), emat)

    first = _run_cms(RSCRIPT, emat, tmp_path / "cms_first.parquet")
    second = _run_cms(RSCRIPT, emat, tmp_path / "cms_second.parquet")

    # Before comparing: prove this fixture COULD have caught the bug.
    _assert_fixture_can_discriminate(first)

    # The whole frame. p_value/FDR are the sensitive columns; CMS alone differs in 0/40 unseeded.
    pd.testing.assert_frame_equal(first, second)
