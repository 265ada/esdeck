"""Scan an incoming drop folder and describe what each game *is*.

Detection never depends on a README existing. Files are classified first
(ROM / disc image / archive / installer / doc / support), and a README, when
present, only adds hints on top of what the files already say.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import systems as sysmod
from . import readme_parse

MAX_DEPTH = 6
_TAG_RE = re.compile(r"\s*[\(\[][^)\]]*[\)\]]")
_DISC_TAG_RE = re.compile(r"\b(?:disc|disk|cd)\s*([1-9])\b", re.I)


@dataclass
class FileInfo:
    path: Path
    rel: str
    size: int
    kind: str          # rom | disc | archive | installer | doc | support
    ext: str

    def to_dict(self) -> dict:
        return {"rel": self.rel, "size": self.size, "kind": self.kind}


@dataclass
class ScanItem:
    """One prospective game: a top-level folder, or a single loose file."""
    root: Path
    name: str
    files: list[FileInfo] = field(default_factory=list)
    hints: readme_parse.ReadmeHints | None = None
    system: str | None = None
    candidates: list[str] = field(default_factory=list)
    confidence: str = "low"      # high | medium | low
    reasons: list[str] = field(default_factory=list)

    def by_kind(self, kind: str) -> list[FileInfo]:
        return [f for f in self.files if f.kind == kind]

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "root": str(self.root),
            "system": self.system,
            "candidates": self.candidates,
            "confidence": self.confidence,
            "reasons": self.reasons,
            "files": [f.to_dict() for f in self.files],
            "hints": self.hints.to_dict() if self.hints else {},
        }


def classify(path: Path) -> str:
    name = path.name.lower()
    ext = path.suffix.lower()
    if sysmod.is_doc(path.name):
        return "doc"
    if name in sysmod.INSTALLER_NAMES or (
            ext in sysmod.INSTALLER_EXTS and re.search(r"setup|install", name)):
        return "installer"
    if ext in sysmod.ARCHIVE_EXTS:
        return "archive"
    if ext in sysmod.DISC_EXTS:
        return "disc"
    if sysmod.systems_for_ext(ext):
        return "rom"
    if ext in sysmod.INSTALLER_EXTS:
        return "installer"
    return "support"


def clean_title(name: str) -> str:
    """'Some Game (USA) [!].zip' -> 'Some Game'."""
    stem = Path(name).stem
    stem = _TAG_RE.sub("", stem)
    return re.sub(r"[._]+", " ", stem).strip(" -") or Path(name).stem


def _walk(root: Path) -> list[FileInfo]:
    out: list[FileInfo] = []
    base_depth = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        if len(d.parts) - base_depth >= MAX_DEPTH:
            dirnames[:] = []
        for fn in filenames:
            p = d / fn
            try:
                size = p.stat().st_size
            except OSError:
                continue
            out.append(FileInfo(p, str(p.relative_to(root)), size, classify(p), p.suffix.lower()))
    return out


def _resolve_system(item: ScanItem) -> None:
    """Decide the ES-DE system for an item, recording why."""
    votes: dict[str, int] = {}

    def vote(key: str, weight: int, why: str) -> None:
        if not key:
            return
        votes[key] = votes.get(key, 0) + weight
        item.reasons.append(f"{why} -> {key} (+{weight})")

    # 1. Folder-name / parent-folder hint, e.g. incoming/PS2/Game Name/
    for part in (item.name, item.root.name, item.root.parent.name):
        hit = sysmod.system_from_hint(part)
        if hit:
            vote(hit, 3, f"name hint {part!r}")
            break

    # 2. Unambiguous ROM extensions are the strongest signal.
    for f in item.files:
        if f.kind in ("rom", "disc"):
            cands = sysmod.systems_for_ext(f.ext)
            if len(cands) == 1:
                vote(cands[0], 5, f"extension {f.ext}")
            elif cands:
                for c in cands:
                    votes.setdefault(c, 0)
                item.candidates = sorted(set(item.candidates) | set(cands))

    # 3. README hints (emulator names) - weak, corroborating only.
    if item.hints:
        for key in item.hints.systems:
            vote(key, 3, "readme mentions emulator")

    # 4. Windows installers with no ROM anywhere.
    if item.by_kind("installer") and not any(f.kind in ("rom", "disc") for f in item.files):
        vote("windows", 4, "installer, no ROM")

    if votes:
        top = max(votes.values())
        winners = sorted(k for k, v in votes.items() if v == top)
        if top == 0:
            item.confidence = "low"
        else:
            item.system = winners[0]
            item.candidates = winners if len(winners) > 1 else item.candidates
            item.confidence = "high" if top >= 5 else "medium" if top >= 3 else "low"
    if item.system and item.system in item.candidates:
        item.candidates = [c for c in item.candidates if c != item.system]


def scan_item(root: Path) -> ScanItem:
    """Build a ScanItem from one folder (or a single file's parent)."""
    if root.is_file():
        files = [FileInfo(root, root.name, root.stat().st_size, classify(root), root.suffix.lower())]
        item = ScanItem(root=root.parent, name=clean_title(root.name), files=files)
    else:
        item = ScanItem(root=root, name=clean_title(root.name), files=_walk(root))

    docs = sorted(item.by_kind("doc"), key=lambda f: (f.rel.count(os.sep), len(f.rel)))
    if docs:
        try:
            item.hints = readme_parse.parse(readme_parse.read_text(docs[0].path), docs[0].rel)
        except OSError:
            item.hints = None

    _resolve_system(item)
    return item


def should_split(folder: Path) -> bool:
    """True for a *system* folder holding several standalone games, not one game.

    A folder with a README, an installer, or a multi-file disc set is one game.
    A folder of loose ROMs (often named after the system) is many.
    """
    try:
        entries = [p for p in folder.iterdir() if p.is_file()]
    except OSError:
        return False
    if any(classify(p) in ("doc", "installer") for p in entries):
        return False
    if any(p.suffix.lower() in {".cue", ".bin", ".ccd", ".sub", ".mds", ".mdf"} for p in entries):
        return False
    games = [p for p in entries if classify(p) in ("rom", "disc", "archive")]
    if not games:
        return False
    if any(p.is_dir() for p in folder.iterdir()):
        return False
    stems = {p.stem.lower() for p in games}
    return len(stems) > 1 or sysmod.system_from_hint(folder.name) is not None


def scan(source: Path) -> list[ScanItem]:
    """Scan a drop folder. Each subfolder is one game; loose files are one each."""
    source = Path(source)
    if source.is_file():
        return [scan_item(source)]
    items = []
    for entry in sorted(source.iterdir(), key=lambda p: p.name.lower()):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            if should_split(entry):
                items.extend(scan_item(f) for f in sorted(entry.iterdir())
                             if f.is_file() and classify(f) in ("rom", "disc", "archive"))
            else:
                items.append(scan_item(entry))
        elif classify(entry) in ("rom", "disc", "archive", "installer"):
            items.append(scan_item(entry))
    return items


def disc_number(name: str) -> int | None:
    m = _DISC_TAG_RE.search(name)
    return int(m.group(1)) if m else None
