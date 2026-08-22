"""Find the drives a game library could live on, and how much room they have.

Hardcoding D:\\ is wrong on most machines - plenty have only C:, and where a
second drive exists it is not always the biggest or the one you want. So esdeck
measures what is actually there, suggests the roomiest, and lets a human pick.
"""

from __future__ import annotations

import ctypes
import re
import shutil
import string
from dataclasses import dataclass
from pathlib import Path

DRIVE_FIXED = 3          # from Windows GetDriveTypeW
DRIVE_REMOTE = 4         # network share - offered, but never suggested
GB = 1024 ** 3

#: A library needs room to grow; warn below this.
COMFORTABLE_FREE_GB = 20


@dataclass
class Drive:
    letter: str          # "C:"
    total: int
    free: int
    kind: int = DRIVE_FIXED
    is_system: bool = False

    @property
    def free_gb(self) -> float:
        return self.free / GB

    @property
    def total_gb(self) -> float:
        return self.total / GB

    @property
    def roomy(self) -> bool:
        return self.free_gb >= COMFORTABLE_FREE_GB

    def describe(self) -> str:
        tags = []
        if self.is_system:
            tags.append("system drive")
        if self.kind == DRIVE_REMOTE:
            tags.append("network")
        if not self.roomy:
            tags.append("low space")
        suffix = f"  ({', '.join(tags)})" if tags else ""
        return (f"{self.letter}  {self.free_gb:>8.1f} GB free "
                f"of {self.total_gb:>8.1f} GB{suffix}")


def _drive_type(letter: str) -> int:
    try:
        return ctypes.windll.kernel32.GetDriveTypeW(f"{letter}\\")
    except (AttributeError, OSError):
        return DRIVE_FIXED


def list_drives() -> list[Drive]:
    """Every usable drive, biggest free space first."""
    system_letter = str(Path.home().drive).upper()
    found = []
    for ch in string.ascii_uppercase:
        letter = f"{ch}:"
        root = f"{letter}\\"
        if not Path(root).exists():
            continue
        kind = _drive_type(letter)
        if kind not in (DRIVE_FIXED, DRIVE_REMOTE):
            continue                      # skip optical, removable, RAM disks
        try:
            usage = shutil.disk_usage(root)
        except OSError:
            continue
        found.append(Drive(letter, usage.total, usage.free, kind,
                           letter.upper() == system_letter))
    found.sort(key=lambda d: d.free, reverse=True)
    return found


def normalize_target(text: str, folder_name: str = "Games") -> str:
    """Turn whatever someone typed at the prompt into an absolute folder.

    The drive list shows entries as "G:", so people reasonably answer "G" - and
    a bare "G" is a *relative* path, which quietly created a folder called G
    next to the script instead of using the drive. Anything that names a drive
    is expanded to <drive>\\<folder_name>; a relative path is rejected outright
    rather than guessed at.

    Returns "" when the answer cannot be made into an absolute path.
    """
    raw = (text or "").strip().strip('"').strip()
    if not raw:
        return suggest(folder_name)

    # "G" -> "G:", so the two forms below handle it together.
    if len(raw) == 1 and raw.isalpha():
        raw = f"{raw.upper()}:"

    # "G:" or "G:\" - a drive with no folder.
    if re.fullmatch(r"[A-Za-z]:[\\/]?", raw):
        return f"{raw[0].upper()}:\\{folder_name}"

    # Anything else must already be absolute: a drive path or a UNC share.
    if re.match(r"^[A-Za-z]:[\\/]", raw) or raw.startswith("\\\\"):
        return raw.rstrip("\\/") or raw
    return ""


def suggest(folder_name: str = "Games") -> str:
    """The path to offer as the default: roomiest drive, system drive last.

    A non-system drive is preferred when it has real space, because keeping a
    large library off C: is usually what people want - but only when it is
    genuinely roomier, not merely different.
    """
    drives = list_drives()
    if not drives:
        return str(Path.home() / folder_name)

    local = [d for d in drives if d.kind == DRIVE_FIXED]
    pool = local or drives
    best = pool[0]

    non_system = [d for d in pool if not d.is_system and d.roomy]
    if non_system and non_system[0].free >= best.free * 0.5:
        best = non_system[0]

    return f"{best.letter}\\{folder_name}"
