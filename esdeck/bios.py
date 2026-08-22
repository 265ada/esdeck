"""Which BIOS/firmware files a system needs, and whether they are present.

esdeck does not download BIOS files. They are copyrighted console firmware, and
no legitimate emulator ships them - RetroArch's own Online Updater fetches
cores, shaders, cheats and databases, but deliberately not BIOS.

What esdeck can do is remove every bit of guesswork: name the exact file, say
which folder it goes in, verify the copy you supply by checksum, and warn you
*before* you wonder why a game will not start.

The requirements come from RetroArch's own core info files, which declare each
core's firmware with a path, an optional flag and often an md5. That makes this
universal - it covers whatever cores are installed, and stays correct as they
change - with a small built-in table as a fallback for machines where RetroArch
is not installed yet.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from . import cores as cores_mod


@dataclass(frozen=True)
class BiosFile:
    name: str                 # path relative to the system folder, e.g. "dc/dc_boot.bin"
    md5: str | None = None
    required: bool = True     # False = improves accuracy but is not needed to run
    note: str = ""

    @property
    def filename(self) -> str:
        return Path(self.name).name


# --------------------------------------------------------------------------
# Reading RetroArch's core info files - the authoritative source.
# --------------------------------------------------------------------------

_KV_RE = re.compile(r'^\s*(\w+)\s*=\s*"?([^"\n]*)"?\s*$')
_NOTE_MD5_RE = re.compile(r"\(!\)\s*([^\s(]+)\s*\(md5\):\s*([0-9a-f]{32})", re.I)


def info_dir() -> Path | None:
    base, _ = cores_mod.retroarch_dirs()
    if base is None:
        return None
    d = base / "info"
    return d if d.is_dir() else None


def parse_info(path: Path) -> tuple[BiosFile, ...]:
    """Firmware requirements declared by one core .info file."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ()
    fields: dict[str, str] = {}
    for line in text.splitlines():
        m = _KV_RE.match(line)
        if m:
            fields[m.group(1)] = m.group(2)

    # md5s are sometimes only in the free-text notes field.
    note_md5 = {name.lower(): digest.lower()
                for name, digest in _NOTE_MD5_RE.findall(fields.get("notes", ""))}

    try:
        count = int(fields.get("firmware_count", "0"))
    except ValueError:
        count = 0

    out = []
    for i in range(count):
        rel = fields.get(f"firmware{i}_path")
        if not rel:
            continue
        md5 = fields.get(f"firmware{i}_md5") or note_md5.get(Path(rel).name.lower())
        out.append(BiosFile(
            name=rel,
            md5=md5.lower() if md5 else None,
            required=fields.get(f"firmware{i}_opt", "true").lower() != "true",
            note=fields.get(f"firmware{i}_desc", ""),
        ))
    return tuple(out)


@lru_cache(maxsize=1)
def _core_requirements() -> dict:
    """{core name: (BiosFile, ...)} from every installed core info file."""
    d = info_dir()
    if d is None:
        return {}
    out = {}
    for p in d.glob("*_libretro.info"):
        reqs = parse_info(p)
        if reqs:
            out[p.name[:-len("_libretro.info")]] = reqs
    return out


#: Fallback for machines with no RetroArch yet. Only the systems people hit
#: first; the info files cover everything else once RetroArch is installed.
FALLBACK: dict[str, tuple[BiosFile, ...]] = {
    "psx": (BiosFile("scph5501.bin", "490f666e1afb15b7362b406ed1cea246", False, "PS1 US BIOS"),),
    "saturn": (BiosFile("sega_101.bin", "85ec9ca47d8f6807718151cbcca8b964", True, "Saturn JP BIOS"),
               BiosFile("mpr-17933.bin", "3240872c70984b6cbfda1586cab68dbe", True, "Saturn US/EU BIOS")),
    "dreamcast": (BiosFile("dc/dc_boot.bin", "e10c53c2f8b90bab96ead2d368858623", True),),
    "ps2": (BiosFile("ps2-0230a-20080220.bin", None, True, "any SCPH dump"),),
    "megacd": (BiosFile("bios_CD_U.bin", "2efd74e3232ff260e371b99f84024f7f", True, "Mega CD US"),),
    "pcenginecd": (BiosFile("syscard3.pce", "38179df8f4ac870017db21ebcbf53114", True),),
    "fds": (BiosFile("disksys.rom", "ca30b50f880eb660a320674ed365ef7a", True),),
    "atarilynx": (BiosFile("lynxboot.img", "fcd403db69f54290b51035d82f835e7b", True),),
    "3do": (BiosFile("panafz1.bin", "f47264dd47fe30f73ab3c010015c155b", True),),
}


