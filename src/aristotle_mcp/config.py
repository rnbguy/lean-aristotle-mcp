"""Environment and Aristotle SDK configuration."""

from __future__ import annotations

import os

from dotenv import load_dotenv

_dotenv_loaded = False


def _ensure_dotenv() -> None:
    """Load .env once, when configuration is first accessed."""
    global _dotenv_loaded
    if not _dotenv_loaded:
        load_dotenv()
        _dotenv_loaded = True


def configure_sdk() -> None:
    """Configure aristotlelib with the environment API key, when present."""
    _ensure_dotenv()
    api_key = os.environ.get("ARISTOTLE_API_KEY")
    if api_key:
        from aristotlelib import set_api_key

        set_api_key(api_key)


def is_mock_mode() -> bool:
    """Check if the server is running in mock mode."""
    _ensure_dotenv()
    return os.environ.get("ARISTOTLE_MOCK", "").lower() in ("true", "1", "yes")


def has_api_key() -> bool:
    """Check if an API key is configured."""
    _ensure_dotenv()
    return bool(os.environ.get("ARISTOTLE_API_KEY"))
