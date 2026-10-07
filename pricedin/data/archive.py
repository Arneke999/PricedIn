"""Immutable raw archive.

Bodies are stored content-addressed (sha256), so an unchanged response takes no new
space and nothing is ever overwritten. An append-only manifest per kind logs every fetch.
Kinds are prefixed by vendor (e.g. "sec/...") so vendor data can be purged separately
when its terms require it (Hard rule 4).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from pricedin import config

MANIFEST = "manifest.jsonl"


def store(kind: str, url: str, body: bytes) -> dict:
    folder = config.raw_dir() / kind
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(body).hexdigest()
    try:
        with open(folder / f"{digest}.json", "xb") as f:
            f.write(body)
    except FileExistsError:
        pass
    entry = {
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "url": url,
        "sha256": digest,
        "bytes": len(body),
    }
    with open(folder / MANIFEST, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def latest(kind: str) -> tuple[bytes, dict] | None:
    """The most recently fetched body for a kind, with its manifest entry."""
    folder = config.raw_dir() / kind
    manifest = folder / MANIFEST
    if not manifest.exists():
        return None
    entry = json.loads(manifest.read_text().splitlines()[-1])
    return (folder / f"{entry['sha256']}.json").read_bytes(), entry


def path_for(kind: str) -> Path:
    return config.raw_dir() / kind
