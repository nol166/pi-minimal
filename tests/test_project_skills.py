"""Runnable check: python3 tests/test_project_skills.py

Discovery is checked against what pi loads (pi 1.6.0; see test_pi_parity.py for the side-by-side check), not what pi-minimal used to list.
"""

import json
import os
import shlex
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pi_minimal as main  # noqa: E402


def _make_skill(root: Path, rel: str, name: str | None = None) -> Path:
    d = root / rel
    d.mkdir(parents=True, exist_ok=True)
    body = f"name: {name}\n" if name else ""
    (d / "SKILL.md").write_text(f"---\n{body}description: test\n---\n")
    return d


class _Sandbox:
    """Point PI_AGENT, HOME and cwd at a temp tree, then put everything back."""

    def __init__(self, t: Path, agent: Path, home: Path, cwd: Path):
        self.t, self.agent, self.home, self.cwd = t, agent, home, cwd

    def __enter__(self):
        self.old = (main.PI_AGENT, os.environ.get("HOME"), os.getcwd())
        main.PI_AGENT = self.agent
        os.environ["HOME"] = str(self.home)
        os.chdir(self.cwd)
        return self

    def __exit__(self, *exc):
        main.PI_AGENT, home, cwd = self.old
        if home is None:
            del os.environ["HOME"]
        else:
            os.environ["HOME"] = home
        os.chdir(cwd)
        return False


def _sandbox(t: Path, cwd: Path, agent: Path | None = None) -> _Sandbox:
    home = t / "home"
    home.mkdir(parents=True, exist_ok=True)
    return _Sandbox(t, agent or t / "agent", home, cwd)


def _items(sections, name: str) -> dict[str, main.Item]:
    return {i.name: i for s in sections if s.name == name for i in s.items}


def test_project_dirs_walks_up_to_repo_root():
    with tempfile.TemporaryDirectory() as t:
        root = Path(t).resolve() / "repo"
        (root / ".git").mkdir(parents=True)
        cwd = root / "work"
        cwd.mkdir()
        old = os.getcwd()
        os.chdir(cwd)
        try:
            dirs = main._project_dirs()
        finally:
            os.chdir(old)
        assert dirs == [cwd, root], dirs


def test_discover_and_command_include_project_skill():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t).resolve()
        root = t / "repo"
        (root / ".git").mkdir(parents=True)
        sk = _make_skill(root, ".pi/skills/proj-skill")
        (t / "agent").mkdir()
        with _sandbox(t, root):
            sections = main.discover()
            proj = {s.name: s for s in sections}["Project skills"]
            assert [i.name for i in proj.items] == ["proj-skill"], [i.name for i in proj.items]
            proj.items[0].checked = True
            cmd = " ".join(main.build_command(sections))
            assert f"--skill {sk}" in cmd, cmd


def test_symlinked_skill_listed_once():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t).resolve()
        agent, home = t / "agent", t / "home"
        real = _make_skill(agent, "skills/foo")
        link = home / ".agents" / "skills" / "foo-link"
        link.parent.mkdir(parents=True)
        os.symlink(real, link)
        cwd = t / "work"
        (cwd / ".git").mkdir(parents=True)
        with _sandbox(t, cwd, agent):
            skills = _items(main.discover(), "Skills")
        assert list(skills) == ["foo"], skills
        assert skills["foo"].args == [str(real)], skills["foo"].args


def test_declared_skill_paths_are_added():
    """settings `skills` entries that name a path add it, relative to the settings directory."""
    with tempfile.TemporaryDirectory() as t:
        t = Path(t).resolve()
        agent, root = t / "agent", t / "repo"
        (root / ".git").mkdir(parents=True)
        global_skill = _make_skill(t, "elsewhere/g-skill")
        claude_skill = _make_skill(root / ".claude" / "skills", "c-skill")
        agent.mkdir()
        (agent / "settings.json").write_text(json.dumps({"skills": [str(global_skill)]}))
        (root / ".pi").mkdir()
        (root / ".pi" / "settings.json").write_text(json.dumps({"skills": ["../.claude/skills"]}))
        with _sandbox(t, root, agent):
            items = {name: _items(main.discover(), name) for name in ("Skills", "Project skills")}
        assert items["Skills"]["g-skill"].args == [str(global_skill)], items["Skills"]
        assert items["Project skills"]["c-skill"].args == [str(claude_skill)], items["Project skills"]


