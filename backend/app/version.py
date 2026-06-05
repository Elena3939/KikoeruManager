from __future__ import annotations

import os
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path


_VERSION_ENV_KEYS = (
    "KIKOERUMANAGER_VERSION",
    "APP_VERSION",
)
_VERSION_FILE_NAME = "version.txt"


def _normalize_version(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    if text.startswith("refs/tags/"):
        text = text.removeprefix("refs/tags/")

    if re.match(r"^v\d+\.\d+\.\d+(?:[-+].*)?$", text, flags=re.IGNORECASE):
        text = text[1:]

    return text.strip()


def _read_env_version() -> str:
    for key in _VERSION_ENV_KEYS:
        value = _normalize_version(os.environ.get(key, ""))
        if value:
            return value
    return ""


def _read_bundled_version_file() -> str:
    candidates: list[Path] = []

    bundle_root = getattr(sys, "_MEIPASS", "")
    if bundle_root:
        candidates.append(Path(bundle_root) / "backend" / "app" / _VERSION_FILE_NAME)
    else:
        candidates.append(Path(__file__).with_name(_VERSION_FILE_NAME))

    for path in candidates:
        try:
            value = _normalize_version(path.read_text(encoding="utf-8").splitlines()[0])
        except Exception:
            continue
        if value:
            return value
    return ""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_git_version() -> str:
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0", "--match", "v*.*.*"],
            cwd=_repo_root(),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except Exception:
        return ""

    if result.returncode != 0:
        return ""
    return _normalize_version(result.stdout)


@lru_cache(maxsize=1)
def get_app_version() -> str:
    return _read_env_version() or _read_git_version() or _read_bundled_version_file() or "dev"
