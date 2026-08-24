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

The Bedrock client factory (auth + corporate-CA handling + the framework model pin)
lives in `_skills_common.bedrock_client` (extracted 2026-08-14 from the deprecated
workflow-target-evaluation-onc skill). This module defines a `synthesize_structured()`
helper that packages the tool-use call + provenance-tag stamping around that client.
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
    """Load the shared Bedrock client from _skills_common.bedrock_client.

    Kept lazy so skills that don't invoke LLM synthesis don't pay import
    cost for the anthropic SDK. Raises ImportError with a clear message if
    the anthropic[bedrock] extra isn't installed (surfaced by get_bedrock_client).
    """
    from _skills_common.bedrock_client import (             # noqa: F401
        get_bedrock_client, ModelConfig, BedrockAuthError,
    )
    return get_bedrock_client, ModelConfig, BedrockAuthError


# Shared evidence-only directive appended to every synthesis system prompt (2026-08-09). A live
# blinding experiment found the LLM imports PRIOR KNOWLEDGE of a named target beyond the presented
# data (e.g. the name "KRAS" shifted the read more-caveated than the identical data blinded — the
# model reasoned from what it "knows about KRAS", not only the evidence). This directive fences the
# narration to the supplied decision spine, so the synthesis reflects THIS target's measured data
# rather than the model's memorized lore about a famous gene. It does NOT ask the model to ignore
# the target name (the name legitimately labels the section); it asks it not to substitute prior
# belief for the presented evidence.
EVIDENCE_ONLY_DIRECTIVE = (
    " EVIDENCE-ONLY GROUNDING: reason SOLELY from the fields presented in this decision package. Do "
    "NOT introduce facts, frequencies, dependencies, compounds, or claims from prior knowledge of the "
    "named gene that are not in the provided evidence — even if you recognise the target. If the "
    "evidence is thin or a value is DATA_UNAVAILABLE, say so; do not backfill it from what the gene is "
    "'known' to do. Your read must be reproducible by another analyst given only this package."
)


def _prompt_hash(system: str, user: str, tool: dict, model_id: str,
                 temperature: Optional[float] = None) -> str:
    """Deterministic hash of everything that shapes the LLM output.

    Includes system prompt, user prompt, tool schema (serialized as
    sort-key JSON so field-order permutations don't change the hash),
    model_id, and the sampling temperature (or `default` when unset —
    Opus 4.8 deprecates the param, see synthesize_structured). Two runs
    producing the same hash MUST have received the same LLM invocation;
    different hashes explain any output drift. Temperature is part of the
    hash so a determinism-setting change is visible in provenance.
    """
    h = hashlib.sha256()
    temp_part = "temp=default" if temperature is None else f"temp={temperature}"
    for part in (system, user, json.dumps(tool, sort_keys=True), model_id, temp_part):
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
        if k.startswith("_"):
            # Framework-added meta (e.g. _malformed_fields from salvage) — never LLM content;
            # pass through untagged so it isn't mistaken for a synthesized field.
            stamped[k] = v
            continue
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


# Signatures of the harness/XML tool-call dialect leaking INTO a tool_input field value.
# When the model lapses out of native JSON tool-use into the `<parameter name="...">` XML
# convention, the SDK captures the first array/string parameter's value as a raw string that
# swallows every subsequent parameter — so a value carrying any of these markers is malformed
# (observed 2026-08-24: `top_arguments_for` == '\n<parameter name="top_arguments_against">...',
# and `top_arguments_against` dropped to None, in 12/25 target-profile runs).
_LEAKED_TOOLCALL_MARKERS = (
    "<parameter name=", "</parameter>", "<function", "</function", "antml:",
)


def _leaks_toolcall_markup(s: str) -> bool:
    return any(m in s for m in _LEAKED_TOOLCALL_MARKERS)


