"""Choose which emulator ES-DE uses for a system, and make it stick.

ES-DE lists several emulators per system and runs the first unless told
otherwise. That default is not always the easiest one to get working: for PSX it
is Beetle PSX, whose core info marks three BIOS files as required, while
SwanStation sits further down the same list and marks all of its firmware
optional. Same games, no BIOS hunt.

ES-DE stores a per-system override at the top of that system's gamelist.xml:

    <alternativeEmulator><label>SwanStation</label></alternativeEmulator>

esdeck writes that file, records the choice in its own config so it travels to
other machines with `esdeck profile`, and works out which alternatives avoid a
BIOS requirement by reading the cores' own metadata rather than guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import bios as bios_mod
from . import esde

_ALT_BLOCK_RE = re.compile(
    r"<alternativeEmulator>.*?</alternativeEmulator>\s*", re.S | re.I)

#: Emulators esdeck picks by default where ES-DE's first choice is awkward.
#: Only where there is a clear reason - here, avoiding a required BIOS.
DEFAULT_CHOICES = {
    "psx": "SwanStation",
}


@dataclass
class Choice:
    label: str
    core: str | None
    requires_bios: bool
    standalone: bool = False

    def describe(self) -> str:
        if self.standalone:
            return f"{self.label} (separate emulator, not a core)"
        need = "needs BIOS" if self.requires_bios else "no BIOS needed"
        return f"{self.label} [{self.core}] - {need}"


def choices_for(system: str) -> list[Choice]:
    """Every emulator ES-DE offers for a system, in ES-DE's own order."""
    sysdef = esde.load().get(system)
    if sysdef is None:
        return []
    out = []
    for label, cmd in sysdef.commands:
        if not label:
            continue
        m = esde._CORE_RE.search(cmd)
        core = m.group(1).lower() if m else None
        out.append(Choice(label, core, _core_needs_bios(core) if core else False,
                          standalone=core is None))
    return out


def _core_needs_bios(core: str) -> bool:
    """Whether a core declares any firmware as required rather than optional."""
    reqs = bios_mod._core_requirements().get(core)
    if not reqs:
        return False
    return any(b.required for b in reqs)


def effective(system: str, es_config_dir=None) -> Choice | None:
    """The emulator ES-DE will actually use: the override, else its default."""
    options = choices_for(system)
    if not options:
        return None
    if es_config_dir:
        label = current(Path(es_config_dir), system)
        if label:
            for c in options:
                if c.label == label:
                    return c
    return options[0]


def suggest(system: str, es_config_dir=None) -> Choice | None:
    """A BIOS-free alternative, when the emulator in use needs firmware you lack.

    Returns None when what is already in use is fine - including when an
    override has been set - or when nothing better exists. Suggesting a change
    for its own sake would be noise.
    """
    options = choices_for(system)
    if not options:
        return None
    in_use = effective(system, es_config_dir)
    if in_use is None or not in_use.requires_bios:
        return None
    if not bios_mod.blocking(bios_mod.check_system(system)):
        return None          # the BIOS is present, so it works as configured
    # Prefer esdeck's own pick for this system when it is one of the options,
    # so the suggestion matches what a fresh install would have configured.
    preferred = DEFAULT_CHOICES.get(system)
    for choice in options:
        if choice.label == preferred and choice.core and not choice.requires_bios:
            return choice
    for choice in options:
        if choice.core and not choice.requires_bios:
            return choice
    return None


# --------------------------------------------------------------------------
# Reading and writing ES-DE's per-system override.
# --------------------------------------------------------------------------

def gamelist_path(es_config_dir: Path, system: str) -> Path:
    return Path(es_config_dir) / "gamelists" / system / "gamelist.xml"


def current(es_config_dir: Path, system: str) -> str | None:
    """The emulator ES-DE is currently set to use, or None for its default."""
    path = gamelist_path(es_config_dir, system)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r"<alternativeEmulator>\s*<label>([^<]*)</label>", text, re.I)
    return m.group(1).strip() if m else None


def set_emulator(es_config_dir: Path, system: str, label: str, *,
                 dry_run: bool = False) -> str:
    """Write the per-system override into gamelist.xml, preserving the games.

    ES-DE rewrites gamelist.xml on exit, so it must not be running.
    """
    path = gamelist_path(es_config_dir, system)
    block = f"<alternativeEmulator>\n\t<label>{label}</label>\n</alternativeEmulator>\n"

    if not path.is_file():
        if dry_run:
            return f"{system}: would create gamelist.xml with {label}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('<?xml version="1.0"?>\n' + block + "<gameList />\n",
                        encoding="utf-8")
        return f"{system}: set to {label} (new gamelist.xml)"

    text = path.read_text(encoding="utf-8", errors="replace")
    if current(es_config_dir, system) == label:
        return f"{system}: already {label}"
    if dry_run:
        return f"{system}: would set to {label}"

    stripped = _ALT_BLOCK_RE.sub("", text)
    if "<?xml" in stripped:
        head, _, rest = stripped.partition("?>")
        new = head + "?>\n" + block + rest.lstrip("\n")
    else:
        new = block + stripped
    path.write_text(new, encoding="utf-8")
    return f"{system}: set to {label}"


def apply_choices(es_config_dir: Path, choices: dict, *, dry_run: bool = False,
                  log=print) -> int:
    """Apply a {system: label} mapping, skipping labels ES-DE does not offer."""
    applied = 0
    for system, label in sorted(choices.items()):
        available = {c.label for c in choices_for(system)}
        if available and label not in available:
            log(f"  SKIP   {system}: ES-DE has no emulator called {label!r}")
            continue
        log("  " + set_emulator(Path(es_config_dir), system, label, dry_run=dry_run))
        applied += 1
    return applied
