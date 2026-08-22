"""Scan an incoming drop folder and describe what each game *is*.

Detection never depends on a README existing. Files are classified first
(ROM / disc image / archive / installer / doc / support), and a README, when
present, only adds hints on top of what the files already say.
"""

from __future__ import annotations

import os
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import systems as sysmod
from . import readme_parse
from . import sniff

MAX_DEPTH = 6
#: Archives we can look inside without an external tool.
PEEKABLE_EXTS = (".zip",)
#: An extension claimed by at most this many systems is decisive enough to use.
EXT_DECIDES_UP_TO = 3
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
    raw_name: str = ""           # folder/file name before tag cleanup
    files: list[FileInfo] = field(default_factory=list)
    hints: readme_parse.ReadmeHints | None = None
    system: str | None = None
    candidates: list[str] = field(default_factory=list)
    confidence: str = "low"      # high | medium | low
    reasons: list[str] = field(default_factory=list)
    archive_contents: dict = field(default_factory=dict)   # rel -> member names
    opaque_archives: list[str] = field(default_factory=list)  # need 7-Zip to inspect
    unrecognized: bool = False   # nothing here looks like a game

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
            "opaque_archives": self.opaque_archives,
            "unrecognized": self.unrecognized,
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


def base_stem(stem: str) -> str:
    """Stem with disc/tag noise removed, for grouping files of one game."""
    s = _DISC_TAG_RE.sub("", stem)
    s = _TAG_RE.sub("", s)
    return re.sub(r"[\s._-]+", " ", s).strip().lower()


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

    # 2. Look inside disc images - the disc states what console it is, which
    #    beats every filename-based guess.
    sniffed = False
    for f in item.files:
        if f.kind == "disc":
            hit = sniff.identify(f.path)
            if hit:
                vote(hit, 8, f"disc signature in {f.rel}")
                sniffed = True
                break

    # 3. Extensions. How much an extension is worth depends on how many systems
    #    claim it: .n64 means one of two things, .cue means one of seventy-three.
    for f in item.files:
        if f.kind not in ("rom", "disc"):
            continue
        cands = sysmod.systems_for_ext(f.ext)
        if not cands:
            continue
        if sysmod.is_genuinely_ambiguous(f.ext):
            if not sniffed:
                item.candidates = sorted(set(item.candidates) | set(cands[:8]))
        elif len(cands) == 1:
            vote(cands[0], 5, f"extension {f.ext}")
        elif len(cands) <= EXT_DECIDES_UP_TO and not sniffed:
            # Few enough to call it, ranked most-common-first, but say so.
            vote(cands[0], 4, f"extension {f.ext} (of {len(cands)} candidates)")
            item.candidates = sorted(set(item.candidates) | set(cands[1:]))
        elif not sniffed:
            item.candidates = sorted(set(item.candidates) | set(cands[:8]))

    # 4. README hints (emulator names) - weak, corroborating only.
    if item.hints:
        for key in item.hints.systems:
            vote(key, 3, "readme mentions emulator")

    # 5. Contents of archives we could open - the payload is usually in there.
    for rel, members in item.archive_contents.items():
        exts = {Path(n).suffix.lower() for n in members}
        if exts & set(sysmod.INSTALLER_EXTS):
            vote("windows", 4, f"{rel} contains an installer/exe")
            continue
        for ext in exts:
            cands = sysmod.systems_for_ext(ext)
            if len(cands) == 1:
                vote(cands[0], 4, f"{rel} contains {ext}")
            elif cands:
                item.candidates = sorted(set(item.candidates) | set(cands))

    # 6. Windows installers with no ROM anywhere.
    if item.by_kind("installer") and not any(f.kind in ("rom", "disc") for f in item.files):
        vote("windows", 4, "installer, no ROM")

    if votes:
        top = max(votes.values())
        # Break ties by how common the system is, not alphabetically: ES-DE has
        # both "doom" and "dos", and a DOS game should not land in "doom"
        # purely because d-o-o sorts before d-o-s.
        winners = sysmod.rank_candidates([k for k, v in votes.items() if v == top])
        if top == 0:
            item.confidence = "low"
        else:
            item.system = winners[0]
            item.candidates = winners if len(winners) > 1 else item.candidates
            item.confidence = "high" if top >= 5 else "medium" if top >= 3 else "low"
    if item.system and item.system in item.candidates:
        item.candidates = [c for c in item.candidates if c != item.system]


def archive_members(path: Path) -> list[str] | None:
    """Names inside an archive, or None when we cannot open it without 7-Zip."""
    if path.suffix.lower() not in PEEKABLE_EXTS:
        return None
    try:
        with zipfile.ZipFile(path) as zf:
            return [n for n in zf.namelist() if not n.endswith("/")]
    except (OSError, zipfile.BadZipFile):
        return None


def _archive_readme(path: Path, members: list[str]) -> readme_parse.ReadmeHints | None:
    """Read a README stored *inside* a zip, so archived games get hints too."""
    docs = [n for n in members if sysmod.is_doc(Path(n).name)]
    if not docs:
        return None
    docs.sort(key=lambda n: (n.count("/"), len(n)))
    try:
        with zipfile.ZipFile(path) as zf:
            raw = zf.read(docs[0])[:readme_parse.MAX_BYTES]
    except (OSError, zipfile.BadZipFile, KeyError):
        return None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return readme_parse.parse(raw.decode(enc), f"{path.name}:{docs[0]}")
        except UnicodeDecodeError:
            continue
    return None


