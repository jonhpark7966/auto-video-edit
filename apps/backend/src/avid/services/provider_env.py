"""Helpers for passing provider runtime overrides into skill subprocesses."""

from __future__ import annotations

import os
from typing import Mapping


def build_provider_subprocess_env(
    provider: str,
    *,
    model: str | None = None,
    effort: str | None = None,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = dict(os.environ if base_env is None else base_env)

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
