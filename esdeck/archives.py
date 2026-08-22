"""Read and unpack archives of any kind.

Python's stdlib only opens .zip and .tar, which leaves .rar and .7z - both very
common for shared games - as black boxes. 7-Zip handles every format worth
caring about, is already installed by `esdeck bootstrap`, and is driven here
through its command line.

The stdlib is still used for .zip so scanning works before 7-Zip is installed.
Everything degrades to "cannot inspect" rather than to a wrong guess.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import zipfile
from functools import lru_cache
from pathlib import Path

TIMEOUT = 600

SEVENZIP_PATHS = (
    r"C:\Program Files\7-Zip\7z.exe",
    r"C:\Program Files (x86)\7-Zip\7z.exe",
    "/usr/bin/7z",
    "/usr/local/bin/7z",
)

#: Every archive extension esdeck will look inside or unpack. 7-Zip reads all
#: of them; only .zip works without it.
ARCHIVE_EXTS = (
    ".zip", ".zipx", ".7z", ".rar", ".cab", ".arj", ".lzh", ".lha", ".ace",
    ".tar", ".gz", ".tgz", ".bz2", ".tbz", ".tbz2", ".xz", ".txz", ".lzma",
    ".z", ".zst", ".wim",
)

#: Split archives arrive as dozens of volumes - Game.part01.rar .. .part47.rar,
#: Game.7z.001 .., Game.zip.001 .., Game.r00 .., or bare Game.part01 .. part47.
#: Only the first volume is opened; 7-Zip pulls in the rest by itself. The
#: others must be ignored, or a 47-part set becomes 47 "games".
_FIRST_VOLUME_RE = re.compile(
    r"\.(?:part0*1(?:\.(?:rar|7z|zip))?|(?:7z|zip|tar)\.0*1|001|r00)$", re.I)
_LATER_VOLUME_RE = re.compile(
    r"\.(?:part\d+(?:\.(?:rar|7z|zip))?|(?:7z|zip|tar)\.\d+|\d{3}|r\d{2})$", re.I)


def volume_stem(path) -> str:
    """The archive name shared by every volume of a split set."""
    name = Path(path).name
    return re.sub(r"\.(?:part\d+(?:\.(?:rar|7z|zip))?|(?:7z|zip|tar)\.\d+|\d{3}|r\d{2})$",
                  "", name, flags=re.I)

_LINE_RE = re.compile(r"^Path = (.+)$")
_ATTR_RE = re.compile(r"^Attributes = (.+)$")


@lru_cache(maxsize=1)
def sevenzip() -> str | None:
    """Path to 7z.exe, or None when 7-Zip is not installed."""
    for candidate in SEVENZIP_PATHS:
        if Path(candidate).is_file():
            return candidate
    return shutil.which("7z") or shutil.which("7za")


def is_first_volume(path) -> bool:
    """True for volume 1 of a split set - the only one worth opening."""
    return bool(_FIRST_VOLUME_RE.search(Path(path).name))


def is_later_volume(path) -> bool:
    """True for part 2+ of a split archive, which must not be treated as a game."""
    name = Path(path).name
    return bool(_LATER_VOLUME_RE.search(name)) and not _FIRST_VOLUME_RE.search(name)


def is_archive(path) -> bool:
    """Whether this file is an archive esdeck should look inside."""
    p = Path(path)
    return p.suffix.lower() in ARCHIVE_EXTS or is_first_volume(p)


def can_read(path) -> bool:
    """Whether this archive can be inspected on this machine right now."""
    if Path(path).suffix.lower() == ".zip" and not is_first_volume(path):
        return True
    return sevenzip() is not None      # split sets always need 7-Zip


def _list_with_7z(path: Path) -> list[str] | None:
    exe = sevenzip()
    if exe is None:
        return None
    try:
        proc = subprocess.run([exe, "l", "-slt", "-ba", str(path)],
                              capture_output=True, text=True, timeout=TIMEOUT,
                              errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None

    names, current, is_dir = [], None, False
    for line in proc.stdout.splitlines():
        m = _LINE_RE.match(line)
        if m:
            if current is not None and not is_dir:
                names.append(current)
            current, is_dir = m.group(1).strip(), False
            continue
        a = _ATTR_RE.match(line)
        if a and "D" in a.group(1):
            is_dir = True
    if current is not None and not is_dir:
        names.append(current)
    return [n.replace("\\", "/") for n in names]


def _list_with_zipfile(path: Path) -> list[str] | None:
    try:
        with zipfile.ZipFile(path) as zf:
            return [n for n in zf.namelist() if not n.endswith("/")]
    except (OSError, zipfile.BadZipFile):
        return None


def members(path) -> list[str] | None:
    """Filenames inside an archive, or None if it cannot be opened here."""
    path = Path(path)
    # A split .zip.001 is not a zip file on its own - only 7-Zip can join it.
    if path.suffix.lower() == ".zip" and not is_first_volume(path):
        got = _list_with_zipfile(path)
        if got is not None:
            return got
    return _list_with_7z(path)


def extract(path, dest, *, log=print) -> int:
    """Unpack an archive into dest. Returns the number of files written.

    Raises RuntimeError when the format needs 7-Zip and it is not installed,
    so the caller can report that rather than silently doing nothing.
    """
    path, dest = Path(path), Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    if path.suffix.lower() == ".zip" and sevenzip() is None:
        return _extract_zipfile(path, dest)

    exe = sevenzip()
    if exe is None:
        raise RuntimeError(f"{path.suffix} needs 7-Zip; install it with "
                           f"'esdeck bootstrap --packages 7zip --yes'")

    before = sum(1 for _ in dest.rglob("*") if _.is_file())
    proc = subprocess.run(
        [exe, "x", str(path), f"-o{dest}", "-y", "-bso0", "-bsp0"],
        capture_output=True, text=True, timeout=TIMEOUT, errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"7-Zip failed on {path.name}: "
                           f"{(proc.stderr or proc.stdout).strip()[:200]}")
    after = sum(1 for _ in dest.rglob("*") if _.is_file())
    return after - before


def _extract_zipfile(path: Path, dest: Path) -> int:
    """stdlib fallback, with the zip-slip guard 7-Zip applies itself."""
    count = 0
    with zipfile.ZipFile(path) as zf:
        for member in zf.infolist():
            if member.filename.endswith("/"):
                continue
            target = (dest / member.filename).resolve()
            if not str(target).startswith(str(dest.resolve())):
                raise PermissionError(f"unsafe path in archive: {member.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            count += 1
    return count
