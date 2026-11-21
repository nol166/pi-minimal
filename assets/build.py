#!/usr/bin/env python3
"""Regenerate the README graphics: python3 assets/build.py

Writes hero-{light,dark}.svg and screen-{light,dark}.svg next to this file. Both
themes share one geometry; only the palette differs. The screen is a drawing of the
TUI with made-up item names, laid out exactly as pi_minimal._draw lays it out.
"""

from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace"

PALETTES = {
    "light": dict(ink="#171717", mute="#a3a3a3", line="#e5e5e5", faint="#ededed",
                  window="#ffffff", bar="#fafafa", inv="#ffffff"),
    "dark": dict(ink="#ededed", mute="#737373", line="#262626", faint="#1f1f1f",
                 window="#0a0a0a", bar="#111111", inv="#0a0a0a"),
}


def hero(c: dict) -> str:
    """Many rows, a few ticked, and the ticked ones join into one `pi` launch."""
    rows = [(118, True), (82, False), (146, False), (96, True), (130, True), (70, False)]
    x0, y0, step, box = 302, 44, 26, 14
    join_x, cy = x0 + 242, y0 + box / 2 + step * (len(rows) - 1) / 2
    out = []
    for i, (w, on) in enumerate(rows):
        y = y0 + i * step
        if on:
            out.append(f'<rect x="{x0}" y="{y}" width="{box}" height="{box}" rx="3" fill="{c["ink"]}"/>')
            out.append(f'<path d="M{x0 + 3.5} {y + 7.2}l2.6 2.6 4.6-5.2" fill="none" '
                       f'stroke="{c["inv"]}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>')
            out.append(f'<rect x="{x0 + 26}" y="{y + 4}" width="{w}" height="6" rx="3" fill="{c["ink"]}"/>')
            sx, sy = x0 + 26 + w + 10, y + box / 2
            mx = (sx + join_x) / 2
            out.append(f'<path d="M{sx} {sy}C{mx} {sy} {mx} {cy} {join_x} {cy}" fill="none" '
                       f'stroke="{c["ink"]}" stroke-width="1.25"/>')
        else:
            out.append(f'<rect x="{x0 + .75}" y="{y + .75}" width="{box - 1.5}" height="{box - 1.5}" rx="2.5" '
                       f'fill="none" stroke="{c["mute"]}" stroke-opacity=".55" stroke-width="1.5"/>')
            out.append(f'<rect x="{x0 + 26}" y="{y + 4}" width="{w}" height="6" rx="3" fill="{c["line"]}"/>')
    out.append(f'<circle cx="{join_x}" cy="{cy}" r="2.5" fill="{c["ink"]}"/>')
    out.append(f'<path d="M{join_x} {cy}H{join_x + 26}" stroke="{c["ink"]}" stroke-width="1.25"/>')
    px, pw, ph = join_x + 26, 88, 40
    out.append(f'<rect x="{px + .5}" y="{cy - ph / 2 + .5}" width="{pw}" height="{ph}" rx="8" '
               f'fill="{c["window"]}" stroke="{c["ink"]}" stroke-width="1.25"/>')
    out.append(f'<text x="{px + 18}" y="{cy + 5.5}" font-family="{MONO}" font-size="16" fill="{c["mute"]}">$</text>')
    out.append(f'<text x="{px + 36}" y="{cy + 5.5}" font-family="{MONO}" font-size="16" '
               f'font-weight="600" fill="{c["ink"]}">pi</text>')
    out.append(f'<rect x="{px + 62}" y="{cy - 9}" width="9" height="18" rx="1" fill="{c["ink"]}"/>')
    out.append(f'<text x="480" y="262" text-anchor="middle" font-family="{MONO}" font-size="30" '
               f'font-weight="600" letter-spacing="-0.5" fill="{c["ink"]}">pi-minimal</text>')
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="960" height="300" viewBox="0 0 960 300" '
            'role="img" aria-label="pi-minimal">' + "".join(out) + "</svg>\n")


# (text, style): style is "" plain, "b" bold, "cur" the cursor row, "dim" the command line
SCREEN = [
    ("pi-minimal — check what to load, Enter launches", ""),
    ("", ""),
    ("BUILT-IN", "b"),
    (" [x] builtin:mcp", ""),
    (" [ ] builtin:llama.cpp", ""),
    (" [x] builtin:codemode", ""),
    (" [x] builtin:tool-search", ""),
    ("", ""),
    ("EXTENSIONS", "b"),
    (" [x] pi-web-access", ""),
    (" [ ] git-guard", "cur"),
    (" [ ] token-meter", ""),
    ("", ""),
    ("SKILLS", "b"),
    (" [x] release-notes", ""),
    (" [ ] code-review", ""),
    ("", ""),
    ("PROJECT SKILLS", "b"),
    (" [x] db-migrations", ""),
    ("", ""),
    ("OPTIONS", "b"),
    (" [x] AGENTS.md / CLAUDE.md context files", ""),
    ("", ""),
    ("pi --no-extensions --no-skills --no-prompt-templates --no-themes -e builtin:mcp -e builtin:", "dim"),
    ("j/↓ down  k/↑ up  space toggle  enter launch  q quit", ""),
]


def screen(c: dict) -> str:
    W, pad, top, lh, fs, cw = 880, 28, 44, 22, 14, 8.43
    H = top + 22 + lh * len(SCREEN) + 18
    out = [
        f'<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="12" fill="{c["window"]}" stroke="{c["line"]}"/>',
        f'<path d="M1 {top}V13a12 12 0 0 1 12-12h{W - 26}a12 12 0 0 1 12 12V{top}z" fill="{c["bar"]}"/>',
        f'<path d="M1 {top}H{W - 1}" stroke="{c["line"]}"/>',
    ]
    for i in range(3):
        out.append(f'<circle cx="{22 + i * 18}" cy="{top / 2}" r="5.5" fill="{c["line"]}"/>')
    out.append(f'<text x="{W / 2}" y="{top / 2 + 4.5}" text-anchor="middle" font-family="{MONO}" '
               f'font-size="12.5" fill="{c["mute"]}">pi-minimal</text>')
    y = top + 22
    for text, style in SCREEN:
        base = y + fs - 3
        if style == "cur":
            out.append(f'<rect x="{pad - 2}" y="{y - 3}" width="{len(text) * cw + 4}" height="{lh - 2}" '
                       f'rx="2" fill="{c["ink"]}"/>')
        fill = {"cur": c["inv"], "dim": c["mute"]}.get(style, c["ink"])
        weight = ' font-weight="700"' if style == "b" else ""
        if text:
            out.append(f'<text x="{pad}" y="{base}" xml:space="preserve" font-family="{MONO}" '
                       f'font-size="{fs}" fill="{fill}"{weight}>{escape(text)}</text>')
        y += lh
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
            f'role="img" aria-label="The pi-minimal picker">' + "".join(out) + "</svg>\n")


if __name__ == "__main__":
    for theme, c in PALETTES.items():
        (HERE / f"hero-{theme}.svg").write_text(hero(c))
        (HERE / f"screen-{theme}.svg").write_text(screen(c))
    print("wrote", ", ".join(sorted(p.name for p in HERE.glob("*.svg"))))