def _tool_input_defects(payload: dict, tool_schema: dict) -> list[str]:
    """Return the names of tool_input fields that violate the declared schema.

    Catches the malformed-tool-use failure mode (a model that lapsed into the XML
    `<parameter>` dialect): a field the schema declares an `array` that arrived as a
    non-list, a `string` field carrying leaked tool-call markup, a missing required
    field, or ANY string value (at any depth) carrying leaked markup. VALIDATION-ONLY —
    never mutates payload. The caller decides whether to retry or salvage.
    """
    props = tool_schema.get("properties", {}) or {}
    required = tool_schema.get("required", []) or []
    defects: list[str] = []

    for name in required:
        if name not in payload or payload.get(name) is None:
            defects.append(name)

    for name, spec in props.items():
        if name not in payload or payload.get(name) is None:
            continue
        val = payload[name]
        declared = spec.get("type")
        if declared == "array" and not isinstance(val, list):
            defects.append(name)
        elif declared == "string" and (not isinstance(val, str) or _leaks_toolcall_markup(val)):
            defects.append(name)
        elif isinstance(val, str) and _leaks_toolcall_markup(val):
            defects.append(name)
        elif isinstance(val, list) and any(
            isinstance(x, str) and _leaks_toolcall_markup(x) for x in val
        ):
            defects.append(name)

    # Dedup, preserve first-seen order.
    seen: dict[str, None] = {}
    for d in defects:
        seen.setdefault(d, None)
    return list(seen)


def _salvage_tool_input(payload: dict, tool_schema: dict, defects: list[str]) -> dict:
    """Coerce malformed fields to schema-valid EMPTIES and record the loss visibly.

    Last resort after retries are exhausted: an `array` defect becomes `[]`, a `string`
    defect becomes `""`, anything else becomes None. The dropped fields are recorded on
    `_malformed_fields` so the loss is AUDITABLE (never a silent garbage string in the
    package). Mirrors the framework's fail-visible ethos.
    """
    props = tool_schema.get("properties", {}) or {}
    for name in defects:
        declared = (props.get(name) or {}).get("type")
        payload[name] = [] if declared == "array" else ("" if declared == "string" else None)
    payload["_malformed_fields"] = list(defects)
    return payload


def synthesize_structured(
    system_prompt: str,
    user_prompt: str,
    tool_name: str,
    tool_schema: dict,
    model_id: Optional[str] = None,
    max_tokens: int = 8192,
    temperature: Optional[float] = None,
    max_retries: int = 2,
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
        temperature: OPTIONAL sampling temperature. Default None = do NOT
            send the parameter (the current behaviour). IMPORTANT — the
            framework synthesis model (Opus 4.8 / Claude-5 family) has
            DEPRECATED the `temperature` API parameter: it accepts only the
            default (1.0) or omission, and returns HTTP 400
            ("`temperature` is deprecated for this model") for any other
            value including 0.0 (verified live 2026-08-09). So on this
            model, output reproducibility CANNOT be obtained by pinning
            temperature — the model manages its own decoding. This param is
            retained for (a) older/other models that still honour it and
            (b) explicit callers, and is validated below: a non-default
            value is only sent when it is safe to. Part of the _prompt_hash
            when set, so a determinism-setting change is visible in provenance.

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

        prompt_hash = _prompt_hash(system_prompt, user_prompt, tool, model, temperature)

        # `temperature` is DEPRECATED on Opus 4.8 / Claude-5 (400 for any non-default value); only
        # forward it when a caller explicitly set it, leaving the model's own decoding otherwise.
        create_kwargs = dict(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            tools=[tool],
            tool_choice={"type": "tool", "name": tool_name},
        )
        if temperature is not None:
            create_kwargs["temperature"] = temperature

        # Call + validate, retrying on a malformed tool_input. The model intermittently lapses
        # out of native JSON tool-use into the XML `<parameter>` dialect (observed clean in
        # 13/25 runs, malformed in 12/25); since it is nondeterministic, a re-call usually
        # yields a clean object. On persistent malformation we SALVAGE (coerce defective fields
        # to schema-valid empties + record `_malformed_fields`) rather than ship leaked markup.
        payload: Optional[dict] = None
        defects: list[str] = []
        for attempt in range(max_retries + 1):
            response = client.messages.create(**create_kwargs)
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
            payload = dict(tool_use_block.input)
            defects = _tool_input_defects(payload, tool_schema)
            if not defects:
                break
            print(
                f"[llm.synthesize_structured] tool {tool_name!r} returned malformed field(s) "
                f"{defects} (attempt {attempt + 1}/{max_retries + 1}"
                + ("; retrying)" if attempt < max_retries else "; salvaging)"),
                file=sys.stderr,
            )

    if defects:
        payload = _salvage_tool_input(payload, tool_schema, defects)

    return _stamp_llm_provenance(
        payload=payload,
        model_id=model,
        prompt_hash=prompt_hash,
    )