def test_name_collision_project_wins():
    """pi discovers project resources before user ones, so the project copy is the one loaded."""
    with tempfile.TemporaryDirectory() as t:
        t = Path(t).resolve()
        agent, root = t / "agent", t / "repo"
        (root / ".git").mkdir(parents=True)
        _make_skill(agent, "skills/dup")
        project_skill = _make_skill(root, ".pi/skills/dup")
        with _sandbox(t, root, agent):
            items = _items(main.discover(), "Project skills")
        assert items["dup"].args == [str(project_skill)], items["dup"]


def test_nested_skills_are_found_at_any_depth():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t).resolve()
        agent = t / "agent"
        deep = _make_skill(agent, "skills/team/frontend/api-guide")
        cwd = t / "work"
        (cwd / ".git").mkdir(parents=True)
        with _sandbox(t, cwd, agent):
            skills = _items(main.discover(), "Skills")
        assert skills["api-guide"].args == [str(deep)], skills


def test_settings_arrays_filter_skills_and_extensions():
    """'-' excludes what discovery found; '+' keeps it despite an earlier '!glob'."""
    with tempfile.TemporaryDirectory() as t:
        t = Path(t).resolve()
        agent = t / "agent"
        _make_skill(agent, "skills/keep")
        _make_skill(agent, "skills/drop")
        ext_dir = agent / "extensions"
        ext_dir.mkdir(parents=True)
        (ext_dir / "on.ts").write_text("")
        (ext_dir / "off.ts").write_text("")
        (agent / "settings.json").write_text(json.dumps({
            "skills": ["-skills/drop/SKILL.md"],
            "extensions": ["-extensions/off.ts"],
        }))
        cwd = t / "work"
        (cwd / ".git").mkdir(parents=True)
        with _sandbox(t, cwd, agent):
            sections = main.discover()
        assert list(_items(sections, "Skills")) == ["keep"], _items(sections, "Skills")
        assert list(_items(sections, "Extensions")) == ["on"], _items(sections, "Extensions")


def test_glob_helper_matches_paths_like_minimatch():
    """'*' and '?' stop at '/', '**' crosses it, and a wildcard never matches a leading dot."""
    base = Path("/r")

    def hit(rel, pattern):
        return main._hit(main._keys(base / rel, base), [pattern])

    assert hit("extensions/b.ts", "extensions/*.ts") and hit("extensions/b.ts", "?.ts")
    assert hit("extensions/b.ts", "b.*") and hit("extensions/b.ts", "**/b.ts")
    assert not hit("extensions/sub/b.ts", "extensions/*.ts")  # '*' does not cross '/'
    assert hit("extensions/sub/b.ts", "extensions/**/*.ts") and hit("extensions/b.ts", "extensions/**")
    assert not hit("extensions", "extensions/**")  # a trailing '**' still needs one file
    assert not hit("extensions/.hidden.ts", "extensions/*.ts")  # wildcards never match a dot
    assert not hit("extensions/b.ts", "extensions/*.js")
    # '+'/'-' are exact: they never match a bare file name, only the relative or absolute path
    ext = base / "extensions" / "b.ts"
    assert "b.ts" in main._keys(ext, base) and "b.ts" not in main._exact_keys(ext, base)
    assert main._hit_exact(main._exact_keys(ext, base), ["./extensions/b.ts", str(ext)])
    assert not main._hit_exact(main._exact_keys(ext, base), ["b.ts", "extensions/*.ts"])


