"""gen_summary_schemas: the corpus harvest is the REAL observed-type source.

The retired compose-dashboard stub fixtures collapsed real fields to {'type': ['null']}; the corpus of
emitted packages (`<corpus>/<target-indication>/evidence_package.json` → cards[].summary) carries the
actually-emitted values, so a field that ships an integer is typed `integer`, not `null`. These tests use
a fabricated temp corpus so they are deterministic and need no ~/dev checkout.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
import sys  # noqa: E402

sys.path.insert(0, str(REPO / "validators"))
import gen_summary_schemas as g  # noqa: E402


def _pkg(root: Path, name: str, cards: list) -> None:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "evidence_package.json").write_text(json.dumps({"cards": cards}))


def test_harvest_infers_real_types_not_null(tmp_path):
    _pkg(
        tmp_path,
        "KRAS-COADREAD",
        [
            {
                "card_id": "dep",
                "summary": {
                    "n_lines": 1538,  # integer
                    "median_chronos": -1.18,  # number
                    "dep_class": "selective",  # string
                    "_internal": 7,  # excluded (underscore)
                },
            }
        ],
    )
    obs = g._harvest_corpus(tmp_path)
    assert obs["dep"]["n_lines"] == {"integer"}
    assert obs["dep"]["median_chronos"] == {"number"}
    assert obs["dep"]["dep_class"] == {"string"}
    assert "_internal" not in obs["dep"]  # underscore keys are not the declared contract


def test_harvest_unions_across_packages(tmp_path):
    # measured (integer) on one target, unmeasured (null) on another → the honest union, not one type.
    _pkg(tmp_path, "A-IND", [{"card_id": "dep", "summary": {"n_lines": 100}}])
    _pkg(tmp_path, "B-IND", [{"card_id": "dep", "summary": {"n_lines": None}}])
    obs = g._harvest_corpus(tmp_path)
    assert obs["dep"]["n_lines"] == {"integer", "null"}


def test_truncated_package_contributes_nothing_not_a_crash(tmp_path):
    _pkg(tmp_path, "GOOD-IND", [{"card_id": "dep", "summary": {"n_lines": 5}}])
    bad = tmp_path / "BAD-IND"
    bad.mkdir()
    (bad / "evidence_package.json").write_text("{ this is not json")
    obs = g._harvest_corpus(tmp_path)  # must not raise
    assert obs["dep"]["n_lines"] == {"integer"}


def test_missing_corpus_dir_fails_loudly(tmp_path):
    with pytest.raises(SystemExit):
        g._harvest_corpus(tmp_path / "does-not-exist")
