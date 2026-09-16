"""Runnable check: uv run test_project_skills.py"""

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
        agent = t / "agent"
        agent.mkdir()
        old_agent, old_home, old_cwd = main.PI_AGENT, os.environ.get("HOME"), os.getcwd()
        main.PI_AGENT = agent
        if old_home is None:
            del os.environ["HOME"]
        else:
            os.environ["HOME"] = str(t / "home")
        os.chdir(root)
        try:
            sections = main.discover()
            by = {s.name: s for s in sections}
            proj = by["Project skills"]
            assert [i.name for i in proj.items] == ["proj-skill"], [i.name for i in proj.items]
            proj.items[0].checked = True
            cmd = " ".join(main.build_command(sections))
            assert f"--skill {sk}" in cmd, cmd
        finally:
            main.PI_AGENT = old_agent
            if old_home is None:
                del os.environ["HOME"]
            else:
                os.environ["HOME"] = old_home
            os.chdir(old_cwd)


def test_symlinked_skill_listed_once():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t).resolve()
        agent, home = t / "agent", t / "home"
        real = _make_skill(agent, "skills/foo")
        link = home / ".agents" / "skills" / "foo-link"
        link.parent.mkdir(parents=True)
        os.symlink(real, link)
        old_agent, old_home, old_cwd = main.PI_AGENT, os.environ.get("HOME"), os.getcwd()
        main.PI_AGENT = agent
        if old_home is None:
            del os.environ["HOME"]
        else:
            os.environ["HOME"] = str(home)
        os.chdir(t)
        try:
            skills = {i.name: i for s in main.discover() if s.name == "Skills" for i in s.items}
        finally:
            main.PI_AGENT = old_agent
            if old_home is None:
                del os.environ["HOME"]
            else:
                os.environ["HOME"] = old_home
            os.chdir(old_cwd)
        assert list(skills) == ["foo"], skills


def test_name_collision_global_wins():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t).resolve()
        agent, root = t / "agent", t / "repo"
        (root / ".git").mkdir(parents=True)
        _make_skill(agent, "skills/dup")
        _make_skill(root, ".pi/skills/dup")
        old_agent, old_home, old_cwd = main.PI_AGENT, os.environ.get("HOME"), os.getcwd()
        main.PI_AGENT = agent
        if old_home is None:
            del os.environ["HOME"]
        else:
            os.environ["HOME"] = str(t / "home")
        os.chdir(root)
        try:
            all_items = {i.name: i for s in main.discover() for i in s.items}
        finally:
            main.PI_AGENT = old_agent
            if old_home is None:
                del os.environ["HOME"]
            else:
                os.environ["HOME"] = old_home
            os.chdir(old_cwd)
        assert all_items["dup"].path == agent / "skills" / "dup", all_items["dup"].path


def test_settings_skills_arrays():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t).resolve()
        agent, root, home = t / "agent", t / "repo", t / "home"
        (root / ".git").mkdir(parents=True)
        global_skill = _make_skill(t, "elsewhere/g-skill")
        claude = root / ".claude" / "skills"
        claude_skill = _make_skill(claude, "c-skill")
        agent.mkdir()
        (agent / "settings.json").write_text(
            json.dumps({"skills": [str(global_skill.parent)]}))
        (root / ".pi").mkdir()
        (root / ".pi" / "settings.json").write_text(
            json.dumps({"skills": ["../.claude/skills"]}))
        old_agent, old_home, old_cwd = main.PI_AGENT, os.environ.get("HOME"), os.getcwd()
        main.PI_AGENT = agent
        if old_home is None:
            del os.environ["HOME"]
        else:
            os.environ["HOME"] = str(home)
        os.chdir(root)
        try:
            by = {s.name: {i.name: i for i in s.items} for s in main.discover()}
        finally:
            main.PI_AGENT = old_agent
            if old_home is None:
                del os.environ["HOME"]
            else:
                os.environ["HOME"] = old_home
            os.chdir(old_cwd)
        assert by["Skills"]["g-skill"].path.resolve() == global_skill, by["Skills"]
        assert by["Project skills"]["c-skill"].path.resolve() == claude_skill, by["Project skills"]


if __name__ == "__main__":
    test_project_dirs_walks_up_to_repo_root()
    test_discover_and_command_include_project_skill()
    test_symlinked_skill_listed_once()
    test_name_collision_global_wins()
    test_settings_skills_arrays()
    print("ok")
