"""Edit-decision prompt profiles shared by podcast-cut analyzers."""

from functools import lru_cache
from pathlib import Path
from typing import Final, Literal

PromptProfile = Literal["podcast", "ai_frontier"]
PROMPT_PROFILES: Final[tuple[PromptProfile, ...]] = ("podcast", "ai_frontier")
AI_FRONTIER_PROMPT_SHA256: Final = (
    "71965cc1e42be15d216ef26a8306b48ac7393c71876572fef1479fabd20fd28c"
)

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_AI_FRONTIER_PROMPT_PATH = _PROMPTS_DIR / "ai_frontier.md"


def _validate_template(template: str, profile: str) -> str:
    if template.count("{segments}") != 1:
        raise RuntimeError(
            f"Prompt profile {profile!r} must contain exactly one {{segments}} placeholder"
        )
    return template


@lru_cache(maxsize=1)
def _load_ai_frontier_prompt() -> str:
    try:
        template = _AI_FRONTIER_PROMPT_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            f"Unable to load AI Frontier prompt: {_AI_FRONTIER_PROMPT_PATH}"
        ) from exc
    return _validate_template(template, "ai_frontier")


def load_edit_decision_prompt(
    prompt_profile: PromptProfile | str,
    *,
    podcast_prompt: str,
) -> str:
    """Return the base Edit Decision template for a named profile.

    ``podcast_prompt`` is supplied by the calling analyzer so the established
    Codex and Claude podcast prompts remain byte-for-byte unchanged. Both
    analyzers share the packaged AI Frontier template.
    """
    if prompt_profile == "podcast":
        return _validate_template(podcast_prompt, "podcast")
    if prompt_profile == "ai_frontier":
        return _load_ai_frontier_prompt()
    choices = ", ".join(PROMPT_PROFILES)
    raise ValueError(f"Unsupported prompt profile {prompt_profile!r}; expected one of: {choices}")


def render_edit_decision_prompt(
    prompt_profile: PromptProfile | str,
    segments_text: str,
    *,
    podcast_prompt: str,
) -> str:
    """Render only the selected base template with transcript segments."""
    template = load_edit_decision_prompt(
        prompt_profile,
        podcast_prompt=podcast_prompt,
    )
    try:
        return template.format(segments=segments_text)
    except (IndexError, KeyError, ValueError) as exc:
        raise RuntimeError(f"Invalid {prompt_profile!r} prompt template") from exc