def test_two_extensions_of_the_same_name_are_both_offered():
    """pi dedupes extensions by path, so a package and a file that share a name both load."""
    with tempfile.TemporaryDirectory() as t:
        t = Path(t).resolve()
        agent = t / "agent"
        pkg = agent / "npm" / "node_modules" / "dup"
        (pkg / "dist").mkdir(parents=True)
        pkg_file = pkg / "dist" / "index.js"
        pkg_file.write_text("")
        (pkg / "package.json").write_text(json.dumps({"pi": {"extensions": ["./dist"]}}))
        file_ext = agent / "extensions" / "dup.ts"
        file_ext.parent.mkdir(parents=True)
        file_ext.write_text("")
        (agent / "settings.json").write_text(json.dumps({"packages": ["npm:dup"]}))
        cwd = t / "work"
        (cwd / ".git").mkdir(parents=True)
        with _sandbox(t, cwd, agent):
            exts = _items(main.discover(), "Extensions")
        assert exts["dup"].args == [str(pkg_file)], exts
        assert exts["dup (Extensions)"].args == [str(file_ext)], exts


def test_project_extensions_are_discovered_and_only_their_own_scope_filters_them():
    """<cwd>/.pi/extensions is listed; project and user settings never cross over."""
    with tempfile.TemporaryDirectory() as t:
        t = Path(t).resolve()
        agent = t / "agent"
        (agent / "extensions").mkdir(parents=True)
        user_ext = agent / "extensions" / "user.ts"
        user_ext.write_text("")
        root = t / "repo"
        proj_ext = root / ".pi" / "extensions" / "proj.ts"
        proj_ext.parent.mkdir(parents=True)
        proj_ext.write_text("")
        (root / ".git").mkdir(parents=True)
        (agent / "settings.json").write_text(json.dumps({"extensions": ["-extensions/proj.ts"]}))
        (root / ".pi" / "settings.json").write_text(json.dumps({"extensions": ["-extensions/user.ts"]}))
        with _sandbox(t, root, agent):
            names = list(_items(main.discover(), "Extensions"))
        assert names == ["proj", "user"], names  # project first, and neither '-' touches the other's files

        (root / ".pi" / "settings.json").write_text(json.dumps({"extensions": ["-extensions/proj.ts"]}))
        with _sandbox(t, root, agent):
            names = list(_items(main.discover(), "Extensions"))
        assert names == ["user"], names


def test_settings_entries_add_extensions():
    """An `extensions` entry naming a path adds it, resolved against its own settings directory."""
    with tempfile.TemporaryDirectory() as t:
        t = Path(t).resolve()
        agent, root = t / "agent", t / "repo"
        (root / ".git").mkdir(parents=True)
        user_ext = agent / "extras" / "one.ts"
        user_ext.parent.mkdir(parents=True)
        user_ext.write_text("")
        vendor = root / "vendor" / "two.ts"
        vendor.parent.mkdir(parents=True)
        vendor.write_text("")
        (agent / "settings.json").write_text(json.dumps({"extensions": ["extras/one.ts"]}))
        (root / ".pi").mkdir()
        (root / ".pi" / "settings.json").write_text(json.dumps({"extensions": ["../vendor/two.ts"]}))
        cwd = t / "work"
        (cwd / ".git").mkdir(parents=True)
        with _sandbox(t, root, agent):
            exts = _items(main.discover(), "Extensions")
        assert exts["one"].args == [str(user_ext)], exts
        assert exts["two"].args == [str(vendor)], exts


