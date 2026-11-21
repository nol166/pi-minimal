"""Parity check: what pi itself loads vs what pi-minimal lists, scenario by scenario.

Runnable: python3 tests/test_pi_parity.py (exit 1 on any difference).

Each scenario builds a fixture tree (a home, an agent directory, a repo), asks the
installed pi's own package manager what it resolves (pi_resolve.mjs), and compares
that with main.discover():

- extensions and skills: the files pi loads (enabled) must be exactly the files
  pi-minimal offers as items;
- built-ins: an item is ticked by default exactly when pi enables it.

Needs node and an installed pi. PI_PKG names the pi-coding-agent package directory;
otherwise it is found from the pi install under PI_CODING_AGENT_DIR (~/.pi/agent).
Without them the check prints "skipped" and exits 0.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import pi_minimal as main  # noqa: E402


def pi_package() -> Path | None:
    if os.environ.get("PI_PKG"):
        return Path(os.environ["PI_PKG"])
    agent = Path(os.environ.get("PI_CODING_AGENT_DIR", "~/.pi/agent")).expanduser()
    try:
        version = (agent / "install" / "current-version").read_text().strip()
    except OSError:
        return None
    pkg = agent / "install" / "releases" / version / "node_modules" / "@earendil-works" / "pi-coding-agent"
    return pkg if (pkg / "dist" / "core" / "package-manager.js").is_file() else None


SKILL = "---\ndescription: test\n---\n"

# name -> (files relative to the case root, global settings, project settings)
# Roots: home/ (HOME), agent/ (the pi agent dir), repo/ (cwd; has .git). "@ROOT" in a
# settings string becomes the case root's absolute path.
BASE_FILES = {
    "agent/extensions/a.ts": "", "agent/extensions/b.ts": "",
    "agent/skills/keep/SKILL.md": SKILL, "agent/skills/drop/SKILL.md": SKILL,
    "repo/.pi/skills/proj/SKILL.md": SKILL,
}
DIST_WITH_INDEX = {"pkg/dist/index.js": "", "pkg/dist/mcp-cli.js": "",
                   "pkg/package.json": json.dumps({"pi": {"extensions": ["./dist"]}})}
DIST_NO_INDEX = {"pkg/dist/one.js": "", "pkg/dist/two.js": "",
                 "pkg/package.json": json.dumps({"pi": {"extensions": ["./dist"]}})}

CASES = {
    "baseline": ({}, None, None),
    # '-' and '+' are exact: relative to the settings dir, or absolute; never a bare name
    "ext_minus_bare_name_is_no_match": ({}, {"extensions": ["-b.ts"]}, None),
    "ext_minus_relative_path": ({}, {"extensions": ["-extensions/b.ts"]}, None),
    "ext_minus_absolute_path": ({}, {"extensions": ["-@ROOT/agent/extensions/b.ts"]}, None),
    "skill_minus_bare_name_is_no_match": ({}, {"skills": ["-drop"]}, None),
    "skill_minus_relative_dir": ({}, {"skills": ["-skills/drop"]}, None),
    # '!' is a glob, and does match file names (and a skill's folder name)
    "ext_bang_glob_on_file_name": ({}, {"extensions": ["!b.*"]}, None),
    "skill_bang_glob_on_folder_name": ({}, {"skills": ["!dro*"]}, None),
    # order: '!' then '+' (exact) then '-' (exact)
    "plus_restores_a_bang_exclusion": ({}, {"extensions": ["!extensions/*.ts", "+extensions/b.ts"]}, None),
    "minus_beats_plus": ({}, {"extensions": ["!extensions/*.ts", "+extensions/b.ts", "-extensions/b.ts"]}, None),
    "plus_is_exact_not_a_glob": ({}, {"extensions": ["!extensions/*.ts", "+extensions/*.ts"]}, None),
    # each scope filters its own resources: project settings do not touch user ones
    "project_settings_do_not_filter_user_ext": ({}, None, {"extensions": ["-@ROOT/agent/extensions/a.ts"]}),
    # a directory resolves like an extension folder: manifest, else index.ts, else index.js
    "package_dir_entry_with_index": (DIST_WITH_INDEX, {"packages": ["@ROOT/pkg"]}, None),
    "package_dir_entry_without_index": (DIST_NO_INDEX, {"packages": ["@ROOT/pkg"]}, None),
    "package_filter_drops_one_file": (DIST_NO_INDEX, {"packages": [{"source": "@ROOT/pkg",
                                                                     "extensions": ["-dist/two.js"]}]}, None),
    "folder_ext_partial_minus": ({"agent/extensions/two/a.js": "", "agent/extensions/two/b.js": "",
                                  "agent/extensions/two/package.json":
                                      json.dumps({"pi": {"extensions": ["./a.js", "./b.js"]}})},
                                 {"extensions": ["-extensions/two/b.js"]}, None),
    # dedupe is by path: a package and a file that share a name both load
    "package_named_like_an_extension_file": ({"a/index.js": "",
                                              "a/package.json": json.dumps({"pi": {"extensions": ["./index.js"]}})},
                                             {"packages": ["@ROOT/a"]}, None),
    # relative settings entries resolve from the settings file's own directory
    "settings_relative_entry_base": ({"home/.agents/extras/wrong/SKILL.md": SKILL,
                                      "agent/extras/right/SKILL.md": SKILL},
                                     {"skills": ["extras"]}, None),
    # a trusted project's .pi/extensions load too
    "project_pi_extensions": ({"repo/.pi/extensions/p.ts": ""}, None, None),
    # built-ins: on unless the settings switch them off
    "builtin_switched_off": ({}, {"extensions": ["-builtin:mcp"]}, None),
}


def _build(root: Path, files: dict, global_settings, project_settings) -> None:
    for rel, text in {**BASE_FILES, **files}.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    (root / "repo" / ".git").mkdir(parents=True, exist_ok=True)
    (root / "home").mkdir(exist_ok=True)

    def subst(obj):
        return json.loads(json.dumps(obj).replace("@ROOT", str(root)))

    if global_settings is not None:
        (root / "agent" / "settings.json").write_text(json.dumps(subst(global_settings)))
    if project_settings is not None:
        (root / "repo" / ".pi" / "settings.json").write_text(json.dumps(subst(project_settings)))


def _pi(root: Path, pkg: Path) -> tuple[set[str], set[str], set[str]]:
    out = subprocess.run(["node", str(HERE / "pi_resolve.mjs"), str(root / "agent"), str(root / "repo")],
                         capture_output=True, text=True, timeout=60,
                         env={**os.environ, "PI_PKG": str(pkg), "HOME": str(root / "home")})
    if out.returncode:
        raise RuntimeError("pi_resolve.mjs failed: " + out.stderr[-400:])
    res = json.loads(out.stdout)
    ext = {os.path.realpath(r["path"]) for r in res["extensions"]
           if r["enabled"] and not r["path"].startswith("builtin:")}
    builtins = {r["path"] for r in res["extensions"] if r["enabled"] and r["path"].startswith("builtin:")}
    skills = {os.path.realpath(r["path"]) for r in res["skills"] if r["enabled"]}
    return ext, skills, builtins


def _minimal(root: Path) -> tuple[set[str], set[str], set[str]]:
    saved = (main.PI_AGENT, main.STATE_FILE, os.environ.get("HOME"), os.getcwd())
    main.PI_AGENT, main.STATE_FILE = root / "agent", root / "no-state.json"
    os.environ["HOME"] = str(root / "home")
    os.chdir(root / "repo")
    try:
        sections = main.discover()
    finally:
        main.PI_AGENT, main.STATE_FILE = saved[0], saved[1]
        if saved[2] is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = saved[2]
        os.chdir(saved[3])
    ext, skills, builtins = set(), set(), set()
    for sec in sections:
        for it in sec.items:
            if sec.name == "Built-in":
                if it.checked:
                    builtins.add(it.name)
            elif sec.flag == "-e":
                ext |= {os.path.realpath(a) for a in it.args}
            elif sec.flag == "--skill":
                skills |= {os.path.realpath(a if a.endswith(".md") else os.path.join(a, "SKILL.md"))
                           for a in it.args}
    return ext, skills, builtins


def run() -> int:
    pkg = pi_package()
    if pkg is None or shutil.which("node") is None:
        print("skipped: needs node and an installed pi (set PI_PKG)")
        return 0
    failed = 0
    with tempfile.TemporaryDirectory() as t:
        for name, (files, gs, ps) in CASES.items():
            root = Path(t).resolve() / name
            _build(root, files, gs, ps)
            want, got = _pi(root, pkg), _minimal(root)
            diffs = []
            for label, w, g in zip(("extension", "skill", "built-in"), want, got):
                diffs += [f"only pi loads {label} {p.replace(str(root) + '/', '')}" for p in sorted(w - g)]
                diffs += [f"only pi-minimal offers {label} {p.replace(str(root) + '/', '')}" for p in sorted(g - w)]
            print(f"{'ok  ' if not diffs else 'FAIL'} {name}")
            for d in diffs:
                print(f"       {d}")
            failed += bool(diffs)
    print(f"\n{len(CASES) - failed}/{len(CASES)} scenarios match pi {pkg.parent.parent.parent.name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
