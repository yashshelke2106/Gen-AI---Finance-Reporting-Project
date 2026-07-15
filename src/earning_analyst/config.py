"""Central configuration, loaded from environment / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional at runtime
    pass


DEFAULT_MODEL = "claude-3-5-sonnet-latest"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_EDGAR_UA = "earnings-analyst example@example.com"


@dataclass
class Settings:
    provider: str = "anthropic"  # 'anthropic' | 'gemini'
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None
    model: str = DEFAULT_MODEL
    gemini_model: str = DEFAULT_GEMINI_MODEL
    edgar_user_agent: str = DEFAULT_EDGAR_UA
    max_tool_iterations: int = 8
    request_timeout: int = 30

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            provider=os.getenv("EARNINGS_ANALYST_PROVIDER", "anthropic").lower(),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            gemini_api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"),
            model=os.getenv("EARNINGS_ANALYST_MODEL", DEFAULT_MODEL),
            gemini_model=os.getenv("EARNINGS_ANALYST_GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
            edgar_user_agent=os.getenv("SEC_EDGAR_USER_AGENT", DEFAULT_EDGAR_UA),
        )


settings = Settings.from_env()
