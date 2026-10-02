"""Scorecard shard guard (#1990) — the COMMITTED on-target-safety-liability shard stays honest.
Copies the tumor-presence exemplar's shape (#1988, `skills/tumor-presence/tests/test_scorecard_shard.py`).

The shard (`scorecard/on-target-safety-liability.json`) is a committed artifact built by
`scripts/scorecard_adapter.py`; A0a's drift guard checks schema + render staleness but deliberately
never interprets adapter-owned evidence. This module supplies the adapter-side guards the exemplar
promises siblings:

  1. every criterion the shard marks GREEN cites at least one test file that EXISTS in the tree —
     evidence naming a phantom test is a fabricated measurement;
  2. the L1 panel_consistency evidence carries the FULL 5-pair roster with computed checks, no
     placeholder residue — a partial or hand-typed panel cannot ship as GREEN;
  3. the panel checks have TEETH: fed a doctored panel (every target emitting one constant class),
     `collect_panel_rows` reds its own checks — the GREEN is a live function of the package bytes.
  4. the layer states are honest: L2a/L2b are BUILT (PR-1a of epic SK#2210 / #1507 built the exported
     source_properties / integrated_properties sections) but UNMEASURED — every criterion NULL with a
     reason, never promoted on the strength of the layer merely existing — while L3/L4 stay NOT_BUILT
     (safety emits no l3d, and there is no L4 layer here).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
REPO_ROOT = SKILLS_ROOT.parent

from _skills_common import component_scorecard as cs  # noqa: E402

SHARD_PATH = REPO_ROOT / cs.SCORECARD_DIRNAME / "on-target-safety-liability.json"


def _load_adapter():
    spec = importlib.util.spec_from_file_location(
        "t1990_scorecard_adapter_under_test", SKILL_DIR / "scripts" / "scorecard_adapter.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _shard_dict() -> dict:
    return json.loads(SHARD_PATH.read_text())


def test_roundtrip_deterministic_surface_equals_the_adapter_output(monkeypatch):
    """ROUND-TRIP TEETH on the DETERMINISTIC surface of the shard (#2435): the committed file must equal
    what `build_shard()` produces for every cell the adapter builds deterministically — the shared
    L2-seed factory output (L2a/L2b), the NOT_BUILT L3/L4, and the static L1 criteria
    (accuracy / utilization / fail_open) plus L1's built flag and notes. A drift between the adapter's
    data literal and the committed artifact (in either direction — a hand-edit, or an adapter change not
    re-materialised) reds here, which is what makes the committed JSON a live function of this code
    rather than a hand-typed fixture.

    The live L1 `panel_consistency` criterion (and its `status_as_of` date) is NON-DETERMINISTIC and
    credential-bound — it is regenerated faithfully with creds and guarded by the panel-specific tests
    below — so it is excluded from this byte comparison; `_load_package` is stubbed to absent so the
    comparison never fires the (slow, creds-needing) 5x live panel."""
    ad = _load_adapter()
    # Exclude the live panel from the round-trip: no creds in CI, and it is guarded separately below.
    monkeypatch.setattr(ad, "_load_package", lambda *a, **k: (None, None))
    built = ad.build_shard().to_dict()
    committed = _shard_dict()
    for layer in ("L2a", "L2b", "L3", "L4"):
        assert built["cells"][layer] == committed["cells"][layer], (
            f"{layer} has drifted between scorecard_adapter.build_shard() and the committed "
            "scorecard/on-target-safety-liability.json — re-run the adapter and re-render."
        )
    for key in ("built", "notes"):
        assert built["cells"]["L1"][key] == committed["cells"]["L1"][key], f"L1 {key} drifted from the adapter"
    for crit in ("accuracy", "utilization", "fail_open"):
        assert built["cells"]["L1"]["criteria"][crit] == committed["cells"]["L1"]["criteria"][crit], (
            f"L1/{crit} (a deterministic criterion) drifted between the adapter and the committed shard"
        )


def test_shard_validates_and_upper_layers_are_not_built():
    shard = cs.shard_from_dict(_shard_dict(), expected_skill="on-target-safety-liability")
    # PR-1a (epic SK#2210 / #1507) BUILT L2a/L2b for this skill, so NOT_BUILT would now be a false
    # statement about the artifact. They must be built=True AND fully NULL: building a layer is not
    # measuring it, and a criterion that goes GREEN because the layer exists is the fail-open promotion
    # the rollup refuses. Each NULL must say WHY, or the cell is an undated blank.
    for layer in ("L2a", "L2b"):
        cell = shard.cells[layer]
        assert cell.built is True, f"{layer} is exported by run.py::_evidence_sections — built must be True"
        assert cs.cell_rollup(cell) == cs.NULL, f"{layer} rolled up {cs.cell_rollup(cell)}, expected NULL (unmeasured)"
        for name in cs.CRITERIA:
            crit = cell.criteria[name]
            assert crit.status == cs.NULL, f"{layer}/{name} claims {crit.status} with no measurement built"
            assert (crit.evidence or {}).get("null_reason"), f"{layer}/{name} is NULL with no reason recorded"
    # Safety emits no l3d section and has no L4 layer — both remain architecture gaps by design.
    for layer in ("L3", "L4"):
        assert cs.cell_rollup(shard.cells[layer]) == cs.NOT_BUILT
    # L1: utilization/fail_open are always measured (never NULL); accuracy is deliberately NULL
    # (re-derivation is covered by #1792/#1793/#1794, not this issue). panel_consistency is measured
    # (GREEN/RED) once the whole roster is emitted, else an honest NULL with a disposition.
    l1 = shard.cells["L1"]
    assert l1.built is True
    assert l1.criteria["accuracy"].status == cs.NULL
    assert (l1.criteria["accuracy"].evidence or {}).get("reason")
    for c in ("utilization", "fail_open"):
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
    assert checked >= 4, f"suspiciously few citations checked ({checked}) — did the evidence shrink?"


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
        # Full roster emitted with reachable card data: every OK row cites its package source, and
        # the status is the computed verdict (GREEN iff all checks pass, else RED) — never withheld.
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
    constant_pkg = {"headline": {"safety_verdict": "tolerant_reduced_safety_risk"}}
    monkeypatch.setattr(ad, "_load_package", lambda t, i: (constant_pkg, "doctored://constant"))
    rows, checks = ad.collect_panel_rows()
    assert len(rows) == 5 and all(r["status"] == "OK" for r in rows)
    assert checks["safety_verdict_not_constant"] is False
    assert checks["all_pass"] is False


def test_teeth_a_partial_panel_cannot_pass(monkeypatch):
    ad = _load_adapter()
    monkeypatch.setattr(ad, "_load_package", lambda t, i: (None, None))
    rows, checks = ad.collect_panel_rows()
    assert all(r["status"] == "PACKAGE_MISSING" for r in rows)
    assert checks["all_roster_rows_present"] is False and checks["all_pass"] is False
