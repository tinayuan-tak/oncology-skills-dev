"""Step 2a — the machine export carries the field descriptor. The widened summary_stats.csv must not
break the pre-existing (field, value) contract, and the field_descriptors.json sidecar must describe
every field including the nested ones the flat CSV structurally cannot hold. Both come from ONE source
(field_descriptor.describe_summary), so a drift test is a same-source-agreement test.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from _skills_common.write_package import _SUMMARY_STATS_COLUMNS, write_card_tables

_CID = "pan-cancer-crispr-dependency-distribution"


def _cards():
    return [
        {
            "card_id": _CID,
            "summary": {
                "median_chronos": -1.18,  # effect, measured
                "q_value": 3.8e-16,  # significance
                "n_cell_lines_panel": 1538,  # n
                "dep_control_position_class": "selective",  # categorical
                "not_measured_here": None,  # measured=0
                "method_version": "0.1.0",  # envelope
                "novel_undeclared_field": 7,  # unclassified
                "_private": "hidden",  # underscore-filtered from the CSV entirely
                "enriched_lineages": [  # nested list-of-dict — the flat CSV cannot hold it
                    {"lineage": "COAD", "median_chronos": -1.4},
                    {"lineage": "PAAD", "median_chronos": -1.1},
                ],
            },
        }
    ]


def _write(tmp_path) -> Path:
    write_card_tables(tmp_path, _cards())
    return tmp_path


def _read_csv(tmp_path):
    rows = list(csv.reader((tmp_path / f"{_CID}_summary_stats.csv").open()))
    return rows[0], rows[1:]


def test_summary_stats_header_is_the_widened_column_set(tmp_path):
    header, _ = _read_csv(_write(tmp_path))
    assert header == _SUMMARY_STATS_COLUMNS


def test_preexisting_field_value_pairs_survive_unchanged(tmp_path):
    """The contract other consumers may rely on: the first two columns are still (field, value) with the
    same values as the pre-Step-2a `field,value` CSV. Only columns were added."""
    _, rows = _read_csv(_write(tmp_path))
    got = {r[0]: r[1] for r in rows}
    assert got["median_chronos"] == "-1.18"
    assert got["n_cell_lines_panel"] == "1538"
    assert got["not_measured_here"] == ""  # None still renders empty, as before
    assert got["method_version"] == "0.1.0"
    assert "_private" not in got  # underscore keys still excluded


def test_descriptor_columns_carry_role_units_significance_and_measured(tmp_path):
    _, rows = _read_csv(_write(tmp_path))
    by_field = {r[0]: dict(zip(_SUMMARY_STATS_COLUMNS, r)) for r in rows}
    eff = by_field["median_chronos"]
    assert eff["role"] == "effect" and eff["units"] == "CHRONOS"
    assert eff["direction"] == "lower_is_stronger" and eff["significance_field"] == "q_value"
    assert eff["measured"] == "1"
    assert by_field["q_value"]["role"] == "significance"
    assert by_field["n_cell_lines_panel"]["role"] == "n"
    assert by_field["dep_control_position_class"]["role"] == "categorical"
    assert by_field["method_version"]["role"] == "envelope"
    assert by_field["novel_undeclared_field"]["role"] == "unclassified"
    assert by_field["not_measured_here"]["measured"] == "0"  # a None reads as not measured


def test_sidecar_describes_every_field_including_the_nested_one(tmp_path):
    sc = json.loads((_write(tmp_path) / "field_descriptors.json").read_text())
    card = sc[_CID]
    # the nested strata array the flat CSV omits IS in the sidecar — the reason the sidecar is not redundant
    assert "enriched_lineages" in card
    assert card["enriched_lineages"]["role"] == "strata" and card["enriched_lineages"]["measured"] is True
    # and it carries the whole scalar tuple too
    assert card["median_chronos"]["significance_field"] == "q_value"
    assert card["median_chronos"]["units"] == "CHRONOS"


def test_csv_and_sidecar_agree_on_every_scalar(tmp_path):
    tp = _write(tmp_path)
    _, rows = _read_csv(tp)
    sc = json.loads((tp / "field_descriptors.json").read_text())[_CID]
    for r in rows:
        row = dict(zip(_SUMMARY_STATS_COLUMNS, r))
        assert sc[row["field"]]["role"] == row["role"]
        assert bool(sc[row["field"]]["measured"]) == bool(int(row["measured"]))


def test_export_is_deterministic(tmp_path):
    a = _write(tmp_path / "a")
    b = _write(tmp_path / "b")
    for name in (f"{_CID}_summary_stats.csv", "field_descriptors.json"):
        assert (a / name).read_bytes() == (b / name).read_bytes()
