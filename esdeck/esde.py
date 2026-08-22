"""Read ES-DE's own system definitions.

ES-DE ships es_systems.xml describing every system it supports - 195 of them -
including the folder name and the file extensions each one accepts. Using that
file as the source of truth means esdeck supports exactly what the installed
ES-DE supports, including systems added by future ES-DE releases and any the
user defines in custom_systems/.

Falls back to a small built-in table when ES-DE is not installed, so scanning
still works on a machine that has not been set up yet.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

#: %CORE_RETROARCH%\something_libretro.dll inside a launch command.
_CORE_RE = re.compile(r"%CORE_RETROARCH%[\\/]([A-Za-z0-9_-]+)_libretro\.dll", re.I)

ES_DE_RESOURCE_DIRS = (
    r"C:\Program Files\ES-DE\resources\systems\windows",
    r"C:\Program Files (x86)\ES-DE\resources\systems\windows",
    "/usr/share/es-de/resources/systems/linux",
    "/usr/local/share/es-de/resources/systems/linux",
)


@dataclass
class EsSystem:
    key: str                       # folder name, e.g. "psx"
    fullname: str = ""             # e.g. "Sony PlayStation"
    exts: set = field(default_factory=set)   # lowercase, with leading dot
    commands: list = field(default_factory=list)   # (label, command) in ES-DE order

    @property
    def default_core(self) -> str | None:
        """The libretro core ES-DE uses unless told otherwise.

        ES-DE runs the *first* command listed for a system, so that is the core
        that has to be installed. Guessing instead produces exactly the error
        this exists to prevent: "couldn't find emulator core file".
        """
        for _label, cmd in self.commands:
            m = _CORE_RE.search(cmd)
            if m:
                return m.group(1).lower()
        return None

    def __repr__(self) -> str:      # keeps test failures readable
        return f"EsSystem({self.key!r}, {len(self.exts)} exts)"


def find_es_systems_xml(es_config_dir: Path | None = None) -> list[Path]:
    """Every es_systems.xml worth reading, custom definitions last (they win)."""
    found = []
    for d in ES_DE_RESOURCE_DIRS:
        p = Path(d) / "es_systems.xml"
        if p.is_file():
            found.append(p)
            break
    if es_config_dir:
        custom = Path(es_config_dir) / "custom_systems" / "es_systems.xml"
        if custom.is_file():
            found.append(custom)
    return found


def parse(path: Path) -> dict:
    """{key: EsSystem} from one es_systems.xml."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return {}
    out = {}
    for node in root.findall("system"):
        key = (node.findtext("name") or "").strip()
        if not key:
            continue
        exts = {e.lower() for e in (node.findtext("extension") or "").split()
                if e.startswith(".")}
        commands = [((c.get("label") or "").strip(), (c.text or "").strip())
                    for c in node.findall("command")]
        out[key] = EsSystem(key, (node.findtext("fullname") or "").strip(),
                            exts, commands)
    return out


@lru_cache(maxsize=4)
def load(es_config_dir: str | None = None) -> dict:
    """All systems ES-DE knows about, or {} when ES-DE is not installed."""
    systems: dict = {}
    for path in find_es_systems_xml(Path(es_config_dir) if es_config_dir else None):
        systems.update(parse(path))
    return systems


def extension_index(systems: dict) -> dict:
    """{extension: [system keys]} - one extension usually maps to many systems."""
    index: dict[str, list[str]] = {}
    for key, sysdef in systems.items():
        for ext in sysdef.exts:
            index.setdefault(ext, [])
            if key not in index[ext]:
                index[ext].append(key)
    return index
