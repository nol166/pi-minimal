#!/usr/bin/env python3
"""pi-minimal: pick which pi extensions/skills to load, then launch pi stripped down.

--no-extensions/--no-skills/etc stop pi discovering anything, then the checked items go
back on the command line as -e / --skill. Discovery mirrors pi 1.0 (see package-manager.js):
package manifests and filters, the +/-/! prefixes in resource arrays, and the built-in
extensions that --no-extensions switches off too.
"""

import curses
import fnmatch
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

PI_AGENT = Path(os.environ.get("PI_CODING_AGENT_DIR") or os.environ.get("PI_AGENT_DIR", "~/.pi/agent")).expanduser()
STATE_FILE = Path(os.environ.get("PI_MINIMAL_STATE", "~/.config/pi-minimal/selections.json")).expanduser()
CODE_EXTS = {".ts", ".js"}
CONFIG_FILE = STATE_FILE.parent / "config.json"
CONTEXT_OPT = "AGENTS.md / CLAUDE.md context files"
SKIP_DIRS = {"node_modules"}
# Loaded by default in plain pi; --no-extensions kills them, -e builtin:<name> brings one back.
BUILTIN_EXTS = ("builtin:mcp", "builtin:llama.cpp", "builtin:codemode", "builtin:tool-search")


@dataclass
class Item:
    name: str
    args: list[str] = field(default_factory=list)  # values that follow the section flag
    checked: bool = False
    default: bool = False  # on unless settings or a saved "-name" turn it off


@dataclass
class Section:
    name: str
    items: list[Item] = field(default_factory=list)
    flag: str = ""  # "" marks the inverted Options toggle


