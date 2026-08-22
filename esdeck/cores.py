"""Install RetroArch cores - the piece that makes a ROM actually launch.

A fresh RetroArch ships with no cores at all, so every ES-DE launch fails until
at least one is present. Cores come from the official libretro buildbot, the
same origin RetroArch's own "Core Downloader" and its winget installer use.

Downloads are opt-in: nothing here runs unless the caller passes dry_run=False.
"""

from __future__ import annotations

import io
import os
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

BUILDBOT = "https://buildbot.libretro.com/nightly/windows/x86_64/latest"
USER_AGENT = "esdeck/0.1 (+https://github.com/265ada/esdeck)"
TIMEOUT = 120
MAX_CORE_BYTES = 200 * 1024 * 1024

#: ES-DE system -> the libretro core ES-DE reaches for by default.
SYSTEM_CORES = {
    "nes": "mesen",
    "snes": "snes9x",
    "n64": "mupen64plus_next",
    "gb": "gambatte",
    "gbc": "gambatte",
    "gba": "mgba",
    "nds": "melonds",
    "megadrive": "genesis_plus_gx",
    "mastersystem": "genesis_plus_gx",
    "gamegear": "genesis_plus_gx",
    "psx": "swanstation",
    "psp": "ppsspp",
    "saturn": "yabause",
    "dreamcast": "flycast",
    "pcengine": "mednafen_pce",
    "atari2600": "stella",
    "atari7800": "prosystem",
    "atarilynx": "handy",
    "neogeo": "fbneo",
    "arcade": "fbneo",
    "dos": "dosbox_pure",
    "scummvm": "scummvm",
}


def retroarch_dirs() -> tuple[Path | None, Path | None]:
    """(install dir, cores dir) for RetroArch, or (None, None) if not found."""
    candidates = [
        Path(r"C:\RetroArch-Win64"),
        Path(os.environ.get("APPDATA", "")) / "RetroArch",
        Path(r"C:\Program Files\RetroArch"),
    ]
    for base in candidates:
        if (base / "retroarch.exe").is_file():
            return base, base / "cores"
    return None, None


def installed_cores(cores_dir: Path) -> set[str]:
    if not cores_dir.is_dir():
        return set()
    return {p.name.replace("_libretro.dll", "") for p in cores_dir.glob("*_libretro.dll")}


def cores_for_systems(rom_dir: Path) -> list[str]:
    """Cores needed for the systems that actually have games in them."""
    rom_dir = Path(rom_dir)
    needed = []
    for key, core in SYSTEM_CORES.items():
        d = rom_dir / key
        if d.is_dir() and any(d.iterdir()) and core not in needed:
            needed.append(core)
    return needed


def core_url(core: str) -> str:
    return f"{BUILDBOT}/{core}_libretro.dll.zip"


def download_core(core: str, cores_dir: Path, *, dry_run: bool = True, log=print) -> bool:
    """Fetch one core zip from the libretro buildbot and unpack the .dll."""
    url = core_url(core)
    dest = Path(cores_dir) / f"{core}_libretro.dll"
    if dest.is_file():
        log(f"  ok       {core} already installed")
        return True
    if dry_run:
        log(f"  download {core}  <- {url}")
        return True

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = resp.read(MAX_CORE_BYTES + 1)
    except (urllib.error.URLError, OSError) as exc:
        log(f"  ERROR    {core}: {exc}")
        return False
    if len(payload) > MAX_CORE_BYTES:
        log(f"  ERROR    {core}: archive larger than {MAX_CORE_BYTES} bytes, refusing")
        return False

    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            names = [n for n in zf.namelist() if n.endswith(".dll") and "/" not in n]
            if not names:
                log(f"  ERROR    {core}: no .dll inside the archive")
                return False
            Path(cores_dir).mkdir(parents=True, exist_ok=True)
            data = zf.read(names[0])
    except (zipfile.BadZipFile, KeyError) as exc:
        log(f"  ERROR    {core}: bad archive ({exc})")
        return False

    dest.write_bytes(data)
    log(f"  installed {core} ({len(data) // 1024} KB)")
    return True


def run(rom_dir: Path, *, only: list[str] | None = None, dry_run: bool = True,
        log=print) -> int:
    base, cores_dir = retroarch_dirs()
    if cores_dir is None:
        log("RetroArch not found - install it first (esdeck bootstrap --packages retroarch --yes)")
        return 0
    wanted = only or cores_for_systems(rom_dir)
    if not wanted:
        log(f"No cores needed: nothing in {rom_dir} maps to a libretro core.")
        return 0
    log(f"RetroArch: {base}")
    log(f"Cores dir: {cores_dir}  ({len(installed_cores(cores_dir))} installed)")
    ok = 0
    for core in wanted:
        ok += bool(download_core(core, cores_dir, dry_run=dry_run, log=log))
    return ok
