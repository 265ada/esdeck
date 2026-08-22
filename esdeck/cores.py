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

from . import esde

BUILDBOT = "https://buildbot.libretro.com/nightly/windows/x86_64/latest"
USER_AGENT = "esdeck/0.1 (+https://github.com/265ada/esdeck)"
TIMEOUT = 120
MAX_CORE_BYTES = 200 * 1024 * 1024

#: ES-DE system -> the libretro core ES-DE reaches for by default. Covers the
#: systems that have a working libretro core; the rest of ES-DE's 195 systems
#: either use a standalone emulator or have no core, and are skipped.
#:
#: An empty string means "no libretro core on the Windows buildbot" - Vita and
#: PICO-8 need standalone emulators, and a few obscure cores are not built for
#: x86_64 Windows at all. Verified against the buildbot's own index.
SYSTEM_CORES = {
    # Nintendo
    "nes": "mesen", "famicom": "mesen", "fds": "mesen",
    "snes": "snes9x", "sfc": "snes9x", "snesna": "snes9x", "satellaview": "snes9x",
    "sufami": "snes9x",
    "n64": "mupen64plus_next", "n64dd": "mupen64plus_next",
    "gb": "gambatte", "gbc": "gambatte", "gba": "mgba",
    "nds": "melonds", "virtualboy": "mednafen_vb",
    "gc": "dolphin", "wii": "dolphin",
    "pokemini": "pokemini", "gameandwatch": "gw",
    # Sega
    "megadrive": "genesis_plus_gx", "genesis": "genesis_plus_gx",
    "mastersystem": "genesis_plus_gx", "gamegear": "genesis_plus_gx",
    "sg-1000": "genesis_plus_gx", "megacd": "genesis_plus_gx",
    "segacd": "genesis_plus_gx", "sega32x": "picodrive",
    "saturn": "mednafen_saturn", "dreamcast": "flycast",
    # Sony
    "psx": "swanstation", "psp": "ppsspp", "psvita": "",
    # NEC
    "pcengine": "mednafen_pce", "pcenginecd": "mednafen_pce",
    "tg16": "mednafen_pce", "tg-cd": "mednafen_pce",
    "supergrafx": "mednafen_supergrafx", "pcfx": "mednafen_pcfx",
    # SNK
    "neogeo": "fbneo", "neogeocd": "neocd",
    "ngp": "mednafen_ngp", "ngpc": "mednafen_ngp",
    # Atari
    "atari2600": "stella", "atari5200": "atari800", "atari7800": "prosystem",
    "atarilynx": "handy", "atarijaguar": "virtualjaguar", "atarist": "hatari",
    "atari800": "atari800",
    # Bandai / other handhelds
    "wonderswan": "mednafen_wswan", "wonderswancolor": "mednafen_wswan",
    # Computers
    "c64": "vice_x64", "vic20": "vice_xvic", "plus4": "vice_xplus4",
    "amiga": "puae", "amiga600": "puae", "amiga1200": "puae", "cdtv": "puae",
    "cd32": "puae", "msx": "bluemsx", "msx2": "bluemsx", "msxturbor": "bluemsx",
    "zxspectrum": "fuse", "zx81": "81", "amstradcpc": "cap32",
    "x68000": "px68k", "pc98": "np2kai", "apple2": "mame",
    # Consoles, misc
    "3do": "opera", "colecovision": "bluemsx", "intellivision": "freeintv",
    "vectrex": "vecx", "channelf": "freechaf", "odyssey2": "o2em",
    "videopac": "o2em", "arcadia": "mame", "astrocade": "mame",
    "supervision": "potator", "gamate": "", "creativision": "",
    # Arcade
    "arcade": "fbneo", "mame": "mame", "fbneo": "fbneo", "cps1": "fbneo",
    "cps2": "fbneo", "cps3": "fbneo", "daphne": "mame",
    # PC / engines / ports
    "dos": "dosbox_pure", "pc": "dosbox_pure", "scummvm": "scummvm",
    "doom": "prboom", "quake": "tyrquake", "wolfenstein3d": "ecwolf",
    "lowresnx": "lowresnx", "uzebox": "uzem", "tic80": "tic80",
    "pico8": "", "solarus": "", "easyrpg": "easyrpg",
}

#: Cores worth having on any machine, before a single game is added. Chosen for
#: coverage of the common systems at a sane download size - fbneo alone is 60 MB,
#: so arcade is deliberately left to --all or to the first arcade game added.
COMMON_CORES = (
    "mesen", "snes9x", "mupen64plus_next", "gambatte", "mgba", "melonds",
    "genesis_plus_gx", "swanstation", "flycast", "mednafen_pce", "dosbox_pure",
)


def all_cores() -> list:
    """Every core esdeck knows how to fetch, de-duplicated."""
    out = []
    for core in known_core_systems().values():
        if core and core not in out:
            out.append(core)
    return out


#: Cores ES-DE references that libretro does not build for Windows x86_64.
#: Verified against the buildbot index; requesting them only yields a 404.
UNAVAILABLE = {"mess2015", "gamate", "crvision", "solarus"}


def core_for_system(key: str) -> str | None:
    """The core ES-DE will actually launch for a system.

    ES-DE runs the first <command> listed for each system, so that is the core
    that must be installed. Reading it beats guessing: a hand-written map had
    psx on swanstation while ES-DE calls Beetle PSX, which fails at launch with
    "couldn't find emulator core file". The built-in table is only a fallback
    for machines where ES-DE is not installed yet.
    """
    sysdef = esde.load().get(key)
    if sysdef is not None:
        found = sysdef.default_core
        if found and found not in UNAVAILABLE:
            return found
    fallback = SYSTEM_CORES.get(key)
    return fallback if fallback and fallback not in UNAVAILABLE else None


def known_core_systems() -> dict:
    """{system: core} for everything that can run on a libretro core."""
    out = {k: v for k, v in SYSTEM_CORES.items() if v}
    for key, sysdef in esde.load().items():
        core = sysdef.default_core
        if core and core not in UNAVAILABLE:
            out[key] = core
    return {k: v for k, v in out.items() if v and v not in UNAVAILABLE}


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
    for key, core in known_core_systems().items():
        d = rom_dir / key
        if core and d.is_dir() and any(d.iterdir()) and core not in needed:
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
    wanted = [c for c in wanted if c]
    log(f"RetroArch: {base}")
    log(f"Cores dir: {cores_dir}  ({len(installed_cores(cores_dir))} installed)")
    ok = 0
    for core in wanted:
        ok += bool(download_core(core, cores_dir, dry_run=dry_run, log=log))
    return ok
