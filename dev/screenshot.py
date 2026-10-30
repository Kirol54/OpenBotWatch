#!/usr/bin/env python3
"""Render obwatch screens to PNG for the README. Needs `pyte` and `Pillow`.

  python3 dev/demo.py start
  HOME=/tmp/obwatch-demo/home python3 dev/screenshot.py docs/
  python3 dev/demo.py stop

Runs obwatch in a virtual terminal, presses keys, and saves what the screen shows.
"""
import fcntl, os, pty, select, struct, sys, termios, time

import pyte
from pyte import graphics
from PIL import Image, ImageDraw, ImageFont

COLS, ROWS = 132, 30
HERE = os.path.dirname(os.path.abspath(__file__))
OBWATCH = os.path.join(HERE, "..", "obwatch")
FONT_DIR = os.environ.get("FONT_DIR", "/usr/share/fonts/truetype/dejavu")   # DejaVu Sans Mono
SCALE = 2
FS = 14 * SCALE

# A dark terminal theme (One Dark-ish).
BG, FG = "#1e2127", "#c8ccd4"
PALETTE = {"black": "#1e2127", "red": "#e06c75", "green": "#98c379", "brown": "#e5c07b", "yellow": "#e5c07b",
           "blue": "#61afef", "magenta": "#c678dd", "cyan": "#56b6c2", "white": "#dcdfe4"}
DIM = "#7f848e"

graphics.TEXT[2] = "+italics"   # pyte ignores SGR 2 (dim); track it as italics and draw it grey
graphics.TEXT[22] = "-italics"

SHOTS = [  # (file name, keys to press first, settle seconds, rows to keep)
    ("activity.png", "", 3, ROWS),
    ("log-tab.png", "2", 4, ROWS),
    ("agents.png", "a", 2, 7),
]


def color(c, default):
    if c == "default":
        return default
    if c in PALETTE:
        return PALETTE[c]
    if len(c) == 6:
        return "#" + c
    return default


def render(screen, path, rows=ROWS):
    font = ImageFont.truetype(f"{FONT_DIR}/DejaVuSansMono.ttf", FS)
    bold = ImageFont.truetype(f"{FONT_DIR}/DejaVuSansMono-Bold.ttf", FS)
    cw = font.getbbox("M")[2]
    ch = int(FS * 1.35)
    pad = 16 * SCALE
    bar = 28 * SCALE
    img = Image.new("RGB", (cw * COLS + 2 * pad, ch * rows + 2 * pad + bar), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, img.width, bar], fill="#2c313a")   # window title bar
    for i, c in enumerate(["#ff5f56", "#ffbd2e", "#27c93f"]):
        x = pad + i * 22 * SCALE
        d.ellipse([x, bar / 2 - 6 * SCALE, x + 12 * SCALE, bar / 2 + 6 * SCALE], fill=c)
    d.text((img.width / 2, bar / 2), "obwatch", fill=DIM, font=font, anchor="mm")
    for y in range(rows):
        line = screen.buffer[y]
        for x in range(COLS):
            c = line[x]
            fg, bg = color(c.fg, FG), color(c.bg, BG)
            if c.reverse:
                fg, bg = bg, fg
            if c.italics and not c.reverse:
                fg = DIM
            px, py = pad + x * cw, bar + pad + y * ch
            if bg != BG:
                d.rectangle([px, py, px + cw, py + ch], fill=bg)
            if c.data.strip():
                d.text((px, py + (ch - FS) / 2), c.data, fill=fg, font=bold if c.bold else font)
    img.save(path)
    print("saved", path)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out, exist_ok=True)
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["TERM"] = "xterm-256color"
        os.execvp(sys.executable, [sys.executable, OBWATCH, "coder"])
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
    screen = pyte.Screen(COLS, ROWS)
    stream = pyte.ByteStream(screen)

    def pump(sec):
        end = time.time() + sec
        while time.time() < end:
            if select.select([fd], [], [], 0.1)[0]:
                try:
                    stream.feed(os.read(fd, 1 << 16))
                except OSError:
                    return

    pump(4)
    for name, keys, settle, rows in SHOTS:
        if keys:
            os.write(fd, keys.encode())
        pump(settle)
        render(screen, os.path.join(out, name), rows)
    os.write(fd, b"q")
    pump(0.5)


if __name__ == "__main__":
    main()
