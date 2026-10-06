# pi-minimal

A curses TUI for starting pi with only the extensions and skills you want. pi-minimal lists every extension and skill it can find, you tick what you need, and Enter launches pi with just those loaded.

## How it works

By default pi discovers a lot: every extension in your agent directory, every skill, prompt templates, themes, context files, and anything shipped inside installed packages. pi-minimal launches pi with `--no-extensions --no-skills --no-prompt-templates --no-themes` so that nothing is discovered, then adds back only the items you checked: one `-e` flag per extension, one `--skill` flag per skill.

`--no-extensions` also switches off pi's built-in extensions, so they get their own section: MCP (which is how your `mcp.json` servers run), llama.cpp, codemode, and tool-search. They start checked, which is what a plain `pi` launch gives you; uncheck one to actually drop it. Switching MCP off also turns off every MCP server.

There is also a toggle for the AGENTS.md / CLAUDE.md context files. Leave it checked and pi runs normally; uncheck it and `--no-context-files` goes on the command line.

Your pi `settings.json` is never touched. The selection list is saved to `~/.config/pi-minimal/selections.json`, and a plain `pi` launch afterwards behaves exactly as before.

### Selections file

The state file is a list of names: a plain name is checked, and a name prefixed with `-` records that you switched a default-on item (a built-in extension) off. So `["builtin:codemode", "ollama-lan"]` means codemode off, ollama-lan on.

Before you have launched once, everything starts from what plain pi would load, plus a `default_checked` list of names you can put in `~/.config/pi-minimal/config.json`. Once `selections.json` exists it wins, and stays in control until you delete it.

## Where it looks

Discovery follows pi 1.0, in pi's load order, so a name that exists twice is listed where pi would load it:

- Packages listed in `~/.pi/agent/settings.json` (`git:` and `npm:` sources). What a package ships comes from its `package.json` `pi` manifest (`extensions`, `skills`); without a manifest it is the conventional `extensions/` and `skills/` folders. A manifest directory expands to the files inside it, so `"./dist"` lists every `.js` in `dist/`, not a guessed `index.ts`.
- Project skills: `.pi/skills/` in the current directory, and `.agents/skills/` in the current directory and each ancestor up to the repo root.
- `~/.pi/agent/skills/` and `~/.agents/skills/`: folders with a `SKILL.md`, searched recursively (grouping folders are fine) and through symlinks.
- The `skills` arrays in `~/.pi/agent/settings.json` and project `.pi/settings.json`: entries naming a skill folder, a folder of skills, or a `.md` file add those files. Relative entries resolve against the settings file's directory.
- `~/.pi/agent/extensions/`: standalone `.ts`/`.js` files, and folders that resolve to their declared `pi.extensions` or to `index.ts`/`index.js`. Files ending in `.disabled` are skipped.

Settings entries can also turn things off, and pi-minimal honours that instead of listing the item anyway: `-` excludes one exact path, `!` excludes a glob, and `+` puts a path back. A package entry can filter itself, e.g. `{"source": "npm:pi-web-access", "extensions": ["+index.ts"]}`.

Deduplication matches pi: a skill file reached twice (through a symlink, or once by its package and once by the skills folder) is listed once, and extensions and skills are matched by name separately.

Project skills and project settings are discovered relative to where you run pi-minimal, so they only appear for the project you launch from. pi only loads them in an untrusted project after you answer its trust prompt.

The agent directory defaults to `~/.pi/agent` and is read from `PI_CODING_AGENT_DIR` (`PI_AGENT_DIR` still works), and is passed on to the pi it launches. The state file location can be overridden with `PI_MINIMAL_STATE`.

Not covered yet: packages and extensions declared in a project's `.pi/settings.json`, and pinned package sources with a `@version` or `@ref` suffix.

## Usage

```sh
uv run main.py          # open the TUI
uv run main.py --list   # non-interactive: print all items and the command that would run
```

Inside the TUI:

| Key | Action |
| --- | --- |
| j / k, up / down | move the cursor (wraps around) |
| space | toggle the item under the cursor |
| enter | save the selection and launch pi |
| q | save and quit without launching |

The bottom of the screen shows the exact `pi` command that will run, updating as you toggle items, so you can verify it before hitting Enter.

## Notes

- The launch is an `exec`, so pi replaces the pi-minimal process; quitting pi returns you to your shell.
- If an item you once checked disappears (package removed, file renamed), its name stays in the state file harmlessly until you toggle something else.