def scan_item(root: Path) -> ScanItem:
    """Build a ScanItem from one folder (or a single file's parent)."""
    if root.is_file():
        files = [FileInfo(root, root.name, root.stat().st_size, classify(root), root.suffix.lower())]
        item = ScanItem(root=root.parent, name=clean_title(root.name),
                        raw_name=root.name, files=files)
    else:
        item = ScanItem(root=root, name=clean_title(root.name),
                        raw_name=root.name, files=_walk(root))

    docs = sorted(item.by_kind("doc"), key=lambda f: (f.rel.count(os.sep), len(f.rel)))
    if docs:
        try:
            item.hints = readme_parse.parse(readme_parse.read_text(docs[0].path), docs[0].rel)
        except OSError:
            item.hints = None

    # Look inside archives: they hide both the payload and often the README.
    for f in item.by_kind("archive"):
        members = archive_members(f.path)
        if members is None:
            item.opaque_archives.append(f.rel)
            continue
        item.archive_contents[f.rel] = members
        if item.hints is None:
            item.hints = _archive_readme(f.path, members)

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
    # 'MGS (Disc 1).chd' + 'MGS (Disc 2).chd' collapse to one stem: one game.
    stems = {base_stem(p.stem) for p in games}
    if len(games) > 1 and len(stems) == 1:
        return False
    # Several distinct games, or a lone ROM sitting in a system-named folder.
    return len(stems) > 1 or sysmod.system_from_hint(folder.name) is not None


#: Loose files that are never a game and never worth reporting as one.
IGNORE_EXTS = (".txt", ".md", ".nfo", ".diz", ".1st", ".rtf", ".url", ".sfv", ".md5",
               ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".ini", ".log", ".db")

GAME_KINDS = ("rom", "disc", "archive", "installer")


def is_container(folder: Path) -> bool:
    """True for a grouping folder ('Konami Collection/') that holds game folders.

    Such a folder has subdirectories and nothing game-like of its own, so the
    games are one level down and it should be descended into, not treated as
    a single game.
    """
    try:
        entries = list(folder.iterdir())
    except OSError:
        return False
    subdirs = [p for p in entries if p.is_dir()]
    if not subdirs:
        return False
    own = [p for p in entries if p.is_file() and classify(p) in GAME_KINDS]
    return not own


def scan(source: Path, _depth: int = 0) -> list[ScanItem]:
    """Scan a drop folder. Each subfolder is one game; loose files are one each."""
    source = Path(source)
    if source.is_file():
        return [scan_item(source)]
    items: list[ScanItem] = []
    for entry in sorted(source.iterdir(), key=lambda p: p.name.lower()):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            if should_split(entry):
                items.extend(scan_item(f) for f in sorted(entry.iterdir())
                             if f.is_file() and classify(f) in ("rom", "disc", "archive"))
            elif is_container(entry) and _depth < MAX_DEPTH:
                items.extend(scan(entry, _depth + 1))
            else:
                items.append(scan_item(entry))
        elif classify(entry) in GAME_KINDS:
            items.append(scan_item(entry))
        elif entry.suffix.lower() not in IGNORE_EXTS:
            # Don't silently drop it - an unknown extension may still be a game.
            item = scan_item(entry)
            item.unrecognized = True
            item.reasons.append(f"unrecognized extension {entry.suffix or '(none)'}")
            items.append(item)
    return group_multi_disc(items)


def disc_number(name: str) -> int | None:
    m = _DISC_TAG_RE.search(name)
    return int(m.group(1)) if m else None


def group_multi_disc(items: list[ScanItem]) -> list[ScanItem]:
    """Merge sibling folders that are discs of one game.

    A four-disc PSX game usually arrives as four folders - 'Game (Disc 1)',
    'Game (Disc 2)', ... - which are one game, not four. They are merged so the
    library gets a single entry with an .m3u playlist.
    """
    groups: dict[tuple, list[ScanItem]] = {}
    order: list = []
    for item in items:
        raw = item.raw_name or item.name
        key = (base_stem(Path(raw).stem), item.system, str(item.root.parent))
        if disc_number(raw) is None:
            key = (id(item),)          # not a disc: never merges
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)

    merged = []
    for key in order:
        group = groups[key]
        if len(group) == 1:
            merged.append(group[0])
            continue
        group.sort(key=lambda i: disc_number(i.raw_name or i.name) or 0)
        first = group[0]
        combined = ScanItem(
            root=first.root.parent,
            name=clean_title(first.raw_name or first.name),
            system=first.system,
            candidates=first.candidates,
            confidence=first.confidence,
            hints=next((i.hints for i in group if i.hints), None),
        )
        for i in group:
            for f in i.files:
                # Keep paths absolute; rel is only used for display from here.
                combined.files.append(FileInfo(f.path, str(Path(i.raw_name or i.name) / f.rel),
                                               f.size, f.kind, f.ext))
        combined.reasons = first.reasons + [
            f"merged {len(group)} disc folders into one game"]
        merged.append(combined)
    return merged
