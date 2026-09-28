"""Hermetic tests for run_scorecard_panel — roster parsing, canonical path derivation, and the
offline inventory mode (#2000, A0b). No live target-profile run, no network, no AWS.

Runs via: pixi run pytest eval/tests/test_run_scorecard_panel.py -q   (from the home checkout).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_EVAL = Path(__file__).resolve().parents[1]
if str(_EVAL) not in sys.path:
    sys.path.insert(0, str(_EVAL))

import run_scorecard_panel as panel  # noqa: E402

_ROSTER_TARGETS = {"EPCAM", "KRAS", "ERBB2", "PLK1", "HTR1D"}


def test_parses_the_real_committed_roster():
    """Parses the actual eval/SCORECARD_PANEL_ROSTER.md (#1994) — the committed source of truth,
    not a copy — into exactly the 5 (target, indication) rows the roster decided."""
    rows = panel.parse_roster()
    assert len(rows) == 5
    targets = {r["target"] for r in rows}
    assert targets == _ROSTER_TARGETS


def test_parenthetical_alias_is_stripped_to_the_canonical_symbol():
    # The roster's ERBB2 row is written "**ERBB2 (HER2)**" — the alias is display-only.
    rows = panel.parse_roster()
    erbb2 = next(r for r in rows if r["target"] == "ERBB2")
    assert erbb2["raw_target"] == "**ERBB2 (HER2)**"
    assert erbb2["indication"] == "BRCA"


def test_plain_unbolded_row_parses_too():
    rows = panel.parse_roster()
    plk1 = next(r for r in rows if r["target"] == "PLK1")
    assert plk1["indication"] == "COADREAD"
    htr1d = next(r for r in rows if r["target"] == "HTR1D")
    assert htr1d["indication"] == "COADREAD"


def test_header_and_separator_rows_never_become_a_roster_entry(tmp_path):
    md = tmp_path / "roster.md"
    md.write_text(
        "# Roster doc\n\n"
        "## Roster (1 target)\n\n"
        "| target | indication | archetype | stresses |\n"
        "|---|---|---|---|\n"
        "| **EPCAM** | COADREAD | flagship | surface path |\n\n"
        "## Non-goals\n"
        "| this | should | not | parse |\n"
    )
    rows = panel.parse_roster(md)
    assert len(rows) == 1
    assert rows[0]["target"] == "EPCAM"
    assert rows[0]["indication"] == "COADREAD"


def test_canonical_target_strips_bold_and_alias():
    assert panel._canonical_target("**ERBB2 (HER2)**") == "ERBB2"
    assert panel._canonical_target("EPCAM") == "EPCAM"
    assert panel._canonical_target("**KRAS**") == "KRAS"


def test_dest_dir_is_deterministic_and_indication_lowercased(tmp_path):
    d1 = panel.dest_dir(tmp_path, "ERBB2", "BRCA")
    d2 = panel.dest_dir(tmp_path, "ERBB2", "BRCA")
    assert d1 == d2 == tmp_path / "ERBB2__brca"


def test_dest_dir_disambiguates_by_indication(tmp_path):
    # Same target symbol, two indications (not in this roster, but the harness must not collide).
    d_crc = panel.dest_dir(tmp_path, "KRAS", "COADREAD")
    d_luad = panel.dest_dir(tmp_path, "KRAS", "LUAD")
    assert d_crc != d_luad


def test_inventory_reports_missing_when_nothing_has_been_dumped(tmp_path):
    rows = [{"target": "EPCAM", "indication": "COADREAD", "raw_target": "EPCAM"}]
    inv = panel.inventory(rows, tmp_path)
    assert inv == [
        {
            "target": "EPCAM",
            "indication": "COADREAD",
            "dest": str(tmp_path / "EPCAM__coadread"),
            "manifest": False,
            "evidence_package": False,
            "n_subskill_packages": 0,
            "status": "MISSING",
        }
    ]


def test_inventory_reports_ok_and_counts_subskill_packages_when_dumped(tmp_path):
    rows = [{"target": "EPCAM", "indication": "COADREAD", "raw_target": "EPCAM"}]
    dest = panel.dest_dir(tmp_path, "EPCAM", "COADREAD")
    (dest / "subskills" / "expression").mkdir(parents=True)
    (dest / "subskills" / "expression" / "package.json").write_text("{}")
    (dest / "subskills" / "safety").mkdir(parents=True)
    (dest / "subskills" / "safety" / "package.json").write_text("{}")
    (dest / "MANIFEST.json").write_text("{}")
    (dest / "evidence_package.json").write_text("{}")

    inv = panel.inventory(rows, tmp_path)
    assert len(inv) == 1
    assert inv[0]["status"] == "OK"
    assert inv[0]["manifest"] is True
    assert inv[0]["evidence_package"] is True
    assert inv[0]["n_subskill_packages"] == 2


def test_a_partial_dump_missing_evidence_package_is_still_missing(tmp_path):
    """MANIFEST alone is not sufficient — evidence_package.json must also be present, else the
    adapter-facing contract (both artifacts) is only half-satisfied."""
    rows = [{"target": "EPCAM", "indication": "COADREAD", "raw_target": "EPCAM"}]
    dest = panel.dest_dir(tmp_path, "EPCAM", "COADREAD")
    dest.mkdir(parents=True)
    (dest / "MANIFEST.json").write_text("{}")
    inv = panel.inventory(rows, tmp_path)
    assert inv[0]["status"] == "MISSING"


def test_main_default_mode_is_offline_and_never_gates(tmp_path, monkeypatch, capsys):
    """Default (no --emit) mode never touches the network/AWS and always returns 0 — it is a
    reporting harness, not a gate (verdict-inert, per the plan's governing directive)."""
    monkeypatch.setattr(panel, "REPORT_PATH", tmp_path / "report.json")
    rc = panel.main(["--packages-dir", str(tmp_path / "pkgs")])
    assert rc == 0
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["n_roster_rows"] == 5
    assert report["emit_results"] is None
    assert report["all_dumped"] is False  # nothing was dumped in this tmp dir
    assert len(report["inventory"]) == 5


def test_main_reports_all_dumped_true_once_every_row_is_complete(tmp_path, monkeypatch):
    monkeypatch.setattr(panel, "REPORT_PATH", tmp_path / "report.json")
    pkg_dir = tmp_path / "pkgs"
    for row in panel.parse_roster():
        dest = panel.dest_dir(pkg_dir, row["target"], row["indication"])
        dest.mkdir(parents=True)
        (dest / "MANIFEST.json").write_text("{}")
        (dest / "evidence_package.json").write_text("{}")

    rc = panel.main(["--packages-dir", str(pkg_dir)])
    assert rc == 0
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["all_dumped"] is True
