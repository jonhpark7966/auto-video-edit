"""Unit tests for provider runtime defaults and doctor behavior."""

from __future__ import annotations

import json
from argparse import Namespace

import pytest

from avid.cli import cmd_doctor
from avid.provider_runtime import build_provider_invocation, resolve_provider_config


class TestProviderDefaults:
    def test_claude_defaults(self):
        config = resolve_provider_config("claude")
        assert config.model == "claude-opus-4-6"
        assert config.effort == "medium"
        assert config.source["model"] == "default"
        assert config.source["effort"] == "default"

    def test_codex_defaults(self):
        config = resolve_provider_config("codex")
        assert config.model == "gpt-5.4"
        assert config.effort == "medium"
        assert config.source["model"] == "default"
        assert config.source["effort"] == "default"

    def test_cli_override_beats_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("AVID_CODEX_MODEL", "gpt-5.2")
        monkeypatch.setenv("AVID_CODEX_REASONING_EFFORT", "high")
        config = resolve_provider_config("codex", model="gpt-5.4", effort="medium")
        assert config.model == "gpt-5.4"
        assert config.effort == "medium"
        assert config.source["model"] == "cli"
        assert config.source["effort"] == "cli"


class TestProviderInvocation:
    def test_claude_invocation_contains_model_and_effort(self):
        command, input_text, config, argv_summary = build_provider_invocation(
            "hello",
            "claude",
            model="claude-opus-4-6",
            effort="medium",
        )
        assert input_text is None
        assert config.model == "claude-opus-4-6"
        assert "--model" in command
        assert "--effort" in command
        assert argv_summary[-1] == "<prompt>"

    def test_codex_invocation_contains_model_and_reasoning_effort(self):
        command, input_text, config, argv_summary = build_provider_invocation(
            "hello",
            "codex",
            model="gpt-5.4",
            effort="medium",
        )
        assert input_text == "hello"
        assert config.model == "gpt-5.4"
        assert command[:3] == ["codex", "exec", "-m"]
        assert any("model_reasoning_effort" in item for item in command)
        assert "--skip-git-repo-check" in command
        assert "--sandbox" in command
        assert "read-only" in command
        assert argv_summary == command


class TestDoctor:
    @pytest.mark.asyncio
    async def test_doctor_default_is_binary_only(self, monkeypatch: pytest.MonkeyPatch):
        async def fake_health_check(self):
            return True

        def fake_which(name: str) -> str | None:
            return f"/usr/bin/{name}"

        def should_not_probe(provider: str, **_: object) -> dict[str, object]:
            raise AssertionError(f"probe_provider should not be called for {provider}")

        monkeypatch.setattr(
            "avid.services.transcription.ChalnaTranscriptionService.health_check",
            fake_health_check,
        )
        monkeypatch.setattr("avid.cli.shutil.which", fake_which)
        monkeypatch.setattr("avid.cli.probe_provider", should_not_probe)

        payload = await cmd_doctor(
            Namespace(
                chalna_url=None,
                provider=None,
                probe_providers=False,
                provider_model=None,
                provider_effort=None,
                json=True,
            )
        )

        assert payload["checks"]["provider"] is True
        assert payload["provider_probe_requested"] is False
        assert payload["provider_probe_checks"] == {}
        assert payload["provider_probes"] == {}
        assert set(payload["provider_checks"]) == {"claude", "codex"}
        assert payload["provider_checks"]["claude"] is True
        assert payload["provider_checks"]["codex"] is True
        assert payload["hints"]

    @pytest.mark.asyncio
    async def test_doctor_probe_mode_calls_provider_probe(self, monkeypatch: pytest.MonkeyPatch):
        async def fake_health_check(self):
            return True

        def fake_which(name: str) -> str | None:
            return f"/usr/bin/{name}"

        def fake_probe(provider: str, **_: object) -> dict[str, object]:
            return {
                "status": "ok",
                "provider": provider,
                "model": "claude-opus-4-6" if provider == "claude" else "gpt-5.4",
                "reasoning_effort": "medium",
                "response": "OK",
            }

        monkeypatch.setattr(
            "avid.services.transcription.ChalnaTranscriptionService.health_check",
            fake_health_check,
        )
        monkeypatch.setattr("avid.cli.shutil.which", fake_which)
        monkeypatch.setattr("avid.cli.probe_provider", fake_probe)

        payload = await cmd_doctor(
            Namespace(
                chalna_url=None,
                provider=None,
                probe_providers=True,
                provider_model=None,
                provider_effort=None,
                json=True,
            )
        )

        assert payload["checks"]["provider"] is True
        assert payload["provider_probe_requested"] is True
        assert set(payload["provider_probes"]) == {"claude", "codex"}
        assert payload["provider_probe_checks"]["claude"] is True
        assert payload["provider_probe_checks"]["codex"] is True

    @pytest.mark.asyncio
    async def test_doctor_failure_payload_contains_provider_error(self, monkeypatch: pytest.MonkeyPatch):
        async def fake_health_check(self):
            return True

        def fake_which(name: str) -> str | None:
            return f"/usr/bin/{name}"

        def fake_probe(provider: str, **_: object) -> dict[str, object]:
            if provider == "codex":
                raise RuntimeError("Codex CLI error: bad auth")
            return {
                "status": "ok",
                "provider": provider,
                "model": "claude-opus-4-6",
                "reasoning_effort": "medium",
                "response": "OK",
            }

        monkeypatch.setattr(
            "avid.services.transcription.ChalnaTranscriptionService.health_check",
            fake_health_check,
        )
        monkeypatch.setattr("avid.cli.shutil.which", fake_which)
        monkeypatch.setattr("avid.cli.probe_provider", fake_probe)

        with pytest.raises(RuntimeError) as exc_info:
            await cmd_doctor(
                Namespace(
                    chalna_url=None,
                    provider=None,
                    probe_providers=True,
                    provider_model=None,
                    provider_effort=None,
                    json=True,
                )
            )

        payload = json.loads(str(exc_info.value))
        assert payload["checks"]["provider"] is False
        assert payload["provider_checks"]["codex"] is True
        assert payload["provider_probe_checks"]["codex"] is False
        assert payload["provider_probes"]["codex"]["status"] == "failed"
        assert "bad auth" in payload["provider_probes"]["codex"]["error"]

    @pytest.mark.asyncio
    async def test_doctor_requires_probe_flag_for_model_override(self):
        with pytest.raises(RuntimeError, match="--probe-providers"):
            await cmd_doctor(
                Namespace(
                    chalna_url=None,
                    provider=None,
                    probe_providers=False,
                    provider_model="gpt-5.4",
                    provider_effort="medium",
                    json=True,
                )
            )

    @pytest.mark.asyncio
    async def test_doctor_rejects_global_override_for_multiple_providers(self):
        with pytest.raises(RuntimeError, match="정확히 하나의 --provider"):
            await cmd_doctor(
                Namespace(
                    chalna_url=None,
                    provider=None,
                    probe_providers=True,
                    provider_model="gpt-5.4",
                    provider_effort="medium",
                    json=True,
                )
            )
