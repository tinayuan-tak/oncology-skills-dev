"""Offline-fallback fix for the curated pan-essential anchor (2026-09-01).

The T3 re-anchor (2026-08-31) co-requires a >=85% strongly-dependent fraction to ALSO be a
DepMap curated core-essential (AchillesCommonEssentialControls) before it fires the pan-essential
broad-tox KILLER — removing the CD19 / KRAS-CRISPRInferred false-veto. But it left a residual trap:
when the curated list is UNREACHABLE (offline / creds fail, curated_common_essential=None) the real
dependency_class fell through to a fraction-only `common_essential` KILLER — the exact unjustified
veto the re-anchor removed, re-exposed on a bare 0.85 fraction.

Fix: at the real dependency_class call site (treat_missing_anchor_as_underpowered=True), a >=85%
call with a missing anchor routes to `common_essential_underpowered` (→ insufficient, NO veto) — the
honest "can't-trust-this-pan-essential" bucket. The audit/ladder field (flag left False) still reports
the raw fraction-only `common_essential`, so the degradation is auditable. Default False keeps every
other caller byte-for-byte.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Derive the repo root from THIS file so the test imports the checkout it lives in (worktree or home),
# not a hardcoded home path — otherwise a worktree edit is invisible to the test.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from methods.depmap_chronos_distribution.cli import _classify_dependency  # noqa: E402

_ADEQUATE = dict(n_cell_lines_evaluated=1500)


def test_anchor_true_is_common_essential_unchanged():
    # ONLINE: curated says core-essential → killer fires as before.
    assert _classify_dependency(0.90, -1.2, "pan_essential", curated_common_essential=True,
                                treat_missing_anchor_as_underpowered=True, **_ADEQUATE) == "common_essential"


def test_anchor_false_is_broadly_dependent_unchanged():
    # ONLINE: curated says NOT core-essential (context-essential oncogene) → no killer (T3).
    assert _classify_dependency(0.90, -1.2, "pan_essential", curated_common_essential=False,
                                treat_missing_anchor_as_underpowered=True, **_ADEQUATE) == "broadly_dependent"


def test_missing_anchor_routes_to_underpowered_at_real_call_site():
    # THE FIX: anchor unreachable (None) + real call site → underpowered, NOT a fraction-only killer.
    assert _classify_dependency(0.90, -1.2, "pan_essential", curated_common_essential=None,
                                treat_missing_anchor_as_underpowered=True,
                                **_ADEQUATE) == "common_essential_underpowered"


def test_missing_anchor_audit_ladder_keeps_fraction_only_common_essential():
    # AUDIT LADDER (flag False, the pan_essential_fraction_call path): raw fraction-only call preserved
    # byte-for-byte, so the offline degradation is fully auditable against the raw heuristic.
    assert _classify_dependency(0.90, -1.2, "pan_essential", curated_common_essential=None,
                                treat_missing_anchor_as_underpowered=False, **_ADEQUATE) == "common_essential"
    # default is False → prior behavior unchanged for any caller that does not opt in
    assert _classify_dependency(0.90, -1.2, "pan_essential", curated_common_essential=None,
                                **_ADEQUATE) == "common_essential"


def test_flag_is_inert_below_pan_essential_fraction():
    # The flag only guards the >=85% branch; a selective/non-dependent call is untouched.
    assert _classify_dependency(0.30, -0.8, "selective", curated_common_essential=None,
                                treat_missing_anchor_as_underpowered=True, **_ADEQUATE) != "common_essential_underpowered"
