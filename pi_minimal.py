#!/usr/bin/env python3
"""pi-minimal: pick which pi extensions/skills to load, then launch pi stripped down.

--no-extensions/--no-skills/etc stop pi discovering anything, then the checked items go
back on the command line as -e / --skill. Discovery mirrors pi 1.6.0 (see package-manager.js):
package manifests and directory resolution, the +/-/! prefixes in resource arrays, per-scope
filtering, and the built-in extensions that --no-extensions switches off too.
"""

import curses
import glob
import json
import os
import re
import shlex
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

PI_AGENT = Path(os.environ.get("PI_CODING_AGENT_DIR") or os.environ.get("PI_AGENT_DIR", "~/.pi/agent")).expanduser()
STATE_FILE = Path(os.environ.get("PI_MINIMAL_STATE", "~/.config/pi-minimal/selections.json")).expanduser()
CODE_EXTS = {".ts", ".js"}
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
# An entry is a path or a glob to include, or is prefixed: '+' force-include (exact path),
# '-' exclude one exact path, '!glob' exclude a glob. Relative entries resolve against the
# settings file's directory, a package root, or a skills directory.


def _split(values) -> tuple[list[str], list[str], list[str], list[str]]:
    """Split a resource array into (plain, '+', '!', '-') entries, prefixes stripped."""
    plain, plus, bangs, minus = [], [], [], []
    for v in values if isinstance(values, list) else []:
        if not isinstance(v, str) or not v.strip():
            continue
        v = v.strip()
        target = {"+": plus, "-": minus, "!": bangs}.get(v[0], plain)
        target.append(v[1:] if v[0] in "+-!" else v)
    return plain, plus, bangs, minus


def _is_filter(entry: str) -> bool:
    """Only '+'/'-'/'!' entries filter; plain manifest entries are just paths."""
    return entry.startswith(("+", "-", "!"))


def _is_pattern(entry: str) -> bool:
    return _is_filter(entry) or "*" in entry or "?" in entry


def _glob_seg(seg: str) -> str:
    """One path segment of a glob as a regex; '*' and '?' never cross a '/'."""
    out, j = [], 0
    while j < len(seg):
        c = seg[j]
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[" and "]" in seg[j + 1:]:
            end = seg.index("]", j + 1)
            body = seg[j + 1:end]
            neg = body[:1] in ("!", "^")
            out.append(f"[{'^' if neg else ''}{re.escape(body[1:] if neg else body)}]")
            j = end
        else:
            out.append(re.escape(c))
        j += 1
    return ("(?!\\.)" if seg[:1] in "*?[" else "") + "".join(out)  # a wildcard never matches a dot


@lru_cache(maxsize=None)
def _glob(pattern: str) -> re.Pattern:
    """minimatch semantics: a '**' segment crosses '/' and may stand for no segment at all
    ('a/**/b' matches 'a/b'), a trailing 'a/**' needs at least one file under 'a/'. Cached."""
    out, need_sep, segs = "", False, pattern.split("/")
    for i, seg in enumerate(segs):
        if seg == "**" and i < len(segs) - 1:
            out += ("/" if need_sep else "") + "(?:[^/]+/)*"  # the group carries the next separator
            need_sep = False
            continue
        out += ("/" if need_sep else "") + ("[^/]+(?:/.*)?" if seg == "**" else _glob_seg(seg))
        need_sep = True
    return re.compile(out + r"\Z")


def _rel(path: Path, base: Path) -> str | None:
    """`path` relative to `base` (pi's relative(), so '../..' when outside it); nothing for the
    synthetic 'builtin:...' entries, which are not paths at all."""
    return Path(os.path.relpath(path, base)).as_posix() if path.is_absolute() else None


def _keys(path: Path, base: Path) -> list[str]:
    """What pi's matchesAnyPattern tries a glob against: the absolute path, the file name, the
    path relative to the base dir and, for a SKILL.md, those three for its folder as well."""
    keys = [str(path), path.name]
    rel = _rel(path, base)
    if rel is not None:
        keys.append(rel)
    if path.name == "SKILL.md":
        keys += _keys(path.parent, base)
    return keys


