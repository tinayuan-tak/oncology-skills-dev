"""Presence gate for the L2b `abundance_concordance` ISLAND (SK#2019, umbrella #1740, epic #1938).

Mutation teeth for the design call: the abundance island (RNA transcript x mass-spec protein) is
tumor-grain-preferred but FALLS BACK to the cell-line grain when the tumor arm is unavailable. On a
target measured-ABSENT in the tumor (CD19/COADREAD-style: claim A absent, malignant fraction 0.00, IHC
not_detected) that fallback surfaced an `rna_high_protein_low` cell-line split and its ADC/degrader
PAYLOAD-delivery caveat — a modality/payload narrative for an antigen not in the tumor at all.

The fix gates the island on the SAME per-modality-matrix presence predicate that PR-A (#1999 /
afbdb3c4) used for `_abundance_floor` — `_any_modality_presence_positive` — so the two abundance islands
are gated consistently. When NOT presence-positive the island is SUPPRESSED (key dropped), mirroring
`_abundance_floor`'s `return None` and the island's own byte-stable `single_modality_only` key-omission.

Unit-tested on the pure gate helper `_gate_abundance_concordance_on_presence` (it never touches the
collapsed spine — presence_verdict / presence_verdict_by_modality / resolver goldens stay byte-stable).
Disjoint by design from #2020's end-to-end CD19 replay fixture (skills/tumor-presence/tests/fixtures/).
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parent.parent, "tp_run_abundance_gate")

# The exact ADC/degrader payload caveat the island emits on an `rna_high_protein_low` split — the
# misleading narrative this gate withholds from a measured-absent antigen.
_ADC_PAYLOAD_PHRASE = "ADC/degrader payload delivery"


def _ladder_bucket(verdict, rule_id="tumor-expression-broadly-high-supportive"):
    """A per-modality MATRIX with ONE ladder bucket (driving_rule_id set) at `verdict` — the shape the
    gate reads (comparator / measured-unruled buckets fire no ladder rung and are excluded)."""
    return {
        "bulk_rna/tumor": {
            "measurement": "bulk_rna",
            "sample_context": "tumor",
            "verdict": verdict,
            "driving_rule_id": rule_id,
            "evidence_state": "measured",
        }
    }


def _abundance_island_rna_high_protein_low():
    """A minimal `abundance_concordance` island in the `rna_high_protein_low` class carrying the
    ADC/degrader payload caveat — the exact directional-split narrative CD19 fell back to on cell-line."""
    return {
        "concordance_class": "rna_high_protein_low",
        "corroboration": "single_arm",
        "grain": "cell_line",
        "qualifying_signal": {
            "statement": (
                "MS-protein abundance ranks BELOW RNA (cell_line grain) — a post-transcriptional "
                "attenuation / low proxy-quality signal, tempering RNA-based abundance expectations "
                f"for abundance-dependent modalities ({_ADC_PAYLOAD_PHRASE})."
            ),
            "source": "ms_protein_abundance",
            "provenance_ref": "ms_protein_abundance",
        },
    }


def _claim_vector_with_island():
    return {
        "A": {"signal": "absent"},
        "abundance_concordance": _abundance_island_rna_high_protein_low(),
    }


# ── MUTATION TEETH: the over-surfacing must be suppressed on a measured-absent antigen ────────────
def test_island_suppressed_on_measured_negative_target():
    """CD19-style measured-ABSENT (bulk-RNA ladder bucket a MEASURED negative): the gate DROPS the
    abundance_concordance island, so the ADC/degrader payload caveat is NOT surfaced. RED before the gate
    (the island — and its payload narrative — surfaced unconditionally on the cell-line fallback)."""
    per_modality = _ladder_bucket("broadly_low_expression")  # measured-negative
    assert tp._any_modality_presence_positive(per_modality) is False  # precondition: measured-absent
    cv = _claim_vector_with_island()
    # sanity: the caveat we are guarding against is actually present pre-gate
    assert _ADC_PAYLOAD_PHRASE in cv["abundance_concordance"]["qualifying_signal"]["statement"]

    tp._gate_abundance_concordance_on_presence(cv, per_modality)

    assert "abundance_concordance" not in cv  # island (and its payload caveat) suppressed
    # the ADC/degrader payload narrative appears NOWHERE in the gated vector
    assert _ADC_PAYLOAD_PHRASE not in repr(cv)


def test_island_suppressed_on_coverage_gap_and_empty_matrix():
    """A coverage GAP (data_unavailable) and an empty matrix are BOTH non-positive → island suppressed
    (nothing measured the antigen present, so no abundance/payload narrative should ride)."""
    for per_modality in (_ladder_bucket("data_unavailable"), {}, None):
        cv = _claim_vector_with_island()
        tp._gate_abundance_concordance_on_presence(cv, per_modality)
        assert "abundance_concordance" not in cv


# ── BYTE-STABILITY: a presence-positive target is untouched ───────────────────────────────────────
def test_island_retained_byte_identical_on_presence_positive_target():
    """A presence-positive target (a positive ladder rung fired) keeps the island EXACTLY — the gate must
    be byte-stable for every legitimately-present antigen (EPCAM/ERBB2 and every flagship)."""
    per_modality = _ladder_bucket("tumor_broadly_expressed")  # measured-positive
    assert tp._any_modality_presence_positive(per_modality) is True
    cv = _claim_vector_with_island()
    expected = _abundance_island_rna_high_protein_low()

    tp._gate_abundance_concordance_on_presence(cv, per_modality)

    assert cv["abundance_concordance"] == expected  # retained, unchanged
    assert _ADC_PAYLOAD_PHRASE in cv["abundance_concordance"]["qualifying_signal"]["statement"]


def test_gate_noop_when_island_absent():
    """When the island never resolved (single_modality_only → key already omitted), the gate is a no-op
    regardless of presence — it must not synthesize a key or crash."""
    for per_modality in (_ladder_bucket("broadly_low_expression"), _ladder_bucket("tumor_broadly_expressed")):
        cv = {"A": {"signal": "absent"}}
        tp._gate_abundance_concordance_on_presence(cv, per_modality)
        assert cv == {"A": {"signal": "absent"}}


def test_gate_consistent_with_abundance_floor_predicate():
    """The island gate reuses the SAME predicate as the sibling _abundance_floor gate (PR-A #1999) — so
    the two abundance islands suppress on exactly the same measured-absent set. Pin the shared basis."""
    for verdict in ("broadly_low_expression", "data_unavailable"):
        pm = _ladder_bucket(verdict)
        floor_suppressed = tp._abundance_floor([], pm) == (None, [])
        cv = _claim_vector_with_island()
        tp._gate_abundance_concordance_on_presence(cv, pm)
        island_suppressed = "abundance_concordance" not in cv
        assert floor_suppressed and island_suppressed, verdict
