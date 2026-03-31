"""LLM configuration for the demo agents."""

import os

from langchain_anthropic import ChatAnthropic

MODEL = os.getenv("DEMO_MODEL", "claude-haiku-4-5-20251001")

# Hard timeout on every LLM call. Prevents the UI from getting stuck on
# "Processing..." indefinitely if the model hangs or the API is slow.
LLM_TIMEOUT_SECONDS = int(os.getenv("DEMO_LLM_TIMEOUT", "60"))


def get_llm(**kwargs) -> ChatAnthropic:
    """Get a configured Claude Haiku instance for demo agents."""
    return ChatAnthropic(
        model=MODEL,
        temperature=0,
        max_tokens=1024,
        timeout=LLM_TIMEOUT_SECONDS,
        **kwargs,
    )