def _settings() -> dict:
    try:
        return json.loads((PI_AGENT / "settings.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {}


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


def _project_dirs() -> list[Path]:
    """cwd up to the repo root (or filesystem root)."""
    out, d = [], Path.cwd()
    while True:
        out.append(d)
        if (d / ".git").exists() or d.parent == d:
            break
        d = d.parent
    return out


def _project_settings() -> list[tuple[Path, dict]]:
    """Project `.pi/settings.json` for cwd and ancestors, cwd first."""
    out = []
    for d in _project_dirs():
        path = d / ".pi" / "settings.json"
        if path.is_file():
            try:
                out.append((d, json.loads(path.read_text())))
            except (OSError, json.JSONDecodeError):
                continue
    return out


# --- pi's resource-list syntax -------------------------------------------------------------
# An entry is a path or glob to include, or is prefixed: '+' force-include, '-' exclude one
# exact path, '!glob' exclude a glob. Relative entries resolve against the settings file's
# directory, a package root, or a skills directory.


def _split(values) -> tuple[list[str], list[str], list[str]]:
    """Split a resource array into (plain, '+' includes, '-'/'!' excludes), prefixes stripped."""
    plain, plus, drops = [], [], []
    for v in values if isinstance(values, list) else []:
        if not isinstance(v, str) or not v.strip():
            continue
        v = v.strip()
        target = plus if v[0] == "+" else drops if v[0] in "-!" else plain
        target.append(v[1:] if v[0] in "+-!" else v)
    return plain, plus, drops


def _is_pattern(entry: str) -> bool:
    return entry.startswith(("+", "-", "!")) or "*" in entry or "?" in entry


def _is_filter(entry: str) -> bool:
    """Only '+'/'-'/'!' entries filter; plain manifest entries are just paths."""
    return entry.startswith(("+", "-", "!"))


def _keys(path: Path, base: Path) -> list[str]:
    """Names pi matches a resource against: absolute, file name, relative to `base`, and for
    a SKILL.md also its parent directory, so '-skills/foo' hits 'skills/foo/SKILL.md'."""
    keys = [str(path), path.name]
    try:
        keys.append(path.relative_to(base).as_posix())
    except ValueError:
        pass
    if path.name == "SKILL.md":
        keys += _keys(path.parent, base)
    return keys


def _hit(keys: list[str], patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(key, pattern.removeprefix("./")) for pattern in patterns for key in keys)


def _on(path: Path, scopes: list[tuple[list[str], Path]]) -> bool:
    """Is an auto-discovered resource enabled? The first scope that mentions it decides, so
    project settings override user settings, matching pi's isEnabledByOverrides."""
    for patterns, base in scopes:
        _, plus, drops = _split(patterns)
        keys = _keys(path, base)
        if _hit(keys, drops) or _hit(keys, plus):
            return not _hit(keys, drops)
    return True


def _narrow(files: list[Path], patterns, base: Path) -> list[Path]:
    """Filter a package's resources (pi's applyPatterns): plain entries narrow the list,
    '-'/'!' remove, '+' restores what a removal took out."""
    plain, plus, drops = _split(patterns)
    if plain:
        files = [f for f in files if _hit(_keys(f, base), plain)]
    kept = [f for f in files if not _hit(_keys(f, base), drops)]
    if plus:
        kept += [f for f in files if f not in kept and _hit(_keys(f, base), plus)]
    return kept


# --- discovery -----------------------------------------------------------------------------


def _expand(values, base: Path) -> list[Path]:
    """Resolve declared paths/globs against `base`; unlike filters these add resources."""
    out = []
    for value in values:
        path = Path(os.path.expanduser(value))
        if not path.is_absolute():
            path = base / path
        out += sorted(path.parent.glob(path.name)) if set("*?") & set(value) else [path]
    return out


def _resolved_dir(d: Path) -> list[Path]:
    """What one directory contributes: declared `pi.extensions`, else index.ts/index.js."""
    declared = _manifest(d).get("extensions", [])
    if declared:
        paths = _expand([e for e in declared if not _is_filter(e)], d)
        if paths:
            return _narrow(_resource_files(paths, "extensions"), [e for e in declared if _is_filter(e)], d)
    for name in ("index.ts", "index.js"):
        if (d / name).is_file():
            return [d / name]
    return []


def _manifest(path: Path) -> dict:
    """The `pi` key of a package.json: declared resource paths and filters."""
    try:
        manifest = json.loads((path / "package.json").read_text()).get("pi")
    except (OSError, json.JSONDecodeError, AttributeError):
        return {}
    return manifest if isinstance(manifest, dict) else {}


def _resource_files(paths, kind: str) -> list[Path]:
    """Expand candidate paths into resource files: a file is itself, a directory is walked."""
    out = []
    for path in paths:
        if path.is_dir():
            out += _skill_files(path) if kind == "skills" else _code_files(path)
        elif path.is_file() and path.suffix in ((".md",) if kind == "skills" else CODE_EXTS):
            out.append(path)
    return out


def _skill_files(base: Path, seen: set[str] | None = None) -> list[Path]:
    """SKILL.md files at or under `base`; pi recurses past grouping folders (symlinked ones
    included, hence the resolve) and stops descending once a folder has its own SKILL.md."""
    seen = seen if seen is not None else set()
    real = str(base.resolve())
    if real in seen:
        return []
    seen.add(real)
    if (base / "SKILL.md").is_file():
        return [base / "SKILL.md"]
    try:
        entries = sorted(base.iterdir())
    except OSError:
        return []
    out = []
    for entry in entries:
        if entry.name.startswith(".") or entry.name in SKIP_DIRS:
            continue
        if entry.is_dir():
            out += _skill_files(entry, seen)
    return out


def _code_files(base: Path) -> list[Path]:
    """Code files pi picks up inside a directory: loose .ts/.js here, plus each subdir's own entry."""
    out = []
    for path in sorted(base.iterdir()):
        if path.name in SKIP_DIRS or path.name.startswith("."):
            continue
        if path.is_file() and path.suffix in CODE_EXTS:
            out.append(path)
        elif path.is_dir():
            out += _resolved_dir(path)
    return out


def _entry_files(entry: Path) -> list[Path]:
    """One entry of an extensions directory: a code file, or what its directory resolves to."""
    if entry.is_file():
        return [entry] if entry.suffix in CODE_EXTS else []
    return _resolved_dir(entry) if entry.is_dir() else []


def _packages() -> list[tuple[Path, dict]]:
    """Configured packages as (install path, settings entry); the entry's arrays filter it."""
    out = []
    for pkg in _settings().get("packages", []):
        source = pkg if isinstance(pkg, str) else pkg.get("source", "")
        if source.startswith("git:"):
            rest = source[4:]
            if rest.startswith("git@github.com:"):
                rest = "github.com/" + rest[len("git@github.com:"):]
            path = PI_AGENT / "git" / rest
        elif source.startswith("npm:"):
            path = PI_AGENT / "npm" / "node_modules" / source[4:]
        else:
            path = Path(os.path.expanduser(source))
        if path.is_dir() or path.is_file():
            out.append((path, pkg if isinstance(pkg, dict) else {}))
    return out


def _package_resources(pkg: Path, filters: dict) -> tuple[list[Path], list[Path]]:
    """(extensions, skills) a package loads, with manifest and settings filters applied."""
    manifest = _manifest(pkg) if pkg.is_dir() else {}
    ext_files, skill_files = [], []
    for kind, sink in (("extensions", ext_files), ("skills", skill_files)):
        declared = manifest.get(kind)
        if declared is None:  # no manifest: the conventional <package>/<kind>/ directory
            roots = [pkg] if pkg.is_file() else [pkg / kind]
            files = _resource_files([r for r in roots if r.exists()], kind)
        else:
            files = _resource_files(_expand([e for e in declared if not _is_filter(e)], pkg), kind)
            files = _narrow(files, [e for e in declared if _is_filter(e)], pkg)  # its own '!path' drops
        sink += _narrow(files, filters.get(kind, []), pkg)  # then the settings filter
    return ext_files, skill_files


def discover() -> list[Section]:
    exts = Section("Extensions", flag="-e")
    skills = Section("Skills", flag="--skill")
    proj = Section("Project skills", flag="--skill")
    seen: dict[str, set[str]] = {"-e": set(), "--skill": set()}  # pi dedupes extensions and skills separately
    keys: set[str] = set()  # state-file names, one per item
    loaded: set[Path] = set()  # real SKILL.md paths; pi loads a file once, symlink or not

    def add(section, name, args):
        if name in seen[section.flag]:
            return
        seen[section.flag].add(name)
        # a package can ship an extension and a skill of the same name; separate keys keep
        # their checkboxes independent in the state file
        key = name if name not in keys else f"{name} ({section.name})"
        keys.add(key)
        section.items.append(Item(key, [str(a) for a in args]))

    def add_skill(section, unit: Path, scopes):
        if unit.resolve() in loaded or not _on(unit, scopes):
            return
        loaded.add(unit.resolve())
        if unit.name == "SKILL.md":
            add(section, unit.parent.name, [unit.parent])
        else:
            add(section, _frontmatter_name(unit) or unit.stem, [unit])

    user = _settings()
    projects = _project_settings()
    cwd = Path.cwd()
    # pi keeps one project settings object; the nearest .pi wins and its directory is the
    # base for relative entries there.
    project_cfg = projects[0][1] if projects else {}

    def declare(entries, base, section, scopes):
        """Settings entries that name a path or glob add whatever they point at."""
        for entry in entries:
            if not isinstance(entry, str) or _is_filter(entry):
                continue
            # normpath so "../x" entries do not end up as "<dir>/.pi/../x" on the command line
            path = Path(os.path.normpath(os.path.join(base, os.path.expanduser(entry))))
            for unit in _resource_files([path], "skills"):
                add_skill(section, unit, scopes)

    # Order matches pi: packages, then project, then user, so a name collision drops the
    # same loser here as in pi. Project resources also need pi's project trust to load.
    for pkg, filters in _packages():
        pkg_ext, pkg_skills = _package_resources(pkg, filters)
        if pkg_ext:
            add(exts, pkg.name, pkg_ext)
        for unit in pkg_skills:
            add_skill(skills, unit, [])

    project_patterns = project_cfg.get("skills", [])
    user_patterns = user.get("skills", [])
    # Each source: where to look, the directory relative settings paths resolve against, the
    # section it lands in, and the resource array that filters it.
    sources = [(cwd / ".pi" / "skills", cwd / ".pi", proj, project_patterns)]
    sources += [(d / ".agents" / "skills", d / ".agents", proj, project_patterns) for d in _project_dirs()]
    sources += [(PI_AGENT / "skills", PI_AGENT, skills, user_patterns),
                (Path.home() / ".agents" / "skills", Path.home() / ".agents", skills, user_patterns)]
    for scan, base, section, patterns in sources:
        for unit in _resource_files([scan], "skills"):
            add_skill(section, unit, [(patterns, base)])
        declare(patterns, base, section, [(patterns, base)])

    project_ext = [(cfg.get("extensions", []), dir_ / ".pi") for dir_, cfg in projects]
    ext_dir = PI_AGENT / "extensions"
    if ext_dir.is_dir():
        scopes = project_ext + [(user.get("extensions", []), PI_AGENT)]
        for entry in sorted(ext_dir.iterdir()):
            if entry.name.endswith(".disabled") or entry.name.startswith("."):
                continue
            files = _entry_files(entry)
            if files and all(_on(f, scopes) for f in files):
                add(exts, entry.stem if entry.is_file() else entry.name, files)

    builtin_scopes = project_ext + [(user.get("extensions", []), PI_AGENT)]
    builtins = Section("Built-in",
                       [Item(name, [name], _on(Path(name), builtin_scopes), True) for name in BUILTIN_EXTS], "-e")
    opts = Section("Options", [Item(CONTEXT_OPT, [], True)])
    return [builtins, exts, skills, proj, opts]


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
            if it.name in saved:
                it.checked = True  # explicit pick, also overriding a settings "-builtin:..."
            elif f"-{it.name}" in saved:
                it.checked = False  # opt-out recorded by save_state for a default-on item


def save_state(sections) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    names = [it.name for sec in sections for it in sec.items if it.checked]
    names += [f"-{it.name}" for sec in sections for it in sec.items if it.default and not it.checked]
    STATE_FILE.write_text(json.dumps(sorted(names)))


def build_command(sections) -> list[str]:
    args = ["pi", "--no-extensions", "--no-skills", "--no-prompt-templates", "--no-themes"]
    for sec in sections:
        for it in sec.items:
            if not sec.flag:  # Options: checked means leave pi's default alone
                if not it.checked:
                    args.append("--no-context-files")
            elif it.checked:
                args += [sec.flag, *it.args]
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


def _child_env() -> dict:
    """Pass the agent directory on, or the launched pi would read the default one."""
    env = dict(os.environ)
    if os.environ.get("PI_AGENT_DIR") or os.environ.get("PI_CODING_AGENT_DIR"):
        env["PI_CODING_AGENT_DIR"] = str(PI_AGENT)
    return env


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
                os.execvpe("pi", build_command(sections), _child_env())
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
                print(f"  {'[x]' if it.checked else '[ ]'} {it.name}  ->  {' '.join(it.args) or '-'}")
        print("\n$ " + " ".join(build_command(sections)))
        return
    curses.wrapper(_tui)


if __name__ == "__main__":
    main()