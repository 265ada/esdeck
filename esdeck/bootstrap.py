"""Bring a fresh Windows machine up to a working ES-DE install.

Everything here is idempotent and prints what it would do under --dry-run.
Package installs go through winget so we never download binaries ourselves.
"""

from __future__ import annotations

import shutil
import subprocess

from . import proc as proc_mod
from pathlib import Path

from .config import Config
from .systems import SYSTEMS

#: winget package ids. Emulators are optional; ES-DE + RetroArch cover most systems.
PACKAGES = {
    "es-de": ("ES-DE.EmulationStation-DE", "EmulationStation Desktop Edition"),
    "retroarch": ("Libretro.RetroArch", "RetroArch (multi-system cores)"),
    "dolphin": ("DolphinEmulator.Dolphin", "Dolphin (GameCube / Wii)"),
    "pcsx2": ("PCSX2Team.PCSX2", "PCSX2 (PlayStation 2)"),
    "duckstation": ("Stenzek.DuckStation", "DuckStation (PlayStation 1)"),
    "ppsspp": ("PPSSPPTeam.PPSSPP", "PPSSPP (PSP)"),
    "7zip": ("7zip.7zip", "7-Zip (needed for .7z/.rar game archives)"),
}
DEFAULT_PACKAGES = ("es-de", "retroarch", "7zip")


#: winget exit codes worth translating; anything else is reported verbatim.
WINGET_ERRORS = {
    0x8A15002B: "no such package id (winget may have renamed it)",
    0x8A150011: "no applicable installer for this system",
    0x8A150056: "already installed and up to date",
}


def _winget_error(code: int) -> str:
    return WINGET_ERRORS.get(code & 0xFFFFFFFF, f"winget exit code {code}")


def have_winget() -> bool:
    return shutil.which("winget") is not None


def winget_installed(package_id: str) -> bool:
    try:
        out = proc_mod.run(
            ["winget", "list", "--id", package_id, "--exact",
             "--accept-source-agreements", "--disable-interactivity"],
            capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return False
    return package_id.lower() in out.stdout.lower()


def install_package(key: str, *, dry_run: bool = True, repair: bool = False,
                    log=print) -> bool:
    """Install a package, or reinstall it over the top when repairing.

    Repair uses winget's --force, which reinstalls without uninstalling first.
    That matters: uninstalling RetroArch would take your saves, save states,
    controller bindings, playlists and the BIOS files in system/ with it, and
    those are not things a setup script should throw away.
    """
    package_id, label = PACKAGES[key]
    if not have_winget():
        log(f"  SKIP   {label}: winget not available - install it manually")
        return False
    already = winget_installed(package_id)
    if already and not repair:
        log(f"  ok     {label} already installed")
        return True
    log(f"  {'reinstall' if already else 'install'} {label} ({package_id})")
    if dry_run:
        return True
    cmd = ["winget", "install", "--id", package_id, "--exact", "--silent",
           "--accept-package-agreements", "--accept-source-agreements"]
    if already:
        cmd.append("--force")
    proc = proc_mod.run(cmd, text=True)
    if proc.returncode != 0:
        log(f"  ERROR  {label}: {_winget_error(proc.returncode)} [{package_id}]")
    return proc.returncode == 0


#: Where ES-DE's executable normally lands on Windows.
ES_DE_BINARIES = (
    r"C:\Program Files\ES-DE\ES-DE.exe",
    r"C:\Program Files (x86)\ES-DE\ES-DE.exe",
)


def find_es_de() -> Path | None:
    """Locate an installed ES-DE binary, whether or not it has ever been run."""
    for candidate in ES_DE_BINARIES:
        p = Path(candidate)
        if p.is_file():
            return p
    found = shutil.which("ES-DE")
    return Path(found) if found else None


def es_de_running() -> bool:
    """ES-DE overwrites its settings file on exit, so edits need it stopped."""
    try:
        out = proc_mod.run(["tasklist", "/FI", "IMAGENAME eq ES-DE.exe", "/NH"],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return "ES-DE.exe" in out.stdout


def retroarch_running() -> bool:
    """RetroArch overwrites retroarch.cfg on exit, so edits need it stopped."""
    try:
        out = proc_mod.run(["tasklist", "/FI", "IMAGENAME eq retroarch.exe", "/NH"],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return "retroarch.exe" in out.stdout


def make_rom_tree(cfg: Config, *, dry_run: bool = True, log=print) -> list[Path]:
    """Create <ROMs>/<system>/ for the enabled systems (all of them by default)."""
    root = Path(cfg.rom_dir)
    keys = cfg.systems_enabled or [s.key for s in SYSTEMS]
    made = []
    for key in keys:
        p = root / key
        if p.is_dir():
            continue
        log(f"  mkdir  {p}")
        made.append(p)
        if not dry_run:
            p.mkdir(parents=True, exist_ok=True)
    if not made:
        log(f"  ok     ROM tree already present under {root}")
    return made


#: User data that must survive a repair - saves, bindings, playlists, BIOS.
RETROARCH_USER_DATA = ("retroarch.cfg", "saves", "states", "system", "playlists",
                       "config", "cheats", "screenshots")


def backup_user_data(dest: Path, *, dry_run: bool = True, log=print) -> Path | None:
    """Copy RetroArch and ES-DE user data somewhere safe before a repair."""
    base, _ = None, None
    try:
        from . import cores as cores_mod
        base, _ = cores_mod.retroarch_dirs()
    except Exception:                                   # noqa: BLE001
        base = None
    dest = Path(dest)
    log(f"  backup -> {dest}")
    if dry_run:
        return dest
    dest.mkdir(parents=True, exist_ok=True)
    if base:
        for name in RETROARCH_USER_DATA:
            src = base / name
            if not src.exists():
                continue
            target = dest / "RetroArch" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                if src.is_dir():
                    shutil.copytree(src, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, target)
            except OSError as exc:
                log(f"  WARN   could not back up {name}: {exc}")
    es_dir = Path.home() / "ES-DE"
    if es_dir.is_dir():
        for name in ("settings", "collections", "gamelists", "custom_systems", "controllers"):
            src = es_dir / name
            if src.is_dir():
                try:
                    shutil.copytree(src, dest / "ES-DE" / name, dirs_exist_ok=True)
                except OSError as exc:
                    log(f"  WARN   could not back up ES-DE/{name}: {exc}")
    return dest


def run(cfg: Config, *, packages=DEFAULT_PACKAGES, dry_run: bool = True,
        repair: bool = False, log=print) -> None:
    if repair:
        from datetime import datetime
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        log("Backing up existing settings before reinstalling:")
        backup_user_data(Path(cfg.rom_dir).parent / f"esdeck-backup-{stamp}",
                         dry_run=dry_run, log=log)
    log("Packages:")
    for key in packages:
        if key not in PACKAGES:
            log(f"  SKIP   unknown package {key!r}")
            continue
        install_package(key, dry_run=dry_run, repair=repair, log=log)
    log("ROM directories:")
    make_rom_tree(cfg, dry_run=dry_run, log=log)
    log("Install dir:")
    p = Path(cfg.install_dir)
    if p.is_dir():
        log(f"  ok     {p}")
    else:
        log(f"  mkdir  {p}")
        if not dry_run:
            p.mkdir(parents=True, exist_ok=True)
