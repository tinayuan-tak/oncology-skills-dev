"""Bedrock client factory for the v1.4.0 facts.yaml extractor.

Single source of `AnthropicBedrock()` setup. All extraction stages
(extract_claims, synthesize_facts) call `get_bedrock_client()` rather
than constructing the client themselves — keeps env-var handling and
auth-error reporting in one place.

Authentication is inherited from the environment, which the Claude
Code harness configures via ~/.claude/settings.json:
  AWS_PROFILE=cmp-dev
  AWS_REGION=us-east-1

If the token has expired (AWS SSO), the user gets a clear "run
`aws sso login --profile cmp-dev`" message rather than a generic
boto3 stack trace.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from anthropic import AnthropicBedrock
except ImportError:  # pragma: no cover — handled in get_bedrock_client
    AnthropicBedrock = None  # type: ignore[assignment]


@dataclass(frozen=True)
class ModelConfig:
    """Bedrock model IDs, sourced from the harness env vars (with defaults)."""

    extraction_model: str    # Stage 1: per-abstract claim extraction (Sonnet)
    synthesis_model: str     # Stage 2: per-category synthesis (Opus)
    max_output_tokens: int

    @classmethod
    def from_env(cls) -> 'ModelConfig':
        """Read model IDs from the same env vars Claude Code uses."""
        return cls(
            extraction_model=os.environ.get(
                'ANTHROPIC_DEFAULT_SONNET_MODEL',
                'us.anthropic.claude-sonnet-4-6',
            ),
            synthesis_model=os.environ.get(
                'ANTHROPIC_MODEL',
                'us.anthropic.claude-opus-4-7',
            ),
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
            "anthropic[bedrock] is required for v1.4.0 facts extraction. "
            "Install via `pixi install` from the workflow skill dir."
        )

    aws_region = os.environ.get('AWS_REGION', 'us-east-1')
    aws_profile = os.environ.get('AWS_PROFILE')

    try:
        return AnthropicBedrock(aws_region=aws_region)
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


class BedrockAuthError(RuntimeError):
    """Raised when Bedrock client init or call fails due to auth."""