def _exact_keys(path: Path, base: Path) -> list[str]:
    """What '+'/'-' are compared with (pi's matchesAnyExactPattern): only the relative path or
    the absolute path, plus the folder's two for a SKILL.md. Never a bare file name."""
    keys = [str(path)]
    rel = _rel(path, base)
    if rel is not None:
        keys.append(rel)
    if path.name == "SKILL.md":
        keys += _exact_keys(path.parent, base)
    return keys


def _hit(keys: list[str], patterns: list[str]) -> bool:
    """Glob match, like pi's matchesAnyPattern (a leading '~' is expanded in a pattern)."""
    return any(_glob(os.path.expanduser(p)).match(key) for p in patterns for key in keys)


def _hit_exact(keys: list[str], patterns: list[str]) -> bool:
    """Exact match, no globbing: pi only strips a leading './' (and expands a leading '~')."""
    for p in patterns:
        p = os.path.expanduser(p)
        if (p[2:] if p.startswith("./") else p) in keys:
            return True
    return False


def _on(path: Path, values, base: Path) -> bool:
    """Is an auto-discovered resource enabled? pi's isEnabledByOverrides: '!' globs disable,
    then '+' (exact) puts one back, and '-' (exact) has the last word."""
    _, plus, bangs, minus = _split(values)
    enabled = not (bangs and _hit(_keys(path, base), bangs))
    if plus and _hit_exact(_exact_keys(path, base), plus):
        enabled = True
    if minus and _hit_exact(_exact_keys(path, base), minus):
        enabled = False
    return enabled


def _override_state(path: Path, values, base: Path) -> bool | None:
    """pi's applyAutoloadDisabledPatterns: the last '!', '+' or '-' entry mentioning the path
    decides (only '+' enables); None when no override mentions it, so the caller decides."""
    state = None
    for v in values if isinstance(values, list) else []:
        if not isinstance(v, str) or not v.strip() or v[0] not in "+-!":
            continue
        v = v.strip()
        exact = v[0] in "+-"
        keys = _exact_keys(path, base) if exact else _keys(path, base)
        if (_hit_exact(keys, [v[1:]]) if exact else _hit(keys, [v[1:]])):
            state = v[0] == "+"
    return state


def _narrow(files: list[Path], patterns, base: Path) -> list[Path]:
    """Filter a resource list the way pi's applyPatterns does: plain entries narrow it, '!'
    removes, '+' restores from the original list, and '-' (exact) removes last of all."""
    plain, plus, bangs, minus = _split(patterns)
    result = list(files)
    if plain:
        result = [f for f in result if _hit(_keys(f, base), plain)]
    if bangs:
        result = [f for f in result if not _hit(_keys(f, base), bangs)]
    if plus:
        wanted = {f for f in files if _hit_exact(_exact_keys(f, base), plus)}
        result += [f for f in files if f not in result and f in wanted]
    if minus:
        result = [f for f in result if not _hit_exact(_exact_keys(f, base), minus)]
    return result


# --- discovery -----------------------------------------------------------------------------


def _from_base(entry: str, base: Path) -> Path:
    """A resource entry as a path: a relative one resolves against `base`, which is the settings
    file's own directory, a package root or a skills dir - never another scope's directory.
    (normpath so "../x" entries do not end up as "<dir>/.pi/../x" on the command line.)"""
    path = Path(os.path.expanduser(entry))
    return Path(os.path.normpath(path if path.is_absolute() else base / path))


def _expand(values, base: Path) -> list[Path]:
    """Resolve declared manifest paths/globs against `base`; unlike filters these add resources."""
    out = []
    for value in values:
        path = _from_base(value, base)
        if set("*?") & set(value):
            out += [Path(p) for p in sorted(glob.glob(str(path), recursive="**" in value))]
        else:
            out.append(path)
    return out


def _listdir(base: Path) -> list[Path]:
    """A directory's contents in pi's order: sorted, without dot entries and node_modules."""
    try:
        entries = sorted(base.iterdir())
    except OSError:
        return []
    return [e for e in entries if not e.name.startswith(".") and e.name not in SKIP_DIRS]


