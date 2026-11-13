"""Runtime configuration, read from environment / .env."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    provider: str
    model: str
    api_key: str
    fallback_key: str = ""


def load_settings() -> Settings:
    api_key = os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY", "")
    if not api_key or api_key == "your-api-key-here":
        raise RuntimeError("API_KEY is not set. Copy .env.example to .env and add your key.")
    return Settings(
        provider=os.getenv("MODEL_PROVIDER", "google"),
        model=os.getenv("MODEL_NAME", "gemini-3.5-flash-lite"),
        api_key=api_key,
        fallback_key=os.getenv("FALLBACK_KEY", ""),
    )
