"""CLI utilities for calling AI providers (Claude, Codex)."""

from __future__ import annotations

import json

from avid.provider_runtime import (
    ProviderConfig,
    build_provider_invocation,
    probe_provider,
    provider_config_payload,
    resolve_provider_config,
    run_provider_prompt,
)


def call_claude(
    prompt: str,
    timeout: int = 300,
    model: str | None = None,
    effort: str | None = None,
) -> str:
    """Call Claude CLI and get response."""
    return run_provider_prompt(
        "claude",
        prompt,
        timeout=timeout,
        model=model,
        effort=effort,
    )


def call_codex(
    prompt: str,
    timeout: int = 300,
    model: str | None = None,
    effort: str | None = None,
) -> str:
    """Call Codex CLI (exec mode) and get response."""
    return run_provider_prompt(
        "codex",
        prompt,
        timeout=timeout,
        model=model,
        effort=effort,
    )


def parse_json_response(response: str) -> dict:
    """Parse JSON from AI response.

    Handles both clean JSON responses and JSON embedded in text.
    """
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        pass

    start = response.find("{")
    end = response.rfind("}") + 1

    if start == -1 or end == 0:
        raise ValueError(f"No JSON found in response: {response[:200]}")

    json_str = response[start:end]
    return json.loads(json_str)
