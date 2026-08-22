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
# Systems where a game is a whole folder of files (executable + data), not one
# ROM file. Cherry-picking recognized extensions here would drop the game.
FOLDER_SYSTEMS = {"dos", "scummvm", "ports"}
# Multi-file disc formats that belong in a per-game subfolder.
MULTIFILE_EXTS = {".cue", ".bin", ".ccd", ".img", ".sub", ".mds", ".mdf", ".gdi", ".raw"}

# Extensions that can head an .m3u playlist, i.e. one entry per disc.
PLAYLIST_EXTS = (".cue", ".chd", ".iso", ".pbp", ".gdi", ".ccd", ".toc")

# The file an emulator should actually be pointed at, best first. A .cue
# describes the .bin next to it, so the .cue is the game and the .bin is data.
ENTRY_POINT_ORDER = (".m3u", ".cue", ".gdi", ".ccd", ".toc", ".chd", ".iso", ".img", ".bin")


def entry_point(roms):
    """The one file that should be visible in ES-DE for a multi-file game."""
    for ext in ENTRY_POINT_ORDER:
        for f in roms:
            if f.ext == ext:
                return f
    return None

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
        game_dir = Path(cfg.install_dir) / item.name
        actions.append(_action("mkdir", path=str(game_dir)))

        # A PC game shipped as an archive still has to be unpacked somewhere.
        for f in archives:
            if cfg.auto_extract and f.ext == ".zip":
                actions.append(_action("extract", src=str(f.path), dst=str(game_dir)))
            else:
                actions.append(_action(
                    "extract", src=str(f.path), dst=str(game_dir), needs_review=True,
                    why=f"{f.ext} needs an external extractor (7-Zip); verify contents first."))

        for f in installers:
            actions.append(_action(
                "install", exe=str(f.path), cwd=str(f.path.parent),
                dest=str(Path(cfg.install_dir) / item.name),
                needs_review=True,
                why="Runs a third-party installer; approve after reading the README."))
        actions.append(_action(
            "make_launcher",
            dest=str(target / f"{item.name}.lnk"),
            search_in=str(game_dir),
            target_exe=None,
            needs_review=True,
            why="Point this at the installed game .exe so ES-DE can launch it."))
        if not installers and not archives:
            warnings.append("No installer or archive found for a PC game; check the README steps.")

    # --- DOS/ScummVM/ports: the whole folder is the game -----------------
    elif system in FOLDER_SYSTEMS and item.root.is_dir():
        actions.append(_action("copy_tree", src=str(item.root),
                               dst=str(target / item.name), size=item.total_size))

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
        #
        # ES-DE lists every file whose extension the system claims, and psx
        # claims .bin, .cue and .m3u alike - so four discs would appear nine
        # times. The .m3u therefore lives in the system folder, the discs live
        # in a subfolder, and that subfolder is hidden so only the .m3u shows.
        made_playlist = False
        if cfg.make_m3u:
            discs = {}
            for f in roms:
                n = disc_number(f.path.stem)
                if n and f.ext in PLAYLIST_EXTS:
                    discs[n] = f.path.name
            if len(discs) > 1:
                title = clean_title(item.name)
                entries = [f"{dest_dir.name}/{discs[k]}" for k in sorted(discs)]
                actions.append(_action("m3u", path=str(target / f"{title}.m3u"),
                                       entries=entries))
                actions.append(_action(
                    "hide", path=str(dest_dir),
                    why="so ES-DE shows the .m3u only, not every disc twice"))
                made_playlist = True

        # A single-disc game still has a .cue and a .bin, which ES-DE would
        # list as two games. Hide everything that is not the entry point.
        if not made_playlist and len(roms) > 1:
            primary = entry_point(roms)
            if primary is not None:
                for f in roms:
                    if f.path != primary.path:
                        actions.append(_action(
                            "hide", path=str(dest_dir / f.path.name),
                            why=f"data file for {primary.path.name}"))

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
