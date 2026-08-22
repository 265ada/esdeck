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


def es_settings_path(es_config_dir: Path) -> Path:
    """Where ES-DE keeps es_settings.xml (it moved into settings/ in ES-DE 3)."""
    nested = Path(es_config_dir) / "settings" / "es_settings.xml"
    flat = Path(es_config_dir) / "es_settings.xml"
    return nested if nested.is_file() or not flat.is_file() else flat


def write_es_settings(es_config_dir: Path, values: dict, *, dry_run: bool = False,
                      create: bool = False) -> list[str]:
    """Set values in es_settings.xml in place, keeping every other line intact.

    ES-DE rewrites this file when it exits, so it must not be running.

    With create=True a minimal file is written when none exists yet - ES-DE
    only creates its settings on first launch, and the file is a flat list of
    elements with no root wrapper, so ES-DE reads our entries and fills in the
    rest of its defaults itself. Returns a description of each change made.
    """
    path = es_settings_path(Path(es_config_dir))
    if not path.is_file():
        if not create:
            raise FileNotFoundError(f"{path} - launch ES-DE once so it writes its settings")
        changes = [f"created {path}"] + [f"{k}: -> {v!r}" for k, v in values.items()]
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            body = "".join(f'<string name="{k}" value="{v}" />\n' for k, v in values.items())
            path.write_text('<?xml version="1.0"?>\n' + body, encoding="utf-8")
        return changes

    text = path.read_text(encoding="utf-8", errors="replace")
    changes = []

    for name, value in values.items():
        pattern = re.compile(rf'(<\w+\s+name="{re.escape(name)}"\s+value=")([^"]*)(")')
        m = pattern.search(text)
        if not m:
            changes.append(f"{name}: not present in es_settings.xml, skipped")
            continue
        if m.group(2) == value:
            changes.append(f"{name}: already {value!r}")
            continue
        changes.append(f"{name}: {m.group(2)!r} -> {value!r}")
        text = text[:m.start()] + m.group(1) + value + m.group(3) + text[m.end():]

    if not dry_run:
        backup = path.with_suffix(".xml.esdeck-backup")
        if not backup.exists():
            backup.write_text(path.read_text(encoding="utf-8", errors="replace"),
                              encoding="utf-8")
        path.write_text(text, encoding="utf-8")
    return changes


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
