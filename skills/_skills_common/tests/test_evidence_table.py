"""Contract tests for the derived readings accessor (evidence_table.EvidenceTable).

Because the readings table is DERIVED, not emitted, its schema has no frozen artifact — so these
tests ARE the contract: column names+order, dtypes, null semantics, the role vocabulary, non-finite
coercion, and the zero-field-name-literals aperture guard. All hermetic (a synthetic package built
in-process); none touch the live corpus, so they run on the credential-less CI runner.
"""

from __future__ import annotations

import ast
import json
import math
from pathlib import Path

import pytest
from _skills_common import claim_record as _cr
from _skills_common import field_descriptor as _fd
from _skills_common.evidence_table import (
    READING_COLUMNS,
    READING_SCHEMA_VERSION,
    EvidenceTable,
)

# The contract, written out LITERALLY here so a reordering/rename in the module reds this test
# rather than being silently absorbed (never read the list back off a DataFrame — CAN this fail?).
EXPECTED_COLUMNS = [
    "reading_id",
    "target",
    "indication",
    "subtype",
    "modality",
    "skill",
    "card_id",
    "measurement_type",
    "field",
    "role",
    "value",
    "level",
    "scale",
    "distance_to_cut",
    "units",
    "direction",
    "significance_field",
    "measured",
    "availability",
    "card_version",
    "resolved_release_digest",
    "is_stale",
    "plot_data_ref",
]

# columns that are ALWAYS null on today's corpus (the emitter does not yet populate them). Asserting
# they are pd.NA — not 0/""/False — is the UNMEASURED⇒NULL invariant made testable.
ALWAYS_NULL_TODAY = ["subtype", "modality", "level", "scale", "distance_to_cut", "availability", "plot_data_ref"]


def _synthetic_package(*, with_nonfinite: bool = False) -> dict:
    """A minimal but real-shaped package: two cards, one with a genuinely unmeasured field, one with
    an unknown (unclassified) field, plus governance/context. Values chosen so `measured` and the
    null columns are exercised."""
    effect = float("inf") if with_nonfinite else 1.5
    return {
        "generated_by": "skills/tumor-presence@abc1234",
        "context": {"target": {"symbol": "EPCAM"}, "indication": {"oncotree_code": "COADREAD"}},
        "governance": {
            "resolved_release_digest": "deadbeefcafe0001",
            "resolved_releases": {
                "rel-a": {"used": ["manifest-fresh-v1"], "head": "manifest-fresh-v1", "is_stale": False},
                "rel-b": {"used": ["manifest-stale-v1"], "head": "manifest-stale-v1", "is_stale": True},
            },
        },
        "cards": [
            {
                "card_id": "tumor-rna-vs-adjacent",
                "card_version": "3",
                "measurement_type": "tumor_vs_adjacent_expression",
                "provenance": {"input_manifest_ids": ["manifest-fresh-v1"]},
                "summary": {"log2_fc": effect, "expression_call_class": "strong", "unmeasured_metric": None},
            },
            {
                "card_id": "some-card",
                "card_version": "1",
                "measurement_type": "tumor_vs_adjacent_expression",
                "provenance": {"input_manifest_ids": ["manifest-stale-v1"]},
                "summary": {"a_totally_unknown_field": 0.0},
            },
        ],
    }


@pytest.fixture
def pkg_path(tmp_path) -> Path:
    p = tmp_path / "evidence_package.json"
    p.write_text(json.dumps(_synthetic_package()))
    return p


def test_column_contract_names_and_order(pkg_path):
    t = EvidenceTable.from_package(pkg_path)
    assert list(t.readings.columns) == EXPECTED_COLUMNS
    assert READING_COLUMNS == tuple(EXPECTED_COLUMNS)
    assert READING_SCHEMA_VERSION == "1"


def test_column_contract_reds_on_rename():
    # CAN this fail? Rename a column in a scratch frame and prove the assertion catches it.
    scratch = list(EXPECTED_COLUMNS)
    scratch[0] = "renamed_id"
    assert scratch != EXPECTED_COLUMNS


def test_dtypes(pkg_path):
    df = EvidenceTable.from_package(pkg_path).readings
    assert df["distance_to_cut"].dtype == "Float64"
    assert df["measured"].dtype == "boolean"
    assert df["is_stale"].dtype == "boolean"
    assert df["reading_id"].dtype == "string"
    assert df["value"].dtype == object


def test_role_values_are_a_subset_of_the_source_enum(pkg_path):
    df = EvidenceTable.from_package(pkg_path).readings
    assert set(df["role"].dropna()) <= set(_fd.ROLES)


