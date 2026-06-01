"""Tests for the Bedrock client factory.

No real API calls — covers env-var handling, error messaging, and
default model IDs.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from integrated_report.bedrock_client import (  # noqa: E402
    BedrockAuthError, ModelConfig, _refresh_hint, get_bedrock_client,
)


# ---------------------------------------------------------------------------
# ModelConfig: env-var defaults
# ---------------------------------------------------------------------------

def test_model_config_defaults_match_harness_env() -> None:
    """When env vars are set (as in Claude Code's ~/.claude/settings.json),
    ModelConfig should pick them up."""
    env = {
        'ANTHROPIC_DEFAULT_SONNET_MODEL': 'us.anthropic.claude-sonnet-4-6',
        'ANTHROPIC_MODEL': 'us.anthropic.claude-opus-4-7',
        'CLAUDE_CODE_MAX_OUTPUT_TOKENS': '16384',
    }
    with patch.dict(os.environ, env, clear=False):
        cfg = ModelConfig.from_env()
    assert cfg.extraction_model == 'us.anthropic.claude-sonnet-4-6'
    assert cfg.synthesis_model == 'us.anthropic.claude-opus-4-7'
    assert cfg.max_output_tokens == 16384


def test_model_config_defaults_when_env_missing() -> None:
    """If env vars are missing, fall back to baked-in defaults rather
    than crashing."""
    drop = ['ANTHROPIC_DEFAULT_SONNET_MODEL', 'ANTHROPIC_MODEL',
            'CLAUDE_CODE_MAX_OUTPUT_TOKENS']
    env_without = {k: v for k, v in os.environ.items() if k not in drop}
    with patch.dict(os.environ, env_without, clear=True):
        cfg = ModelConfig.from_env()
    # Baked-in defaults match the harness's typical settings.
    assert 'sonnet' in cfg.extraction_model.lower()
    assert 'opus' in cfg.synthesis_model.lower()
    assert cfg.max_output_tokens > 0


def test_model_config_is_frozen() -> None:
    """Frozen dataclass — accidental mutation should raise."""
    cfg = ModelConfig.from_env()
    with pytest.raises((AttributeError, TypeError)):
        cfg.extraction_model = 'something-else'   # type: ignore[misc]


# ---------------------------------------------------------------------------
# Refresh hint formatting
# ---------------------------------------------------------------------------

def test_refresh_hint_with_profile() -> None:
    assert _refresh_hint('cmp-dev') == 'aws sso login --profile cmp-dev'


def test_refresh_hint_without_profile() -> None:
    hint = _refresh_hint(None)
    assert 'aws sso login' in hint
    assert 'AWS_PROFILE' in hint


# ---------------------------------------------------------------------------
# get_bedrock_client error handling
# ---------------------------------------------------------------------------

def test_bedrock_auth_error_is_runtimeerror() -> None:
    """BedrockAuthError should be catchable as RuntimeError so callers
    can handle auth issues without importing the specific class."""
    assert issubclass(BedrockAuthError, RuntimeError)


def test_get_bedrock_client_wraps_init_failure_with_helpful_message() -> None:
    """Patch AnthropicBedrock to raise; verify the wrapper message
    includes the SSO refresh suggestion."""
    with patch('integrated_report.bedrock_client.AnthropicBedrock',
               side_effect=Exception('fake auth failure'), create=True):
        # Need to reload the import attempt within get_bedrock_client.
        # Easier: patch the module-level import path the function uses.
        pass

    # The function imports inside the call, so patch sys.modules level
    # by simulating an exception in the constructor.
    import integrated_report.bedrock_client as bc

    class _FakeAnthropicBedrock:
        def __init__(self, *args, **kwargs):
            raise RuntimeError('expired SSO token')

    with patch.dict(os.environ, {'AWS_PROFILE': 'cmp-dev'}, clear=False):
        with patch.object(bc, 'AnthropicBedrock',
                          _FakeAnthropicBedrock, create=True):
            with pytest.raises(BedrockAuthError) as exc:
                bc.get_bedrock_client()
    msg = str(exc.value)
    assert 'aws sso login' in msg
    assert 'cmp-dev' in msg


def test_get_bedrock_client_returns_client_when_init_succeeds() -> None:
    """Sanity: when constructor doesn't raise, get_bedrock_client
    returns the client unchanged."""
    import integrated_report.bedrock_client as bc

    sentinel = object()

    class _FakeAnthropicBedrock:
        def __init__(self, *args, **kwargs):
            pass

        def __new__(cls, *args, **kwargs):
            return sentinel

    with patch.object(bc, 'AnthropicBedrock', _FakeAnthropicBedrock, create=True):
        client = bc.get_bedrock_client()
    assert client is sentinel