def _manifest(path: Path) -> dict:
    """The `pi` key of a package.json: declared resource paths and filters."""
    try:
        manifest = json.loads((path / "package.json").read_text()).get("pi")
    except (OSError, json.JSONDecodeError, AttributeError):
        return {}
    return manifest if isinstance(manifest, dict) else {}


def _manifest_entries(path: Path, kind: str) -> list[str] | None:
    """One `pi` manifest array, or None when the package does not declare that resource kind;
    pi then falls back to the conventional <package>/<kind>/ folder."""
    entries = _manifest(path).get(kind)
    if isinstance(entries, list) and all(isinstance(e, str) for e in entries):
        return entries
    return None


def _resolved_dir(d: Path) -> list[Path] | None:
    """What one directory resolves to (pi's resolveExtensionEntries): the declared
    `pi.extensions` entries that exist, else index.ts, else index.js, else None, which means
    the caller should look inside the directory instead."""
    declared = _manifest_entries(d, "extensions")
    if declared:
        paths = [p for e in declared if not _is_filter(e) for p in [_from_base(e, d)] if p.exists()]
        if paths:  # pi returns these as they are; whoever collects the folder expands a directory
            return paths
    for name in ("index.ts", "index.js"):
        if (d / name).is_file():
            return [d / name]
    return None


def _collect_ext_dir(base: Path) -> list[Path]:
    """Collect an extensions directory (pi's collectAutoExtensionEntries): the directory's own
    resolution if it has one, else its loose .ts/.js files plus each subdirectory's resolution."""
    own = _resolved_dir(base)
    if own:
        return own
    out = []
    for entry in _listdir(base):
        if entry.is_file() and entry.suffix in CODE_EXTS:
            out.append(entry)
        elif entry.is_dir():
            out += _resolved_dir(entry) or []
    return out


def _resource_files(paths, kind: str) -> list[Path]:
    """Expand candidate paths into resource files: a file is itself, a directory is collected."""
    out = []
    for path in paths:
        if path.is_dir():
            out += _skill_files(path) if kind == "skills" else _collect_ext_dir(path)
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


