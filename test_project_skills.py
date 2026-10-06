"""Runnable check: python3 test_project_skills.py (or uv run test_project_skills.py)

Discovery is checked against what pi 1.0 loads, not what pi-minimal used to list.
"""

import json
import os
import tempfile
from pathlib import Path

import main


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
            "extensions": ["-off.ts"],
        }))
        cwd = t / "work"
        (cwd / ".git").mkdir(parents=True)
        with _sandbox(t, cwd, agent):
            sections = main.discover()
        assert list(_items(sections, "Skills")) == ["keep"], _items(sections, "Skills")
        assert list(_items(sections, "Extensions")) == ["on"], _items(sections, "Extensions")


def test_package_uses_its_declared_extension_paths():
    """A package declaring ./dist loads dist/*.js, not a guessed source file."""
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
        assert exts["fake-pkg"].args == [str(pkg / "dist" / "index.js"),
                                         str(pkg / "dist" / "mcp-cli.js")], exts["fake-pkg"].args

        # a "-" filter on one of the declared files drops just that file
        (agent / "settings.json").write_text(json.dumps(
            {"packages": [{"source": "npm:fake-pkg", "extensions": ["-dist/mcp-cli.js"]}]}))
        with _sandbox(t, cwd, agent):
            exts = _items(main.discover(), "Extensions")
        assert exts["fake-pkg"].args == [str(pkg / "dist" / "index.js")], exts["fake-pkg"].args


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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
