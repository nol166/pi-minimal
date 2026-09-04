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
DEFAULT_CHECKED = {"ollama-lan", "grove-pi-extension"}
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


def discover() -> list[Section]:
    exts, skills, seen = Section("Extensions"), Section("Skills"), set()

    def add(section, name, path):
        if name in seen:
            return
        seen.add(name)
        section.items.append(Item(name, path))

    for d in sorted(_package_dirs(), key=lambda p: p.name):
        for cand in (d / "pi-extension" / "index.js", d / "index.ts", d / "index.js"):
            if cand.exists():
                add(exts, d.name, cand)
                break
        for sk in sorted((d / "skills").iterdir()) if (d / "skills").is_dir() else []:
            if (sk / "SKILL.md").exists():
                add(skills, sk.name, sk)

    ext_dir = PI_AGENT / "extensions"
    if ext_dir.is_dir():
        for p in sorted(ext_dir.iterdir()):
            if p.name.endswith(".disabled"):
                continue
            if p.is_file() and p.suffix in CODE_EXTS:
                add(exts, p.stem, p)
            elif p.is_dir() and any(p.glob("index.*")):
                add(exts, p.name, p)

    skills_dir = PI_AGENT / "skills"
    if skills_dir.is_dir():
        for p in sorted(skills_dir.iterdir()):
            if (p / "SKILL.md").exists():
                add(skills, p.name, p)

    opts = Section("Options", [Item(CONTEXT_OPT, None)])
    return [exts, skills, opts]


def load_state(sections) -> None:
    try:
        saved = set(json.loads(STATE_FILE.read_text()))
    except (OSError, json.JSONDecodeError):
        saved = set(DEFAULT_CHECKED)
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
    for sec in sections:
        if row < h - 3:
            stdscr.addnstr(row, 0, sec.name.upper(), w - 1, curses.A_BOLD)
        row += 1
        for i, it in enumerate(sec.items):
            if row >= h - 3:
                break
            mark = "[x]" if it.checked else "[ ]"
            label = f" {mark} {it.name}"
            if i == cursor:
                stdscr.addnstr(row, 0, label[: w - 1], w - 1, curses.A_REVERSE)
            else:
                stdscr.addnstr(row, 0, label, w - 1)
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
            os.execvp("pi", build_command(sections))
        elif key == "q":
            save_state(sections)
            return


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
