"""#822: the co-essentiality reader wrapped its parquet read in a bare ``except Exception`` that
encoded *any* failure — including transient S3 throttling / creds / parse faults — as a benign
``_data_unavailable=True`` result. Same anti-pattern as the SIGNOR lane (lower stakes: display-only,
not verdict-driving). Narrow the catch to genuine absence so a transient fault re-raises (fail-loud).

  1. a genuine NoSuchKey / FileNotFoundError still yields ``_data_unavailable`` — no raise.
  2. a simulated transient error RE-RAISES.
(A gene simply absent from the substrate is handled by the len(table)==0 branch, not this catch.)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import onc_methods.depmap_coessentiality.read as coess_read


def _nosuchkey():
    from botocore.exceptions import ClientError

    return ClientError({"Error": {"Code": "NoSuchKey", "Message": "not found"}}, "GetObject")


def _throttling():
    from botocore.exceptions import ClientError

    return ClientError({"Error": {"Code": "SlowDown", "Message": "please reduce request rate"}}, "GetObject")


def _run(read_table_side_effect):
    # parquet_path set so path resolution is deterministic (no S3/cache probe); patch the read itself.
    with patch.object(coess_read.pq, "read_table", side_effect=read_table_side_effect):
        return coess_read.read_coessential_partners("KRAS", parquet_path="/tmp/does-not-matter.parquet")


class TestCoessentialityHonestLoud:
    def test_genuine_nosuchkey_yields_data_unavailable(self):
        result = _run(_nosuchkey())
        assert result["_data_unavailable"] is True
        assert result["n_partners"] == 0

    def test_filenotfound_is_genuine_absence(self):
        result = _run(FileNotFoundError("no local substrate"))
        assert result["_data_unavailable"] is True

    def test_transient_throttling_reraises(self):
        with pytest.raises(Exception) as ei:
            _run(_throttling())
        assert "SlowDown" in str(ei.value) or "reduce request rate" in str(ei.value)

    def test_parse_fault_reraises(self):
        with pytest.raises(ValueError):
            _run(ValueError("corrupted parquet footer"))
