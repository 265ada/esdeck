"""Execute a plan.

Safe actions (mkdir/copy/extract/m3u) run on approval of the plan as a whole.
Actions flagged ``needs_review`` - installers, README-derived commands, manual
steps - are never executed by this module. `suggested_command` is *always*
inert: it is printed for a human to run, because its text came from a file we
did not write.
"""

from __future__ import annotations

import ctypes
import os
import shutil
from pathlib import Path

from . import archives
from . import patch as patch_mod

SAFE_TYPES = {"mkdir", "copy", "copy_tree", "extract", "m3u", "hide", "patch"}
INERT_TYPES = {"manual", "suggested_command", "make_launcher"}


class Result:
    def __init__(self) -> None:
        self.done: list[str] = []
        self.skipped: list[str] = []
        self.errors: list[str] = []
        #: Paths this run created, so a later undo can remove exactly these.
        self.created: list[tuple] = []      # (Path, "file" | "dir")

    def __str__(self) -> str:
        return f"{len(self.done)} applied, {len(self.skipped)} skipped, {len(self.errors)} errors"


FILE_ATTRIBUTE_HIDDEN = 0x02


def set_hidden(path: Path) -> bool:
    """Mark a file or folder hidden so ES-DE skips it (ShowHiddenFiles=false).

    ES-DE lists every file matching a system extension, and psx accepts .bin,
    .cue and .m3u alike - so a four-disc game shows up nine times. Hiding the
    parts that are not the entry point leaves exactly one launchable item.
    """
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.kernel32.SetFileAttributesW(str(path),
                                                              FILE_ATTRIBUTE_HIDDEN))
    except (AttributeError, OSError):
        return False


def apply_plan(plan: dict, *, dry_run: bool = True, roots: list[str] | None = None,
               overwrite: bool = False, log=print, on_progress=None) -> Result:
    """Execute a plan.

    on_progress, if given, is called after each action that moves data with
    (action_type, bytes, label) so a caller can show progress and an estimate.
    """
    res = Result()
    root_paths = [Path(r) for r in (roots or []) if r]

    def guard(dst: Path) -> None:
        if not root_paths:
            return
        for r in root_paths:
            try:
                dst.resolve().relative_to(r.resolve())
                return
            except ValueError:
                continue
        raise PermissionError(f"refusing to write outside {', '.join(map(str, root_paths))}: {dst}")

    for a in plan.get("actions", []):
        kind = a["type"]
        if a.get("needs_review") or kind in INERT_TYPES:
            res.skipped.append(f"{kind}: {a.get('text') or a.get('exe') or a.get('dest') or ''}")
            continue
        if kind not in SAFE_TYPES:
            res.skipped.append(f"{kind}: unknown action type")
            continue
        try:
            if kind == "mkdir":
                p = Path(a["path"]); guard(p)
                log(f"  mkdir  {p}")
                if not dry_run:
                    existed = p.is_dir()
                    p.mkdir(parents=True, exist_ok=True)
                    if not existed:
                        res.created.append((p, "dir"))

            elif kind == "copy":
                src, dst = Path(a["src"]), Path(a["dst"]); guard(dst)
                if dst.exists() and not overwrite:
                    res.skipped.append(f"copy: {dst.name} already exists")
                    continue
                log(f"  copy   {src.name} -> {dst}")
                if not dry_run:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    res.created.append((dst, "file"))

            elif kind == "copy_tree":
                src, dst = Path(a["src"]), Path(a["dst"]); guard(dst)
                if dst.exists() and not overwrite:
                    res.skipped.append(f"copy_tree: {dst.name} already exists")
                    continue
                log(f"  copydir {src.name} -> {dst}")
                if not dry_run:
                    shutil.copytree(src, dst, dirs_exist_ok=overwrite)
                    res.created.append((dst, "dir"))
                    for made in dst.rglob("*"):
                        res.created.append((made, "dir" if made.is_dir() else "file"))

            elif kind == "extract":
                src, dst = Path(a["src"]), Path(a["dst"]); guard(dst)
                log(f"  unpack {src.name} -> {dst}")
                if not dry_run:
                    before = {p for p in dst.rglob("*")} if dst.is_dir() else set()
                    written = archives.extract(src, dst, log=log)
                    log(f"         {written} file(s)")
                    for made in dst.rglob("*"):
                        if made not in before:
                            res.created.append(
                                (made, "dir" if made.is_dir() else "file"))

            elif kind == "hide":
                p = Path(a["path"]); guard(p)
                log(f"  hide   {p.name}  ({a.get('why', '')})")
                if not dry_run and p.exists():
                    set_hidden(p)

            elif kind == "patch":
                base_p, patch_p = Path(a["base"]), Path(a["patch"])
                dst = Path(a["dst"]); guard(dst)
                if dst.exists() and not overwrite:
                    res.skipped.append(f"patch: {dst.name} already exists")
                    continue
                log(f"  mod    {patch_p.name} -> {dst.name}")
                if not dry_run:
                    out = patch_mod.apply_patch(base_p, patch_p, dst)
                    res.created.append((dst, "file"))
                    log(f"         {out.format.upper()}"
                        f"{', base ROM verified' if out.verified else ''}")

            elif kind == "m3u":
                p = Path(a["path"]); guard(p)
                log(f"  m3u    {p.name} ({len(a['entries'])} discs)")
                if not dry_run:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text("\n".join(a["entries"]) + "\n", encoding="utf-8")
                    res.created.append((p, "file"))

            res.done.append(kind)
            if on_progress is not None and kind in ("copy", "copy_tree",
                                                    "extract", "patch"):
                moved = int(a.get("size") or 0)
                label = Path(a.get("dst") or a.get("path") or "").name
                on_progress(kind, moved, label)
        except Exception as exc:                     # noqa: BLE001 - reported, not raised
            res.errors.append(f"{kind}: {exc}")
            log(f"  ERROR  {kind}: {exc}")
    return res


def manual_steps(plan: dict) -> list[str]:
    """Human-facing to-do list left over after a plan is applied."""
    out = []
    for a in plan.get("actions", []):
        if a["type"] == "manual":
            out.append(a["text"] + (f"  [{a.get('source')}]" if a.get("source") else ""))
        elif a["type"] == "suggested_command":
            out.append(f"Review before running ({a.get('source')}): {a['text']}")
        elif a["type"] == "install":
            out.append(f"Run installer: {a['exe']}  (install into {a.get('dest')})")
        elif a["type"] == "make_launcher":
            out.append(f"Create launcher {a['dest']} pointing at the installed game .exe")
    return out
