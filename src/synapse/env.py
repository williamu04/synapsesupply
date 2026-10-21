"""Local secrets: entry points load `.env` (git-ignored) without overriding the real environment.
On Cloud Foundry / AWS the variables come from the platform (`cf set-env`, Secrets Manager) instead."""
from pathlib import Path

from dotenv import load_dotenv


def load_env(path: str | Path = ".env") -> bool:
    return load_dotenv(path, override=False)
