"""The frozen embedding is REPRODUCIBLE from the shipped artifact, and the solver that reproduces it is
pinned by name.

Why this file exists as a separate guard from `test_atlas_stability.py`: that one pins the frozen BYTES, so
it catches a value that moved. It cannot catch a value that would move on the next re-freeze for a reason
unrelated to the substrate — and `build_atlas` had exactly one of those. The PCA was fit with sklearn's
default `svd_solver="auto"`, whose choice depends on CORPUS SIZE: the exact `full` solver while
`max(n_samples, n_features) <= 500`, the stochastic `randomized` approximation above it. At n=297 that
resolved to `full`; the authorised panel expansion adds 207 targets and lands n at 504.

So the very next re-freeze would have swapped the algorithm underneath the embedding, and the diff — moved
loadings plus every moved coord — would have been indistinguishable from the effect of the new targets. The
fix is a by-name pin (`build_atlas.PCA_SVD_SOLVER`); this file is what makes the pin more than a comment:

  1. the pin exists and is not `auto` (the size-dependent value);
  2. the pinned solver actually REPRODUCES the frozen loadings from the shipped `X`;
  3. an unpinned solver measurably does NOT (anti-vacuity — without this, 2 passes for free if the two
     solvers happened to agree, and the pin would be protecting nothing);
  4. the pin is honoured at BOTH the current and the post-expansion corpus size, which is the property
     `auto` lacked and the only reason the pin was needed.

`sklearn` is imported unconditionally: it is declared in `pixi.toml` as of 2026-09-13, and the whole point
of declaring it is that the rebuild path runs here. A conditional skip would report success in exactly the
environment this guard exists to cover — see the repo's skip-is-not-pass rule.
"""

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from sklearn.decomposition import PCA

SKILLS_DIR = Path(__file__).resolve().parents[2]
if str(SKILLS_DIR) not in sys.path:
    sys.path.insert(0, str(SKILLS_DIR))

ATLAS = Path(__file__).resolve().parents[1] / "atlas" / "atlas.json"
BUILD = Path(__file__).resolve().parents[1] / "scripts" / "build_atlas.py"

# The frozen floats are rounded to 6 dp, so a perfect refit still differs by ~2e-05. Measured 2026-09-13:
# the pinned solver lands at 2.24e-05 and `randomized` at 1.23e-02, so this tolerance sits ~550x below the
# difference it has to reject and ~4x above the difference it has to accept.
ROUNDING_TOLERANCE = 1e-4


def _load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def doc():
    return json.loads(ATLAS.read_text())


@pytest.fixture(scope="module")
def build_mod():
    return _load(BUILD)


@pytest.fixture(scope="module")
def Z(doc):
    """The EXACT matrix the PCA was fit on: z-score vs the frozen mu/sd, missing -> mean -> z=0."""
    Xn = np.array([[np.nan if v is None else v for v in row] for row in doc["X"]], dtype=float)
    mu = np.array(doc["mu"], dtype=float)
    sd = np.array(doc["sd"], dtype=float)
    return (np.where(np.isnan(Xn), mu, Xn) - mu) / sd


def _max_loading_deviation(components, frozen):
    """Compare on |loading|: a PCA component is only defined up to sign, and a sign flip is not a change in
    the embedding (the coords flip with it). A magnitude change is."""
    return float(np.abs(np.abs(np.asarray(frozen, dtype=float)) - np.abs(components)).max())


def test_the_solver_is_pinned_by_name_and_is_not_the_size_dependent_default(build_mod):
    solver = getattr(build_mod, "PCA_SVD_SOLVER", None)
    assert solver, "build_atlas no longer declares PCA_SVD_SOLVER — the solver is implicit again"
    assert solver != "auto", (
        "PCA_SVD_SOLVER is back to sklearn's `auto`, which selects `full` or `randomized` depending on "
        "corpus size — the exact condition this pin exists to remove"
    )


def test_the_build_actually_passes_the_pin_to_the_pca(build_mod):
    """A constant nothing reads is a comment. Asserted against the source because the call sits inside
    `build()`, which needs the ~200-run corpus and so cannot be invoked here."""
    src = BUILD.read_text()
    assert "svd_solver=PCA_SVD_SOLVER" in src, (
        "the PCA call does not pass PCA_SVD_SOLVER — the pin is declared but the build still uses sklearn's "
        "default solver"
    )


