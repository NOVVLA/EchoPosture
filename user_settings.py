"""Privacy-minimal user settings for mode selection.

Only product preferences are stored. Camera frames, face crops, templates,
embeddings, measurements, and identity state are never accepted by this API.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Optional

from vision_modes import VISION_MODE_COMPATIBILITY, VISION_MODE_SPECS


SETTINGS_VERSION = 1
VALID_MODES = frozenset(spec.mode for spec in VISION_MODE_SPECS)


@dataclass(frozen=True)
class UserSettings:
    vision_mode: str = VISION_MODE_COMPATIBILITY
    ask_on_startup: bool = True


def settings_path(env: Optional[Mapping[str, str]] = None) -> Path:
    values = os.environ if env is None else env
    local_app_data = values.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / "EchoPosture" / "settings.json"


def load_user_settings(path: Optional[Path] = None) -> UserSettings:
    target = path or settings_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return UserSettings()
    mode = payload.get("vision_mode")
    ask = payload.get("ask_on_startup")
    if mode not in VALID_MODES or not isinstance(ask, bool):
        return UserSettings()
    return UserSettings(vision_mode=mode, ask_on_startup=ask)


def save_user_settings(settings: UserSettings, path: Optional[Path] = None) -> Path:
    if settings.vision_mode not in VALID_MODES:
        raise ValueError(f"unknown vision mode: {settings.vision_mode}")
    target = path or settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    payload = {"version": SETTINGS_VERSION, **asdict(settings)}
    temporary.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    return target


__all__ = ["UserSettings", "load_user_settings", "save_user_settings", "settings_path"]
