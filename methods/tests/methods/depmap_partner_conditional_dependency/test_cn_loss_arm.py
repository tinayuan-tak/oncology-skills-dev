"""cn_loss deficiency arm (2026-08-19): partner deep-deletion (relative CN < 0.5) as a partner-
deficiency, unlocking codeletion synthetic-lethality (MTAP/CDKN2A-deletion → PRMT5/MAT2A). Hermetic —
stubs the CN loader (no S3)."""

from __future__ import annotations

from onc_methods.depmap_partner_conditional_dependency import cli


def test_cn_loss_thresholds_at_deep_del(monkeypatch):
    # relative CN < 0.5 → deep deletion (partner-deficient); >= 0.5 → intact; NaN → omitted.
    fake_cn = {"ACH-1": 0.1, "ACH-2": 0.49, "ACH-3": 0.5, "ACH-4": 1.0, "ACH-5": float("nan")}
    monkeypatch.setattr(cli, "load_cn_files", lambda rp, gene: (fake_cn, {}, "wes", []), raising=False)
    # patch the name as imported inside the function
    import onc_methods.depmap_cn_distribution.cli as cn_cli

    monkeypatch.setattr(cn_cli, "load_cn_files", lambda rp, gene: (fake_cn, {}, "wes", []))
    vec = cli.build_partner_deficiency_vector("26q1", "MTAP", "cn_loss")
    assert vec == {"ACH-1": True, "ACH-2": True, "ACH-3": False, "ACH-4": False}  # ACH-5 (NaN) omitted


def test_cn_loss_empty_on_loader_error(monkeypatch):
    import onc_methods.depmap_cn_distribution.cli as cn_cli

    monkeypatch.setattr(
        cn_cli, "load_cn_files", lambda rp, gene: ({}, {}, "data_unavailable", [{"_live_read_error": "x"}])
    )
    assert cli.build_partner_deficiency_vector("26q1", "MTAP", "cn_loss") == {}


def test_cn_loss_wired_into_dispatch():
    # unknown types still raise; cn_loss no longer does
    import pytest

    with pytest.raises(ValueError):
        cli.build_partner_deficiency_vector("26q1", "X", "bogus_type")


def test_mtap_codeletion_partners_curated():
    pmap = cli.load_partner_map()
    for tgt in ("PRMT5", "MAT2A"):
        assert tgt in pmap
        entry = pmap[tgt][0]
        assert entry["partner"] == "MTAP" and entry["deficiency_type"] == "cn_loss"
