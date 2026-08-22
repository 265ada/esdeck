"""Bring a fresh Windows machine up to a working ES-DE install.

Everything here is idempotent and prints what it would do under --dry-run.
Package installs go through winget so we never download binaries ourselves.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .config import Config
from .systems import SYSTEMS

#: winget package ids. Emulators are optional; ES-DE + RetroArch cover most systems.
PACKAGES = {
    "es-de": ("ES-DE.ES-DE", "EmulationStation Desktop Edition"),
    "retroarch": ("Libretro.RetroArch", "RetroArch (multi-system cores)"),
    "dolphin": ("DolphinEmulator.Dolphin", "Dolphin (GameCube / Wii)"),
    "pcsx2": ("PCSX2.PCSX2", "PCSX2 (PlayStation 2)"),
    "duckstation": ("StenzekConsulting.DuckStation", "DuckStation (PlayStation 1)"),
    "ppsspp": ("PPSSPPTeam.PPSSPP", "PPSSPP (PSP)"),
    "7zip": ("7zip.7zip", "7-Zip (needed for .7z/.rar game archives)"),
}
DEFAULT_PACKAGES = ("es-de", "retroarch", "7zip")


def have_winget() -> bool:
    return shutil.which("winget") is not None


def winget_installed(package_id: str) -> bool:
    try:
        out = subprocess.run(
            ["winget", "list", "--id", package_id, "--exact",
             "--accept-source-agreements", "--disable-interactivity"],
            capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return False
    return package_id.lower() in out.stdout.lower()


def install_package(key: str, *, dry_run: bool = True, log=print) -> bool:
    package_id, label = PACKAGES[key]
    if not have_winget():
        log(f"  SKIP   {label}: winget not available - install it manually")
        return False
    if winget_installed(package_id):
        log(f"  ok     {label} already installed")
        return True
    log(f"  install {label} ({package_id})")
    if dry_run:
        return True
    proc = subprocess.run(
        ["winget", "install", "--id", package_id, "--exact", "--silent",
         "--accept-package-agreements", "--accept-source-agreements"],
        text=True)
    if proc.returncode != 0:
        log(f"  ERROR  winget exited {proc.returncode} for {package_id}")
    return proc.returncode == 0


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


def run(cfg: Config, *, packages=DEFAULT_PACKAGES, dry_run: bool = True, log=print) -> None:
    log("Packages:")
    for key in packages:
        if key not in PACKAGES:
            log(f"  SKIP   unknown package {key!r}")
            continue
        install_package(key, dry_run=dry_run, log=log)
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
