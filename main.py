#!/usr/bin/env python3
"""pi-minimal: pick which pi extensions/skills to load, then launch pi stripped down.

Uses --no-extensions/--no-skills/etc so nothing is discovered, then re-adds
only the checked items via -e / --skill.
"""

import curses
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

PI_AGENT = Path(os.environ.get("PI_AGENT_DIR", "~/.pi/agent")).expanduser()
STATE_FILE = Path(os.environ.get("PI_MINIMAL_STATE", "~/.config/pi-minimal/selections.json")).expanduser()
CODE_EXTS = {".ts", ".js", ".mjs", ".cjs"}
CONFIG_FILE = STATE_FILE.parent / "config.json"
CONTEXT_OPT = "AGENTS.md / CLAUDE.md context files"


@dataclass
class Item:
    name: str
    path: Path | None
    checked: bool = False


@dataclass
class Section:
    name: str
    items: list[Item] = field(default_factory=list)


def _settings() -> dict:
    try:
        return json.loads((PI_AGENT / "settings.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _package_dirs() -> list[Path]:
    out = []
    for pkg in _settings().get("packages", []):
        source = pkg if isinstance(pkg, str) else pkg.get("source", "")
        if source.startswith("git:"):
            rest = source[4:]
            if rest.startswith("git@github.com:"):
                rest = "github.com/" + rest[len("git@github.com:"):]
            out.append(PI_AGENT / "git" / rest)
        elif source.startswith("npm:"):
            out.append(PI_AGENT / "npm" / "node_modules" / source[4:])
    return [d for d in out if d.is_dir()]


def _project_dirs() -> list[Path]:
    """cwd up to the repo root (or filesystem root)."""
    out, d = [], Path.cwd()
    while True:
        out.append(d)
        if (d / ".git").exists() or d.parent == d:
            break
        d = d.parent
    return out


def _frontmatter_name(path: Path) -> str | None:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return None
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith("name:"):
            return line.split(":", 1)[1].strip().strip("\"'") or None
    return None


def _settings_skill_entries(settings: dict, base: Path) -> list[Path]:
    """`skills` array entries (files or dirs), resolved against the settings file's dir."""
    out = []
    for e in settings.get("skills", []):
        if not isinstance(e, str):
            continue
        p = Path(os.path.expanduser(e))
        out.append(p if p.is_absolute() else base / p)
    return out


def discover() -> list[Section]:
    exts, skills, proj = Section("Extensions"), Section("Skills"), Section("Project skills")
    seen: set[str] = set()
    loaded: set[Path] = set()  # real path of each skill file; pi's symlink dedupe

    def add(section, name, path):
        if name in seen:
            return
        seen.add(name)
        section.items.append(Item(name, path))

    def add_skill(section, base: Path, file: str = "SKILL.md"):
        skill_file = base / file
        real = skill_file.resolve()
        if real in loaded:
            return  # same file already listed (e.g. via symlink); pi skips silently
        loaded.add(real)
        if file == "SKILL.md":
            add(section, base.name, base)  # pi may rename via frontmatter; dir name is the spec default
        else:  # ponytail: frontmatter name, stem fallback (pi falls back to the parent dir name)
            add(section, _frontmatter_name(skill_file) or file[:-3], skill_file)

    def scan_skills(section, base: Path, root_files: bool = False):
        # ponytail: one level deep; pi also recurses into grouping folders
        if not base.is_dir():
            return
        for p in sorted(base.iterdir()):
            if p.is_dir() and (p / "SKILL.md").is_file():
                add_skill(section, p)
            elif root_files and p.is_file() and p.suffix == ".md":
                add_skill(section, p.parent, p.name)

    def add_settings_entry(section, e: Path):
        if (e / "SKILL.md").is_file():
            add_skill(section, e)
        elif e.is_dir():
            for p in sorted(e.iterdir()):
                if p.is_dir() and (p / "SKILL.md").is_file():
                    add_skill(section, p)
        elif e.is_file() and e.suffix == ".md":
            add_skill(section, e.parent, e.name)

    # Load order follows pi so name-collision winners match:
    # global dirs, project dirs, packages, settings. First one listed wins a name.
    scan_skills(skills, PI_AGENT / "skills", root_files=True)
    scan_skills(skills, Path.home() / ".agents" / "skills")
    for d in _project_dirs():
        scan_skills(proj, d / ".pi" / "skills", root_files=True)
        scan_skills(proj, d / ".agents" / "skills")

    for d in sorted(_package_dirs(), key=lambda p: p.name):
        for cand in (d / "pi-extension" / "index.js", d / "index.ts", d / "index.js"):
            if cand.exists():
                add(exts, d.name, cand)
                break
        scan_skills(skills, d / "skills")

    ext_dir = PI_AGENT / "extensions"
    if ext_dir.is_dir():
        for p in sorted(ext_dir.iterdir()):
            if p.name.endswith(".disabled"):
                continue
            if p.is_file() and p.suffix in CODE_EXTS:
                add(exts, p.stem, p)
            elif p.is_dir() and any(p.glob("index.*")):
                add(exts, p.name, p)

    for e in _settings_skill_entries(_settings(), PI_AGENT):
        add_settings_entry(skills, e)
    for d in _project_dirs():
        sp = d / ".pi" / "settings.json"
        if sp.is_file():
            try:
                cfg = json.loads(sp.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            for e in _settings_skill_entries(cfg, d / ".pi"):
                add_settings_entry(proj, e)

    opts = Section("Options", [Item(CONTEXT_OPT, None)])
    return [exts, skills, proj, opts]


def _defaults() -> set[str]:
    try:
        cfg = json.loads(CONFIG_FILE.read_text())
        return set(cfg.get("default_checked", []))
    except (OSError, json.JSONDecodeError):
        return set()


def load_state(sections) -> None:
    try:
        saved = set(json.loads(STATE_FILE.read_text()))
    except (OSError, json.JSONDecodeError):
        saved = _defaults()
    for sec in sections:
        for it in sec.items:
            it.checked = it.name in saved


def save_state(sections) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(
        sorted(it.name for sec in sections for it in sec.items if it.checked)))


def build_command(sections) -> list[str]:
    args = ["pi", "--no-extensions", "--no-skills", "--no-prompt-templates", "--no-themes"]
    for sec in sections:
        if sec.name == "Options":
            if not sec.items[0].checked:
                args.append("--no-context-files")  # option OFF means strip context files
            continue
        flag = "-e" if sec.name == "Extensions" else "--skill"
        for it in sec.items:
            if it.checked:
                args += [flag, str(it.path)]
    return args


def _draw(stdscr, sections, cursor) -> None:
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    for r, line in enumerate(["pi-minimal — check what to load, Enter launches", ""]):
        if r < h:
            stdscr.addnstr(0, 0, line, w - 1)
    row = 2
    pos = 0
    for sec in sections:
        if row < h - 3:
            stdscr.addnstr(row, 0, sec.name.upper(), w - 1, curses.A_BOLD)
        row += 1
        for it in sec.items:
            if row >= h - 3:
                break
            mark = "[x]" if it.checked else "[ ]"
            label = f" {mark} {it.name}"
            if pos == cursor:
                stdscr.addnstr(row, 0, label[: w - 1], w - 1, curses.A_REVERSE)
            else:
                stdscr.addnstr(row, 0, label, w - 1)
            pos += 1
            row += 1
        row += 1
    cmd = " ".join(build_command(sections))
    if h >= 2:
        stdscr.addnstr(h - 2, 0, cmd[: w - 1], w - 1, curses.A_DIM)
    stdscr.addnstr(h - 1, 0, "↑/j down  ↓/k up  space toggle  enter launch  q quit"[: w - 1], w - 1)
    stdscr.refresh()


def _flat(sections):
    return [it for sec in sections for it in sec.items]


def _move(sections, cursor, delta) -> int:
    flat = _flat(sections)
    return (cursor + delta) % len(flat)


def _toggle_at(sections, cursor, flat) -> None:
    n = 0
    for sec in sections:
        for it in sec.items:
            if n == cursor:
                it.checked = not it.checked
                return
            n += 1


def _tui(stdscr) -> None:
    sections = discover()
    load_state(sections)
    flat = _flat(sections)
    cursor = next(i for i, it in enumerate(flat) if it.checked) if any(i.checked for i in flat) else 0
    try:
        while True:
            _draw(stdscr, sections, cursor)
            key = stdscr.getkey()
            if key in ("KEY_UP", "k"):
                cursor = _move(sections, cursor, -1)
            elif key in ("KEY_DOWN", "j"):
                cursor = _move(sections, cursor, 1)
            elif key == " ":
                _toggle_at(sections, cursor, flat)
            elif key == "KEY_ENTER" or key == "\n":
                save_state(sections)
                curses.endwin()  # leave curses mode
                os.write(1, b"\x1b[2J\x1b[H")  # clear + home; endwin leaves cursor mid-line
                os.execvp("pi", build_command(sections))
            elif key == "q":
                save_state(sections)
                return
    except KeyboardInterrupt:
        save_state(sections)  # same as q: keep the selection, exit cleanly


def main() -> None:
    if "--list" in sys.argv:
        sections = discover()
        load_state(sections)
        for sec in sections:
            print(sec.name)
            for it in sec.items:
                print(f"  {'[x]' if it.checked else '[ ]'} {it.name}  ->  {it.path or '-'}")
        print("\n$ " + " ".join(build_command(sections)))
        return
    curses.wrapper(_tui)


if __name__ == "__main__":
    main()
