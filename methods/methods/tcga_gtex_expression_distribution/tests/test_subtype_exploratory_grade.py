"""The tumor-RNA arm's opt-in to the `exploratory` (10-29) evidence band, end-to-end and offline.

Exercised through `read_tumor_subtype_values` — the per-stratum figure companion — because it is the
reachable half of the arm with three stubs rather than five (the landscape reader additionally
resolves matched normals and a live join-coverage read). The two functions cannot silently diverge:
`read_tumor_subtype_values`'s own docstring promises it "Shares the SAME bridge + shard as
read_tumor_expression_subtype_landscape (no drift)", and that invariant is pinned structurally in
`methods/subgroup_common/tests/test_arm_grade_optin.py`, which asserts both call sites carry the
same opt-in kwargs.

`evaluated=` is deliberately NOT wired on this arm: strata are enumerated from `is_member == True`
rows, so every stratum in the loop has >=1 classified member and the flag would never vary. The
fixture below reproduces that — there is no way to ask this reader about an unclassified stratum.
S3-free: pooled vector, case bridge and assignment shard are all stubbed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.tcga_gtex_expression_distribution import read as R  # noqa: E402

# One stratum per grade, sized to sit unambiguously inside its band rather than on an edge the
# band-edge tests below probe deliberately: 40 >= 30 (measured), 15 in [10,30) (exploratory),
# 5 < 10 (underpowered).
_STRATUM_SIZES = {"BIG": 40, "MID": 15, "TINY": 5}


def _stub_arm(monkeypatch, sizes: dict[str, int] = _STRATUM_SIZES) -> None:
    """Stub the three live reads `read_tumor_subtype_values` performs."""
    cases: list[str] = []
    rows: list[dict] = []
    for stratum, n in sizes.items():
        for i in range(n):
            case = f"TCGA-{stratum}-{i:03d}"
            cases.append(case)
            rows.append({"sample_id": case, "stratum_id": stratum, "is_member": True})
            # A non-member row per stratum, so the shard is a realistic partition rather than a
            # members-only table — and so `is_member == True` filtering is actually exercised.
            rows.append({"sample_id": f"TCGA-OTHER-{stratum}-{i:03d}", "stratum_id": stratum, "is_member": False})
    bridged = pd.DataFrame({"case": cases, "log2_tpm": [6.0 + (i % 7) * 0.1 for i in range(len(cases))]})
    assignments = pd.DataFrame(rows)

    monkeypatch.setattr(R, "read_tumor_samples", lambda t, i: bridged["log2_tpm"].tolist())
    monkeypatch.setattr(R, "read_tumor_samples_with_case", lambda t, i: bridged)
    monkeypatch.setattr(R, "_load_subtype_assignments", lambda i: (assignments, "stub-shard-v1"))


def _grades(monkeypatch, sizes: dict[str, int] = _STRATUM_SIZES) -> dict[str, str]:
    _stub_arm(monkeypatch, sizes)
    out = R.read_tumor_subtype_values("EPCAM", "COADREAD")
    assert out["available"] is True, "stubs failed to produce a usable arm — the rest is vacuous"
    return {r["stratum_id"]: r["evidence_state"] for r in out["strata"]}


def test_three_grades_are_all_reachable_on_the_tumor_arm(monkeypatch):
    """One stratum per grade in a single pass — the anti-vacuity control for the band.

    Before the opt-in, MID (n=15) and TINY (n=5) both graded `underpowered` and were
    indistinguishable to any consumer. Asserting all three in one call proves the new grade
    SEPARATES strata rather than merely renaming a category.
    """
    assert _grades(monkeypatch) == {"BIG": "measured", "MID": "exploratory", "TINY": "underpowered"}


@pytest.mark.parametrize(
    "n,expected",
    [(9, "underpowered"), (10, "exploratory"), (29, "exploratory"), (30, "measured")],
)
def test_band_edges_are_inclusive_at_the_bottom_and_exclusive_at_the_top(monkeypatch, n, expected):
    """Both edges, because a one-sided test cannot distinguish an inclusive floor from an exclusive one.

    Inclusivity is load-bearing on this arm specifically: the live NSCLC MAF shard's
    `EGFR_mut_ex19del` stratum has exactly n=10, so `>` rather than `>=` would leave the most
    clinically loaded stratum on the whole arm invisible.
    """
    assert _grades(monkeypatch, {"EDGE": n})["EDGE"] == expected


def test_exploratory_stratum_carries_values_but_never_a_signal(monkeypatch):
    """Visible, not claimable — the distinction from relaxing SUBGROUP_N_FLOOR.

    `subtype_signal` stays None because it is gated on `floor_met`, and `subgroup_n_floor_met`
    stays False. An `exploratory` stratum therefore cannot enter the omnibus, the spread reducers
    or any scoped call; the only thing that changed is that a consumer can now see it and say so.
    """
    _stub_arm(monkeypatch)
    out = R.read_tumor_subtype_values("EPCAM", "COADREAD")
    mid = next(r for r in out["strata"] if r["stratum_id"] == "MID")
    assert mid["evidence_state"] == "exploratory"
    assert mid["n"] == 15 and len(mid["values"]) == 15  # the data IS reported
    assert mid["median"] is not None
    assert mid["subtype_signal"] is None  # …but no signal is claimed
    assert mid["subgroup_n_floor_met"] is False  # …and the n-floor keeps its one meaning
    # The powered stratum is the control: same code path, and it DOES get a signal.
    big = next(r for r in out["strata"] if r["stratum_id"] == "BIG")
    assert big["subgroup_n_floor_met"] is True and big["subtype_signal"] is not None


def test_unevaluable_is_unreachable_on_this_arm_by_construction(monkeypatch):
    """A stratum absent from the `is_member == True` rows is never enumerated at all.

    This is why `evaluated=` is not passed here: there is no code path on which it could vary. The
    grade `unevaluable` is reachable only from the DepMap/CPTAC arms, which are handed `subgroups`
    by the CALLER. Pinning it means a future change to the stratum enumeration surfaces as a failure
    here rather than as a silently constant argument.
    """
    cases = [f"TCGA-BIG-{i:03d}" for i in range(40)]
    bridged = pd.DataFrame({"case": cases, "log2_tpm": [6.0] * len(cases)})
    # NEVER_ASSIGNED is the shape that grades `unevaluable` on the other two arms: rows exist but
    # not one is `is_member is True`. Here it must not appear in the output AT ALL.
    assignments = pd.DataFrame(
        [{"sample_id": c, "stratum_id": "BIG", "is_member": True} for c in cases]
        + [{"sample_id": c, "stratum_id": "NEVER_ASSIGNED", "is_member": None} for c in cases]
    )
    monkeypatch.setattr(R, "read_tumor_samples", lambda t, i: bridged["log2_tpm"].tolist())
    monkeypatch.setattr(R, "read_tumor_samples_with_case", lambda t, i: bridged)
    monkeypatch.setattr(R, "_load_subtype_assignments", lambda i: (assignments, "stub-shard-v1"))

    out = R.read_tumor_subtype_values("EPCAM", "COADREAD")
    assert [r["stratum_id"] for r in out["strata"]] == ["BIG"]  # NEVER_ASSIGNED not enumerated
    assert "unevaluable" not in {r["evidence_state"] for r in out["strata"]}
