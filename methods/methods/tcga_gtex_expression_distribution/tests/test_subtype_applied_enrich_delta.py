"""The APPLIED enrichment cut, emitted per stratum by the tumour-RNA landscape reader.

Follow-on to target-contracts #811, which declared `subtype_enrich_log2_delta` on all three
by-subtype cards as "the enrichment cutoff ACTUALLY APPLIED to produce `subtype_signal` on this
row". The word `enriched` means three different things across the arms — a 0.585 log2(TPM+1) median
shift here, 1.0 on the cell-line RNA arm, and 0.25 of a tumour-vs-reference log2 RATIO on the CPTAC
protein arm — and until now the number lived only as a constant inside each method and was emitted
nowhere, so a consumer joining the arms per stratum could not tell that two `subtype_enriched`
tokens are not the same claim.

The card's wording makes the NULL cases load-bearing, and this arm has three of them where the
siblings have two. Tested through `read_tumor_expression_subtype_landscape` rather than the
`read_tumor_subtype_values` figure companion because the landscape is the card's producer:
`cli.py:145` passes `subtype_landscape` through verbatim as `per_subgroup_metrics`, while the figure
rows carry `values`/`n`/`median`, which that record schema's `additionalProperties: false` rejects.
That costs five stubs instead of three; all live reads are stubbed, so this test is S3-free.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.tcga_gtex_expression_distribution import read as R  # noqa: E402

_DELTA = 0.585


def _stub_landscape(
    monkeypatch,
    strata: dict,
    *,
    pooled_median: float | None = 6.0,
    pooled_detectable: float | None = 0.9,
) -> list:
    """Stub every live read the landscape performs and return the resulting landscape records.

    `strata` maps stratum_id -> (n, per-sample log2tpm value). The pooled summary is injected rather
    than computed so the two comparators the classifier reads (`pooled_median`,
    `detectable_fraction`) can be set independently — `subtype_restricted` is a function of the
    POOLED detectability, so it is unreachable without that control.

    A value of None means the stratum is ASSIGNED but its cases are absent from the bridge, so the
    reader takes its no-values `else` branch. That is not a contrived shape: it is the live
    id-convention mismatch this arm warns about ("only 0/193 members matched column 'case'"), and it
    is the only way to reach the second of the two places that must declare the field.
    """
    cases: list[str] = []
    values: list[float] = []
    rows: list[dict] = []
    for stratum_id, (n, val) in strata.items():
        for i in range(n):
            case = f"TCGA-{stratum_id}-{i:03d}"
            rows.append({"sample_id": case, "stratum_id": stratum_id, "is_member": True})
            if val is None:
                continue  # assigned, but never lands in the bridge -> the no-values branch
            cases.append(case)
            values.append(val)
    bridged = pd.DataFrame({"case": cases, "log2_tpm": values})
    assignments = pd.DataFrame(rows)

    pooled = {
        "tumor_expression_class": "broadly_detected",
        "median_log2tpm": pooled_median,
        "detectable_fraction": pooled_detectable,
        "high_fraction": 0.4,
        "n_tumor_samples": len(cases),
    }
    monkeypatch.setattr(R, "read_tumor_expression_distribution", lambda t, i: dict(pooled))
    monkeypatch.setattr(R, "read_tumor_samples_with_case", lambda t, i: bridged)
    monkeypatch.setattr(R, "_load_subtype_assignments", lambda i: (assignments, "stub-shard-v1"))
    # a matched normal is supplied so the proxy-panel branch (an extra live read) stays unentered
    monkeypatch.setattr(R, "read_normal_samples", lambda t, i: ([0.2] * 20, "Colon"))
    # Both of these are imported INSIDE the reader body, so the RESOLVING namespace is the source
    # module, not `R` — patching R would leave the real function bound at call time.
    import methods.expression_purity_confound.read as purity
    import methods.subgroup_common.scoping as scoping

    monkeypatch.setattr(purity, "_load_purity_by_case", lambda: {})
    # the join-coverage guard is a SIXTH live read: it re-loads the shard to compare member ids
    # against the bridge. Stubbed to a full match — the id-convention warning is not under test.
    monkeypatch.setattr(
        scoping,
        "compute_join_coverage",
        lambda *a, **k: SimpleNamespace(match_rate=1.0, n_matched=len(cases), n_members=len(cases)),
    )

    out = R.read_tumor_expression_subtype_landscape("EPCAM", "COADREAD")
    assert out["subtype_axis_available"] is True, "stubs failed to build an axis — the rest is vacuous"
    land = out["subtype_landscape"]
    assert land, "empty landscape — an assertion over zero rows passes vacuously"
    return land


def _by_id(land: list) -> dict:
    return {r["stratum_id"]: r for r in land}


def test_applied_delta_is_emitted_on_rows_the_cut_produced(monkeypatch):
    """The positive case, on both sides of the band: an `enriched` call and a real `uniform` one.

    A `uniform` verdict is still a verdict the cut produced — both comparisons ran and neither
    fired — so it carries the delta. Asserting it alongside the enriched row prevents a future
    implementation from emitting the delta only for non-uniform signals, which would look correct
    on every headline field while stripping the join key from the majority of rows.
    """
    land = _by_id(_stub_landscape(monkeypatch, {"HIGH": (40, 7.0), "SAME": (40, 6.0)}))
    assert land["HIGH"]["subtype_signal"] == "subtype_enriched"
    assert land["HIGH"]["subtype_enrich_log2_delta"] == _DELTA
    assert land["SAME"]["subtype_signal"] == "subtype_uniform"
    assert land["SAME"]["subtype_enrich_log2_delta"] == _DELTA


def test_emitted_delta_is_this_arm_s_constant_not_a_sibling_s(monkeypatch):
    """0.585 here, 1.0 on the cell-line arm — the cross-arm divergence this field exists to expose.

    The two constants are deliberately NOT aligned: changing the cell-line cut would silently
    reclassify live strata, so emitting the applied value is the fix instead. Pinned against both
    the module constant and the literal, because asserting only `== SUBTYPE_ENRICH_LOG2_DELTA` would
    pass if someone "harmonised" the arms by editing the constant.
    """
    land = _by_id(_stub_landscape(monkeypatch, {"HIGH": (40, 7.0)}))
    assert land["HIGH"]["subtype_enrich_log2_delta"] == R.SUBTYPE_ENRICH_LOG2_DELTA == 0.585


def test_restricted_call_carries_no_delta_because_the_cut_never_ran(monkeypatch):
    """The null case unique to this arm — and the reason the signal alone cannot gate the field.

    `subtype_restricted` is a DETECTABILITY call (stratum detectable >= 0.5 while pooled < 0.3) and
    its branch returns BEFORE either delta comparison, so no cut was applied to that row. A
    consumer normalising an `enriched` threshold across arms must not be handed a cutoff that played
    no part in the call.

    UNDETECTED is the in-run control and it has to be built deliberately: with pooled detectability
    this low, EVERY stratum whose own detectability clears 0.5 is restricted, so a second
    highly-expressed stratum would just be a second restricted row and could not distinguish "null
    where the cut was bypassed" from "null everywhere". A stratum that is itself undetectable skips
    the restricted branch, reaches the delta comparison, and must carry the cut.
    """
    land = _by_id(
        _stub_landscape(
            monkeypatch,
            {"DETECTED": (40, 6.0), "UNDETECTED": (40, 0.1)},
            pooled_median=6.0,
            pooled_detectable=0.1,  # broadly absent pooled -> the restricted branch is reachable
        )
    )
    assert land["DETECTED"]["subtype_signal"] == "subtype_restricted"
    assert land["DETECTED"]["subtype_enrich_log2_delta"] is None
    # control: the delta comparison DID run here, so the cut is attested
    assert land["UNDETECTED"]["subtype_signal"] == "subtype_depleted"
    assert land["UNDETECTED"]["subtype_enrich_log2_delta"] == _DELTA


def test_exploratory_and_underpowered_strata_carry_no_delta(monkeypatch):
    """No signal means no applied cut: the field must not imply a comparison the floor forbade.

    `subtype_signal` is gated on `floor_met`, so a 10-29 member `exploratory` stratum is computed
    and reported but never classified. Emitting the cut there would suggest it had been applied and
    found nothing — exactly the abstention-as-measurement confusion the grade exists to prevent.
    The powered stratum is the in-run control.
    """
    land = _by_id(_stub_landscape(monkeypatch, {"BIG": (40, 7.0), "MID": (15, 7.0), "TINY": (5, 7.0)}))
    assert land["MID"]["evidence_state"] == "exploratory"
    assert land["MID"]["subtype_signal"] is None
    assert land["MID"]["subtype_enrich_log2_delta"] is None
    assert land["TINY"]["subtype_signal"] is None
    assert land["TINY"]["subtype_enrich_log2_delta"] is None
    assert land["BIG"]["subtype_enrich_log2_delta"] == _DELTA  # control: the cut DID run here


def test_missing_pooled_median_is_an_abstention_not_a_uniform_finding(monkeypatch):
    """The third null case, and the one a `subtype_signal` check cannot see.

    `_classify_subtype_signal` FALLS THROUGH to "subtype_uniform" when either median is None, so an
    uncompared stratum carries a token indistinguishable from a measured finding — the fall-through
    absorbs the abstention. The delta is therefore gated on the medians as well as the signal, and a
    null delta on a `uniform` row is the reader's only signal that nothing was compared.
    Defensive rather than observed: the stub forces a pooled summary with no median, which
    production reaches only through a pooled read that is itself degraded.
    """
    land = _by_id(_stub_landscape(monkeypatch, {"BIG": (40, 7.0)}, pooled_median=None))
    assert land["BIG"]["subtype_signal"] == "subtype_uniform"  # the token looks measured…
    assert land["BIG"]["subtype_enrich_log2_delta"] is None  # …the delta says otherwise


def test_every_landscape_row_declares_the_field(monkeypatch):
    """Key PRESENCE, across every grade in one run — the record shape must not encode the grade.

    An absent key is worse than a null: `rec["subtype_enrich_log2_delta"]` raises on the first
    unclassified stratum, and `rec.get(..., DEFAULT)` silently substitutes a cut for exactly the
    rows where none was applied. The reader declares the field in TWO places — the measured path and
    the no-values `else` branch — so UNMATCHED below is not padding: without a stratum that reaches
    the second branch, deleting that default leaves every assertion here green (measured by mutation:
    it was the sweep's one survivor).
    """
    land = _stub_landscape(monkeypatch, {"BIG": (40, 7.0), "MID": (15, 7.0), "TINY": (5, 7.0), "UNMATCHED": (40, None)})
    assert all("subtype_enrich_log2_delta" in r for r in land), "a row omits the field entirely"
    assert all(r["subtype_enrich_log2_delta"] is None for r in land if r["stratum_id"] == "UNMATCHED")
    by_id = _by_id(land)
    assert by_id["UNMATCHED"]["n_tumor_samples"] == 0  # assigned, but nothing bridged
    assert {r["evidence_state"] for r in land} == {"measured", "exploratory", "underpowered", "absent"}
