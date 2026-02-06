"""CLI utilities for calling AI providers (Claude, Codex)."""

import json
import subprocess


def call_claude(prompt: str, timeout: int = 120) -> str:
    """Call Claude CLI and get response.

    Args:
        prompt: The prompt to send to Claude
        timeout: Timeout in seconds (default: 120)

    Returns:
        Claude's response as string

    Raises:
        RuntimeError: If Claude CLI is not found or times out
    """
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Claude CLI error: {result.stderr}")
        return result.stdout.strip()
    except FileNotFoundError:
        raise RuntimeError("Claude CLI not found. Please install claude-code.")
    except subprocess.TimeoutExpired:
        raise RuntimeError("Claude CLI timeout")


def call_codex(prompt: str, timeout: int = 300) -> str:
    """Call Codex CLI (exec mode) and get response.

    Uses `codex exec` with gpt-5.2 model and medium reasoning effort.

    Args:
        prompt: The prompt to send to Codex
        timeout: Timeout in seconds (default: 300)

    Returns:
        Codex's response as string

    Raises:
        RuntimeError: If Codex CLI is not found or times out
    """
    try:
        result = subprocess.run(
            [
                "codex", "exec",
                "-m", "gpt-5.2",
                "-c", "model_reasoning_effort=medium",
                "--full-auto",
                "-",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Codex CLI error: {result.stderr}")
        return result.stdout.strip()
    except FileNotFoundError:
        raise RuntimeError("Codex CLI not found. Please install codex.")
    except subprocess.TimeoutExpired:
        raise RuntimeError("Codex CLI timeout")


def parse_json_response(response: str) -> dict:
    """Parse JSON from AI response.

    Handles both clean JSON responses and JSON embedded in text.

    Args:
        response: Raw response string from AI

    Returns:
        Parsed JSON as dict

    Raises:
        ValueError: If no valid JSON found in response
    """
    # Try direct JSON parse first
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        pass

    # Find JSON in response (handle markdown code blocks, etc.)
    start = response.find("{")
    end = response.rfind("}") + 1

    if start == -1 or end == 0:
        raise ValueError(f"No JSON found in response: {response[:200]}")

    json_str = response[start:end]
    return json.loads(json_str)