def test_package_uses_its_declared_extension_paths():
    """A directory entry resolves like an extension folder: index.ts, index.js, else its files."""
    with tempfile.TemporaryDirectory() as t:
        t = Path(t).resolve()
        agent = t / "agent"
        pkg = agent / "npm" / "node_modules" / "fake-pkg"
        for name in ("index.js", "mcp-cli.js"):
            (pkg / "dist").mkdir(parents=True, exist_ok=True)
            (pkg / "dist" / name).write_text("")
        (pkg / "index.ts").write_text("")  # what pi-minimal used to guess, and pi ignores
        (pkg / "package.json").write_text(json.dumps({"pi": {"extensions": ["./dist"]}}))
        (agent / "settings.json").write_text(json.dumps({"packages": ["npm:fake-pkg"]}))
        cwd = t / "work"
        (cwd / ".git").mkdir(parents=True)
        with _sandbox(t, cwd, agent):
            exts = _items(main.discover(), "Extensions")
        assert exts["fake-pkg"].args == [str(pkg / "dist" / "index.js")], exts["fake-pkg"].args

        # without an index, dist/ is its loose files, and a "-" filter drops just one of them
        (pkg / "dist" / "other.js").write_text("")
        (pkg / "dist" / "index.js").unlink()
        (agent / "settings.json").write_text(json.dumps(
            {"packages": [{"source": "npm:fake-pkg", "extensions": ["-dist/mcp-cli.js"]}]}))
        with _sandbox(t, cwd, agent):
            exts = _items(main.discover(), "Extensions")
        assert exts["fake-pkg"].args == [str(pkg / "dist" / "other.js")], exts["fake-pkg"].args


def test_package_skill_filters():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t).resolve()
        agent = t / "agent"
        pkg = agent / "npm" / "node_modules" / "fake-skills"
        _make_skill(pkg, "skills/used")
        _make_skill(pkg, "skills/unused")
        (pkg / "package.json").write_text(json.dumps({"pi": {"skills": ["./skills"]}}))
        (agent / "settings.json").write_text(json.dumps(
            {"packages": [{"source": "npm:fake-skills", "skills": ["-skills/unused/SKILL.md"]}]}))
        cwd = t / "work"
        (cwd / ".git").mkdir(parents=True)
        with _sandbox(t, cwd, agent):
            skills = _items(main.discover(), "Skills")
        assert list(skills) == ["used"], skills


def test_extension_and_skill_of_the_same_name_stay_independent():
    """The state file keys one checkbox each; otherwise unchecking the extension would revert."""
    with tempfile.TemporaryDirectory() as t:
        t = Path(t).resolve()
        agent = t / "agent"
        pkg = agent / "npm" / "node_modules" / "dup"
        (pkg / "dist").mkdir(parents=True)
        (pkg / "dist" / "index.js").write_text("")
        skill = _make_skill(pkg, "skills/dup")
        (pkg / "package.json").write_text(json.dumps({"pi": {"extensions": ["./dist"], "skills": ["./skills"]}}))
        (agent / "settings.json").write_text(json.dumps({"packages": ["npm:dup"]}))
        state = t / "selections.json"
        state.write_text(json.dumps(["dup"]))  # what an older pi-minimal would have saved
        cwd = t / "work"
        (cwd / ".git").mkdir(parents=True)
        old_state = main.STATE_FILE
        main.STATE_FILE = state
        try:
            with _sandbox(t, cwd, agent):
                sections = main.discover()
                main.load_state(sections)
                items = {i.name: i for s in sections for i in s.items}
        finally:
            main.STATE_FILE = old_state
        assert items["dup"].args == [str(pkg / "dist" / "index.js")], items["dup"].args
        assert items["dup (Skills)"].args == [str(skill)], items["dup (Skills)"].args
        assert items["dup"].checked and not items["dup (Skills)"].checked, items


def test_builtin_extensions_are_toggleable():
    """--no-extensions kills the built-ins too, so they need their own checkboxes."""
    with tempfile.TemporaryDirectory() as t:
        t = Path(t).resolve()
        agent = t / "agent"
        agent.mkdir()
        cwd = t / "work"
        (cwd / ".git").mkdir(parents=True)
        with _sandbox(t, cwd, agent):
            builtins = _items(main.discover(), "Built-in")
            assert all(i.checked and i.default for i in builtins.values()), builtins
            cmd = " ".join(main.build_command(main.discover()))
            assert "-e builtin:mcp" in cmd, cmd

            (agent / "settings.json").write_text(json.dumps({"extensions": ["-builtin:mcp"]}))
            sections = main.discover()
            builtins = _items(sections, "Built-in")
            cmd = " ".join(main.build_command(sections))
        assert not builtins["builtin:mcp"].checked, builtins
        assert builtins["builtin:codemode"].checked, builtins
        assert "builtin:mcp" not in cmd, cmd