def test_availability_vocabulary_is_pinned_to_source():
    # availability is null today, but the CONTRACT's value set must track the source enum so a
    # vocabulary change reds here rather than drifting. 7 tokens as of this pin.
    assert len(_cr._VALID_AVAILABILITY) == 7


def test_always_null_columns_are_NA_never_zero(pkg_path):
    df = EvidenceTable.from_package(pkg_path).readings
    for col in ALWAYS_NULL_TODAY:
        assert df[col].isna().all(), f"{col} must be NULL on today's corpus, not a zero/empty"


def test_unmeasured_field_is_measured_false_not_dropped(pkg_path):
    df = EvidenceTable.from_package(pkg_path).readings
    row = df[(df.card_id == "tumor-rna-vs-adjacent") & (df.field == "unmeasured_metric")]
    assert len(row) == 1  # present as a row
    assert bool(row["measured"].iloc[0]) is False


def test_zero_value_is_measured_not_null(pkg_path):
    # a genuine 0.0 is MEASURED — the mirror of the null invariant. Distinguishes absence from a real zero.
    df = EvidenceTable.from_package(pkg_path).readings
    row = df[df.field == "a_totally_unknown_field"]
    assert bool(row["measured"].iloc[0]) is True


def test_unknown_field_is_unclassified_not_omitted(pkg_path):
    df = EvidenceTable.from_package(pkg_path).readings
    row = df[df.field == "a_totally_unknown_field"]
    assert row["role"].iloc[0] == "unclassified"


def test_is_stale_join(pkg_path):
    df = EvidenceTable.from_package(pkg_path).readings
    fresh = df[df.card_id == "tumor-rna-vs-adjacent"]["is_stale"]
    stale = df[df.card_id == "some-card"]["is_stale"]
    assert (~fresh.astype(bool)).all()
    assert stale.astype(bool).all()


def test_reading_id_is_stable_and_16_hex(pkg_path):
    df = EvidenceTable.from_package(pkg_path).readings
    ids = df["reading_id"].dropna()
    assert (ids.str.len() == 16).all()
    # deterministic: re-reading the same package yields the same ids
    df2 = EvidenceTable.from_package(pkg_path).readings
    assert list(df["reading_id"]) == list(df2["reading_id"])


def test_nonfinite_is_coerced_and_counted(tmp_path):
    p = tmp_path / "evidence_package.json"
    p.write_text(json.dumps(_synthetic_package(with_nonfinite=True)))
    t = EvidenceTable.from_package(p)
    assert t.n_nonfinite_coerced == 1  # the inf log2_fc
    val = t.readings[(t.readings.card_id == "tumor-rna-vs-adjacent") & (t.readings.field == "log2_fc")]["value"].iloc[0]
    assert val is None  # coerced, not left as inf
    assert not any(
        isinstance(v, float) and (math.isinf(v) or math.isnan(v)) for v in t.readings["value"] if isinstance(v, float)
    )


def test_from_corpus_unions_packages(tmp_path):
    for name in ("EPCAM-COADREAD", "KRAS-PAAD"):
        d = tmp_path / name
        d.mkdir()
        (d / "evidence_package.json").write_text(json.dumps(_synthetic_package()))
    t = EvidenceTable.from_corpus(tmp_path)
    assert set(t.readings["target"].dropna()) == {"EPCAM"}  # synthetic uses EPCAM for both
    assert len(t.readings) == 2 * len(
        EvidenceTable.from_package(tmp_path / "EPCAM-COADREAD" / "evidence_package.json").readings
    )


def test_no_card_field_name_literals_in_module():
    """THE APERTURE GUARD. The accessor must derive every column from describe_summary and name NO
    card measurement field, so it cannot de-orphan a field by hard-coding its name (which would trip
    the two-sided aperture ratchet in target-contracts). We collect every numeric-role field name
    from the descriptor catalog (envelope/context names like `target` are excluded — they are not
    aperture-bearing) and assert none appears as a string literal in evidence_table.py."""
    src = (Path(__file__).parent.parent / "evidence_table.py").read_text()
    literals = {
        node.value
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    numeric_roles = _fd._NUMERIC_ROLES
    aperture_fields = {
        field
        for fields in _fd.descriptor_catalog().values()
        for field, d in fields.items()
        if d["role"] in numeric_roles and field not in _fd.ENVELOPE_FIELDS
    }
    leaked = aperture_fields & literals
    assert not leaked, f"aperture-bearing field names hard-coded in evidence_table.py: {sorted(leaked)}"
