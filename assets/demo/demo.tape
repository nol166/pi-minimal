# Records assets/demo.gif. Run from the repo root: vhs assets/demo/demo.tape
# setup.sh makes a throwaway home with made-up items; the real pi starts at the end.

Output assets/demo.gif

Set Shell bash
Set FontFamily "Menlo"
Set FontSize 16
Set LineHeight 1.25
Set Width 1000
Set Height 700
Set Padding 28
Set WindowBar Rings
Set WindowBarSize 40
Set BorderRadius 12
Set TypingSpeed 70ms
Set Framerate 30
Set Theme { "name": "pi-minimal", "background": "#0a0a0a", "foreground": "#ededed", "cursor": "#ededed", "selection": "#262626", "black": "#0a0a0a", "red": "#ededed", "green": "#ededed", "yellow": "#ededed", "blue": "#ededed", "magenta": "#ededed", "cyan": "#ededed", "white": "#ededed", "brightBlack": "#737373", "brightRed": "#ededed", "brightGreen": "#ededed", "brightYellow": "#ededed", "brightBlue": "#ededed", "brightMagenta": "#ededed", "brightCyan": "#ededed", "brightWhite": "#ffffff" }

Hide
Type "source assets/demo/setup.sh && clear"
Enter
Sleep 500ms
Show

Sleep 700ms
Type "pi-minimal"
Sleep 400ms
Enter
Sleep 1.6s

# llama.cpp off
Down
Sleep 350ms
Space
Sleep 700ms

# pi-web-access on
Down 4
Sleep 350ms
Space
Sleep 700ms

# release-notes on
Down 3
Sleep 350ms
Space
Sleep 600ms

# this project's db-migrations skill on
Down
Sleep 350ms
Space
Sleep 1.4s

# launch: pi starts with only what was ticked
Enter
Sleep 5s