def _entry_files(entry: Path) -> list[Path]:
    """One entry of an extensions directory: a code file, or what its directory resolves to."""
    if entry.is_file():
        return [entry] if entry.suffix in CODE_EXTS else []
    if entry.is_dir():
        return _resolved_dir(entry) or []
    return []


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
    ext_files, skill_files = [], []
    for kind, sink in (("extensions", ext_files), ("skills", skill_files)):
        declared = _manifest_entries(pkg, kind) if pkg.is_dir() else None
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
    skill_names: set[str] = set()  # skill items offered so far; pi loads one name once, project first
    keys: set[str] = set()  # state-file names, one per item
    offered: set[str] = set()  # real paths already offered as extensions; pi dedupes by path
    loaded: set[str] = set()  # real SKILL.md paths; pi loads a file once, symlink or not

    def add(section, name, args):
        """Offer one item. State keys stay unique: '<name> (<section>)', then '<name> (<section>) 2'."""
        key = name
        if key in keys:
            key = f"{name} ({section.name})"
            n = 1
            while key in keys:
                n += 1
                key = f"{name} ({section.name}) {n}"
        keys.add(key)
        section.items.append(Item(key, [str(a) for a in args]))

    def add_ext(name: str, files: list[Path]) -> None:
        """One extensions item, listing only the files it contributes. pi dedupes extensions by
        resolved path, so a file already offered is dropped and two files sharing a name stay."""
        keep = [f for f in files if str(f.resolve()) not in offered]
        if not keep:
            return
        offered.update(str(f.resolve()) for f in keep)
        add(exts, name, keep)

    def add_skill(section, unit: Path, values, base: Path) -> None:
        real = str(unit.resolve())
        if real in loaded or not _on(unit, values, base):
            return
        loaded.add(real)
        in_folder = unit.name == "SKILL.md"
        name = unit.parent.name if in_folder else (_frontmatter_name(unit) or unit.stem)
        if name in skill_names:  # pi keeps the first resource of a name; project ones come first
            return
        skill_names.add(name)
        add(section, name, [unit.parent if in_folder else unit])

    def scan_skills(scan: Path, base: Path, section, values) -> None:
        """A skills directory: every SKILL.md in it, filtered by that scope's own settings array."""
        for unit in _resource_files([scan], "skills"):
            add_skill(section, unit, values, base)

    def declare_skills(values, base: Path, section) -> None:
        """A settings `skills` array adds what its plain entries name (pi's resolveLocalEntries);
        its patterns only narrow the files those entries brought in."""
        if not isinstance(values, list):
            return
        units = [u for e in _split(values)[0] for u in _resource_files([_from_base(e, base)], "skills")]
        keep = set(_narrow(units, [e for e in values if _is_pattern(e)], base))
        for unit in units:
            if unit in keep:
                add_skill(section, unit, [], base)

    def scan_ext_dir(scan: Path, values, base: Path) -> None:
        """An auto-discovered extensions directory: one item per entry, listing its enabled files,
        so a folder with some files switched off is still offered with the rest."""
        for entry in _listdir(scan):
            if entry.name.endswith(".disabled"):
                continue
            files = [f for f in _entry_files(entry) if _on(f, values, base)]
            add_ext(entry.stem if entry.is_file() else entry.name, files)

    def declare_ext(values, base: Path) -> None:
        """A settings `extensions` array adds extensions the same way a `skills` array adds skills."""
        if not isinstance(values, list):
            return
        units = []  # (item name, file), in entry order
        for entry in _split(values)[0]:
            path = _from_base(entry, base)
            name = path.stem if path.is_file() else path.name
            units += [(name, f) for f in _resource_files([path], "extensions")]
        keep = set(_narrow([f for _, f in units], [e for e in values if _is_pattern(e)], base))
        grouped: dict[str, list[Path]] = {}
        for name, path in units:
            if path in keep:
                grouped.setdefault(name, []).append(path)
        for name, files in grouped.items():
            add_ext(name, files)

    user = _settings()
    projects = _project_settings()
    cwd = Path.cwd()
    # pi keeps one project settings object; the nearest .pi wins, and its directory is the base
    # for the relative entries there. User entries resolve against the agent dir, never ~/.agents.
    project_cfg = projects[0][1] if projects else {}
    project_base = cwd / ".pi"
    user_ext, user_skills = user.get("extensions", []), user.get("skills", [])
    project_ext, project_skills = project_cfg.get("extensions", []), project_cfg.get("skills", [])
    user_agents = Path.home() / ".agents" / "skills"

    def builtin_on(name: str) -> bool:
        """A built-in is on unless the user settings switch it off; a project override decides first."""
        state = _override_state(Path(name), project_ext, project_base)
        return _on(Path(name), user_ext, PI_AGENT) if state is None else state

    # Order matches pi: packages, then project, then user, so a name collision drops the
    # same loser here as in pi. Project resources also need pi's project trust to load.
    for pkg, filters in _packages():
        pkg_ext, pkg_skills = _package_resources(pkg, filters)
        add_ext(pkg.name, pkg_ext)
        for unit in pkg_skills:
            add_skill(skills, unit, [], PI_AGENT)

    # Extensions: what the settings arrays name, then the auto-discovered directories, project
    # scope before user scope. Each scope filters only its own resources.
    declare_ext(project_ext, project_base)
    scan_ext_dir(project_base / "extensions", project_ext, project_base)
    declare_ext(user_ext, PI_AGENT)
    scan_ext_dir(PI_AGENT / "extensions", user_ext, PI_AGENT)

    # Skills: <cwd>/.pi/skills and the .agents/skills directories up to the repo root are project
    # resources (project settings, each with its own base); the agent and ~/.agents ones are user ones.
    scan_skills(project_base / "skills", project_base, proj, project_skills)
    declare_skills(project_skills, project_base, proj)
    for d in _project_dirs():
        scan = d / ".agents" / "skills"
        if scan.resolve() != user_agents.resolve():  # that one is a user resource, filtered by user settings
            scan_skills(scan, d / ".agents", proj, project_skills)
    scan_skills(PI_AGENT / "skills", PI_AGENT, skills, user_skills)
    declare_skills(user_skills, PI_AGENT, skills)
    scan_skills(user_agents, user_agents.parent, skills, user_skills)

    builtins = Section("Built-in", [Item(name, [name], builtin_on(name), True) for name in BUILTIN_EXTS], "-e")
    opts = Section("Options", [Item(CONTEXT_OPT, [], True, True)])
    return [builtins, exts, skills, proj, opts]


