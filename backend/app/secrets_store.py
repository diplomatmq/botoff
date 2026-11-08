from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import Settings

_FIELDS = ("secret_key", "encryption_key")


def _read(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {field: str(data[field]) for field in _FIELDS if data.get(field)}


def _write_new(path: Path, payload: dict[str, str]) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def load_or_create_secrets(path: Path) -> dict[str, str]:
    for _ in range(5):
        data = _read(path)
        if all(data.get(field) for field in _FIELDS):
            return data
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {field: data.get(field) or secrets.token_urlsafe(48) for field in _FIELDS}
        try:
            if data:
                path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            else:
                _write_new(path, payload)
        except FileExistsError:
            continue
        return payload
    return _read(path)


def apply_generated_secrets(settings: Settings) -> None:
    if settings.secret_key and settings.encryption_key:
        return
    stored = load_or_create_secrets(Path(settings.secrets_file))
    if not settings.secret_key:
        settings.secret_key = stored.get("secret_key", "")
    if not settings.encryption_key:
        settings.encryption_key = stored.get("encryption_key", "")
