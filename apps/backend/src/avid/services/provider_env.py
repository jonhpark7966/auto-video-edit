"""Helpers for passing provider runtime overrides into skill subprocesses."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


def _backend_src_path() -> str:
    return str(Path(__file__).resolve().parents[2])


def _prepend_pythonpath(env: dict[str, str], path: str) -> None:
    current = env.get("PYTHONPATH")
    parts = current.split(os.pathsep) if current else []
    if path in parts:
        return
    env["PYTHONPATH"] = path if not current else f"{path}{os.pathsep}{current}"


def build_provider_subprocess_env(
    provider: str,
    *,
    model: str | None = None,
    effort: str | None = None,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = dict(os.environ if base_env is None else base_env)
    _prepend_pythonpath(env, _backend_src_path())

    if provider == "claude":
        if model:
            env["AVID_CLAUDE_MODEL"] = model
        if effort:
            env["AVID_CLAUDE_EFFORT"] = effort
    elif provider == "codex":
        if model:
            env["AVID_CODEX_MODEL"] = model
        if effort:
            env["AVID_CODEX_REASONING_EFFORT"] = effort

    return env