def test_the_pinned_solver_reproduces_the_frozen_loadings(doc, build_mod, Z):
    """The reproducibility claim itself, checkable in CI without the run corpus because the atlas ships `X`.
    This is the half of `--verify-rebuild` that needs no corpus: the substrate is frozen in the file, so if
    the loadings do not come back, the embedding was not produced by the transform the file describes."""
    frozen = doc["embedding"]["components"]
    m = len(frozen)
    fitted = PCA(n_components=m, random_state=0, svd_solver=build_mod.PCA_SVD_SOLVER).fit(Z)
    dev = _max_loading_deviation(fitted.components_, frozen)
    assert dev < ROUNDING_TOLERANCE, (
        f"the pinned solver ({build_mod.PCA_SVD_SOLVER}) does not reproduce the frozen loadings: max "
        f"|deviation| {dev:.3e} >= {ROUNDING_TOLERANCE:.0e}. Either the atlas was frozen under a different "
        f"solver / numeric stack, or mu/sd/X no longer describe the matrix the PCA was fit on."
    )


def test_an_unpinned_solver_would_measurably_move_the_embedding(doc, Z):
    """Anti-vacuity for the test above: if every solver agreed to within the tolerance, the pin would be
    protecting nothing and the test above would pass for free. `randomized` is the value `auto` selects once
    the corpus crosses 500 rows, so this measures the exact swap the pin prevents."""
    frozen = doc["embedding"]["components"]
    m = len(frozen)
    rand = PCA(n_components=m, random_state=0, svd_solver="randomized").fit(Z).components_
    dev = _max_loading_deviation(rand, frozen)
    assert dev > 10 * ROUNDING_TOLERANCE, (
        f"`randomized` now reproduces the frozen loadings to {dev:.3e} — the two solvers agree, so the pin "
        "no longer protects anything measurable and this guard should be re-read rather than kept green"
    )


def test_the_pin_holds_at_the_post_expansion_corpus_size_where_auto_flips(build_mod, Z):
    """The property `auto` lacked, asserted at the size that exposes it. Fitting the real matrix twice would
    not show this — the flip needs n>500 — so the corpus is padded with resampled rows purely to reach the
    boundary. Only the SOLVER SELECTION is under test here, not any embedding value.

    Guards against a future sklearn changing its heuristic as well: `auto`'s branch set last changed in 1.5
    (`covariance_eigh`), and `pixi.toml` declares only `>=1.5`, so the exact heuristic is not pinned — the
    solver is.
    """
    rng = np.random.default_rng(0)
    padded = np.vstack([Z, Z[rng.integers(0, Z.shape[0], 504 - Z.shape[0])]])
    assert padded.shape[0] == 504 > 500, "the padded corpus must actually cross sklearn's 500-row boundary"

    auto_small = PCA(n_components=16, random_state=0).fit(Z)
    auto_large = PCA(n_components=16, random_state=0).fit(padded)
    assert auto_small._fit_svd_solver != auto_large._fit_svd_solver, (
        "sklearn's `auto` no longer changes solver across the 500-row boundary. The hazard may be gone, but "
        "verify that before relaxing the pin — this assertion is what documents that the hazard was real"
    )

    pinned_small = PCA(n_components=16, random_state=0, svd_solver=build_mod.PCA_SVD_SOLVER).fit(Z)
    pinned_large = PCA(n_components=16, random_state=0, svd_solver=build_mod.PCA_SVD_SOLVER).fit(padded)
    assert pinned_small._fit_svd_solver == pinned_large._fit_svd_solver == build_mod.PCA_SVD_SOLVER, (
        f"the pin is not honoured across corpus sizes: {pinned_small._fit_svd_solver} vs {pinned_large._fit_svd_solver}"
    )


def test_the_shipped_atlas_predates_the_solver_stamp(doc):
    """`build_atlas` now stamps `meta.embedding_pca_svd_solver`, but the shipped artifact was frozen before
    that existed. Pinning the artifact's CURRENT state by name — rather than asserting the key is present —
    keeps this from becoming a gate that demands a stamp no build made, which is the same trap
    `test_the_shipped_artifact_is_specifically_the_post_freeze_producer` documents.

    On the next re-freeze this key appears and this test flips: assert it equals `PCA_SVD_SOLVER` instead,
    in the same commit, and expect `--verify-rebuild` to report `meta.embedding_pca_svd_solver` as one
    EXPECTED new key.
    """
    stamped = doc["meta"].get("embedding_pca_svd_solver")
    assert stamped is None or stamped == "full", (
        f"the shipped atlas stamps embedding_pca_svd_solver={stamped!r}. If a re-freeze added it, update "
        f"this test to assert it equals build_atlas.PCA_SVD_SOLVER."
    )
