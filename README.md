# pi-minimal

Launch pi as minimally as possible. The TUI lists every discovered extension
and skill; check what you want, hit Enter.

It runs pi with `--no-extensions --no-skills --no-prompt-templates
--no-themes` (and `--no-context-files` if context files are unchecked), then
re-adds only the checked items via `-e` / `--skill`.

No pi config is ever written — selection state lives in
`~/.config/pi-minimal/selections.json`, so a normal `pi` launch afterwards is
unaffected.

```sh
uv run main.py          # TUI
uv run main.py --list   # non-interactive: print items + launch command
```

Defaults: only `ollama-lan` and `grove-pi-extension` checked.
