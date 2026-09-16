"""The frozen `feature_corr` block — its alignment, its basis, and the provenance claim it makes.

`feature_corr` is per-pair redundancy over the metered numeric columns, so a label-free consumer can
discount a reference column that duplicates another instead of hand-tuning a per-axis weight.

Three properties are worth guarding, and each already has a near-miss behind it in this repo:

  1. **Alignment is declared, not assumed.** The block is aligned to `feature_corr_order`, a strict SUBSET
     of `feature_order`. Indexing it with `feature_order` (the way `reference_mask_fraction` is indexed)
     reads a different column pair and returns a plausible float, so the test asserts the two orders are
     genuinely different rather than merely documenting it.
  2. **A correlation needs its basis.** `feature_corr_n` carries the co-measured row count behind each
     cell, and an unknown cell is `None` rather than 0.0 — "we could not look" is not "independent".
  3. **The provenance claim is CHECKABLE.** The shipped block was derived post-freeze from the frozen `X`
     rather than produced by the original build, and it says so in `meta.feature_corr_provenance`. That
     claim is verified here by RECOMPUTING the block from the shipped `X` — the whole reason amending is
     legitimate is that `feature_corr` is a pure function of a basis that did not move.
"""

import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

SKILLS_DIR = Path(__file__).resolve().parents[2]
if str(SKILLS_DIR) not in sys.path:
    sys.path.insert(0, str(SKILLS_DIR))

ATLAS = Path(__file__).resolve().parents[1] / "atlas" / "atlas.json"
BUILD = Path(__file__).resolve().parents[1] / "scripts" / "build_atlas.py"
AMEND = Path(__file__).resolve().parents[1] / "scripts" / "amend_atlas_feature_corr.py"


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


# ── the positive control, FIRST ───────────────────────────────────────────────────────────────────


def test_the_shipped_atlas_carries_a_populated_feature_corr_block(doc):
    """Anti-vacuity before anything else: every test below is trivially true on an absent block."""
    order = doc.get("feature_corr_order")
    corr = doc.get("feature_corr")
    counts = doc.get("feature_corr_n")
    assert order and corr and counts, "no feature_corr block in the shipped atlas"
    populated = sum(1 for row in corr for v in row if v is not None)
    assert populated > len(order), f"only {populated} populated cells — the block is effectively empty"


# ── 1. alignment is DECLARED ──────────────────────────────────────────────────────────────────────


def test_feature_corr_order_is_a_strict_subset_of_feature_order(doc):
    fo, order = doc["feature_order"], doc["feature_corr_order"]
    assert set(order) < set(fo), "feature_corr_order must be a strict subset of feature_order"
    assert order == [k for k in fo if k in set(order)], "feature_corr_order must preserve feature_order's order"


def test_indexing_the_block_with_feature_order_would_read_the_wrong_column(doc):
    """The trap this block's separate order exists to prevent. `reference_mask_fraction` IS aligned to
    feature_order, so a reader that has internalised that habit will silently mis-index this one — and get
    a perfectly plausible float back. Asserting the misalignment is real keeps that from becoming
    hypothetical: if a future freeze ever made the two orders coincide, this guard should be re-read
    rather than quietly kept passing."""
    fo, order = doc["feature_order"], doc["feature_corr_order"]
    assert len(order) < len(fo)
    first_divergence = next(i for i, k in enumerate(fo) if i >= len(order) or order[i] != k)
    assert first_divergence < len(order), (
        "feature_corr_order is a PREFIX of feature_order, so mis-indexing would be harmless for the whole "
        "block — re-read this guard and the reader it protects"
    )


def test_the_matrix_is_square_and_symmetric(doc):
    order, corr, counts = doc["feature_corr_order"], doc["feature_corr"], doc["feature_corr_n"]
    d = len(order)
    assert len(corr) == d and all(len(r) == d for r in corr)
    assert len(counts) == d and all(len(r) == d for r in counts)
    for i in range(d):
        for j in range(d):
            assert corr[i][j] == corr[j][i], f"asymmetric at {order[i]} / {order[j]}"
            assert counts[i][j] == counts[j][i]


