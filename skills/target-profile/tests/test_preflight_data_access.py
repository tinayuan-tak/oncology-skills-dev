"""_preflight_data_access — data-access preflight account gate (2026-08-25).

Silent-trap guard: the fan-out reads every card's evidence from the onc-compbio derived-products
bucket. If the ambient AWS identity is the wrong account (AWS_PROFILE defaults to cmp-dev →
888307857004, NOT the onc-compbio cbg account 557690623046), every live read returns empty and the
whole profile silently degrades to all-`insufficient` with exit 0 — which would quietly invalidate
an at-scale pressure-test batch. The preflight resolves the identity via a permission-free STS call
and hard-fails (main() → exit 3) when the account is not an onc-compbio account.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parents[1], "tp_run_preflight")


def _fake_boto3(account=None, raise_exc=None):
    """A stand-in boto3 module whose sts client returns `account` (or raises)."""

    class _Client:
        def get_caller_identity(self):
            if raise_exc is not None:
                raise raise_exc
            return {"Account": account, "Arn": f"arn:aws:iam::{account}:user/x"}

    mod = types.ModuleType("boto3")
    mod.client = lambda service, **kw: _Client()
    return mod


def _run_with(monkeypatch, *, account=None, raise_exc=None, env_accounts=None, profile="cbg"):
    monkeypatch.setitem(sys.modules, "boto3", _fake_boto3(account=account, raise_exc=raise_exc))
    # botocore.config.Config is imported inside the function; provide a no-op stand-in.
    botocore = types.ModuleType("botocore")
    config = types.ModuleType("botocore.config")
    config.Config = lambda **kw: None
    botocore.config = config
    monkeypatch.setitem(sys.modules, "botocore", botocore)
    monkeypatch.setitem(sys.modules, "botocore.config", config)
    monkeypatch.setenv("AWS_PROFILE", profile)
    if env_accounts is not None:
        monkeypatch.setenv("ONC_COMPBIO_ACCOUNT_IDS", env_accounts)
        # the account set is captured at import time; re-read it for the test.
        monkeypatch.setattr(
            tp, "_ONC_COMPBIO_ACCOUNT_IDS", frozenset(a.strip() for a in env_accounts.split(",") if a.strip())
        )
    return tp._preflight_data_access()


def test_onc_account_passes(monkeypatch):
    ok, detail = _run_with(monkeypatch, account="557690623046")
    assert ok is True
    assert "557690623046" in detail


def test_wrong_account_fails(monkeypatch):
    ok, detail = _run_with(monkeypatch, account="888307857004", profile="cmp-dev")
    assert ok is False
    assert "888307857004" in detail and "NOT an onc-compbio account" in detail


def test_unresolvable_identity_fails(monkeypatch):
    ok, detail = _run_with(monkeypatch, raise_exc=RuntimeError("ExpiredToken"))
    assert ok is False
    assert "could not resolve AWS identity" in detail


def test_env_override_allows_additional_account(monkeypatch):
    ok, _ = _run_with(monkeypatch, account="123456789012", env_accounts="557690623046,123456789012")
    assert ok is True


def test_preflight_never_raises(monkeypatch):
    # A boto3 whose client() itself explodes must still return (False, detail), not propagate.
    bad = types.ModuleType("boto3")

    def _boom(*a, **k):
        raise OSError("no network")

    bad.client = _boom
    monkeypatch.setitem(sys.modules, "boto3", bad)
    ok, detail = tp._preflight_data_access()
    assert ok is False and "could not resolve AWS identity" in detail
