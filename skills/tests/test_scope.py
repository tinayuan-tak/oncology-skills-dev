"""Phase 5 Scope contract tests.

Verifies the 5-mode invocation contract from
target-contracts/docs/design/IDAS_SUBTYPE_PIPELINE.md and the
resolve_bucket helper's strategic-bucket → indication-list resolution.
"""

import sys
from pathlib import Path

import pytest

# Ensure _skills_common is importable
SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.scope import (
    Scope, ScopeError, resolve_bucket, parse_cli_scope,
)


# ---------- Mode derivation --------------------------------------------------

def test_target_only_mode():
    """No fields → target_only mode."""
    s = Scope()
    assert s.mode == "target_only"
    assert s.resolved_indications() == []


def test_indication_mode():
    """Single indication → indication mode."""
    s = Scope(indication="COADREAD")
    assert s.mode == "indication"
    assert s.resolved_indications() == ["COADREAD"]


def test_multi_indication_mode():
    """Indications list → multi_indication mode."""
    s = Scope(indications=["NSCLC", "SCLC", "HNSC"])
    assert s.mode == "multi_indication"
    assert s.resolved_indications() == ["NSCLC", "SCLC", "HNSC"]


def test_indication_subtype_mode():
    """indication + subtypes → indication_subtype mode."""
    s = Scope(indication="COADREAD", subtypes=["MSI_H", "MSS"])
    assert s.mode == "indication_subtype"


def test_multi_indication_subtype_mode():
    """indications + subtypes → multi_indication_subtype mode."""
    s = Scope(indications=["STAD", "ESCA"], subtypes=["HER2_amp"])
    assert s.mode == "multi_indication_subtype"


# ---------- Validation -------------------------------------------------------

def test_indication_and_indications_mutually_exclusive():
    """Both singular + plural → ScopeError."""
    with pytest.raises(ScopeError, match="mutually exclusive"):
        Scope(indication="COADREAD", indications=["NSCLC"])


def test_subtypes_require_indication():
    """subtypes without indication/indications → ScopeError."""
    with pytest.raises(ScopeError, match="require either indication"):
        Scope(subtypes=["MSI_H"])


def test_invalid_indication_rejected():
    """Unknown iDAS canonical code → ScopeError."""
    with pytest.raises(ScopeError, match="Unknown iDAS"):
        Scope(indication="INVALID_INDICATION")


def test_valid_all_9_iDAS_codes_accepted():
    """All 9 iDAS codes from indication_crosswalk.yaml accept."""
    for code in ["COADREAD", "NSCLC", "SCLC", "HNSC", "STAD", "ESCA", "PAAD", "AML", "CML"]:
        s = Scope(indication=code)
        assert s.mode == "indication"


# ---------- Strategic buckets ------------------------------------------------

def test_resolve_bucket_thoracic():
    """resolve_bucket('Thoracic') → NSCLC + SCLC + HNSC."""
    s = resolve_bucket("Thoracic")
    assert s.mode == "multi_indication"
    assert set(s.indications) == {"NSCLC", "SCLC", "HNSC"}


def test_resolve_bucket_gi_upper():
    """resolve_bucket('GI-upper') → STAD + ESCA + PAAD."""
    s = resolve_bucket("GI-upper")
    assert set(s.indications) == {"STAD", "ESCA", "PAAD"}


def test_resolve_bucket_gi_lower():
    """resolve_bucket('GI-lower') → COADREAD (singleton bucket)."""
    s = resolve_bucket("GI-lower")
    assert s.indications == ["COADREAD"]


def test_resolve_bucket_heme():
    """resolve_bucket('Heme') → AML + CML."""
    s = resolve_bucket("Heme")
    assert set(s.indications) == {"AML", "CML"}


def test_resolve_bucket_invalid():
    """Unknown bucket_id → ScopeError."""
    with pytest.raises(ScopeError, match="Unknown strategic bucket"):
        resolve_bucket("InventedBucket")


# ---------- parse_cli_scope --------------------------------------------------

def test_parse_cli_backward_compat_indication_only():
    """--indication COADREAD → Scope(indication="COADREAD")."""
    s = parse_cli_scope(indication="COADREAD")
    assert s.mode == "indication"
    assert s.indication == "COADREAD"


def test_parse_cli_indications_list():
    """--indications COADREAD,NSCLC → Scope with 2 indications."""
    s = parse_cli_scope(indications="COADREAD,NSCLC")
    assert s.mode == "multi_indication"
    assert set(s.indications) == {"COADREAD", "NSCLC"}


def test_parse_cli_strategic_bucket():
    """--strategic-bucket Thoracic → resolves to Scope(indications=[NSCLC,SCLC,HNSC])."""
    s = parse_cli_scope(strategic_bucket="Thoracic")
    assert s.mode == "multi_indication"
    assert set(s.indications) == {"NSCLC", "SCLC", "HNSC"}


def test_parse_cli_bucket_plus_subgroups():
    """--strategic-bucket Thoracic --subgroups TMB_high → resolves to Scope(indications=[Thoracic 3], subtypes=[TMB_high])."""
    s = parse_cli_scope(strategic_bucket="Thoracic", subgroups="TMB_high")
    assert s.mode == "multi_indication_subtype"
    assert set(s.indications) == {"NSCLC", "SCLC", "HNSC"}
    assert s.subtypes == ["TMB_high"]


def test_parse_cli_bucket_conflicts_with_indication():
    """--strategic-bucket + --indication → ScopeError (mutually exclusive)."""
    with pytest.raises(ScopeError, match="mutually exclusive"):
        parse_cli_scope(strategic_bucket="Thoracic", indication="COADREAD")


def test_parse_cli_subgroups_only_target_only():
    """--subgroups without indication → ScopeError (subtypes require indication)."""
    with pytest.raises(ScopeError, match="require either indication"):
        parse_cli_scope(subgroups="MSI_H")


def test_parse_cli_indication_plus_subgroups():
    """Common Phase-5 CLI pattern: single indication + subgroups list."""
    s = parse_cli_scope(indication="COADREAD", subgroups="MSI_H,MSS")
    assert s.mode == "indication_subtype"
    assert s.indication == "COADREAD"
    assert s.subtypes == ["MSI_H", "MSS"]


def test_parse_cli_target_only():
    """No scope args → target_only mode."""
    s = parse_cli_scope()
    assert s.mode == "target_only"
