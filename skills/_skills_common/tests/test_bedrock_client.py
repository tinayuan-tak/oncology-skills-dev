"""Tests for the shared Bedrock client factory (_skills_common.bedrock_client).

Extracted 2026-08-14 from workflow-target-evaluation-onc into _skills_common so the LLM
synthesis layer no longer depends on a skill dir slated for removal. No real API calls —
covers env-var handling, error messaging, default model IDs, and (the point of the
extraction) that _skills_common.llm imports the client from its NEW home, with no residual
dependency on the workflow skill dir.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from _skills_common.bedrock_client import (
    BedrockAuthError,
    ModelConfig,
    _refresh_hint,
    get_bedrock_client,
    FRAMEWORK_SYNTHESIS_MODEL,
    FRAMEWORK_EXTRACTION_MODEL,
    FRAMEWORK_MODEL_VERSION,
)


# --- ModelConfig: env-var defaults ------------------------------------------


def test_model_config_defaults_match_harness_env() -> None:
    env = {
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "us.anthropic.claude-sonnet-4-6",
        "ANTHROPIC_MODEL": "us.anthropic.claude-opus-4-7",
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "16384",
    }
    with patch.dict(os.environ, env, clear=False):
        cfg = ModelConfig.from_env()
    assert cfg.extraction_model == "us.anthropic.claude-sonnet-4-6"
    assert cfg.synthesis_model == "us.anthropic.claude-opus-4-7"
    assert cfg.max_output_tokens == 16384


def test_model_config_defaults_when_env_missing() -> None:
    drop = ["ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_MODEL", "CLAUDE_CODE_MAX_OUTPUT_TOKENS"]
    env_without = {k: v for k, v in os.environ.items() if k not in drop}
    with patch.dict(os.environ, env_without, clear=True):
        cfg = ModelConfig.from_env()
    assert "sonnet" in cfg.extraction_model.lower()
    assert "opus" in cfg.synthesis_model.lower()
    assert cfg.max_output_tokens > 0


def test_default_pins_the_declared_framework_model(monkeypatch) -> None:
    """Governance item B: with no env override, the synthesis default MUST equal the
    single declared FRAMEWORK_SYNTHESIS_MODEL pin, and the config carries the
    framework_model_version for provenance."""
    for k in ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL"):
        monkeypatch.delenv(k, raising=False)
    cfg = ModelConfig.from_env()
    assert cfg.synthesis_model == FRAMEWORK_SYNTHESIS_MODEL == "us.anthropic.claude-opus-4-8"
    assert cfg.extraction_model == FRAMEWORK_EXTRACTION_MODEL
    assert cfg.framework_model_version == FRAMEWORK_MODEL_VERSION


def test_env_override_still_respected(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_MODEL", "us.anthropic.claude-opus-4-7")
    assert ModelConfig.from_env().synthesis_model == "us.anthropic.claude-opus-4-7"


def test_model_config_is_frozen() -> None:
    cfg = ModelConfig.from_env()
    with pytest.raises((AttributeError, TypeError)):
        cfg.extraction_model = "something-else"  # type: ignore[misc]


# --- Refresh hint formatting ------------------------------------------------


def test_refresh_hint_with_profile() -> None:
    assert _refresh_hint("cmp-dev") == "aws sso login --profile cmp-dev"


def test_refresh_hint_without_profile() -> None:
    hint = _refresh_hint(None)
    assert "aws sso login" in hint
    assert "AWS_PROFILE" in hint


# --- get_bedrock_client error handling --------------------------------------


def test_bedrock_auth_error_is_runtimeerror() -> None:
    assert issubclass(BedrockAuthError, RuntimeError)


def test_get_bedrock_client_wraps_init_failure_with_helpful_message() -> None:
    import _skills_common.bedrock_client as bc

    class _FakeAnthropicBedrock:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("expired SSO token")

    with patch.dict(os.environ, {"AWS_PROFILE": "cmp-dev"}, clear=False):
        with patch.object(bc, "AnthropicBedrock", _FakeAnthropicBedrock, create=True):
            with pytest.raises(BedrockAuthError) as exc:
                bc.get_bedrock_client()
    msg = str(exc.value)
    assert "aws sso login" in msg
    assert "cmp-dev" in msg


def test_get_bedrock_client_returns_client_when_init_succeeds() -> None:
    import _skills_common.bedrock_client as bc

    sentinel = object()

    class _FakeAnthropicBedrock:
        def __new__(cls, *args, **kwargs):
            return sentinel

    with patch.object(bc, "AnthropicBedrock", _FakeAnthropicBedrock, create=True):
        client = bc.get_bedrock_client()
    assert client is sentinel


def test_missing_anthropic_raises_clear_importerror() -> None:
    """When the anthropic SDK isn't installed (AnthropicBedrock is None), the factory
    raises an ImportError naming the extra + that the default pixi env omits it."""
    import _skills_common.bedrock_client as bc

    with patch.object(bc, "AnthropicBedrock", None, create=True):
        with pytest.raises(ImportError) as exc:
            bc.get_bedrock_client()
    assert "anthropic[bedrock]" in str(exc.value)


# --- the extraction contract: llm.py imports from the NEW home --------------


def test_llm_layer_imports_client_from_skills_common_not_workflow_skill() -> None:
    """The point of the extraction: _skills_common.llm resolves the Bedrock client from
    _skills_common.bedrock_client, with no residual dependency on the deprecated
    workflow-target-evaluation-onc skill dir."""
    import _skills_common.llm as llm

    get_client, model_config, auth_error = llm._import_bedrock_client()
    assert get_client is get_bedrock_client
    assert model_config is ModelConfig
    assert auth_error is BedrockAuthError
    # no residual sys.path hack constant pointing at the workflow skill
    assert not hasattr(llm, "WORKFLOW_SCRIPTS")
