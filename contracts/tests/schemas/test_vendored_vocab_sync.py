"""data-catalog's VENDORED copies of our controlled vocabularies must be byte-identical (SK#2097).

data-catalog carries byte-copies of two of this package's controlled vocabularies:

    contracts/vocabularies/measurement_types.yaml
      -> data-catalog core-artifacts-schema/measurement_types.yaml
    contracts/vocabularies/indication_crosswalk.yaml
      -> data-catalog core-artifacts-schema/indication_crosswalk.yaml

THIS package is the source of truth; DC's copies are refreshed FROM here (DC's
`scripts/refresh_vendored_vocab.py`). Unlike `products.yaml` — where the two copies
legitimately differ in fields and the honest guard is semantic (see
`test_products_registry_sync.py`) — these two are meant to be *copies*, so the honest
guard is BYTE equality. Anything weaker lets a reformat or a re-ordered enum through.

WHY THE GUARD LIVES HERE AND NOT THERE. The only sync check used to be DC-side, and it
SKIPPED whenever the target-contracts checkout was absent — i.e. always, in DC CI. So
real drift shipped invisibly: as of 2026-09-29 DC's vendored `measurement_types.yaml`
was missing `depmap_cell_line_rna` (~175 differing lines) and nothing anywhere was red
(DC#647; resynced by DC#731). The DC-side fix (DC PR#716) needed a `CROSS_REPO_TOKEN`
secret that was never provisioned. Owner decision 2026-09-29: enforce MONOREPO-side
instead, where the data-catalog checkout already exists and costs no new secret —
`contracts-pytest` checks DC out at `env.DATA_CATALOG_SHA` and exports
`DATA_CATALOG_ROOT`. CREDIT: the step design this guard is wired with in CI (log
redirect, skip-string grep, explicit passed-count assert) is DC PR#716's — it was well
built, and only its *secret-based cross-repo checkout* was unusable here.

WHAT GOES RED, AND WHEN. The effect of enforcing here is that the drift-INTRODUCING PR
is the one that reds: a monorepo PR editing either vocabulary without a matching DC
resync + pin bump fails this test. That is the point. The remedy is never to relax the
comparison — it is to land the DC resync and bump `env.DATA_CATALOG_SHA`.

FAIL-CLOSED, NOT SKIP-OPEN. `require_data_catalog()` (imported from the sibling module,
deliberately not re-derived) fails under `CI` when the DC checkout is missing and skips
only on a bare local checkout. A sync guard that skips is precisely the DC-side defect
above. `test_vendored_vocab_files_are_present` additionally pins the closed set of
vendored files, so a rename on either side cannot silently empty this guard out.

CLOSED-SET PIN vs GREEN-WHILE-BLIND. This module compares against whatever
`DATA_CATALOG_ROOT` points at, which in `contracts-pytest` is the hand-bumped PIN. A
pinned comparison alone can be green while blind — DC `main` may have moved past the
pin. The nightly `card-behavior-matrix-nightly.yml` therefore runs this same module
against data-catalog @ `main` (credential-less, so it runs whether or not the OIDC role
is wired), covering exactly that window.
"""

import difflib
from pathlib import Path

import pytest

# Sibling-module import (pytest's default prepend import-mode puts this directory on
# sys.path; contracts deliberately does NOT use --import-mode=importlib, see pyproject).
# REUSE, do not re-derive: require_data_catalog() is the fail-closed DATA_CATALOG_ROOT
# resolver hardened for this seam by #2098.
from test_products_registry_sync import require_data_catalog

CONTRACTS_VOCAB_DIR = Path(__file__).resolve().parents[2] / "vocabularies"

# The vocabularies data-catalog vendors as byte-copies. CLOSED SET: vendoring a third
# vocabulary (or retiring one of these) is a real cross-repo decision — DC's
# refresh_vendored_vocab.py and this list must move together — so it is declared here
# rather than discovered. Verified byte-identical 2026-09-29 (DC#731 resync).
VENDORED_VOCABULARIES = ("measurement_types.yaml", "indication_crosswalk.yaml")


def _vendored_pair(filename: str) -> tuple[Path, Path]:
    return CONTRACTS_VOCAB_DIR / filename, require_data_catalog() / "core-artifacts-schema" / filename


def test_vendored_vocab_files_are_present() -> None:
    """Non-vacuity: every declared vendored vocabulary exists on BOTH sides.

    Without this, a rename/removal on either side would turn the byte-comparison below
    into a test of nothing (or an error people would "fix" by trimming the list). A red
    here means the vendoring relationship itself changed and needs a decision, not a
    list edit.
    """
    missing = []
    for filename in VENDORED_VOCABULARIES:
        here, there = _vendored_pair(filename)
        if not here.is_file():
            missing.append(f"contracts/vocabularies/{filename} (source of truth) is absent")
        if not there.is_file():
            missing.append(f"data-catalog core-artifacts-schema/{filename} (vendored copy) is absent at {there}")
    assert not missing, (
        "the vendored-vocabulary relationship changed — this guard cannot compare what is not there:\n  "
        + "\n  ".join(missing)
        + "\nIf a vocabulary genuinely stopped being vendored, remove it from VENDORED_VOCABULARIES "
        "in the same PR that removes it from data-catalog's refresh_vendored_vocab.py."
    )


@pytest.mark.parametrize("filename", VENDORED_VOCABULARIES)
def test_vendored_vocab_is_byte_identical(filename: str) -> None:
    here, there = _vendored_pair(filename)
    # Deliberately NOT a skip on absence: an absent copy is the drift, and a skipping sync
    # guard is the DC-side defect this module replaces. test_vendored_vocab_files_are_present
    # carries the explanatory message; this stays red too rather than going quietly vacuous.
    for path, role in ((here, "source of truth"), (there, "vendored copy")):
        assert path.is_file(), f"{filename} ({role}) is absent at {path} — see test_vendored_vocab_files_are_present"

    here_bytes, there_bytes = here.read_bytes(), there.read_bytes()
    if here_bytes == there_bytes:
        return

    diff = list(
        difflib.unified_diff(
            here_bytes.decode("utf-8", "replace").splitlines(),
            there_bytes.decode("utf-8", "replace").splitlines(),
            fromfile=f"contracts/vocabularies/{filename} (source of truth)",
            tofile=f"data-catalog core-artifacts-schema/{filename} (vendored copy @ {there})",
            lineterm="",
        )
    )
    n_changed = sum(1 for line in diff if line[:1] in "+-" and not line.startswith(("+++", "---")))
    head = "\n".join(diff[:40])
    pytest.fail(
        f"{filename} has DRIFTED between this package and data-catalog's vendored copy "
        f"({n_changed} differing lines; {len(here_bytes)} vs {len(there_bytes)} bytes).\n"
        f"This package is the source of truth. Fix by resyncing data-catalog "
        f"(`scripts/refresh_vendored_vocab.py`), landing that there, and bumping "
        f"`env.DATA_CATALOG_SHA` in .github/workflows/skills-validate.yml in the SAME PR as the "
        f"vocabulary edit — do NOT relax this comparison.\nFirst lines of the diff:\n{head}"
    )
