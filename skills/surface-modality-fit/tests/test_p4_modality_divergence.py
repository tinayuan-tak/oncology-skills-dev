"""Divergence test: ONE card, TWO modality gates, DIVERGENT modality reads.

A recurrent copy-number AMPLIFICATION reads adc-favorable
at the SURFACE modality gate (antigen density) AND SM-relevant at the genomic/intracellular gate — from
the SAME immutable copy-number-distribution card. One change added the surface-axis rule; a follow-up put the
card in surface-modality-fit's set. This test proves the divergence at the fired-rules layer (signal
matrix), NOT the verdict layer (the surface verdict still resolves off adc-tce-modality-fit.fit_class —
byte-stable). Reads the LIVE target-contracts rules; graceful-skips if not checked out alongside."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

SKILLS_DIR = Path(__file__).resolve().parents[2]
if str(SKILLS_DIR) not in sys.path:
    sys.path.insert(0, str(SKILLS_DIR))

_CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
)

from _skills_common import fired_rules  # noqa: E402


def _amplified_cn_card() -> dict:
    """A synthetic copy-number-distribution card output with a recurrent amplification."""
    return {
        "card_id": "copy-number-distribution",
        "summary": {"copy_number_class": "recurrently_amplified"},
    }


@pytest.mark.skipif(
    not (_CONTRACTS / "interpretation-rules").is_dir(), reason="target-contracts not checked out alongside"
)
def test_amplification_diverges_across_modality_gates():
    """The SAME amplified copy-number card fires adc/bite_tce/antibody `supportive` on the surface
    axis AND small_molecule/degrader on the intracellular axis — the divergence."""
    cards = [_amplified_cn_card()]

    surface = fired_rules(cards, axis="surface_intrinsic", card_id_filter=["copy-number-distribution"])
    intra = fired_rules(cards, axis="intracellular_intrinsic", card_id_filter=["copy-number-distribution"])

    # surface axis: the amplification rule fires adc-favorable signals
    surface_signals = {k: v for f in surface for k, v in (f.get("signals") or {}).items()}
    assert surface_signals.get("adc") == "supportive", surface_signals
    assert surface_signals.get("bite_tce") == "supportive", surface_signals
    assert surface_signals.get("antibody") == "supportive", surface_signals
    # and the surface axis must NOT be emitting the SM/degrader channels for this card
    assert "small_molecule" not in surface_signals

    # intracellular axis: the SAME card fires the SM/degrader driver read
    intra_signals = {k: v for f in intra for k, v in (f.get("signals") or {}).items()}
    assert "small_molecule" in intra_signals, intra_signals
    # and the intracellular axis must NOT be emitting surface channels
    assert "adc" not in intra_signals

    # THE divergence: the two gates read the same immutable card through different modality lenses
    assert set(surface_signals) & {"adc", "bite_tce", "antibody"}
    assert set(intra_signals) & {"small_molecule", "degrader"}


@pytest.mark.skipif(
    not (_CONTRACTS / "interpretation-rules").is_dir(), reason="target-contracts not checked out alongside"
)
def test_neutral_cn_does_not_emit_surface_supportive():
    """A copy-number-neutral card must NOT fire adc-supportive (no false antigen-density signal)."""
    cards = [{"card_id": "copy-number-distribution", "summary": {"copy_number_class": "broadly_neutral"}}]
    surface = fired_rules(cards, axis="surface_intrinsic", card_id_filter=["copy-number-distribution"])
    surface_signals = {k: v for f in surface for k, v in (f.get("signals") or {}).items()}
    # the neutral rule fires but emits neutral, not supportive
    assert surface_signals.get("adc") != "supportive", surface_signals