def test_the_diagonal_is_one_and_the_range_is_valid(doc):
    order, corr = doc["feature_corr_order"], doc["feature_corr"]
    for i, k in enumerate(order):
        assert corr[i][i] == 1.0, f"{k} is not perfectly correlated with itself"
    for row in corr:
        for v in row:
            assert v is None or (-1.0 <= v <= 1.0 and math.isfinite(v)), f"out-of-range correlation {v}"


def test_mask_and_non_numeric_columns_are_excluded(doc):
    order = doc["feature_corr_order"]
    assert not [k for k in order if k.endswith("::mask")], "a ::mask column entered the redundancy block"
    assert all("::num::" in k for k in order), "a non-metered column entered the redundancy block"
    # and the exclusion is load-bearing, not decorative — the atlas really does carry masks
    assert [k for k in doc["feature_order"] if k.endswith("::mask")], "no masks in the atlas ⇒ test is vacuous"


# ── 2. a correlation needs its basis ──────────────────────────────────────────────────────────────


def test_every_populated_offdiagonal_cell_clears_the_pairwise_floor(doc, build_mod):
    order, corr, counts = doc["feature_corr_order"], doc["feature_corr"], doc["feature_corr_n"]
    floor = build_mod.FEATURE_CORR_MIN_PAIRWISE_N
    for i in range(len(order)):
        for j in range(len(order)):
            if i != j and corr[i][j] is not None:
                assert counts[i][j] >= floor, f"{order[i]} / {order[j]}: r off {counts[i][j]} rows < {floor}"


def test_unknown_cells_are_none_and_that_branch_is_reachable(doc):
    """An unknown correlation must be None, never 0.0 — a redundancy discount that cannot tell "never
    co-measured" from "measured and independent" will confidently treat the first as the second. The
    second assertion is the anti-vacuity half: if no cell were ever unknown, the None contract would be
    untested by the shipped artifact."""
    corr = doc["feature_corr"]
    unknown = sum(1 for row in corr for v in row if v is None)
    assert unknown > 0, "no unknown cells in the shipped block — the None branch is untested here"
    for row in corr:
        for v in row:
            assert v is None or isinstance(v, (int, float))


def test_the_pairwise_complete_basis_measurably_differs_from_the_imputed_one(doc):
    """Why the block is not just np.corrcoef on the PCA's `Z`. That transform fills every missing cell with
    the column mean, which pulls the covariance toward zero in proportion to missingness — so exactly the
    columns most in need of a redundancy discount receive the smallest one. If the two bases agreed, the
    choice would be arbitrary and this block could be derived at read time from `Z`; they do not."""
    order, corr = doc["feature_corr_order"], doc["feature_corr"]
    fo = doc["feature_order"]
    cols = [fo.index(k) for k in order]
    A = np.array([[np.nan if r[j] is None else r[j] for j in cols] for r in doc["X"]], dtype=float)
    mu = np.array([doc["mu"][j] for j in cols], dtype=float)
    sd = np.array([doc["sd"][j] for j in cols], dtype=float)
    imputed = np.corrcoef((np.where(np.isnan(A), mu, A) - mu) / sd, rowvar=False)
    deltas = [
        abs(corr[i][j]) - abs(imputed[i][j])
        for i in range(len(order))
        for j in range(i + 1, len(order))
        if corr[i][j] is not None and math.isfinite(imputed[i][j])
    ]
    assert deltas
    assert max(deltas) > 0.03, (
        f"the two bases agree to within {max(deltas):.4f} — if imputation no longer attenuates the "
        "correlations, pairwise-complete stops being the load-bearing choice and this block could be "
        "derived from the PCA basis instead"
    )
    # and the attenuation has the predicted SIGN: imputation shrinks toward zero, it does not inflate
    assert sum(1 for d in deltas if d > 0) > sum(1 for d in deltas if d < 0)