def _config_file() -> Path:
    """config.json beside the state file, looked up at call time so it follows STATE_FILE
    (tests that point STATE_FILE at a temp dir no longer read the real config)."""
    return STATE_FILE.parent / "config.json"


def _defaults() -> set[str]:
    try:
        cfg = json.loads(_config_file().read_text())
        return set(cfg.get("default_checked", []))
    except (OSError, json.JSONDecodeError):
        return set()


def _saved() -> list[str]:
    """Names recorded in the state file: [] when there is none, it cannot be read, or it is
    not a JSON list of strings."""
    try:
        saved = json.loads(STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    return saved if isinstance(saved, list) and all(isinstance(v, str) for v in saved) else []


def load_state(sections) -> None:
    saved = set(_saved()) or _defaults()  # no state yet (or nothing usable in it): config defaults
    for sec in sections:
        for it in sec.items:
            if it.name in saved:
                it.checked = True  # explicit pick, also overriding a settings "-builtin:..."
            elif f"-{it.name}" in saved:
                it.checked = False  # opt-out recorded by save_state for a default-on item


def _entry_item(name: str) -> str:
    """The item a state-file entry refers to: the entry without its one leading '-'."""
    return name[1:] if name.startswith("-") else name


def save_state(sections) -> None:
    """Record today's checkboxes, keeping entries for items that are not discovered right now
    (a project skill from another directory, a package that is temporarily missing)."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    current = {it.name for sec in sections for it in sec.items}
    names = [it.name for sec in sections for it in sec.items if it.checked]
    names += [f"-{it.name}" for sec in sections for it in sec.items if it.default and not it.checked]
    names += [n for n in _saved() if _entry_item(n) not in current]
    STATE_FILE.write_text(json.dumps(sorted(set(names))))


def build_command(sections) -> list[str]:
    args = ["pi", "--no-extensions", "--no-skills", "--no-prompt-templates", "--no-themes"]
    for sec in sections:
        for it in sec.items:
            if not sec.flag:  # Options: checked means leave pi's default alone
                if not it.checked:
                    args.append("--no-context-files")
            elif it.checked:  # pi's -e/--skill take one value each; a second would become the prompt
                for value in it.args:
                    args += [sec.flag, value]
    return args


# rows 0-1 header, body 2 .. h-3, command h-2, key help h-1
KEY_HELP = "j/↓ down  k/↑ up  space toggle  enter launch  q quit"
TOO_SMALL = "terminal too small"


def _lines(sections) -> list[tuple[str, int | None]]:
    """The whole scrollable body as (text, flat item index): section header, its items,
    then a blank gap. Header and gap lines carry None, so only items can hold the cursor."""
    out: list[tuple[str, int | None]] = []
    pos = 0
    for sec in sections:
        out.append((sec.name.upper(), None))
        for it in sec.items:
            out.append((f" {'[x]' if it.checked else '[ ]'} {it.name}", pos))
            pos += 1
        out.append(("", None))
    return out


def _scroll(top: int, cursor_line: int, height: int) -> int:
    """First visible body line after the cursor moved to `cursor_line` in `height` rows."""
    if height < 1:
        return 0
    if cursor_line < top:
        return max(cursor_line, 0)
    if cursor_line >= top + height:
        return max(cursor_line - height + 1, 0)
    return top


def _draw(stdscr, sections, cursor, top) -> int:
    """Paint one frame; returns the body scroll position to keep for the next one."""
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    if h < 5 or w < 20:
        if h >= 1 and w >= 2:
            stdscr.addnstr(0, 0, TOO_SMALL, w - 1)
        stdscr.refresh()
        return top
    for r, line in enumerate(["pi-minimal — check what to load, Enter launches", ""]):
        if r < h:
            stdscr.addnstr(r, 0, line, w - 1)
    lines = _lines(sections)
    cursor_line = next((i for i, (_, idx) in enumerate(lines) if idx == cursor), 0)
    height = h - 4
    top = _scroll(top, cursor_line, height)
    # scrolled up onto a section's first item: show its header too, if the cursor still fits
    if top and lines[top - 1][1] is None and lines[top - 1][0] and cursor_line - top + 1 < height:
        top -= 1
    for r, (text, idx) in enumerate(lines[top:top + height]):
        row = 2 + r
        if idx == cursor:
            stdscr.addnstr(row, 0, text[: w - 1], w - 1, curses.A_REVERSE)
        elif idx is None and text:
            stdscr.addnstr(row, 0, text, w - 1, curses.A_BOLD)
        else:
            stdscr.addnstr(row, 0, text, w - 1)
    stdscr.addnstr(h - 2, 0, shlex.join(build_command(sections))[: w - 1], w - 1, curses.A_DIM)
    stdscr.addnstr(h - 1, 0, KEY_HELP[: w - 1], w - 1)
    stdscr.refresh()
    return top


def _flat(sections):
    return [it for sec in sections for it in sec.items]


def _move(sections, cursor, delta) -> int:
    flat = _flat(sections)
    return (cursor + delta) % len(flat)


def _toggle_at(flat, cursor) -> None:
    flat[cursor].checked = not flat[cursor].checked


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
    top = 0
    try:
        while True:
            top = _draw(stdscr, sections, cursor, top)
            key = stdscr.getkey()
            if key in ("KEY_UP", "k"):
                cursor = _move(sections, cursor, -1)
            elif key in ("KEY_DOWN", "j"):
                cursor = _move(sections, cursor, 1)
            elif key == " ":
                _toggle_at(flat, cursor)
            elif key == "KEY_ENTER" or key == "\n":
                save_state(sections)
                curses.endwin()  # leave curses mode
                os.write(1, b"\x1b[2J\x1b[H")  # clear + home; endwin leaves cursor mid-line
                try:
                    os.execvpe("pi", build_command(sections), _child_env())
                except FileNotFoundError:
                    sys.exit("pi-minimal: `pi` is not on PATH. Your selection was saved; "
                             "run `pi-minimal --list` for the command.")
            elif key == "q":
                save_state(sections)
                return
    except KeyboardInterrupt:
        save_state(sections)  # same as q: keep the selection, exit cleanly


def _list_lines(sections) -> list[str]:
    """What --list prints: every item with its checkboxes, then the command it would run."""
    out = []
    for sec in sections:
        out.append(sec.name)
        for it in sec.items:
            out.append(f"  {'[x]' if it.checked else '[ ]'} {it.name}  ->  {' '.join(it.args) or '-'}")
    out.append("")
    out.append("$ " + shlex.join(build_command(sections)))
    return out


USAGE = """usage: pi-minimal [--list]

Pick which pi extensions and skills to load, then launch pi with only those.

  --list       print every item and the pi command that would run, then exit
  --version    print the version
  -h, --help   show this help

Keys: j/k or arrows move, space toggles, enter launches pi, q saves and quits."""


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("pi-minimal")
    except Exception:
        return "unknown (not installed)"


def main() -> None:
    args = sys.argv[1:]
    if any(a in ("-h", "--help") for a in args):
        print(USAGE)
        return
    if "--version" in args:
        print(f"pi-minimal {_version()}")
        return
    unknown = [a for a in args if a != "--list"]
    if unknown:
        sys.exit(f"pi-minimal: unknown option {unknown[0]}\n\n{USAGE}")
    if "--list" in args:
        sections = discover()
        load_state(sections)
        for line in _list_lines(sections):
            print(line)
        return
    curses.wrapper(_tui)


if __name__ == "__main__":
    main()