# pi-minimal

A curses TUI for starting pi with only the extensions and skills you want. It lists everything it can find, you tick what you need, and Enter launches pi with just those loaded.

## How it works

pi discovers a lot by default: every extension in your agent directory, every skill, prompt templates, themes, context files, plus anything shipped inside installed packages. pi-minimal inverts that. It launches pi with `--no-extensions --no-skills --no-prompt-templates --no-themes`, so nothing is discovered, and then re-adds only the items you checked, one `-e` flag per extension and one `--skill` flag per skill.

There is also an option for the AGENTS.md / CLAUDE.md context files. Leave it checked and pi runs normally; uncheck it and `--no-context-files` goes on the command line.

Your pi `settings.json` is never touched. The selection list is saved to `~/.config/pi-minimal/selections.json`, and a plain `pi` launch afterwards behaves exactly as before. The first time you run it, only `ollama-lan` and `grove-pi-extension` are pre-checked.

## Where it looks

Extensions and skills are discovered from three places:

- Packages listed in `~/.pi/agent/settings.json` (both `git:` and `npm:` sources). A package can ship an extension at its root or under `pi-extension/`, and any `skills/` directory inside it.
- `~/.pi/agent/extensions/`, for standalone `.ts`/`.js` files and directories with an `index.*`. Files ending in `.disabled` are skipped.
- `~/.pi/agent/skills/`, for skill folders with a `SKILL.md`.

The agent directory defaults to `~/.pi/agent` and can be overridden with `PI_AGENT_DIR`. The state file location can be overridden with `PI_MINIMAL_STATE`.

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

The bottom of the screen shows the exact `pi` command that will run, updating as you toggle items, so you can verify before you hit Enter.

## Notes

- The launch is an `exec`, so pi replaces the pi-minimal process; quitting pi returns you to your shell.
- Toggling an item you never saw before is fine. If it disappears later (package removed, file renamed), its name stays in the state file harmlessly until you toggle something else.
