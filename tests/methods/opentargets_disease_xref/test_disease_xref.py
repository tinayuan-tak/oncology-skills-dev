"""Hermetic tests for opentargets_disease_xref._extract_mesh (pure; no S3)."""

from __future__ import annotations
import sys
from pathlib import Path

AM = Path(__file__).resolve().parents[3]
if str(AM) not in sys.path:
    sys.path.insert(0, str(AM))

from methods.opentargets_disease_xref.read import _extract_mesh  # noqa: E402


def test_extracts_mesh_and_msh_prefixes():
    xrefs = ["DOID:5672", "MESH:D015179", "UMLS:C0346629", "MSH:D001943", "NCIT:C4978"]
    assert _extract_mesh(xrefs) == ["MESH:D015179", "MESH:D001943"]


def test_ignores_non_mesh_and_empty():
    assert _extract_mesh([]) == []
    assert _extract_mesh(None) == []
    assert _extract_mesh(["Orphanet:466667", "SCTID:363510005"]) == []


def test_no_colon_tokens_skipped():
    assert _extract_mesh(["MESH", "garbage", "MESH:D009369"]) == ["MESH:D009369"]