def requirements_for(system: str, es_config_dir=None) -> tuple[BiosFile, ...]:
    """Firmware the system needs, via the core that will actually run it.

    If an alternative emulator has been chosen for the system, that is the core
    whose requirements matter - SwanStation needs no BIOS where ES-DE's default
    Beetle PSX needs three, and warning about the unused one is just wrong.
    """
    core = None
    if es_config_dir:
        try:
            from . import emulators as emu
            choice = emu.effective(system, es_config_dir)
            if choice is not None:
                core = choice.core
        except Exception:                     # noqa: BLE001 - never block a check
            core = None
    core = core or cores_mod.core_for_system(system)
    if core:
        found = _core_requirements().get(core)
        if found:
            return found
    return FALLBACK.get(system, ())


# --------------------------------------------------------------------------
# Checking what is actually on disk.
# --------------------------------------------------------------------------

def system_dir() -> Path | None:
    base, _ = cores_mod.retroarch_dirs()
    return (base / "system") if base else None


def md5_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


@dataclass
class BiosStatus:
    system: str
    bios: BiosFile
    present: bool
    checksum_ok: bool | None = None    # None when there is no reference md5

    @property
    def state(self) -> str:
        if not self.present:
            return "missing" if self.bios.required else "missing (optional)"
        if self.checksum_ok is False:
            return "WRONG FILE"
        return "ok"


def check_system(system: str, sysdir: Path | None = None, *,
                 verify: bool = True, es_config_dir=None) -> list[BiosStatus]:
    sysdir = Path(sysdir) if sysdir else system_dir()
    out = []
    for bios in requirements_for(system, es_config_dir):
        present = ok = None
        if sysdir is None:
            present = False
        else:
            path = sysdir / bios.name
            present = path.is_file()
            if present and verify and bios.md5:
                try:
                    ok = md5_of(path) == bios.md5
                except OSError:
                    ok = None
        out.append(BiosStatus(system, bios, bool(present), ok))
    return out


def blocking(statuses) -> list[BiosStatus]:
    """Problems that will actually stop a game running.

    A core that lists several regional BIOS as required is satisfied by any one
    of them, so a Saturn with only the US BIOS is fine, not two-thirds broken.
    """
    by_system: dict[str, list[BiosStatus]] = {}
    for s in statuses:
        by_system.setdefault(s.system, []).append(s)

    out = []
    for system, group in by_system.items():
        wrong = [s for s in group if s.checksum_ok is False]
        out.extend(wrong)
        if wrong:
            # Already reported as the wrong file; also calling it missing would
            # be the same problem counted twice.
            continue
        needed = [s for s in group if s.bios.required]
        if needed and not any(s.present for s in needed):
            out.append(needed[0] if len(needed) == 1 else _combined(system, needed))
    return out


def _combined(system: str, needed: list[BiosStatus]) -> BiosStatus:
    """One status standing for 'any one of these regional BIOS files'."""
    names = " or ".join(s.bios.filename for s in needed[:4])
    return BiosStatus(system, BiosFile(names, None, True, "any one of these"), False)


def warn_lines(system: str, sysdir: Path | None = None,
               es_config_dir=None) -> list[str]:
    """Plain-language warnings for one system, ready to print next to a game."""
    problems = blocking(check_system(system, sysdir, es_config_dir=es_config_dir))
    lines = []
    for s in problems:
        where = system_dir() or "RetroArch's system folder"
        if s.checksum_ok is False:
            lines.append(f"BIOS {s.bios.filename} is present but does not match the "
                         f"expected checksum - it is the wrong or a corrupt dump")
        else:
            lines.append(f"needs BIOS {s.bios.filename} in {where} - "
                         f"without it this game will most likely not start")
    return lines
