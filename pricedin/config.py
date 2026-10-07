"""Runtime configuration from the environment or a local .env file.

Nothing personal lives in code. The SEC User-Agent and every API key come from here.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class ConfigError(RuntimeError):
    pass


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("\"'")
    return values


def get(key: str) -> str | None:
    return os.environ.get(key) or _read_env_file(ENV_FILE).get(key)


def sec_user_agent() -> str:
    """The SEC requires a name and contact email on every request."""
    ua = get("SEC_USER_AGENT")
    if not ua or not _EMAIL.search(ua) or "example.com" in ua:
        raise ConfigError(
            "SEC_USER_AGENT is not set. The SEC requires your name and contact email, "
            'e.g. SEC_USER_AGENT="Jane Doe jane@mail.com". Copy .env.example to .env '
            "and fill it in."
        )
    return ua


def raw_dir() -> Path:
    return Path(get("PRICEDIN_RAW_DIR") or ROOT / "raw")


def port() -> int:
    return int(get("PRICEDIN_PORT") or 5000)
