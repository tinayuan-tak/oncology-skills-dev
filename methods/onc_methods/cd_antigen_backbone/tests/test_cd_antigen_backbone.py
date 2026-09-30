"""Tests for the CD/IO-antigen-backbone clinical-precedent signal (E6-CD). Pure — synthetic roster.

Pins: (1) established_io_backbone (CD19 — approved-precedent set); (2) cd_antigen (on roster, not in
the curated approved set); (3) NON-CD-NAMED backbone antigen resolves (PDCD1=CD279 — the family-label
path misses these); (4) not_cd_antigen is NOT a negative (CEACAM5 — a real ADC target that's not a CD
molecule); (5) uniprot/ensembl fallback keys; (6) unreadable roster → data_unavailable (distinct from
not_cd_antigen)."""

from __future__ import annotations

import json

from onc_methods.cd_antigen_backbone import classify as c
from onc_methods.cd_antigen_backbone import read as r


def _roster():
    # UPPER(symbol) -> record, as read._load_roster builds it
    recs = {
        "CD19": {
            "symbol": "CD19",
            "cd": "CD19",
            "uniprot_ids": ["P15391"],
            "ensembl_gene_id": "ENSG00000177455",
            "gene_group": ["CD molecules"],
        },
        "MS4A1": {"symbol": "MS4A1", "cd": "CD20", "uniprot_ids": ["P11836"], "gene_group": ["CD molecules"]},
        "PDCD1": {"symbol": "PDCD1", "cd": "CD279", "uniprot_ids": ["Q15116"], "gene_group": ["CD molecules"]},
        "CD70": {"symbol": "CD70", "cd": "CD70", "uniprot_ids": ["P32970"], "gene_group": ["CD molecules"]},
    }
    d = dict(recs)
    for rec in recs.values():
        for u in rec.get("uniprot_ids", []):
            d.setdefault(u.upper(), rec)
        if rec.get("ensembl_gene_id"):
            d.setdefault(rec["ensembl_gene_id"].upper(), rec)
    return d


def test_established_io_backbone():
    out = c.classify_cd_backbone("CD19", _roster())
    assert out["cd_antigen_backbone_class"] == "established_io_backbone"
    assert out["established_io_precedent"] is True
    assert out["on_cd_roster"] is True
    assert out["cd_number"] == "CD19"


def test_ms4a1_is_cd20_established():
    # a non-"CD"-named symbol (MS4A1) that IS the approved CD20 backbone
    out = c.classify_cd_backbone("MS4A1", _roster())
    assert out["cd_antigen_backbone_class"] == "established_io_backbone"
    assert out["cd_number"] == "CD20"


def test_non_cd_named_checkpoint_resolves_on_roster():
    # PDCD1 (=CD279) has no "CD" in its symbol — a family-label match misses it; the roster catches it
    out = c.classify_cd_backbone("PDCD1", _roster())
    assert out["on_cd_roster"] is True
    assert out["cd_number"] == "CD279"
    # not in the curated approved-precedent set → cd_antigen (still a backbone prior)
    assert out["cd_antigen_backbone_class"] == "cd_antigen"


def test_on_roster_but_not_approved_is_cd_antigen():
    out = c.classify_cd_backbone("CD70", _roster())  # CD70: clinical but not in the conservative approved set
    assert out["cd_antigen_backbone_class"] == "cd_antigen"


def test_not_cd_antigen_is_not_a_negative():
    # CEACAM5 — a real ADC target, NOT a CD molecule. Absence of CD-backbone prior, not a negative.
    out = c.classify_cd_backbone("CEACAM5", _roster())
    assert out["cd_antigen_backbone_class"] == "not_cd_antigen"
    assert out["on_cd_roster"] is False
    assert out["established_io_precedent"] is False


def test_uniprot_fallback_key(tmp_path):
    # a target supplied as a UniProt AC still resolves via the secondary key
    out = c.classify_cd_backbone("P15391", _roster())
    assert out["on_cd_roster"] is True
    assert out["cd_number"] == "CD19"


def test_read_from_local_members_json(tmp_path):
    # end-to-end read path with a local members.json (bare-list container)
    members = [
        {
            "symbol": "CD19",
            "cd": "CD19",
            "uniprot_ids": ["P15391"],
            "ensembl_gene_id": "ENSG00000177455",
            "gene_group": ["CD molecules"],
        },
        {"symbol": "PDCD1", "cd": "CD279", "uniprot_ids": ["Q15116"], "gene_group": ["CD molecules"]},
    ]
    p = tmp_path / "members.json"
    p.write_text(json.dumps(members))
    r._load_roster.cache_clear()
    out = r.read_cd_antigen_backbone("CD19", members_path=str(p))
    assert out["cd_antigen_backbone_class"] == "established_io_backbone"
    assert out["_data_source"] == r.SOURCE_MANIFEST_ID
    r._load_roster.cache_clear()


def test_unreadable_roster_is_data_unavailable():
    r._load_roster.cache_clear()
    out = r.read_cd_antigen_backbone("CD19", members_path="/nonexistent/members.json")
    assert out["cd_antigen_backbone_class"] == "data_unavailable"
    assert out["_live_read_error"] == "cd_antigen_roster_read_failed"
    r._load_roster.cache_clear()


def test_contract_fields_present():
    out = c.classify_cd_backbone("CD19", _roster())
    for f in (
        "cd_antigen_backbone_class",
        "on_cd_roster",
        "cd_number",
        "cd_roster_uniprot",
        "cd_gene_groups",
        "established_io_precedent",
        "method_version",
    ):
        assert f in out
