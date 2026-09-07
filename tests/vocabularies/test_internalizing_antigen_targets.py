"""internalizing_antigen_targets.yaml — structural + curation-discipline lock (B1 Rank-2).

Curated known-ADC-antigen vocabulary supplying a measured-POSITIVE internalization signal for the
adc-tce-modality-fit dispatcher (upgrades ADC-precedent antigens from endocytosis_confidence
'unmeasured' → 'clinically_internalizing'). Positive-only: absence = unchanged 'unmeasured', never
'non-internalizing'. Pins structure + the canonical approved-ADC anchors + per-entry provenance.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[2]
VOCAB = REPO / "vocabularies" / "internalizing_antigen_targets.yaml"


@pytest.fixture(scope="module")
def vocab():
    return yaml.safe_load(VOCAB.read_text())


def test_version_and_curator(vocab):
    assert vocab.get("version")
    assert vocab.get("curator")


def test_entries_wellformed(vocab):
    entries = vocab.get("entries") or {}
    assert entries, "must declare internalizing-antigen entries"
    for sym, spec in entries.items():
        assert spec.get("adc_agents"), f"{sym} missing adc_agents (the clinical-precedent basis)"
        assert spec.get("clinical_stage"), f"{sym} missing clinical_stage"
        assert spec.get("internalization_note"), f"{sym} missing internalization_note"
        assert spec.get("primary_source_citation"), f"{sym} missing citation (curation discipline)"


def test_canonical_approved_adc_antigens_present(vocab):
    """The archetypal approved-ADC internalizing antigens must be anchors."""
    entries = set(vocab.get("entries") or {})
    # HER2 (T-DM1/T-DXd), TROP2 (saci-gov), NECTIN4 (enfortumab), FOLR1 (mirvetuximab)
    assert {"ERBB2", "TACSTD2", "NECTIN4", "FOLR1"}.issubset(entries)


def test_ceacam5_flags_gpi_topology_caveat(vocab):
    """CEACAM5 is GPI-anchored — its note must flag that topology may still gate it out
    (internalization-positive but not single-pass), so the vocab doesn't over-promise."""
    note = (vocab["entries"]["CEACAM5"]["internalization_note"]).lower()
    assert "gpi" in note


def test_dual_liability_antigens_are_cross_noted(vocab):
    """Antigens that are BOTH internalizing AND shed (MSLN, BCMA/TNFRSF17) should note the
    co-occurring shed-sink liability so the two axes aren't read in isolation."""
    for sym in ("MSLN", "TNFRSF17"):
        note = (vocab["entries"][sym]["internalization_note"]).lower()
        assert "shed" in note, f"{sym} should cross-note its shed-antigen liability"
