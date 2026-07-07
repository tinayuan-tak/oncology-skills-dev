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
    """Temporarily set AWS_PROFILE to the Bedrock-enabled profile.

    Rationale: skill runs use `AWS_PROFILE=cbg` for onc-compbio S3
    GetObject (data reads), but that profile lacks
    aws-marketplace:Subscribe permission for Bedrock model access.
    Bedrock calls must use `cmp-dev` (the framework's default per
    ~/.claude/settings.json). Swap the profile in-process for the
    duration of the LLM call, then restore.

    Override via BEDROCK_AWS_PROFILE env var if your account uses a
    different profile.
    """
    old = os.environ.get("AWS_PROFILE")
    os.environ["AWS_PROFILE"] = BEDROCK_AWS_PROFILE
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("AWS_PROFILE", None)
        else:
            os.environ["AWS_PROFILE"] = old


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