# ── 3. the provenance claim is checkable by recomputation ─────────────────────────────────────────


def test_the_shipped_block_recomputes_exactly_from_the_frozen_X(doc, build_mod):
    """The claim that licenses amending a frozen artifact instead of re-freezing it: `feature_corr` is a
    pure function of `X` + `feature_order`, so the numbers a re-freeze would produce are the numbers
    already computable from the file. One implementation (`build_atlas.feature_correlation`) serves both
    the build and the amend path, and this asserts the shipped bytes match it."""
    order, corr, counts = build_mod.feature_correlation(doc["feature_order"], doc["X"])
    assert order == doc["feature_corr_order"]
    assert corr == doc["feature_corr"]
    assert counts == doc["feature_corr_n"]


def test_the_corr_block_declares_which_producer_made_it(doc):
    """`meta.build_git_sha` / `build_date` describe the freeze that produced `X`, and still do. A block
    derived afterwards must not ride on that stamp as if the original build emitted it.

    ★ There are TWO legitimate producers, and this asserts the block SAYS which one:
      - `derived_post_freeze: True`  — amend_atlas_feature_corr.py re-derived it from a shipped artifact
        (the path used for artifacts frozen before build_atlas computed feature_corr at all);
      - `derived_post_freeze: False` — build_atlas emitted it natively, in the same pass that froze X.

    Until 2026-09-13 this test asserted `is True` unconditionally, which was correct for the SHIPPED
    artifact and wrong for the mechanism: build_atlas computes feature_corr natively but stamped no
    provenance, so the next native re-freeze would have failed here — and the quickest way to green it
    would have been to re-run the amend script and assert a post-freeze derivation that never happened.
    Pinning the ARTIFACT's current state instead of the allowed set is how a gate ends up demanding a
    false stamp, so the check now reads the declared flag and holds each branch to its own invariant.
    """
    prov = doc["meta"].get("feature_corr_provenance")
    assert prov, "the feature_corr block ships with no provenance stamp"
    post = prov.get("derived_post_freeze")
    assert isinstance(post, bool), (
        f"derived_post_freeze must be an explicit bool naming the producer, got {post!r} — a missing or "
        f"null flag is the state that let a native rebuild ship an unattributed block"
    )
    assert "pairwise" in prov.get("method", "")
    # Either producer describes the SAME basis it was computed against, so this holds in both branches;
    # it is the assertion that catches a block carried over from a different freeze.
    assert prov.get("basis_build_git_sha") == doc["meta"].get("build_git_sha"), (
        "feature_corr_provenance.basis_build_git_sha does not match meta.build_git_sha — the block "
        "describes a different build than the one shipping it"
    )
    assert prov.get("derived_from"), "provenance must name what the block was derived from"


def test_the_shipped_artifact_is_specifically_the_native_producer(doc):
    """The test above deliberately accepts either producer, which means it is GREEN under a swap. This
    pins what the artifact on disk today actually is, so a change of producer is a visible, reviewed change
    rather than a silent one — and so the widened check above cannot be the only thing standing between a
    substituted stamp and a green suite.

    ⚠️ FLIPPED 2026-09-15, exactly as its predecessor's failure message instructed. The n=504 re-freeze
    computes `feature_corr` inside `build_atlas.feature_correlation` during the freeze itself, so the block
    and the basis it describes are now the SAME build (`basis_build_git_sha` 746f7452 == `meta.build_git_sha`)
    and `derived_post_freeze` is False. The post-freeze path (`amend_atlas_feature_corr.py`) now exists only
    to backfill artifacts frozen before the builder computed `feature_corr` at all. `atlas_freeze.json`'s
    meta digest was re-written in this same commit via `atlas_stability.py --write`, which the predecessor
    also asked to be checked; `--check` passes.

    ★ The direction of this flip is worth keeping: native is STRICTLY better provenance than amended,
    because an amended block can only ever assert that it matches a basis it was computed against later,
    while a native one cannot be carried over from a different freeze at all."""
    prov = doc["meta"]["feature_corr_provenance"]
    assert prov["derived_post_freeze"] is False, (
        "the SHIPPED atlas's feature_corr is back to a post-freeze amendment (derived_post_freeze=True). "
        "That is a REGRESSION in provenance, not a neutral swap: it means the block was computed against a "
        "basis it did not ship with. Re-run the freeze so the builder emits it natively."
    )
    # native means same-build by construction, so assert the property rather than trusting the flag alone
    assert prov["basis_build_git_sha"] == doc["meta"]["build_git_sha"]


