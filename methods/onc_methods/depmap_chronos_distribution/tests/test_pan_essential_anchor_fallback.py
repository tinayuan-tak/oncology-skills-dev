"""Curated pan-essential anchor fallback — the UNANCHORED split (skills #1794, 2026-09-28).

History of this seam:
  * T3 re-anchor (2026-08-31): a >=85% strongly-dependent fraction fires the pan-essential
    broad-tox KILLER only when corroborated by DepMap's curated core-essential control set
    (AchillesCommonEssentialControls) — removing the CD19 / KRAS-CRISPRInferred false-veto.
  * Offline-fallback fix (2026-09-01): anchor unreachable (curated_common_essential=None) no
    longer falls through to a fraction-only `common_essential` KILLER; it was routed to
    `common_essential_underpowered`.
  * UNANCHORED split (skills #1794, 2026-09-28): that routing OVER-degraded on the SAFETY
    axis. `common_essential_underpowered` means "tiny-panel artifact — the fraction itself is
    untrusted" and is deliberately DARK downstream, so a transient anchor outage on a genuine
    core-essential (PLK1-class) produced a CLEAN safety verdict: the
    pan-essential-broad-tox-safety-warning never fired (fail-open in the liability direction).
    A well-powered >=85% call with a missing anchor is DIFFERENT EVIDENCE — the fraction is
    trusted, only the curated corroboration is absent — so it now classifies as the DISTINCT
    `common_essential_unanchored`, which the dependency gate still treats as insufficient (no
    fraction-only veto) and the SAFETY axis treats conservatively (concern, never clean).

The audit/ladder field (flag left False) still reports the raw fraction-only
`common_essential`, so the degradation is auditable. Default False keeps every other caller
byte-for-byte.

MUTATION TEETH: test_missing_anchor_routes_to_unanchored_not_underpowered RED-fails if the
anchor-None branch is reverted to `common_essential_underpowered` (the #1794 fail-open) OR to
a fraction-only `common_essential` (the pre-2026-09-01 false-veto).
"""

from __future__ import annotations

# Derive the repo root from THIS file so the test imports the checkout it lives in (worktree or home),
# not a hardcoded home path — otherwise a worktree edit is invisible to the test.
from onc_methods.depmap_chronos_distribution.cli import _classify_dependency

_ADEQUATE = dict(n_cell_lines_evaluated=1500)


def test_anchor_true_is_common_essential_unchanged():
    # ONLINE: curated says core-essential → killer fires as before.
    assert (
        _classify_dependency(
            0.90,
            -1.2,
            "pan_essential",
            curated_common_essential=True,
            treat_missing_anchor_as_unanchored=True,
            **_ADEQUATE,
        )
        == "common_essential"
    )


def test_anchor_false_is_broadly_dependent_unchanged():
    # ONLINE: curated says NOT core-essential (context-essential oncogene) → no killer (T3).
    assert (
        _classify_dependency(
            0.90,
            -1.2,
            "pan_essential",
            curated_common_essential=False,
            treat_missing_anchor_as_unanchored=True,
            **_ADEQUATE,
        )
        == "broadly_dependent"
    )


def test_missing_anchor_routes_to_unanchored_not_underpowered():
    # THE #1794 FIX (mutation teeth): anchor unreachable (None) on a WELL-POWERED panel at the
    # real call site → the DISTINCT `common_essential_unanchored`. It must be NEITHER the
    # safety-dark `common_essential_underpowered` (the fail-open this fix closes: a transient
    # anchor outage read as a clean safety verdict for a PLK1-class core-essential) NOR a
    # fraction-only `common_essential` killer (the pre-anchor false-veto).
    got = _classify_dependency(
        0.90,
        -1.2,
        "pan_essential",
        curated_common_essential=None,
        treat_missing_anchor_as_unanchored=True,
        **_ADEQUATE,
    )
    assert got == "common_essential_unanchored"
    assert got != "common_essential_underpowered"
    assert got != "common_essential"


def test_tiny_panel_missing_anchor_stays_underpowered():
    # POWER GUARD PRECEDES THE ANCHOR SPLIT: on a panel below PAN_ESSENTIAL_MIN_PANEL_N the
    # FRACTION ITSELF is untrusted — that is genuinely `common_essential_underpowered`, not
    # unanchored (unanchored asserts "trusted fraction, missing corroboration").
    assert (
        _classify_dependency(
            0.90,
            -1.2,
            "pan_essential",
            curated_common_essential=None,
            treat_missing_anchor_as_unanchored=True,
            n_cell_lines_evaluated=100,
        )
        == "common_essential_underpowered"
    )


def test_missing_anchor_audit_ladder_keeps_fraction_only_common_essential():
    # AUDIT LADDER (flag False, the pan_essential_fraction_call path): raw fraction-only call preserved
    # byte-for-byte, so the offline degradation is fully auditable against the raw heuristic.
    assert (
        _classify_dependency(
            0.90,
            -1.2,
            "pan_essential",
            curated_common_essential=None,
            treat_missing_anchor_as_unanchored=False,
            **_ADEQUATE,
        )
        == "common_essential"
    )
    # default is False → prior behavior unchanged for any caller that does not opt in
    assert (
        _classify_dependency(0.90, -1.2, "pan_essential", curated_common_essential=None, **_ADEQUATE)
        == "common_essential"
    )


def test_flag_is_inert_below_pan_essential_fraction():
    # The flag only guards the >=85% branch; a selective/non-dependent call is untouched.
    got = _classify_dependency(
        0.30,
        -0.8,
        "selective",
        curated_common_essential=None,
        treat_missing_anchor_as_unanchored=True,
        **_ADEQUATE,
    )
    assert got not in ("common_essential_underpowered", "common_essential_unanchored")
