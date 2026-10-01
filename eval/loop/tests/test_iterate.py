#!/usr/bin/env python3
"""Teeth for eval/loop/iterate.py (SK#2303 WI-I, #2360) — the end-to-end orchestrator.

These do NOT re-test the parts (substrate / judge / containment / findings / tiers / convergence each
carry their own teeth). They test that iterate.py WIRES them correctly:

  - DEV findings flow through containment → ledger (deduped, chain intact) → tiers;
  - the frozen-symbol denylist still forces T3 THROUGH the orchestrator, and teeth_green=False keeps T1
    empty (report-only / STOP-A);
  - a false-premise finding dropped by containment NEVER reaches the ledger or the tiers;
  - HELD-OUT drives convergence, and the NULL-block holds end-to-end: a missing held-out package
    (judge skipped + probe not_evaluable) blocks convergence even though it emits zero findings;
  - a clean, alive held-out package with a silent judge converges (hysteresis_n=1).

No live Bedrock: the LLM judge is injected. Packages are laid out exactly as ``run_batch`` leaves them
(``<run_dir>/_emit__<target>_<indication>/{evidence_package,decision}.json``) using the REAL emitted
tumor-presence fixtures shared with ``test_substrate.py``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_LOOP = Path(__file__).resolve().parents[1]
if str(_LOOP) not in sys.path:
    sys.path.insert(0, str(_LOOP))

import iterate as IT  # noqa: E402

_FIX = Path(__file__).resolve().parent / "fixtures"
_FAM = "tumor_presence_concordance"  # a real L2b family in both fixtures, carries corroboration + a token


def _fixture(name: str) -> dict:
    return json.loads((_FIX / f"{name}_coadread_emitted.json").read_text())


def _write_package(run_dir: Path, target: str, indication: str, fixture_name: str) -> None:
    """Lay out one emitted package the way run_batch does: _emit__<slug>/{evidence_package,decision}.json."""
    entry = IT.Entry(target=target, indication=indication)
    pkg_dir = entry.package_dir(run_dir)
    pkg_dir.mkdir(parents=True, exist_ok=True)
    bundle = _fixture(fixture_name)
    (pkg_dir / "evidence_package.json").write_text(json.dumps(bundle["evidence_package"]))
    (pkg_dir / "decision.json").write_text(json.dumps(bundle["decision"]))


# ── finding factory ─────────────────────────────────────────────────────────────────────────────────
def _benign_t2() -> dict:
    """A grounded, non-frozen, non-additive-kind finding → CONTAINED → T2 (needs a human, never T1)."""
    return {
        "kind": "missing_relationship",
        "target": "L2b.tumor_presence_concordance",
        "finding": "the measured token is not linked to the abundance arm in the story",
        "why": "the arms carry a datum the relationship layer never joins",
        "datum_refs": [f"l2b.{_FAM}.token"],
    }


def _frozen_t3() -> dict:
    """A T1-ELIGIBLE kind (surface_unused_signal) that NAMES a frozen symbol (corroboration) → forced T3.
    Prose is benign (no 'downgrade/overstate') so the containment corroboration-misread check does NOT
    fire — this isolates the frozen-symbol veto, not a contract drop."""
    return {
        "kind": "surface_unused_signal",
        "target": "L3 story",
        "finding": "the corroboration value is computed but never surfaced in the L3 story",
        "why": "a reader of the story cannot see the corroboration the island carries",
        "datum_refs": [f"l2b.{_FAM}.corroboration"],
    }


def _dropped_by_contract() -> dict:
    """A false-premise finding: it misreads corroboration as a strength measure and proposes to lower it.
    Containment DROPS it on the contract — it must NEVER reach the ledger or the tiers."""
    return {
        "kind": "divergence",
        "target": "L2b.tumor_presence_concordance",
        "finding": "downgrade the corroboration — it overstates a weakly-detected arm",
        "why": "the arm is weak so corroboration:high is too high",
        "datum_refs": [f"l2b.{_FAM}.corroboration"],
    }


def _llm_returning(findings: list[dict]):
    """An injected judge LLM that returns a fixed findings array (bare — parse_findings handles it)."""

    def _llm(system_prompt, user_prompt, tool_name, tool_schema, max_tokens=3000):
        return {"findings": [dict(f) for f in findings]}

    return _llm


# ── end-to-end wiring ────────────────────────────────────────────────────────────────────────────────
def test_iteration_wires_dev_ledger_tiers_and_held_out_convergence(tmp_path):
    run_dir = tmp_path / "iter-001-deadbeef"
    _write_package(run_dir, "CEACAM5", "COADREAD", "ceacam5")
    _write_package(run_dir, "EPCAM", "COADREAD", "epcam")
    _write_package(run_dir, "CEACAM5", "LUAD", "ceacam5")  # held-out (reuses the alive fixture)

    entries = [
        IT.Entry("CEACAM5", "COADREAD", stratum="pos", split="dev"),
        IT.Entry("EPCAM", "COADREAD", stratum="pos", split="dev"),
        IT.Entry("CEACAM5", "LUAD", stratum="pos", split="held_out"),
    ]
    llm = _llm_returning([_benign_t2(), _frozen_t3(), _dropped_by_contract()])

    report, ledger = IT.run_iteration("functional-requirement", entries, run_dir, llm=llm, teeth_green=False)

    # Only C1 is applicable to a non-tumor-presence skill (CALIB would false-NULL on control genes).
    assert report["applicable_probes"] == ["c1"]
    assert report["roster"] == {"n_total": 3, "n_dev": 2, "n_held_out": 1}

    # DEV: the dropped-by-contract finding never routes; the two survivors do (deduped across 2 packages).
    assert ledger.verify()["ok"] is True
    assert report["ledger"]["chain_ok"] is True
    assert report["ledger"]["n_entries"] == 2  # benign + frozen, deduped across CEACAM5 + EPCAM

    tiers = report["dev"]["tiers"]
    assert tiers["T1_land"] == 0  # STOP-A: teeth_green=False ⇒ nothing lands
    assert tiers["T2_propose"] >= 1  # the benign missing_relationship
    assert tiers["T3_adjudicate"] >= 1  # the frozen-symbol finding forced to adjudication
    assert report["report_only"] is True

    # the frozen-symbol finding is in T3 (route_many keys by the tier constants) with the symbol named
    t3 = report["dev"]["tier_report"]["T3_adjudicate"]
    assert any(f["_tier"]["frozen_symbol"] == "corroboration" for f in t3)


def test_dropped_finding_absent_from_ledger(tmp_path):
    run_dir = tmp_path / "iter-001-deadbeef"
    _write_package(run_dir, "CEACAM5", "COADREAD", "ceacam5")
    entries = [IT.Entry("CEACAM5", "COADREAD", split="dev")]
    llm = _llm_returning([_dropped_by_contract()])
    report, ledger = IT.run_iteration("functional-requirement", entries, run_dir, llm=llm)
    assert report["ledger"]["n_entries"] == 0
    assert report["dev"]["tiers"] == {"T1_land": 0, "T2_propose": 0, "T3_adjudicate": 0}
    # the drop is accounted for in the package's containment counts
    assert report["dev"]["packages"][0]["containment"]["n_dropped"] == 1


def test_missing_held_out_package_blocks_convergence(tmp_path):
    """NULL-block end-to-end: a held-out package with no emitted dir contributes ZERO findings but can
    NEVER read as clean — the judge is skipped and C1 is not_evaluable, so convergence blocks on it."""
    run_dir = tmp_path / "iter-001-deadbeef"
    _write_package(run_dir, "CEACAM5", "COADREAD", "ceacam5")  # alive dev
    # held-out "GHOST|X|" has NO _emit__ dir
    entries = [
        IT.Entry("CEACAM5", "COADREAD", split="dev"),
        IT.Entry("GHOST", "X", split="held_out"),
    ]
    report, _ = IT.run_iteration("functional-requirement", entries, run_dir, llm=_llm_returning([]))
    conv = report["held_out"]["convergence"]
    assert conv["converged"] is False
    held_pkg = report["held_out"]["packages"][0]
    assert held_pkg["assembled"] is False
    assert held_pkg["judge_skipped"]
    assert any("NULL" in r or "null" in r for r in conv["latest_block_reasons"])


def test_clean_silent_held_out_converges_with_hysteresis_1(tmp_path):
    """A single alive held-out package, a SILENT judge (no findings), and a clean C1 ⇒ this run converges;
    with hysteresis_n=1 the iteration declares convergence. Proves the happy path wires through."""
    run_dir = tmp_path / "iter-001-deadbeef"
    _write_package(run_dir, "CEACAM5", "LUAD", "ceacam5")
    entries = [IT.Entry("CEACAM5", "LUAD", split="held_out")]
    report, _ = IT.run_iteration("functional-requirement", entries, run_dir, llm=_llm_returning([]), hysteresis_n=1)
    conv = report["held_out"]["convergence"]
    assert conv["converged"] is True
    assert conv["consecutive_clean"] == 1


def test_teeth_green_true_allows_t1_for_additive_nonfrozen(tmp_path):
    """With teeth_green=True an ADDITIVE, non-frozen, T1-eligible finding may land at T1 — the one path
    that reaches T1, and only when the caller asserts the teeth are green."""
    run_dir = tmp_path / "iter-001-deadbeef"
    _write_package(run_dir, "CEACAM5", "COADREAD", "ceacam5")
    entries = [IT.Entry("CEACAM5", "COADREAD", split="dev")]
    additive = {
        "kind": "surface_unused_signal",
        "target": "L3 story",
        "finding": "the resolved source count is computed but not shown in the story",
        "why": "the island carries a count the story never surfaces",
        "datum_refs": [f"l2b.{_FAM}.resolved_source_count"],
    }
    report, _ = IT.run_iteration(
        "functional-requirement", entries, run_dir, llm=_llm_returning([additive]), teeth_green=True
    )
    assert report["dev"]["tiers"]["T1_land"] == 1
    assert report["report_only"] is False


def test_applicable_probes_tumor_presence_includes_calib():
    assert IT.applicable_probes("tumor-presence") == ("c1", "calib")
    assert IT.applicable_probes("functional-requirement") == ("c1",)
    assert IT.applicable_probes("on-target-safety-liability") == ("c1",)
