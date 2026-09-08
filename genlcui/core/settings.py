"""Persisted user settings.

Stored as JSON under $XDG_CONFIG_HOME/genlcui/settings.json. Everything that
identifies a speaker keys off its serial number, never its address.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

APP_NAME = "genlcui"
PRESET_COUNT = 4


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / APP_NAME


@dataclass
class Preset:
    """A level slot.

    `db` is None until captured. Presets are captured from the physical knob,
    never typed -- see docs/DESIGN.md. A stored level is therefore always one
    the user has just listened to.
    """

    name: str
    db: Optional[float] = None

    @property
    def is_set(self) -> bool:
        return self.db is not None


DEFAULT_PRESET_NAMES = ("Quiet", "Listening", "Mixing", "Loud")


def _default_presets() -> List[Preset]:
    return [Preset(name=n) for n in DEFAULT_PRESET_NAMES[:PRESET_COUNT]]


@dataclass
class Settings:
    # Safety ceiling on programmatic writes. See docs/DESIGN.md.
    max_volume_db: float = -30.0
    default_volume_db: float = -50.0

    presets: List[Preset] = field(default_factory=_default_presets)

    # serial -> user-chosen name, e.g. {"1093534": "Left"}
    speaker_names: Dict[str, str] = field(default_factory=dict)

    start_minimised: bool = True
    wake_on_start: bool = False

    # -- persistence -----------------------------------------------------

    @classmethod
    def path(cls) -> Path:
        return config_dir() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        path = cls.path()
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            logger.warning("could not read %s; using defaults", path, exc_info=True)
            return cls()

        presets = [Preset(**p) for p in raw.pop("presets", [])] or _default_presets()
        while len(presets) < PRESET_COUNT:
            presets.append(Preset(name=DEFAULT_PRESET_NAMES[len(presets)]))
        known = {f.name for f in cls.__dataclass_fields__.values()}
        clean = {k: v for k, v in raw.items() if k in known}
        return cls(presets=presets[:PRESET_COUNT], **clean)

    def save(self) -> None:
        path = self.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2))
        tmp.replace(path)          # atomic, so a crash cannot truncate settings

    # -- helpers ---------------------------------------------------------

    def name_for(self, serial: int, fallback: str) -> str:
        return self.speaker_names.get(str(serial), fallback)

    def set_name(self, serial: int, name: str) -> None:
        if name:
            self.speaker_names[str(serial)] = name
        else:
            self.speaker_names.pop(str(serial), None)

    def capture_preset(self, index: int, db: float) -> Preset:
        """Store a level captured from the knob.

        Deliberately does NOT clamp to max_volume_db: the value came from the
        physical control, so the user has already heard it, and silently
        storing something quieter than what they just approved would defeat
        the point. The UI asks about raising the ceiling instead.
        """
        preset = self.presets[index]
        preset.db = float(db)
        return preset

    def exceeds_ceiling(self, db: float) -> bool:
        return db > self.max_volume_db
