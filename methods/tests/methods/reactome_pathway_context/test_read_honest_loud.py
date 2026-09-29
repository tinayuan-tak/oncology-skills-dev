"""#822: the Reactome reader's compute body caught *all* exceptions and returned a benign
``data_unavailable`` result. Same anti-pattern as the SIGNOR lane (lower stakes: pathway-context
annotation, not verdict-driving). Narrow the catch to genuine absence so a transient fault
re-raises (fail-loud).

  1. a genuine NoSuchKey / FileNotFoundError still yields ``data_unavailable`` — no raise.
  2. a simulated transient error RE-RAISES.
(A target genuinely not resolvable / not in Reactome is handled by the dedicated _empty_result
branches, not this catch.)
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

import methods.reactome_pathway_context.read as reactome_read


def _nosuchkey():
    from botocore.exceptions import ClientError

    return ClientError({"Error": {"Code": "NoSuchKey", "Message": "not found"}}, "GetObject")


def _throttling():
    from botocore.exceptions import ClientError

    return ClientError({"Error": {"Code": "SlowDown", "Message": "please reduce request rate"}}, "GetObject")


def _run(product_side_effect):
    # Resolve the symbol to a UAC so control reaches the try-block, then drive the product load to raise.
    with (
        patch.object(reactome_read, "_hgnc_to_uniprot_ac", return_value="P01116"),
        patch.object(reactome_read, "_load_pathways_from_product", side_effect=product_side_effect),
    ):
        return reactome_read.read_target_summary("KRAS")


class TestReactomeHonestLoud:
    def test_genuine_nosuchkey_yields_data_unavailable(self):
        result = _run(_nosuchkey())
        assert result["pathway_class"] == "data_unavailable"

    def test_filenotfound_is_genuine_absence(self):
        result = _run(FileNotFoundError("no local reactome product"))
        assert result["pathway_class"] == "data_unavailable"

    def test_transient_throttling_reraises(self):
        with pytest.raises(Exception) as ei:
            _run(_throttling())
        assert "SlowDown" in str(ei.value) or "reduce request rate" in str(ei.value)

    def test_parse_fault_reraises(self):
        with pytest.raises(ValueError):
            _run(ValueError("corrupted reactome hierarchy"))
