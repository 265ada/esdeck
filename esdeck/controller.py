"""Make the game controller player 1.

The complaint this exists for: games treat the Xbox pad as player 2, so menus
cannot be navigated properly. It happens when something else - a Razer or
Corsair virtual device, a wheel, a capture card's HID interface, or the same
pad enumerating twice through both XInput and DirectInput - takes the first
slot, leaving the real controller behind it.

The fix is to pin RetroArch's player 1 to the pad's own index and use the
XInput driver, which enumerates Xbox pads first. The keyboard is left alone: it
is not a "player" in RetroArch, it has its own bindings, and disabling it only
removes a useful fallback.
"""

from __future__ import annotations

import ctypes
import re
from dataclasses import dataclass
from pathlib import Path

from . import cores as cores_mod

#: What esdeck sets so an Xbox pad lands on player 1.
DESIRED = {
    "input_joypad_driver": "xinput",       # enumerates Xbox pads first
    "input_player1_joypad_index": "0",     # first pad drives player 1
    "input_autodetect_enable": "true",     # keep per-pad profiles working
}

_CFG_LINE = re.compile(r'^(\s*)([\w.]+)\s*=\s*"?([^"\n]*)"?\s*$')
_AUTOCONF = re.compile(r'\[Autoconf\].*?"([^"]+)".*?port (\d+)', re.I)


@dataclass
class Pad:
    index: int
    name: str
    connected: bool = True

    def describe(self) -> str:
        return f"port {self.index}: {self.name}"


def xinput_pads() -> list[Pad]:
    """Controllers Windows reports through XInput, in slot order.

    XInput is what Xbox pads use, and slot 0 is what becomes player 1.
    """
    pads = []
    try:
        for dll in ("XInput1_4.dll", "xinput1_3.dll", "XInput9_1_0.dll"):
            try:
                xi = ctypes.windll.LoadLibrary(dll)
                break
            except OSError:
                continue
        else:
            return []
    except (AttributeError, OSError):
        return []

    class XInputState(ctypes.Structure):
        _fields_ = [("dwPacketNumber", ctypes.c_uint32),
                    ("wButtons", ctypes.c_uint16),
                    ("bLeftTrigger", ctypes.c_uint8),
                    ("bRightTrigger", ctypes.c_uint8),
                    ("sThumbLX", ctypes.c_int16), ("sThumbLY", ctypes.c_int16),
                    ("sThumbRX", ctypes.c_int16), ("sThumbRY", ctypes.c_int16)]

    for i in range(4):
        state = XInputState()
        try:
            if xi.XInputGetState(i, ctypes.byref(state)) == 0:
                pads.append(Pad(i, "XInput controller (Xbox-compatible)"))
        except (AttributeError, OSError):
            break
    return pads


def pads_from_log() -> list[Pad]:
    """Controllers RetroArch itself reported, read from its log."""
    base, _ = cores_mod.retroarch_dirs()
    if base is None:
        return []
    log = base / "logs" / "retroarch.log"
    if not log.is_file():
        return []
    try:
        text = log.read_text(encoding="utf-8", errors="replace")[-200000:]
    except OSError:
        return []
    found = {}
    for name, port in _AUTOCONF.findall(text):
        found[int(port)] = name
    return [Pad(port, name) for port, name in sorted(found.items())]


def read_cfg(path: Path) -> dict:
    out = {}
    try:
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            m = _CFG_LINE.match(line)
            if m:
                out[m.group(2)] = m.group(3)
    except OSError:
        pass
    return out


def apply(path: Path, values: dict, *, dry_run: bool = True) -> list[str]:
    """Set values in retroarch.cfg, leaving every other line untouched.

    RetroArch rewrites this file when it exits, so it must not be running.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found - launch RetroArch once first")
    text = path.read_text(encoding="utf-8", errors="replace")
    changes = []

    for key, want in values.items():
        pattern = re.compile(rf'^(\s*{re.escape(key)}\s*=\s*")([^"]*)(")',
                             re.M)
        m = pattern.search(text)
        if not m:
            text = text.rstrip("\n") + f'\n{key} = "{want}"\n'
            changes.append(f"{key}: added as {want!r}")
            continue
        if m.group(2) == want:
            changes.append(f"{key}: already {want!r}")
            continue
        changes.append(f"{key}: {m.group(2)!r} -> {want!r}")
        text = text[:m.start()] + m.group(1) + want + m.group(3) + text[m.end():]

    if not dry_run:
        backup = path.with_suffix(".cfg.esdeck-backup")
        if not backup.exists():
            backup.write_text(path.read_text(encoding="utf-8", errors="replace"),
                              encoding="utf-8")
        path.write_text(text, encoding="utf-8")
    return changes


def diagnose() -> dict:
    """Everything worth knowing about why a pad might not be player 1."""
    base, _ = cores_mod.retroarch_dirs()
    cfg_path = (base / "retroarch.cfg") if base else None
    cfg = read_cfg(cfg_path) if cfg_path and cfg_path.is_file() else {}
    return {
        "retroarch": base,
        "cfg_path": cfg_path,
        "xinput_pads": xinput_pads(),
        "log_pads": pads_from_log(),
        "joypad_driver": cfg.get("input_joypad_driver", "(unset)"),
        "player1_index": cfg.get("input_player1_joypad_index", "(unset)"),
        "player2_index": cfg.get("input_player2_joypad_index", "(unset)"),
        "autodetect": cfg.get("input_autodetect_enable", "(unset)"),
    }
