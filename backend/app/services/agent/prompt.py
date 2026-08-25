from pathlib import Path

_PROMPT_DIR = Path(__file__).with_name("prompts")


def _read_prompt(filename: str) -> str:
    return (_PROMPT_DIR / filename).read_text(encoding="utf-8").strip()


AGENT_PROMPT = _read_prompt("agent.md")


__all__ = [
    "AGENT_PROMPT",
]