def test_state_remembers_switching_a_builtin_off():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t).resolve()
        agent, cwd = t / "agent", t / "work"
        agent.mkdir()
        cwd.mkdir()
        state = t / "selections.json"
        old_state = main.STATE_FILE
        main.STATE_FILE = state
        try:
            with _sandbox(t, cwd, agent):
                sections = main.discover()
                builtins = _items(sections, "Built-in")
                builtins["builtin:mcp"].checked = False
                main.save_state(sections)
                assert "-builtin:mcp" in json.loads(state.read_text()), state.read_text()

                fresh = main.discover()
                main.load_state(fresh)
                assert not _items(fresh, "Built-in")["builtin:mcp"].checked
        finally:
            main.STATE_FILE = old_state


def test_context_option_off_survives_save():
    """The context-files toggle is default-on, so unchecking it must be written as '-name'."""
    with tempfile.TemporaryDirectory() as t:
        t = Path(t).resolve()
        agent, cwd = t / "agent", t / "work"
        agent.mkdir()
        cwd.mkdir()
        state = t / "selections.json"
        old_state = main.STATE_FILE
        main.STATE_FILE = state
        try:
            with _sandbox(t, cwd, agent):
                sections = main.discover()
                _items(sections, "Options")[main.CONTEXT_OPT].checked = False
                main.save_state(sections)
                assert f"-{main.CONTEXT_OPT}" in json.loads(state.read_text()), state.read_text()

                fresh = main.discover()
                main.load_state(fresh)
                assert not _items(fresh, "Options")[main.CONTEXT_OPT].checked
                assert "--no-context-files" in main.build_command(fresh), main.build_command(fresh)
        finally:
            main.STATE_FILE = old_state


def test_save_keeps_names_that_are_not_discovered_now():
    """The state file is global; names of items missing here stay for when they come back."""
    with tempfile.TemporaryDirectory() as t:
        t = Path(t).resolve()
        agent, cwd = t / "agent", t / "work"
        (cwd / ".git").mkdir(parents=True)
        _make_skill(agent, "skills/keep-skill")
        _make_skill(agent, "skills/drop-skill")
        state = t / "selections.json"
        state.write_text(json.dumps(["elsewhere-skill", "drop-skill"]))
        old_state = main.STATE_FILE
        main.STATE_FILE = state
        try:
            with _sandbox(t, cwd, agent):
                sections = main.discover()
                main.load_state(sections)
                skills = _items(sections, "Skills")
                assert skills["drop-skill"].checked and not skills["keep-skill"].checked, skills
                skills["keep-skill"].checked = True
                skills["drop-skill"].checked = False
                main.save_state(sections)
        finally:
            main.STATE_FILE = old_state
        saved = json.loads(state.read_text())
        assert "elsewhere-skill" in saved, saved
        assert "keep-skill" in saved, saved
        assert "drop-skill" not in saved, saved  # current items follow today's boxes


def test_stale_opt_out_for_a_current_item_is_dropped():
    """Today's checkbox wins for an item that is listed now; unknown entries are kept."""
    with tempfile.TemporaryDirectory() as t:
        t = Path(t).resolve()
        agent, cwd = t / "agent", t / "work"
        (cwd / ".git").mkdir(parents=True)
        agent.mkdir()
        state = t / "selections.json"
        state.write_text(json.dumps(["-builtin:mcp", "-elsewhere"]))
        old_state = main.STATE_FILE
        main.STATE_FILE = state
        try:
            with _sandbox(t, cwd, agent):
                sections = main.discover()  # no load_state: builtin:mcp is ticked here
                assert _items(sections, "Built-in")["builtin:mcp"].checked
                main.save_state(sections)
        finally:
            main.STATE_FILE = old_state
        saved = json.loads(state.read_text())
        assert "builtin:mcp" in saved and "-builtin:mcp" not in saved, saved
        assert "-elsewhere" in saved, saved


