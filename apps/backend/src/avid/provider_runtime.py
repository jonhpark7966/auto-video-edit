"""Provider runtime configuration and CLI invocation helpers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import hashlib
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SMOKE_TEST_PROMPT = "Respond with exactly OK"
_LLM_IO_LOG_LOCK = threading.Lock()

DEFAULT_PROVIDER_MODELS = {
    "claude": "claude-opus-4-6",
    "codex": "gpt-5.5",
}
DEFAULT_PROVIDER_EFFORTS = {
    "claude": "medium",
    "codex": "xhigh",
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
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "-",
        ]
        return command, prompt, config, command.copy()

    raise ValueError(f"unsupported provider: {provider}")


def _prepare_provider_env(provider: str) -> dict[str, str] | None:
    """Prepare provider-specific subprocess environment."""
    if provider != "codex":
        return None

    env = os.environ.copy()
    source_home = Path(env.get("CODEX_HOME") or (Path.home() / ".codex"))
    writable_home = Path(env.get("AVID_CODEX_WRITABLE_HOME", "/tmp/eogum/codex-home"))

    writable_home.mkdir(parents=True, exist_ok=True)
    if source_home.exists() and source_home.resolve() != writable_home.resolve():
        for name in (
            "auth.json",
            "config.toml",
            "installation_id",
            "version.json",
            "models_cache.json",
        ):
            src = source_home / name
            if src.is_file():
                shutil.copy2(src, writable_home / name)

    env["CODEX_HOME"] = str(writable_home)
    return env


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
            env=_prepare_provider_env(provider),
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"{pretty_name} CLI not found: {binary}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{pretty_name} CLI timeout after {timeout}s") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown provider CLI error").strip()
        raise RuntimeError(f"{pretty_name} CLI error: {detail[:1000]}")

    return result.stdout.strip()


def _append_llm_io_log(entry: dict[str, Any]) -> None:
    log_path = os.environ.get("AVID_LLM_IO_LOG_PATH")
    if not log_path:
        return

    try:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with _LLM_IO_LOG_LOCK:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        # Logging must never change provider behavior.
        return


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_provider_prompt(
    provider: str,
    prompt: str,
    *,
    timeout: int = 300,
    model: str | None = None,
    effort: str | None = None,
    environ: Mapping[str, str] | None = None,
    stage: str | None = None,
) -> str:
    command, input_text, config, argv_summary = build_provider_invocation(
        prompt,
        provider,
        model=model,
        effort=effort,
        environ=environ,
    )
    base_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "avid",
        "stage": stage or os.environ.get("AVID_LLM_IO_STAGE", "provider_prompt"),
        "provider": config.provider,
        "model": config.model,
        "reasoning_effort": config.effort,
        "cache_hit": False,
        "argv_summary": argv_summary,
        "timeout_seconds": timeout,
        "input": {
            "prompt": prompt,
            "prompt_sha256": _hash_text(prompt),
        },
    }
    try:
        response = _run_provider_command(
            provider,
            command,
            input_text=input_text,
            timeout=timeout,
        )
    except Exception as exc:
        _append_llm_io_log({
            **base_entry,
            "status": "error",
            "error_type": type(exc).__name__,
            "error": str(exc),
        })
        raise

    _append_llm_io_log({
        **base_entry,
        "status": "ok",
        "output": {
            "response": response,
            "response_sha256": _hash_text(response),
        },
    })
    return response


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
