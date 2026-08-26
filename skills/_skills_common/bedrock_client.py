"""Bedrock client factory — the framework's single source of `AnthropicBedrock()` setup.

Extracted 2026-08-14 into `_skills_common` from the (deprecated)
`workflow-target-evaluation-onc/scripts/integrated_report/bedrock_client.py`, so the
shared LLM-synthesis layer (`_skills_common.llm`) and `target-profile` no longer depend
on a skill dir slated for removal. Logic is unchanged — one place for env-var handling,
the framework model pin, corporate-CA handling, and auth-error reporting.

Every LLM call from a compositional skill routes through `get_bedrock_client()` rather
than constructing the client itself.

Authentication is inherited from the environment. Bedrock calls require a Bedrock-entitled
profile — `_skills_common.llm` resolves `BEDROCK_AWS_PROFILE` (default `cmp-dev`) frozen
credentials for the call, since `AnthropicBedrock` does not honor `AWS_PROFILE`. If the SSO
token has expired, the caller gets a clear "run `aws sso login --profile <p>`" message
rather than a generic boto3 stack trace.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from anthropic import AnthropicBedrock
except ImportError:  # pragma: no cover — handled in get_bedrock_client
    AnthropicBedrock = None  # type: ignore[assignment]


# ── FRAMEWORK MODEL PIN (governance item B, 2026-07-20) ──────────────────────
# ONE declared framework model version — the single source of truth for which LLM
# synthesizes the narrative. Previously the default was a bare string literal inside
# from_env(), env-overridable per-run with no surfaced "framework model version" —
# a governance exposure (the least-controlled component is the most-visible one).
# These constants are stamped into provenance (framework_model_version) so a
# governance audience can see EXACTLY which model produced a given narrative.
#
# UPGRADE CADENCE (deliberate, not per-run drift): bump these constants in a
# reviewed PR when adopting a new model. Every candidate MUST be verified Bedrock-
# invokable in the account first — NOTE: the `...[1m]` context-alias is NOT
# Bedrock-invokable (400s); use the base ID. `us.anthropic.claude-opus-4-8` was
# verified invokable via the framework's own client (cmp-dev) on 2026-07-20.
FRAMEWORK_MODEL_VERSION = "2026-07-20"          # bump on any pin change (audit anchor)
FRAMEWORK_SYNTHESIS_MODEL = "us.anthropic.claude-opus-4-8"   # Opus 4.8 (verified invokable)
FRAMEWORK_EXTRACTION_MODEL = "us.anthropic.claude-sonnet-4-6"


@dataclass(frozen=True)
class ModelConfig:
    """Bedrock model IDs. Defaults are the PINNED framework model version
    (FRAMEWORK_SYNTHESIS_MODEL / FRAMEWORK_EXTRACTION_MODEL); env vars still allow a
    deliberate per-run override (e.g. A/B eval), but the DEFAULT is now a single
    declared version, not a bare literal."""

    extraction_model: str    # Stage 1: per-abstract claim extraction (Sonnet)
    synthesis_model: str     # Stage 2: per-category synthesis (Opus)
    max_output_tokens: int
    framework_model_version: str = FRAMEWORK_MODEL_VERSION   # stamped into provenance

    @classmethod
    def from_env(cls) -> 'ModelConfig':
        """Model IDs default to the PINNED framework version; env vars override for
        deliberate experiments (the override is recorded via _model_id provenance)."""
        return cls(
            extraction_model=os.environ.get(
                'ANTHROPIC_DEFAULT_SONNET_MODEL', FRAMEWORK_EXTRACTION_MODEL),
            synthesis_model=os.environ.get(
                'ANTHROPIC_MODEL', FRAMEWORK_SYNTHESIS_MODEL),
            max_output_tokens=int(os.environ.get(
                'CLAUDE_CODE_MAX_OUTPUT_TOKENS', '16384',
            )),
        )


def get_bedrock_client():
    """Construct an AnthropicBedrock client with helpful error messages.

    Returns:
        AnthropicBedrock instance. Auth + region picked up from
        environment automatically.

    Raises:
        BedrockAuthError: if AWS credentials are missing or expired.
            Message includes the recommended `aws sso login` command.
        ImportError: if the anthropic[bedrock] extra wasn't installed.
    """
    if AnthropicBedrock is None:
        raise ImportError(
            "anthropic[bedrock] is required for LLM synthesis (--synthesize). Install the "
            "`anthropic` package (with the bedrock extra) into the interpreter running "
            "synthesis; the default skills pixi env does not include it."
        )

    aws_region = os.environ.get('AWS_REGION', 'us-east-1')
    aws_profile = os.environ.get('AWS_PROFILE')

    try:
        # Build a custom SSL context if a corporate CA bundle is in use.
        # Python 3.14's stricter X.509 validation rejects some corporate
        # CAs (Basic Constraints not marked critical); httpx (used by
        # the Anthropic SDK) trips on this even when boto3 succeeds.
        # Workaround: build the SSL context ourselves with VERIFY_X509_STRICT
        # cleared, then pass an httpx.Client that uses it.
        http_client = _build_corporate_http_client()
        # Bedrock intermittently returns 503; the SDK default of 2 retries can be
        # exhausted during an outage window, killing a multi-minute full run at the
        # synthesis step. Raise the retry budget (SDK does exponential backoff on
        # 429/5xx/connection errors). Override via BEDROCK_MAX_RETRIES.
        return AnthropicBedrock(
            aws_region=aws_region,
            max_retries=int(os.environ.get('BEDROCK_MAX_RETRIES', '8')),
            **({'http_client': http_client} if http_client else {}),
        )
    except Exception as e:
        # Common failure modes: missing AWS_PROFILE, expired SSO token,
        # IAM lacking bedrock:InvokeModel. Surface the recommended fix
        # rather than letting the user puzzle over a boto3 traceback.
        refresh_hint = _refresh_hint(aws_profile)
        raise BedrockAuthError(
            f"Failed to initialize Bedrock client (region={aws_region}, "
            f"profile={aws_profile or 'not set'}): {e}\n"
            f"Likely cause: expired AWS SSO token or missing IAM "
            f"permission for bedrock:InvokeModel.\n"
            f"Try: {refresh_hint}"
        ) from e


def _refresh_hint(profile: str | None) -> str:
    """Suggest the right `aws sso login` command."""
    if profile:
        return f"aws sso login --profile {profile}"
    return "aws sso login --profile <your-profile>  # set AWS_PROFILE first"


def _build_corporate_http_client():
    """Build an httpx.Client for environments using a corporate CA bundle.

    Returns None if no corporate CA is configured (caller falls back to
    the SDK's default httpx client).

    Background: Python 3.14's stricter X.509 validation rejects some
    corporate CAs whose `Basic Constraints` extension isn't marked
    critical. boto3 uses its own bundled certs and works around this
    automatically; httpx (used by the Anthropic SDK) doesn't. We build
    an SSL context with VERIFY_X509_STRICT cleared so the corporate
    CA validates.
    """
    ca_bundle = os.environ.get('SSL_CERT_FILE') or os.environ.get('REQUESTS_CA_BUNDLE')
    if not ca_bundle or not os.path.exists(ca_bundle):
        return None
    try:
        import ssl
        import httpx
    except ImportError:
        return None
    ctx = ssl.create_default_context(cafile=ca_bundle)
    # Allow CAs with non-critical Basic Constraints (corp CA workaround).
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return httpx.Client(verify=ctx, timeout=120.0)


class BedrockAuthError(RuntimeError):
    """Raised when Bedrock client init or call fails due to auth."""
