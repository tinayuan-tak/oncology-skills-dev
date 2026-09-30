"""s3_client() profile-fallback discipline (2026-08-15).

`cbg` is a developer SSO profile absent in CI/prod/instance-role hosts. The reader-hardening
burndown routed several live readers onto target_id_sidecar.s3_client(), which surfaced a latent
break: an unmocked live read in a non-`cbg` environment raised ProfileNotFound instead of using the
ambient credential chain (first caught by skills compose-dashboard CI). s3_client must fall back to
the default chain when the PREFERRED/DEFAULT profile is missing, but still honor an EXPLICIT profile.
"""

from __future__ import annotations

import pytest
from botocore.exceptions import ProfileNotFound

from onc_methods import target_id_sidecar as tis


def test_missing_default_profile_falls_back_to_ambient(monkeypatch):
    # No AWS_PROFILE set, and the default (cbg) profile is not configured on this host (CI).
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setattr(tis, "DEFAULT_AWS_PROFILE", "definitely-not-a-real-profile-xyz")
    # Must NOT raise ProfileNotFound — falls back to the default credential chain (as the bare
    # boto3.client("s3") it replaced did). Client construction succeeds without live creds.
    client = tis.s3_client()
    assert client.meta.service_model.service_name == "s3"


def test_missing_env_profile_falls_back_to_ambient(monkeypatch):
    # AWS_PROFILE points at a profile that isn't configured -> fall back, don't crash.
    monkeypatch.setenv("AWS_PROFILE", "definitely-not-a-real-profile-xyz")
    client = tis.s3_client()
    assert client.meta.service_model.service_name == "s3"


def test_explicit_missing_profile_still_raises(monkeypatch):
    # A caller that EXPLICITLY demands a profile must not be silently substituted.
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    with pytest.raises(ProfileNotFound):
        tis.s3_client(profile="definitely-not-a-real-profile-xyz")
