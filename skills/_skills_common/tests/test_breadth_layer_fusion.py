"""Two-layer tumor_elevation_breadth fusion (skills-side, Slice-C follow-on).

_dispatch_tumor_elevation_breadth fuses the PROTEIN breadth reader (CPTAC, 10 cohorts) +
the RNA breadth reader (pan-cancer DESeq2, 27 indications) into one card summary, and
computes breadth_layer_concordance. surface_discordance: the two per-layer classes are
surfaced ALONGSIDE, never averaged.

These tests pin (with both method reads monkeypatched — no S3):
  - the concordance derivation over every {elevated | measured-negative | gap} combination;
  - the dispatcher merges both layers' fields without clobber + stamps concordance;
  - a coverage gap (data_unavailable) is NEVER read as a negative (single_layer / *_only),
    the honesty-spine invariant;
  - the RNA read degrading (raises) does not fail the card — protein breadth still returns.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR.parent))  # skills/ — _live_readers rehomed to _skills_common

from _skills_common import _live_readers as lr  # noqa: E402

# --- the pure concordance helper -----------------------------------------------------------


def test_concordance_both_elevated_is_concordant():
    assert lr._breadth_layer_concordance("broadly_tumor_elevated", "multi_tumor_elevated") == "concordant"
    assert lr._breadth_layer_concordance("single_tumor_elevated", "single_tumor_elevated") == "concordant"


def test_concordance_elevated_vs_measured_negative_is_discordant():
    assert lr._breadth_layer_concordance("broadly_tumor_elevated", "not_tumor_elevated") == "discordant"
    assert lr._breadth_layer_concordance("not_tumor_elevated", "multi_tumor_elevated") == "discordant"


def test_concordance_elevated_vs_gap_is_layer_only_not_a_negative():
    # protein elevated, RNA a COVERAGE GAP → protein_only (NOT discordant — gap isn't a negative)
    assert lr._breadth_layer_concordance("broadly_tumor_elevated", "data_unavailable") == "protein_only"
    assert lr._breadth_layer_concordance("multi_tumor_elevated", None) == "protein_only"
    # RNA elevated, protein a gap → rna_only (CPTAC's 10 cohorts vs RNA's 27)
    assert lr._breadth_layer_concordance("data_unavailable", "broadly_tumor_elevated") == "rna_only"


def test_concordance_both_gap_is_single_layer():
    assert lr._breadth_layer_concordance("data_unavailable", "data_unavailable") == "single_layer"
    assert lr._breadth_layer_concordance(None, None) == "single_layer"


def test_concordance_one_gap_one_measured_negative_is_single_layer():
    # only one layer had data, and it was a measured negative → concordance untested
    assert lr._breadth_layer_concordance("not_tumor_elevated", "data_unavailable") == "single_layer"
    assert lr._breadth_layer_concordance(None, "not_tumor_elevated") == "single_layer"


def test_concordance_both_measured_negative_is_concordant_not_elevated():
    # both layers MEASURED + both not_tumor_elevated: they agree the target is NOT elevated.
    # This is a MEASURED negative agreement — NOT `concordant` (reserved for "both elevated —
    # strongest breadth call"); a consumer must not read a non-elevated target as elevated.
    assert lr._breadth_layer_concordance("not_tumor_elevated", "not_tumor_elevated") == "concordant_not_elevated"


# --- the dispatcher fusion -----------------------------------------------------------------


def _patch_readers(monkeypatch, protein_ret, rna_ret=None, rna_raises=False):
    class _ProteinMod:
        @staticmethod
        def read_tumor_elevation_breadth(target):
            return protein_ret

    class _RnaMod:
        @staticmethod
        def read_rna_tumor_elevation_breadth(target):
            if rna_raises:
                raise RuntimeError("stacked product unreachable")
            return rna_ret

    def _fake_import(name):
        return _ProteinMod if name == "cptac_protein_deg" else _RnaMod

    monkeypatch.setattr(lr, "_import_method", _fake_import)


def test_dispatcher_merges_both_layers_and_stamps_concordance(monkeypatch):
    protein = {
        "tumor_elevation_breadth_class": "broadly_tumor_elevated",
        "n_cohorts_elevated": 5,
        "n_cohorts_tested": 8,
    }
    # RNA reader emits GENERIC field names (n_indications_*) — the dispatcher must namespace
    # them to the card's rna_-prefixed contract fields.
    rna = {
        "rna_tumor_elevation_breadth_class": "multi_tumor_elevated",
        "n_indications_elevated": 6,
        "n_indications_tested": 27,
        "fraction_elevated": 0.22,
        "most_elevated_indications": [{"indication": "LUAD"}],
    }
    _patch_readers(monkeypatch, protein, rna)
    out = lr._dispatch_tumor_elevation_breadth("EPCAM", "COADREAD")
    # protein PRIMARY class + n_cohorts_* preserved verbatim
    assert out["tumor_elevation_breadth_class"] == "broadly_tumor_elevated"
    assert out["n_cohorts_elevated"] == 5
    # rna_* block NAMESPACED to the card contract (generic reader names → rna_ prefix)
    assert out["rna_tumor_elevation_breadth_class"] == "multi_tumor_elevated"
    assert out["rna_n_indications_elevated"] == 6
    assert out["rna_n_indications_tested"] == 27
    assert out["rna_fraction_elevated"] == 0.22
    assert out["rna_most_elevated_indications"] == [{"indication": "LUAD"}]
    # the generic (un-prefixed) reader keys must NOT leak into the card summary
    assert "n_indications_elevated" not in out
    # concordance computed
    assert out["breadth_layer_concordance"] == "concordant"


def test_dispatcher_protein_only_when_rna_gap(monkeypatch):
    protein = {"tumor_elevation_breadth_class": "multi_tumor_elevated"}
    rna = {"rna_tumor_elevation_breadth_class": "data_unavailable"}
    _patch_readers(monkeypatch, protein, rna)
    out = lr._dispatch_tumor_elevation_breadth("X", None)
    assert out["breadth_layer_concordance"] == "protein_only"


def test_dispatcher_rna_read_failure_degrades_gracefully(monkeypatch):
    protein = {"tumor_elevation_breadth_class": "broadly_tumor_elevated"}
    _patch_readers(monkeypatch, protein, rna_raises=True)
    out = lr._dispatch_tumor_elevation_breadth("X", None)
    # card still returns; protein breadth intact; RNA is an honest data_unavailable envelope
    assert out["tumor_elevation_breadth_class"] == "broadly_tumor_elevated"
    assert out["rna_tumor_elevation_breadth_class"] == "data_unavailable"
    assert "_rna_read_error" in out
    assert out["breadth_layer_concordance"] == "protein_only"


def test_dispatcher_registered():
    assert lr.CARD_DISPATCHERS["tumor-elevation-breadth"] is lr._dispatch_tumor_elevation_breadth
