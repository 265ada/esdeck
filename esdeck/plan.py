"""Turn a ScanItem into an explicit, reviewable list of actions.

A plan is plain JSON. Nothing in it runs at build time - `esdeck apply` is
what executes it, and any action carrying ``needs_review`` is skipped unless
a human approves it. That is what keeps README-derived instructions safe:
they become *proposed* actions, not executed ones.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from .config import Config
from .scan import ScanItem, disc_number, clean_title

PLAN_VERSION = 1

# Systems where a .zip IS the ROM and must never be extracted.
ZIP_IS_ROM = {"arcade", "neogeo", "mame", "fbneo"}
# Multi-file disc formats that belong in a per-game subfolder.
MULTIFILE_EXTS = {".cue", ".bin", ".ccd", ".img", ".sub", ".mds", ".mdf", ".gdi", ".raw"}

_FLAG_ADVICE = {
    "needs_bios": "BIOS/firmware required - place the listed files in the emulator's system folder.",
    "needs_patch": "A patch must be applied by hand (xdelta/IPS/BPS); esdeck will not patch ROMs.",
    "needs_mount": "README says to mount a disc image; prefer letting the emulator load it directly.",
    "needs_serial": "A serial/product key is required during install - enter it yourself.",
    "modifies_executable": "README describes replacing or modifying a game executable. Review manually.",
    "needs_admin": "Installer expects elevation; run it yourself from an admin prompt.",
}


def _action(kind: str, **kw) -> dict:
    a = {"type": kind}
    a.update(kw)
    a.setdefault("needs_review", False)
    return a


def _zip_looks_like_rom(path: Path, system: str | None) -> bool:
    """True if a .zip should be copied whole rather than extracted."""
    if system in ZIP_IS_ROM:
        return True
    try:
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
    except (OSError, zipfile.BadZipFile):
        return False
    from . import systems as sysmod
    roms = [n for n in names if sysmod.systems_for_ext(Path(n).suffix)]
    return len(names) <= 4 and len(roms) >= 1 and not any(
        Path(n).suffix.lower() in (".exe", ".msi") for n in names)


def build(item: ScanItem, cfg: Config) -> dict:
    warnings: list[str] = []
    actions: list[dict] = []
    system = item.system

    if not system:
        warnings.append(
            "System could not be determined"
            + (f"; candidates: {', '.join(item.candidates)}" if item.candidates else "")
            + ". Set it with --system or edit the plan before applying.")
    elif item.candidates:
        warnings.append(f"Ambiguous: also plausible as {', '.join(item.candidates)}.")

    rom_root = Path(cfg.rom_dir)
    target = rom_root / (system or "UNKNOWN")

    roms = item.by_kind("rom") + item.by_kind("disc")
    archives = item.by_kind("archive")
    installers = item.by_kind("installer")

    # --- Windows/PC games: install, don't copy ---------------------------
    if system == "windows" or (installers and not roms):
        actions.append(_action("mkdir", path=str(Path(cfg.install_dir) / item.name)))
        for f in installers:
            actions.append(_action(
                "install", exe=str(f.path), cwd=str(f.path.parent),
                dest=str(Path(cfg.install_dir) / item.name),
                needs_review=True,
                why="Runs a third-party installer; approve after reading the README."))
        actions.append(_action(
            "make_launcher",
            dest=str(target / f"{item.name}.lnk"),
            target_exe=None,
            needs_review=True,
            why="Point this at the installed game .exe so ES-DE can launch it."))
        if not installers:
            warnings.append("No installer found for a PC game; check the README steps.")

    # --- Everything else: place ROMs into <ROMs>/<system>/ ---------------
    else:
        multi = [f for f in roms if f.ext in MULTIFILE_EXTS]
        needs_subdir = len(roms) > 1 and bool(multi)
        dest_dir = target / item.name if needs_subdir else target
        actions.append(_action("mkdir", path=str(dest_dir)))

        for f in roms:
            actions.append(_action("copy", src=str(f.path), dst=str(dest_dir / f.path.name),
                                   size=f.size))

        for f in archives:
            if _zip_looks_like_rom(f.path, system):
                actions.append(_action("copy", src=str(f.path), dst=str(dest_dir / f.path.name),
                                       size=f.size))
            elif cfg.auto_extract and f.ext == ".zip":
                actions.append(_action("extract", src=str(f.path), dst=str(dest_dir)))
            else:
                actions.append(_action(
                    "extract", src=str(f.path), dst=str(dest_dir), needs_review=True,
                    why=f"{f.ext} needs an external extractor (7-Zip); verify contents first."))

        # Multi-disc sets get an .m3u so ES-DE shows one entry.
        if cfg.make_m3u:
            discs = {}
            for f in roms:
                n = disc_number(f.path.stem)
                if n and f.ext in (".cue", ".chd", ".iso", ".pbp", ".gdi", ".m3u"):
                    discs[n] = (dest_dir / f.path.name).name
            if len(discs) > 1:
                entries = [discs[k] for k in sorted(discs)]
                title = clean_title(item.name)
                actions.append(_action("m3u", path=str(dest_dir / f"{title}.m3u"),
                                       entries=entries))

    # --- README-derived manual steps (never auto-run) --------------------
    hints = item.hints
    if hints:
        for flag in hints.flags:
            actions.append(_action("manual", text=_FLAG_ADVICE.get(flag, flag),
                                   flag=flag, source=hints.source, needs_review=True))
        for c in hints.commands:
            actions.append(_action(
                "suggested_command", text=c["text"], source=f"{hints.source}:{c['line']}",
                needs_review=True,
                why="Command copied verbatim from an untrusted README. Read it before running."))
        if hints.bios:
            actions.append(_action("manual", text="BIOS files referenced: " + ", ".join(hints.bios),
                                   flag="needs_bios", source=hints.source, needs_review=True))
        if hints.discs > 1 and not any(a["type"] == "m3u" for a in actions):
            warnings.append(f"README mentions {hints.discs} discs but only one was found.")
    elif not roms and not archives and not installers:
        warnings.append("Nothing installable found (no ROM, archive, or installer).")

    return {
        "version": PLAN_VERSION,
        "name": item.name,
        "source": str(item.root),
        "system": system,
        "confidence": item.confidence,
        "candidates": item.candidates,
        "reasons": item.reasons,
        "readme": hints.source if hints else None,
        "warnings": warnings,
        "actions": actions,
    }


def build_all(items, cfg: Config) -> dict:
    return {"version": PLAN_VERSION, "rom_dir": cfg.rom_dir,
            "plans": [build(i, cfg) for i in items]}


def summarize(plan: dict) -> str:
    counts: dict[str, int] = {}
    review = 0
    for a in plan["actions"]:
        counts[a["type"]] = counts.get(a["type"], 0) + 1
        review += bool(a.get("needs_review"))
    parts = ", ".join(f"{v}x {k}" for k, v in sorted(counts.items()))
    tail = f" ({review} need review)" if review else ""
    return parts + tail
