"""Scorecard shard guard (#1988, A0c exemplar) — the COMMITTED tumor-presence shard stays honest.

The shard (`scorecard/tumor-presence.json`) is a committed artifact built by
`scripts/scorecard_adapter.py`; A0a's drift guard checks schema + render staleness but deliberately
never interprets adapter-owned evidence. This module supplies the adapter-side guards the exemplar
promises siblings:

  1. every criterion the shard marks GREEN cites at least one test file that EXISTS in the tree —
     evidence naming a phantom test is a fabricated measurement;
  2. the L1 panel_consistency evidence carries the FULL 5-pair roster with computed checks, no
     placeholder residue — a partial or hand-typed panel cannot ship as GREEN;
  3. the panel checks have TEETH: fed a doctored panel (every target emitting one constant class),
     `collect_panel_rows` reds its own checks — the GREEN is a live function of the package bytes.
  4. (#2071) the SAME three guards apply one layer up to `collect_envelope_rows` — the L2a/L2b/L3
     panel_consistency criteria computed over the --emit-envelope export's source_properties/
     integrated_properties/l3d shape across the 5-pair roster.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
REPO_ROOT = SKILLS_ROOT.parent

from _skills_common import component_scorecard as cs  # noqa: E402

SHARD_PATH = REPO_ROOT / cs.SCORECARD_DIRNAME / "tumor-presence.json"


def _load_adapter():
    spec = importlib.util.spec_from_file_location(
        "t1988_scorecard_adapter_under_test", SKILL_DIR / "scripts" / "scorecard_adapter.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _shard_dict() -> dict:
    return json.loads(SHARD_PATH.read_text())


def test_shard_validates_and_l4_is_not_built():
    shard = cs.shard_from_dict(_shard_dict(), expected_skill="tumor-presence")
    assert cs.cell_rollup(shard.cells["L4"]) == cs.NOT_BUILT
    # The exemplar measures every criterion it can on L1: accuracy/utilization/fail_open are always
    # measured (never NULL) — those have committed re-derivation/ledger/probe tests. panel_consistency
    # is measured (GREEN/RED) once the whole A0b roster is emitted, else an honest NULL — and a NULL
    # panel MUST carry a disposition note (never an empty NULL).
    l1 = shard.cells["L1"]
    assert l1.built is True
    for c in ("accuracy", "utilization", "fail_open"):
        assert l1.criteria[c].status != cs.NULL, f"L1/{c} must be measured, not NULL"
    pc = l1.criteria["panel_consistency"]
    if pc.status == cs.NULL:
        assert (pc.evidence or {}).get("null_reason"), "a NULL panel criterion must carry a disposition note"


def test_every_green_criterion_cites_an_existing_test_file():
    """Evidence naming a phantom test is a fabricated measurement — resolve every cited path."""
    data = _shard_dict()
    checked = 0
    for layer, cell in data["cells"].items():
        for name, crit in cell["criteria"].items():
            if crit["status"] != cs.GREEN:
                continue
            ev = crit["evidence"] or {}
            cited = [ev["test"]] if "test" in ev else list(ev.get("tests", []))
            if name == "panel_consistency":
                continue  # panel evidence is package rows + computed checks, not test citations
            assert cited, f"GREEN {layer}/{name} cites no test at all"
            for entry in cited:
                rel = entry.split("::")[0].split(" ")[0]
                assert (REPO_ROOT / rel).exists(), f"GREEN {layer}/{name} cites missing file {rel}"
                checked += 1
    assert checked >= 8, f"suspiciously few citations checked ({checked}) — did the evidence shrink?"


def test_panel_evidence_is_complete_computed_and_placeholder_free():
    crit = _shard_dict()["cells"]["L1"]["criteria"]["panel_consistency"]
    ev = crit["evidence"]
    status = crit["status"]
    rows = ev["rows"]
    # The evidence ALWAYS carries the full 5-pair roster — a pair whose package is not yet emitted is
    # present as a PACKAGE_MISSING row, never omitted (absence is said, not hidden).
    assert isinstance(rows, list) and len(rows) == 5, "panel evidence must carry the full 5-pair roster"
    assert {(r["target"], r["indication"]) for r in rows} == {
        ("EPCAM", "COADREAD"),
        ("KRAS", "COADREAD"),
        ("ERBB2", "BRCA"),
        ("PLK1", "COADREAD"),
        ("HTR1D", "COADREAD"),
    }
    assert "PLACEHOLDER" not in json.dumps(ev)
    checks = ev["checks"]
    ok_rows = [r for r in rows if r["status"] == "OK"]
    if len(ok_rows) == 5:
        # Full roster emitted: every OK row cites its package source, and the status is the computed
        # verdict (GREEN iff all checks pass, else RED) — never withheld.
        assert all(r["source"] for r in ok_rows)
        assert status in (cs.GREEN, cs.RED)
        assert (status == cs.GREEN) == bool(checks["all_pass"]), "panel status must equal its computed checks"
    else:
        # Partial roster: honest NULL with a disposition, and the checks cannot claim a pass.
        assert status == cs.NULL, "a partial panel must not carry a measured status"
        assert ev.get("null_reason") and ev.get("packages_missing")
        assert checks["all_pass"] is False


def test_teeth_a_constant_class_panel_reds_the_checks(monkeypatch):
    """Seed the failure the checks exist to catch: every roster target emitting ONE constant class
    (the single-flagship-overfit shape). `collect_panel_rows` must red its own checks — proving the
    committed GREEN is a live function of the package bytes, not a hand-typed verdict."""
    ad = _load_adapter()
    constant_pkg = {
        "cards": [
            {"card_id": "cellline-rna-distribution", "summary": {"expression_class": "broadly_high"}},
            {
                "card_id": "tumor-scrna-celltype-expression",
                "summary": {"sc_expression_class": "malignant_broadly_detected"},
            },
        ]
    }
    monkeypatch.setattr(ad, "_load_package", lambda t, i: (constant_pkg, "doctored://constant"))
    rows, checks = ad.collect_panel_rows()
    assert len(rows) == 5 and all(r["status"] == "OK" for r in rows)
    assert checks["cellline_class_not_constant"] is False
    assert checks["sc_class_not_constant"] is False
    assert checks["thin_coverage_control_degrades"] is False
    assert checks["all_pass"] is False


def test_teeth_a_partial_panel_cannot_pass(monkeypatch):
    ad = _load_adapter()
    monkeypatch.setattr(ad, "_load_package", lambda t, i: (None, None))
    rows, checks = ad.collect_panel_rows()
    assert all(r["status"] == "PACKAGE_MISSING" for r in rows)
    assert checks["all_roster_rows_present"] is False and checks["all_pass"] is False


# ── #2071: L2a/L2b/L3 panel_consistency (the --emit-envelope export shape, computed over the roster) ──


def test_envelope_panel_evidence_is_complete_computed_and_placeholder_free():
    """Mirrors test_panel_evidence_is_complete_computed_and_placeholder_free (L1) for the three
    envelope-shape criteria: the evidence always carries the full 5-pair roster, never omits an
    unavailable pair, and the shard status equals the computed checks."""
    data = _shard_dict()
    for layer in ("L2a", "L2b", "L3"):
        crit = data["cells"][layer]["criteria"]["panel_consistency"]
        ev = crit["evidence"]
        status = crit["status"]
        rows = ev["rows"]
        assert isinstance(rows, list) and len(rows) == 5, f"{layer} panel evidence must carry the full roster"
        assert {(r["target"], r["indication"]) for r in rows} == {
            ("EPCAM", "COADREAD"),
            ("KRAS", "COADREAD"),
            ("ERBB2", "BRCA"),
            ("PLK1", "COADREAD"),
            ("HTR1D", "COADREAD"),
        }
        assert "PLACEHOLDER" not in json.dumps(ev)
        checks = ev["checks"]
        ok_rows = [r for r in rows if r["status"] == "OK"]
        if len(ok_rows) == 5:
            assert all(r["source"] for r in ok_rows)
            assert status in (cs.GREEN, cs.RED)
            assert (status == cs.GREEN) == bool(checks["all_pass"]), (
                f"{layer} panel status must equal its computed checks"
            )
        else:
            assert status == cs.NULL, f"{layer}: a partial panel must not carry a measured status"
            assert ev.get("null_reason") and ev.get("packages_missing")
            assert checks["all_pass"] is False


def test_teeth_a_constant_envelope_panel_reds_the_checks(monkeypatch):
    """Seed the failure the envelope-shape checks exist to catch: every roster target's export
    reduces to the SAME shape (constant source_properties/integrated_properties keys, constant l3d
    chapter count, no HTR1D degrade). `collect_envelope_rows` must red all three layers' checks."""
    ad = _load_adapter()
    constant_env = {
        "source_properties": {"patient_tumor_abundance": {}, "tumor_normal_selectivity": {}},
        "integrated_properties": {"tumor_presence_concordance": {}},
        "l3d": {"chapters": [{}, {}, {}]},
    }
    monkeypatch.setattr(ad, "_load_envelope", lambda t, i: (constant_env, "doctored://constant"))
    rows, checks = ad.collect_envelope_rows()
    assert len(rows) == 5 and all(r["status"] == "OK" for r in rows)
    assert checks["source_properties_keys_not_constant"] is False
    assert checks["integrated_properties_keys_not_constant"] is False
    assert checks["l3d_presence_or_shape_not_constant"] is False
    assert checks["thin_coverage_control_narrower_source_properties"] is False
    assert checks["thin_coverage_control_narrower_integrated_properties"] is False
    assert checks["thin_coverage_control_narrower_l3d"] is False


def test_teeth_a_partial_envelope_panel_cannot_pass(monkeypatch):
    ad = _load_adapter()
    monkeypatch.setattr(ad, "_load_envelope", lambda t, i: (None, None))
    rows, checks = ad.collect_envelope_rows()
    assert all(r["status"] == "PACKAGE_MISSING" for r in rows)
    assert checks["all_roster_rows_present"] is False
