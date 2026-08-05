"""llm — Tier-3 structured LLM synthesis helpers.

Every LLM call from a compositional skill must:

  1. Use structured tool-use — `tool_choice={"type":"tool","name":<name>}`
     forcing the model to emit a single JSON object matching the tool's
     input_schema.
  2. Use canonical enums on every categorical field so downstream
     consumers can validate against a fixed vocabulary.
  3. Tag every LLM-produced field with `_source: llm_synthesized`,
     `_model_id: <id>`, `_prompt_hash: <sha256>` so audit-time provenance
     is preserved.
  4. Rerunning with identical inputs must produce identical `_prompt_hash`
     so drift between LLM outputs is detectable.

The reference implementation of the tool-use + double-validation pattern
lives in `skills/workflow-target-evaluation-onc/scripts/integrated_report/
synthesize_facts.py`. This module reuses that skill's Bedrock client
factory verbatim (single source of truth for auth + corporate-CA
handling), and defines a `synthesize_structured()` helper that packages
the tool-use call + provenance-tag stamping.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

SKILLS_DIR = Path(__file__).resolve().parent.parent
WORKFLOW_SCRIPTS = SKILLS_DIR / "workflow-target-evaluation-onc" / "scripts"


BEDROCK_AWS_PROFILE = os.environ.get("BEDROCK_AWS_PROFILE", "cmp-dev")


@contextmanager
def _bedrock_profile():
    """Temporarily authenticate as the Bedrock-enabled profile for one LLM call.

    Rationale: skill runs use `AWS_PROFILE=cbg` for onc-compbio S3 GetObject
    (data reads), but that profile lacks the aws-marketplace entitlement for
    Bedrock model access. Bedrock calls must use `cmp-dev` (the framework's
    default per ~/.claude/settings.json; override via BEDROCK_AWS_PROFILE).

    THE SUBTLE PART (fixed 2026-08-05): AnthropicBedrock does NOT honor
    `AWS_PROFILE` — its internal boto3 chain resolves the ambient/instance role
    (on SageMaker, the execution role, which lacks the entitlement) even when
    AWS_PROFILE is set, so a bare profile-swap silently 400s ("account is not
    authorized to invoke this API operation"). boto3's OWN client honors the
    profile, so we RESOLVE the profile's frozen credentials with boto3 and export
    them as the standard AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY /
    AWS_SESSION_TOKEN env vars — which AnthropicBedrock's chain DOES honor. We
    also drop AWS_PROFILE for the duration so the explicit creds win cleanly.
    If the profile can't be resolved (e.g. not configured), fall back to the
    old profile-swap behavior so nothing gets worse than before.
    """
    _CRED_KEYS = ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
                  "AWS_SESSION_TOKEN")
    saved = {k: os.environ.get(k) for k in _CRED_KEYS}
    try:
        frozen = None
        try:
            import boto3
            frozen = boto3.Session(profile_name=BEDROCK_AWS_PROFILE) \
                .get_credentials().get_frozen_credentials()
        except Exception:  # noqa: BLE001 — profile unresolvable → fall back to profile-swap
            frozen = None
        if frozen is not None:
            os.environ.pop("AWS_PROFILE", None)   # explicit creds must win over any ambient profile
            os.environ["AWS_ACCESS_KEY_ID"] = frozen.access_key
            os.environ["AWS_SECRET_ACCESS_KEY"] = frozen.secret_key
            if frozen.token:
                os.environ["AWS_SESSION_TOKEN"] = frozen.token
            else:
                os.environ.pop("AWS_SESSION_TOKEN", None)
        else:
            os.environ["AWS_PROFILE"] = BEDROCK_AWS_PROFILE
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _import_bedrock_client():
    """Load the reference Bedrock client from workflow-target-evaluation-onc.

    Kept lazy so skills that don't invoke LLM synthesis don't pay import
    cost for the anthropic SDK. Raises ImportError with a clear message if
    the workflow skill or its dependencies aren't available.
    """
    if str(WORKFLOW_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(WORKFLOW_SCRIPTS))
    from integrated_report.bedrock_client import (          # noqa: F401
        get_bedrock_client, ModelConfig, BedrockAuthError,
    )
    return get_bedrock_client, ModelConfig, BedrockAuthError


def _prompt_hash(system: str, user: str, tool: dict, model_id: str) -> str:
    """Deterministic hash of everything that shapes the LLM output.

    Includes system prompt, user prompt, tool schema (serialized as
    sort-key JSON so field-order permutations don't change the hash), and
    model_id. Two runs producing the same hash MUST have received the
    same LLM invocation; different hashes explain any output drift.
    """
    h = hashlib.sha256()
    for part in (system, user, json.dumps(tool, sort_keys=True), model_id):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def _stamp_llm_provenance(
    payload: dict,
    model_id: str,
    prompt_hash: str,
) -> dict:
    """Add _source / _model_id / _prompt_hash to every top-level string
    or dict field the LLM produced. Non-content fields (nested lists,
    primitives) are left untagged — the top-level stamping is what the
    audit trail relies on.

    Convention: tagged fields become dicts with structure
      {"value": <original>, "_source": "llm_synthesized",
       "_model_id": <id>, "_prompt_hash": <hash>}
    when the original was a primitive. For dict/list values we add the
    tags as sibling keys at the top level of that value.
    """
    stamped: dict = {}
    for k, v in payload.items():
        if isinstance(v, dict):
            stamped[k] = {
                **v,
                "_source": "llm_synthesized",
                "_model_id": model_id,
                "_prompt_hash": prompt_hash,
            }
        elif isinstance(v, (str, list)):
            stamped[k] = {
                "value": v,
                "_source": "llm_synthesized",
                "_model_id": model_id,
                "_prompt_hash": prompt_hash,
            }
        else:
            # ints, floats, bools, None — kept as-is; tag would be noise.
            stamped[k] = v
    return stamped


def synthesize_structured(
    system_prompt: str,
    user_prompt: str,
    tool_name: str,
    tool_schema: dict,
    model_id: Optional[str] = None,
    max_tokens: int = 8192,
) -> dict:
    """Invoke Bedrock with forced structured tool-use, return the parsed
    tool_input dict stamped with provenance metadata.

    Args:
        system_prompt: system-message text
        user_prompt: user-message text (typically containing the card
            summaries + fired-rules context)
        tool_name: name of the tool the model must call
        tool_schema: JSON Schema for the tool's input parameters. Should
            include canonical enums on every categorical field.
        model_id: override Bedrock model id (defaults to
            ModelConfig.from_env().synthesis_model — Opus by default).
        max_tokens: cap on response size

    Returns:
        Dict shaped like the tool_schema's input_schema, with every
        top-level field tagged with `_source: llm_synthesized`,
        `_model_id`, `_prompt_hash`.

    Raises:
        BedrockAuthError: on AWS SSO / IAM issues
        RuntimeError: if the model didn't use the tool as instructed
    """
    get_client, ModelConfig, _ = _import_bedrock_client()

    with _bedrock_profile():
        client = get_client()
        cfg = ModelConfig.from_env()
        model = model_id or cfg.synthesis_model
        # Strip the `[1m]` context-window ALIAS if present. The Claude Code harness sets
        # ANTHROPIC_MODEL=us.anthropic.claude-opus-4-8[1m], which ModelConfig.from_env() may
        # inherit — but the `[1m]` alias is NOT a Bedrock-invokable model id (invoke returns
        # 400 "account is not authorized to invoke this API operation"). The base id IS
        # invokable. This is a no-op for already-clean ids.
        if model and model.endswith("[1m]"):
            model = model[:-len("[1m]")]

        tool = {
            "name": tool_name,
            "description": tool_schema.get("description", ""),
            "input_schema": tool_schema,
        }

        prompt_hash = _prompt_hash(system_prompt, user_prompt, tool, model)

        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            tools=[tool],
            tool_choice={"type": "tool", "name": tool_name},
        )

    tool_use_block = None
    for block in response.content:
        if getattr(block, "type", None) == "tool_use":
            tool_use_block = block
            break
    if tool_use_block is None:
        raise RuntimeError(
            f"LLM did not use the tool {tool_name!r} as instructed. "
            f"stop_reason={response.stop_reason}"
        )

    return _stamp_llm_provenance(
        payload=dict(tool_use_block.input),
        model_id=model,
        prompt_hash=prompt_hash,
    )