def test_the_native_producer_stamps_a_valid_distinguishable_provenance(build_mod):
    """★ Exercises the OTHER branch, which no shipped artifact currently covers. `build()` needs
    scikit-learn plus the ~200-run corpus, so without a directly-callable stamp this branch would be
    reachable only by a hand-run re-freeze — i.e. first exercised at the moment it has to be right."""
    prov = build_mod.native_feature_corr_provenance("2026-01-02", "deadbeef")
    assert prov["derived_post_freeze"] is False, "the native stamp must not claim a post-freeze derivation"
    assert prov["basis_build_git_sha"] == "deadbeef"
    assert prov["added_date"] == "2026-01-02"
    assert "pairwise" in prov["method"]
    assert prov["derived_from"] and prov["reason"]


def test_the_two_producers_disagree_on_the_flag_and_agree_on_the_rest(build_mod):
    """The flag is only informative if the producers actually differ on it, and only safe if everything a
    consumer reads is present in BOTH shapes. A key that exists on one producer's stamp and not the
    other's is a reader that works until the next re-freeze."""
    src = AMEND.read_text()
    assert '"derived_post_freeze": True' in src, (
        "amend_atlas_feature_corr.py no longer stamps derived_post_freeze=True — the two producers no "
        "longer distinguish themselves and the flag is decorative"
    )
    native = build_mod.native_feature_corr_provenance("2026-01-02", "deadbeef")
    # Keys every consumer of the stamp can rely on, whichever producer ran.
    for k in ("derived_post_freeze", "derived_from", "method", "basis_build_git_sha", "reason", "added_date"):
        assert k in native, f"native stamp is missing the shared key {k!r}"
        assert f'"{k}"' in src, f"amend stamp is missing the shared key {k!r}"


def test_the_recomputation_check_can_actually_fail(doc, build_mod, tmp_path, monkeypatch):
    """Anti-vacuity for the two tests above, and for `amend_atlas_feature_corr.py --check`: mutate one cell
    of the shipped block and confirm the verifier rejects it. A provenance check that cannot fail is a
    comment."""
    amend = _load(AMEND)
    mutated = json.loads(ATLAS.read_text())
    i, j = next(
        (i, j)
        for i in range(len(mutated["feature_corr"]))
        for j in range(len(mutated["feature_corr"]))
        if i != j and mutated["feature_corr"][i][j] is not None
    )
    mutated["feature_corr"][i][j] = round(mutated["feature_corr"][i][j] + 0.25, 4)
    p = tmp_path / "atlas.json"
    p.write_text(json.dumps(mutated, separators=(",", ":")))
    monkeypatch.setattr(sys, "argv", ["amend", "--atlas", str(p), "--check"])
    assert amend.main() == 1, "a mutated feature_corr cell passed the recomputation check"
    # the same verifier must ACCEPT the unmutated artifact, or it would "catch" the mutation by always
    # failing (the vacuous-pass failure mode, inverted)
    monkeypatch.setattr(sys, "argv", ["amend", "--atlas", str(ATLAS), "--check"])
    assert amend.main() == 0, "the verifier rejects the shipped artifact — it fails for every input"
