"""esdeck configuration and ES-DE path discovery.

Config lives at ~/.esdeck/config.json so the same repo works unchanged on
every machine; only this file differs per computer. `esdeck profile` moves
the machine-independent half between computers.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict, field
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("ESDECK_HOME", Path.home() / ".esdeck"))
CONFIG_PATH = CONFIG_DIR / "config.json"

#: Keys that are machine-specific and therefore excluded from a shared profile.
LOCAL_KEYS = ("rom_dir", "es_config_dir", "install_dir", "source_dirs", "media_dir")


@dataclass
class Config:
    rom_dir: str = ""
    es_config_dir: str = ""
    media_dir: str = ""
    install_dir: str = ""            # where Windows/PC games get installed
    source_dirs: list[str] = field(default_factory=list)
    auto_extract: bool = True
    keep_source: bool = True         # copy, never move, by default
    make_m3u: bool = True
    systems_enabled: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def rom_path(self) -> Path:
        return Path(self.rom_dir)


def default_es_config_dir() -> Path:
    """ES-DE keeps settings in ~/ES-DE on Windows/Linux (portable installs vary)."""
    env = os.environ.get("ESDE_APPDATA_DIR")
    if env:
        return Path(env)
    return Path.home() / "ES-DE"


def default_rom_dir() -> Path:
    return Path.home() / "ROMs"


def read_es_settings(es_config_dir: Path) -> dict:
    """Pull a few values out of ES-DE's es_settings.xml without an XML schema."""
    path = Path(es_config_dir) / "settings" / "es_settings.xml"
    if not path.is_file():
        path = Path(es_config_dir) / "es_settings.xml"
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    out = {}
    for m in re.finditer(r'<(\w+)\s+name="([^"]+)"\s+value="([^"]*)"\s*/>', text):
        out[m.group(2)] = m.group(3)
    return out


def discover() -> Config:
    """Best-effort autodetect for a fresh machine."""
    es_dir = default_es_config_dir()
    settings = read_es_settings(es_dir)
    rom = settings.get("ROMDirectory") or ""
    if not rom or rom == "%ROMPATH%":
        rom = str(default_rom_dir())
    media = settings.get("MediaDirectory") or str(Path(es_dir) / "downloaded_media")
    return Config(
        rom_dir=rom,
        es_config_dir=str(es_dir),
        media_dir=media,
        install_dir=str(Path(rom) / "windows"),
    )


def load(path: Path | None = None) -> Config:
    p = Path(path) if path else CONFIG_PATH
    if not p.is_file():
        return discover()
    data = json.loads(p.read_text(encoding="utf-8"))
    known = {f for f in Config().to_dict()}
    return Config(**{k: v for k, v in data.items() if k in known})


def save(cfg: Config, path: Path | None = None) -> Path:
    p = Path(path) if path else CONFIG_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg.to_dict(), indent=2), encoding="utf-8")
    return p


def profile_from(cfg: Config) -> dict:
    """The shareable half of a config: preferences, not paths."""
    return {k: v for k, v in cfg.to_dict().items() if k not in LOCAL_KEYS}


def apply_profile(cfg: Config, profile: dict) -> Config:
    data = cfg.to_dict()
    for k, v in profile.items():
        if k in data and k not in LOCAL_KEYS:
            data[k] = v
    return Config(**data)
