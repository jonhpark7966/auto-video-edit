"""Provider runtime configuration and CLI invocation helpers."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any, Mapping

SMOKE_TEST_PROMPT = "Respond with exactly OK"

DEFAULT_PROVIDER_MODELS = {
    "claude": "claude-opus-4-6",
    "codex": "gpt-5.4",
}
DEFAULT_PROVIDER_EFFORTS = {
    "claude": "medium",
    "codex": "medium",
}
_PROVIDER_MODEL_ENVS = {
    "claude": "AVID_CLAUDE_MODEL",
    "codex": "AVID_CODEX_MODEL",
}
_PROVIDER_EFFORT_ENVS = {
    "claude": "AVID_CLAUDE_EFFORT",
    "codex": "AVID_CODEX_REASONING_EFFORT",
}
_PROVIDER_BINARIES = {
    "claude": "claude",
    "codex": "codex",
}


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model: str
    effort: str
    source: Mapping[str, str]


def provider_config_payload(config: ProviderConfig) -> dict[str, Any]:
    return {
        "provider": config.provider,
        "model": config.model,
        "effort": config.effort,
        "source": dict(config.source),
    }


def resolve_provider_config(
    provider: str,
    model: str | None = None,
    effort: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> ProviderConfig:
    if provider not in DEFAULT_PROVIDER_MODELS:
        raise ValueError(f"unsupported provider: {provider}")

    env = os.environ if environ is None else environ

    model_env = _PROVIDER_MODEL_ENVS[provider]
    effort_env = _PROVIDER_EFFORT_ENVS[provider]

    if model:
        resolved_model = model
        model_source = "cli"
    elif env.get(model_env):
        resolved_model = env[model_env]
        model_source = "env"
    else:
        resolved_model = DEFAULT_PROVIDER_MODELS[provider]
        model_source = "default"

    if effort:
        resolved_effort = effort
        effort_source = "cli"
    elif env.get(effort_env):
        resolved_effort = env[effort_env]
        effort_source = "env"
    else:
        resolved_effort = DEFAULT_PROVIDER_EFFORTS[provider]
        effort_source = "default"

    return ProviderConfig(
        provider=provider,
        model=resolved_model,
        effort=resolved_effort,
        source={
            "provider": "cli",
            "model": model_source,
            "effort": effort_source,
        },
    )


def build_provider_invocation(
    prompt: str,
    provider: str,
    model: str | None = None,
    effort: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[list[str], str | None, ProviderConfig, list[str]]:
    config = resolve_provider_config(provider, model=model, effort=effort, environ=environ)

    if provider == "claude":
        command = [
            "claude",
            "-p",
            "--model",
            config.model,
            "--effort",
            config.effort,
            "--output-format",
            "text",
            prompt,
        ]
        argv_summary = [*command[:-1], "<prompt>"]
        return command, None, config, argv_summary

    if provider == "codex":
        command = [
            "codex",
            "exec",
            "-m",
            config.model,
            "-c",
            f"model_reasoning_effort={json.dumps(config.effort)}",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "-",
        ]
        return command, prompt, config, command.copy()

    raise ValueError(f"unsupported provider: {provider}")


def _run_provider_command(
    provider: str,
    command: list[str],
    *,
    input_text: str | None,
    timeout: int,
) -> str:
    binary = _PROVIDER_BINARIES[provider]
    pretty_name = provider.capitalize()
    try:
        result = subprocess.run(
            command,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"{pretty_name} CLI not found: {binary}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{pretty_name} CLI timeout after {timeout}s") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown provider CLI error").strip()
        raise RuntimeError(f"{pretty_name} CLI error: {detail[:1000]}")

    return result.stdout.strip()


def run_provider_prompt(
    provider: str,
    prompt: str,
    *,
    timeout: int = 300,
    model: str | None = None,
    effort: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    command, input_text, _config, _argv_summary = build_provider_invocation(
        prompt,
        provider,
        model=model,
        effort=effort,
        environ=environ,
    )
    return _run_provider_command(provider, command, input_text=input_text, timeout=timeout)


def probe_provider(
    provider: str,
    *,
    prompt: str = SMOKE_TEST_PROMPT,
    timeout: int = 60,
    model: str | None = None,
    effort: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    command, input_text, config, argv_summary = build_provider_invocation(
        prompt,
        provider,
        model=model,
        effort=effort,
        environ=environ,
    )
    response = _run_provider_command(provider, command, input_text=input_text, timeout=timeout)
    normalized = response.strip()
    if normalized != "OK":
        raise RuntimeError(
            f"{provider} provider probe returned unexpected response: {normalized[:200]!r}"
        )

    return {
        "status": "ok",
        "provider": config.provider,
        "model": config.model,
        "reasoning_effort": config.effort,
        "source": dict(config.source),
        "argv_summary": argv_summary,
        "prompt": prompt,
        "response": normalized,
    }
