"""Turn a game's README / instructions file into structured install hints.

Everything here is *untrusted text*. Commands found in a README are recorded
as suggestions with their source line so a human can approve them; this module
never executes anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_BYTES = 512 * 1024

_SYSTEM_WORDS = {
    "retroarch": "retroarch", "dolphin": "gc", "pcsx2": "ps2", "duckstation": "psx",
    "ppsspp": "psp", "cemu": "wiiu", "yuzu": "switch", "ryujinx": "switch",
    "citra": "n3ds", "azahar": "n3ds", "melonds": "nds", "desmume": "nds",
    "flycast": "dreamcast", "redream": "dreamcast", "mame": "arcade",
    "dosbox": "dos", "scummvm": "scummvm", "rpcs3": "ps3", "vita3k": "psvita",
    "mgba": "gba", "snes9x": "snes", "mesen": "nes",
}

# Files that are BIOS/firmware wherever they appear.
_BIOS_STRONG_RE = re.compile(
    r"\b(scph\d{4}\w*\.bin|prod\.keys|title\.keys|[a-z0-9_\-]+\.bios)\b", re.I)
# Generic filenames only count as BIOS on a line that says so.
_BIOS_CONTEXT_RE = re.compile(r"\b(bios|firmware|boot ?rom)\b", re.I)
_BIOS_FILE_RE = re.compile(r"\b([a-z0-9_\-]+\.(?:bin|rom|keys))\b", re.I)

_PATCH_RE = re.compile(r"\b(xdelta|\.ips|\.bps|\.ups|\.ppf|patch(?:ing|ed)?)\b", re.I)
_DISC_RE = re.compile(r"\b(?:disc|disk|cd)\s*([1-9])\b", re.I)
_MOUNT_RE = re.compile(r"\b(mount|daemon tools|virtual (?:drive|clone))\b", re.I)
_SERIAL_RE = re.compile(r"\b(serial|cd[- ]?key|licen[cs]e key|product key|activation)\b", re.I)
_CRACK_RE = re.compile(r"\b(crack|no[- ]?cd|keygen|trainer)\b", re.I)
_RUNAS_RE = re.compile(r"\b(run as admin(?:istrator)?|compatibility mode)\b", re.I)

# A command-looking line: starts with an executable path, not prose.
_CMD_RE = re.compile(
    r"^\s*(?:[$>#]\s*)?((?:[A-Za-z]:\\|\.[\\/]|/)?[A-Za-z_][\w.\\/-]*"
    r"\.(?:exe|msi|bat|cmd|ps1|sh|py)\b[^\n]*)$", re.I)
_STEP_RE = re.compile(r"^\s*(?:\d{1,2}[.)]|[-*•])\s+(\S.*)$")

#: Flags that mean "a human must look at this before anything runs".
RISK_FLAGS = ("modifies_executable", "needs_admin", "needs_serial")


@dataclass
class ReadmeHints:
    source: str = ""
    title: str | None = None
    steps: list[str] = field(default_factory=list)
    commands: list[dict] = field(default_factory=list)   # {"line": int, "text": str}
    emulators: list[str] = field(default_factory=list)
    systems: list[str] = field(default_factory=list)
    bios: list[str] = field(default_factory=list)
    discs: int = 0
    flags: list[str] = field(default_factory=list)       # needs_patch, needs_mount, ...

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, [], 0, "")}


def read_text(path) -> str:
    """Decode a README tolerantly - these files are often cp1252 or latin-1."""
    with open(path, "rb") as fh:
        raw = fh.read(MAX_BYTES)
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", "replace")


def _dedupe(seq):
    seen, out = set(), []
    for x in seq:
        if x.lower() not in seen:
            seen.add(x.lower())
            out.append(x)
    return out


def parse(text: str, source: str = "") -> ReadmeHints:
    h = ReadmeHints(source=source)
    discs: set[int] = set()

    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if not line.strip():
            continue
        low = line.lower()

        if h.title is None and i <= 12 and len(line.strip()) <= 80:
            stripped = line.strip(" #=*-_\t")
            if stripped and not stripped.lower().startswith(("readme", "read me")):
                h.title = stripped

        step = _STEP_RE.match(line)
        if step and len(step.group(1)) < 300:
            h.steps.append(step.group(1).strip())

        cmd = None if step else _CMD_RE.match(line)
        if cmd and len(cmd.group(1)) < 300:
            h.commands.append({"line": i, "text": cmd.group(1).strip()})

        for word, sys_key in _SYSTEM_WORDS.items():
            if word in low:
                h.emulators.append(word)
                if sys_key != "retroarch":
                    h.systems.append(sys_key)

        for m in _BIOS_STRONG_RE.finditer(line):
            h.bios.append(m.group(1))
        if _BIOS_CONTEXT_RE.search(line):
            h.flags.append("needs_bios")
            for m in _BIOS_FILE_RE.finditer(line):
                h.bios.append(m.group(1))

        for m in _DISC_RE.finditer(line):
            discs.add(int(m.group(1)))

        if _PATCH_RE.search(line):
            h.flags.append("needs_patch")
        if _MOUNT_RE.search(line):
            h.flags.append("needs_mount")
        if _SERIAL_RE.search(line):
            h.flags.append("needs_serial")
        if _CRACK_RE.search(line):
            h.flags.append("modifies_executable")
        if _RUNAS_RE.search(line):
            h.flags.append("needs_admin")

    h.discs = max(discs) if discs else 0
    h.emulators = _dedupe(h.emulators)
    h.systems = _dedupe(h.systems)
    h.bios = _dedupe(h.bios)[:12]
    h.flags = _dedupe(h.flags)
    h.steps = h.steps[:40]
    h.commands = h.commands[:20]
    return h
