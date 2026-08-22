"""System detection: map ROM files to ES-DE system folders.

ES-DE expects ROMs under <ROMDir>/<system>/, where <system> is one of the
short names below (matching es_systems.xml). Detection is deliberately
conservative: ambiguous extensions resolve to a candidate list and the
caller decides (usually via a directory-name hint or the user).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class System:
    key: str          # ES-DE folder name
    name: str         # human readable
    exts: tuple       # lowercase, leading dot
    aliases: tuple = field(default=())   # folder-name hints seen in the wild


SYSTEMS: tuple[System, ...] = (
    System("nes", "Nintendo Entertainment System", (".nes", ".fds", ".unf", ".unif"),
           ("famicom", "nintendo entertainment system")),
    System("snes", "Super Nintendo", (".smc", ".sfc", ".swc", ".fig"),
           ("super nintendo", "super famicom", "sfc")),
    System("n64", "Nintendo 64", (".n64", ".z64", ".v64", ".ndd"), ("nintendo 64",)),
    System("gc", "Nintendo GameCube", (".gcm", ".gcz", ".rvz", ".nkit.iso"), ("gamecube", "ngc")),
    System("wii", "Nintendo Wii", (".wbfs", ".wad",), ()),
    System("wiiu", "Nintendo Wii U", (".wux", ".wua", ".rpx"), ("wii u",)),
    System("switch", "Nintendo Switch", (".nsp", ".xci", ".nsz", ".xcz"), ()),
    System("gb", "Game Boy", (".gb",), ("gameboy",)),
    System("gbc", "Game Boy Color", (".gbc",), ("gameboy color",)),
    System("gba", "Game Boy Advance", (".gba", ".agb"), ("gameboy advance",)),
    System("nds", "Nintendo DS", (".nds", ".dsi"), ("ds",)),
    System("n3ds", "Nintendo 3DS", (".3ds", ".3dsx", ".cia"), ("3ds",)),
    System("megadrive", "Sega Mega Drive / Genesis", (".md", ".gen", ".smd"),
           ("genesis", "mega drive", "megadrive")),
    System("mastersystem", "Sega Master System", (".sms",), ("master system",)),
    System("gamegear", "Sega Game Gear", (".gg",), ("game gear",)),
    System("saturn", "Sega Saturn", (), ()),
    System("dreamcast", "Sega Dreamcast", (".gdi", ".cdi"), ("dc",)),
    System("psx", "Sony PlayStation", (".pbp", ".ecm"), ("ps1", "playstation")),
    System("ps2", "Sony PlayStation 2", (".cso", ".chd.ps2"), ("playstation 2",)),
    System("ps3", "Sony PlayStation 3", (".pkg", ".ps3"), ("playstation 3",)),
    System("psp", "Sony PlayStation Portable", (".cso", ".dax"), ("playstation portable",)),
    System("psvita", "Sony PlayStation Vita", (".vpk",), ("vita",)),
    System("atari2600", "Atari 2600", (".a26",), ("2600",)),
    System("atari7800", "Atari 7800", (".a78",), ("7800",)),
    System("atarilynx", "Atari Lynx", (".lnx",), ("lynx",)),
    System("pcengine", "NEC PC Engine / TurboGrafx-16", (".pce", ".sgx"),
           ("turbografx", "turbografx-16", "tg16")),
    System("neogeo", "SNK Neo Geo", (".neo",), ("neo geo",)),
    System("arcade", "Arcade", (), ("mame", "fbneo", "fba")),
    System("dos", "MS-DOS", (".dosz",), ("msdos", "ms-dos", "pc")),
    System("scummvm", "ScummVM", (".scummvm",), ("scumm",)),
    System("windows", "Windows / PC", (".lnk", ".url"), ("pc games", "win", "pcwindows")),
    System("ports", "Ports", (), ()),
)

BY_KEY = {s.key: s for s in SYSTEMS}

# Extensions that several systems share; never auto-assign on extension alone.
AMBIGUOUS_EXTS = {
    ".iso": ("ps2", "psp", "gc", "wii", "saturn", "dreamcast", "windows", "ps3"),
    ".cue": ("psx", "saturn", "pcengine", "dreamcast", "neogeocd"),
    ".bin": ("psx", "saturn", "megadrive"),
    ".chd": ("psx", "ps2", "dreamcast", "saturn", "pcengine", "arcade"),
    ".img": ("psx", "dreamcast", "windows"),
    ".zip": ("arcade", "neogeo", "nes", "snes", "megadrive"),
    ".7z": ("arcade", "neogeo", "snes"),
    ".rvz": ("gc", "wii"),
    ".wad": ("wii", "ports"),
    ".cso": ("psp", "ps2"),
    ".nds": ("nds",),
}

# Installer / PC-game markers -> the "windows" system, handled as an install job.
INSTALLER_NAMES = ("setup.exe", "install.exe", "autorun.exe")
INSTALLER_EXTS = (".exe", ".msi")
ARCHIVE_EXTS = (".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz", ".tgz")
DISC_EXTS = (".iso", ".cue", ".bin", ".chd", ".gdi", ".cdi", ".img", ".mds", ".mdf", ".ccd")
DOC_NAMES = ("readme", "read me", "read-me", "install", "instructions", "setup",
             "notes", "info", "how to", "howto", "liesmich")
DOC_EXTS = (".txt", ".md", ".nfo", ".rtf", ".diz", ".1st")

_EXT_INDEX: dict[str, list[str]] = {}
for _s in SYSTEMS:
    for _e in _s.exts:
        _EXT_INDEX.setdefault(_e, []).append(_s.key)
for _e, _keys in AMBIGUOUS_EXTS.items():
    for _k in _keys:
        _EXT_INDEX.setdefault(_e, [])
        if _k not in _EXT_INDEX[_e]:
            _EXT_INDEX[_e].append(_k)


def systems_for_ext(ext: str) -> list[str]:
    """Candidate system keys for a file extension, best guess first."""
    return list(_EXT_INDEX.get(ext.lower(), []))


def system_from_hint(text: str) -> str | None:
    """Resolve a folder or archive name to a system key, e.g. 'PSX Games'."""
    t = " " + text.lower().replace("_", " ").replace("-", " ") + " "
    best: tuple[int, str] | None = None
    for s in SYSTEMS:
        for cand in (s.key, s.name.lower(), *s.aliases):
            c = cand.lower()
            if f" {c} " in t or t.strip() == c:
                if best is None or len(c) > best[0]:
                    best = (len(c), s.key)
    return best[1] if best else None


def is_doc(filename: str) -> bool:
    """True for README-ish files worth parsing for install instructions."""
    low = filename.lower()
    stem, _, ext = low.rpartition(".")
    if not stem:
        stem, ext = low, ""
    if "." + ext not in DOC_EXTS:
        return False
    return any(n in stem for n in DOC_NAMES) or stem in ("readme", "read_me")