def _line_sections() -> list[main.Section]:
    """Built-in with a ticked and an unticked item, an empty section, and Options."""
    return [
        main.Section("Built-in", [main.Item("builtin:mcp", ["builtin:mcp"], True, True),
                                  main.Item("builtin:codemode", ["builtin:codemode"], False, True)], "-e"),
        main.Section("Project skills", [], "--skill"),
        main.Section("Options", [main.Item(main.CONTEXT_OPT, [], True, True)]),
    ]


def test_lines_is_the_scrollable_body():
    """Header, items with their flat index, gap; an empty section still gets both lines."""
    sections = _line_sections()
    assert main._lines(sections) == [
        ("BUILT-IN", None),
        (" [x] builtin:mcp", 0),
        (" [ ] builtin:codemode", 1),
        ("", None),
        ("PROJECT SKILLS", None),
        ("", None),
        ("OPTIONS", None),
        (f" [x] {main.CONTEXT_OPT}", 2),
        ("", None),
    ]


def test_lines_indexes_match_flat():
    sections = _line_sections()
    flat = main._flat(sections)
    indexed = [(idx, text) for text, idx in main._lines(sections) if idx is not None]
    assert [idx for idx, _ in indexed] == list(range(len(flat))), indexed
    assert [text == f" {'[x]' if it.checked else '[ ]'} {it.name}"
            for (idx, text), it in zip(indexed, flat)] == [True] * len(flat), indexed


def test_scroll_keeps_the_cursor_in_view():
    assert main._scroll(5, 7, 10) == 5, "already in view: top stays"
    assert main._scroll(5, 5, 10) == 5, "top row is in view"
    assert main._scroll(5, 14, 10) == 5, "last visible row is in view"
    assert main._scroll(5, 2, 10) == 2, "above: bring it to the top (also after wrapping)"
    assert main._scroll(5, 15, 10) == 6, "below: scroll by one"
    assert main._scroll(0, 0, 10) == 0, "never above the first line"
    assert main._scroll(3, 0, 10) == 0, "clamped at 0"
    assert main._scroll(0, 4, 1) == 4, "one row tall follows the cursor"
    assert main._scroll(4, 3, 0) == 0, "no body rows"
    assert main._scroll(4, 3, -2) == 0, "nonsense height"


def test_list_output_quotes_paths_with_spaces():
    """Both --list and the TUI footer show shlex.join, so a spaced path is readable."""
    spaced = "/tmp/my skills/SKILL.md"
    sections = [main.Section("Skills", [main.Item("spaced", [spaced], True)], "--skill")]
    out = "\n".join(main._list_lines(sections))
    assert shlex.join(main.build_command(sections)) in out, out
    assert f"'{spaced}'" in out, out
    assert shlex.split(out.splitlines()[-1])[1:] == main.build_command(sections), out



class _FakeScreen:
    """Just enough of a curses window for _draw: records what lands on each row."""

    def __init__(self, h: int, w: int):
        self.h, self.w, self.rows = h, w, {}

    def erase(self):
        self.rows = {}

    def getmaxyx(self):
        return self.h, self.w

    def addnstr(self, row, col, text, n, *attr):
        self.rows[row] = text[:n]

    def refresh(self):
        pass


def test_scrolling_up_to_a_first_item_shows_its_section_header():
    """Wrapping back to the first item must not leave the section title scrolled off."""
    secs = [main.Section("Built-in", [main.Item(f"b{i}", [f"b{i}"]) for i in range(3)], "-e"),
            main.Section("Skills", [main.Item(f"s{i}", [f"/s{i}"]) for i in range(30)], "--skill")]
    scr = _FakeScreen(10, 40)
    top = main._draw(scr, secs, 32, 0)  # last item: scrolled to the bottom
    assert top > 0, top
    top = main._draw(scr, secs, 0, top)  # wrap to the first item
    assert scr.rows[2] == "BUILT-IN" and scr.rows[3] == " [ ] b0", scr.rows


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
