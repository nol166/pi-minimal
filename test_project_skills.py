"""Runnable check: uv run test_project_skills.py"""

import os
import tempfile
from pathlib import Path

import main


def _make_skill(root: Path, rel: str) -> Path:
    d = root / rel
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text("# skill\n")
    return d


def test_project_skill_dirs_walks_up_to_repo_root():
    with tempfile.TemporaryDirectory() as t:
        root = Path(t).resolve() / "repo"
        (root / ".git").mkdir(parents=True)
        _make_skill(root, ".pi/skills/root-skill")
        _make_skill(root, ".agents/skills/agents-skill")
        cwd = root / "work"
        cwd.mkdir()
        old = os.getcwd()
        os.chdir(cwd)
        try:
            dirs = main._project_skill_dirs()
        finally:
            os.chdir(old)
        assert dirs == [root / ".pi/skills", root / ".agents/skills"], dirs


def test_discover_and_command_include_project_skill():
    with tempfile.TemporaryDirectory() as t:
        root = Path(t).resolve() / "repo"
        (root / ".git").mkdir(parents=True)
        sk = _make_skill(root, ".pi/skills/proj-skill")
        agent = Path(t) / "agent"  # empty agent dir: no globals
        agent.mkdir()
        old_agent, old_cwd = main.PI_AGENT, os.getcwd()
        main.PI_AGENT = agent
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
            os.chdir(old_cwd)


if __name__ == "__main__":
    test_project_skill_dirs_walks_up_to_repo_root()
    test_discover_and_command_include_project_skill()
    print("ok")
