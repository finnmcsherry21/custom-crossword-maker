#!/usr/bin/env python3
"""
crossword_maker.py - build a printable, personalized crossword puzzle.

QUICK START
    1. pip install reportlab        (Mac/Linux may need: pip3 install reportlab)
    2. Edit the CONFIG section just below: title, dedication, answers & clues.
    3. python3 crossword_maker.py   ->  writes crossword.pdf and docs/index.html

The PDF is for printing (puzzle + answer key). The HTML page is a playable
version you can fill in on a phone or computer, and can be hosted as a site.

Optional flags:
    --seed 42          make the layout reproducible (same seed = same puzzle)
    --attempts 3000    try more random layouts (slower, often tighter grids)
    --out mom.pdf      choose the output PDF file name
    --html path.html   choose the output HTML file name (default: docs/index.html)
    --no-html          skip writing the playable HTML page

Tip: if you don't like the layout, just run again (or try a different --seed).
"""

# =============================================================================
# ============================  CONFIG - EDIT ME  =============================
# =============================================================================

TITLE = "All About Melina"
SUBTITLE = "Love, Finn"      # dedication line (or "")

# (ANSWER, CLUE) pairs. Answers can include spaces / punctuation; they're
# stripped for the grid ("SAN LUIS OBISPO" -> SANLUISOBISPO).
# Aim for 10-25 words. Longer lists with shared letters interlock best.
# Many of these come from the Melina Strands puzzles; a few are general.
WORDS = [
    ("MELINA",         "The 'I love _____' at the heart of the first Strands puzzle"),
    ("BEAUTIFUL",      "One of the things I love about you"),
    ("LAVA CAKE",      "Sweet-tooth dessert, promised with vanilla ice cream"),
    ("HARIBO",         "Gummy brand in Melina's sweet tooth puzzle"),
    ("LICORICE",       "Chewy candy from Melina's sweet tooth"),
    ("THAI TEA",       "Iced drink on the 'Sip sip hooray!' list"),
    ("JAGER BOMB",     "Shot from 'Sip sip hooray!,' promised with lavender vanilla lattes"),
    ("DOUBLE DOUBLE",  "In-N-Out order that's the spangram of 'Order like Melina'"),
    ("IN N OUT",       "Burger chain in 'Order like Melina'"),
    ("COKE ZERO",      "Her drink that's '2/3 Diet Coke, 1/3 Coke,' but actually this"),
    ("WATERMELON",     "Fruit that's 'on top' in the juicy Strands puzzle"),
    ("SCALLOPS",       "Seafood from the dinner date puzzle"),
    ("CROSSWORD",      "Printable puzzle like this one"),
    ("STRANDS",        "Word game this puzzle borrows its theme words from"),
    ("FINN",           "Name signed on every Strands win screen"),
]

SHOW_WORD_LENGTHS = True    # adds "(3,4,6)" after multi-word clues, "(7)" otherwise
SHOW_BLACK_SQUARES = False  # True = classic look, fill empty cells black
INCLUDE_ANSWER_KEY = True   # adds an answer-key page at the end
DEFAULT_ATTEMPTS = 1500     # random layouts to try; best one wins
DEFAULT_OUTPUT = "crossword.pdf"
DEFAULT_HTML = "docs/index.html"

# =============================================================================
# ========================  END OF CONFIG - CODE BELOW  =======================
# =============================================================================

import argparse
import base64
import html as html_lib
import json
import os
import random
import re
import sys

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas as pdf_canvas
    from reportlab.lib.utils import simpleSplit
except ImportError:  # friendly fallback note
    sys.exit(
        "This script needs the 'reportlab' library to make the PDF.\n"
        "Install it with:   pip install reportlab\n"
        "  (or: pip3 install reportlab  /  python3 -m pip install reportlab)\n"
        "Then run this script again."
    )

ACROSS, DOWN = (0, 1), (1, 0)  # (row step, col step)


# -----------------------------------------------------------------------------
# Word preparation
# -----------------------------------------------------------------------------
class Entry:
    """One answer/clue pair, cleaned for the grid."""

    def __init__(self, answer, clue):
        self.raw = answer.strip()
        self.word = re.sub(r"[^A-Za-z]", "", answer).upper()
        self.clue = clue.strip()
        parts = [len(p) for p in re.split(r"[^A-Za-z]+", answer) if p]
        self.lengths = "(" + ",".join(map(str, parts)) + ")"

    def clue_text(self):
        return f"{self.clue} {self.lengths}" if SHOW_WORD_LENGTHS else self.clue


# -----------------------------------------------------------------------------
# Layout engine
# -----------------------------------------------------------------------------
class Layout:
    """A grid stored sparsely: {(row, col): letter}. Coordinates may go negative."""

    def __init__(self):
        self.cells = {}          # (r, c) -> letter
        self.dirs = {}           # (r, c) -> set of directions using that cell
        self.placed = []         # (entry, row, col, direction)
        self.intersections = 0

    def copy_bounds(self):
        rs = [r for r, _ in self.cells]
        cs = [c for _, c in self.cells]
        return min(rs), max(rs), min(cs), max(cs)

    def check(self, word, r, c, d):
        """Return number of crossings if `word` fits at (r,c) in direction d,
        else None. Enforces standard crossword adjacency rules."""
        dr, dc = d
        pr, pc = dc, dr  # perpendicular step
        # cells directly before the start and after the end must be empty,
        # otherwise we'd extend another word.
        if (r - dr, c - dc) in self.cells:
            return None
        if (r + dr * len(word), c + dc * len(word)) in self.cells:
            return None
        crossings = 0
        for i, ch in enumerate(word):
            cell = (r + dr * i, c + dc * i)
            existing = self.cells.get(cell)
            if existing is not None:
                if existing != ch or d in self.dirs[cell]:
                    return None          # letter clash or overlapping same way
                crossings += 1
            else:
                # empty cell: side neighbours must be empty, otherwise we'd
                # create unintended two-letter "words" side by side.
                if (cell[0] + pr, cell[1] + pc) in self.cells:
                    return None
                if (cell[0] - pr, cell[1] - pc) in self.cells:
                    return None
        return crossings

    def place(self, entry, r, c, d, crossings):
        dr, dc = d
        for i, ch in enumerate(entry.word):
            cell = (r + dr * i, c + dc * i)
            self.cells[cell] = ch
            self.dirs.setdefault(cell, set()).add(d)
        self.placed.append((entry, r, c, d))
        self.intersections += crossings

    def candidates(self, word):
        """All legal placements of `word` that cross at least one letter."""
        out = []
        for (cr, cc), ch in list(self.cells.items()):
            for i, wch in enumerate(word):
                if wch != ch:
                    continue
                for d in (ACROSS, DOWN):
                    if d in self.dirs[(cr, cc)]:
                        continue
                    r, c = cr - d[0] * i, cc - d[1] * i
                    x = self.check(word, r, c, d)
                    if x:
                        out.append((x, r, c, d))
        return list(set(out))

    def bounds_after(self, word, r, c, d):
        r0, r1, c0, c1 = self.copy_bounds()
        er, ec = r + d[0] * (len(word) - 1), c + d[1] * (len(word) - 1)
        return (max(r1, er) - min(r0, r) + 1, max(c1, ec) - min(c0, c) + 1)

    def score(self):
        """Higher is better: words placed >> crossings >> compact & square."""
        r0, r1, c0, c1 = self.copy_bounds()
        h, w = r1 - r0 + 1, c1 - c0 + 1
        return (len(self.placed) * 10000 + self.intersections * 100
                - (h * w) * 0.5 - abs(h - w) * 3)


def build_layout(entries, rng):
    """One randomized greedy attempt."""
    # longest first, with a little shuffle among similar lengths for variety
    order = sorted(entries, key=lambda e: -(len(e.word) + rng.random() * 2.5))
    lay = Layout()
    first = order[0]
    lay.place(first, 0, 0, rng.choice([ACROSS, DOWN]), 0)
    pending = order[1:]
    # keep looping while we're still making progress (late words can open spots)
    progress = True
    while pending and progress:
        progress = False
        still = []
        for e in pending:
            cands = lay.candidates(e.word)
            if not cands:
                still.append(e)
                continue
            # rank: more crossings, then smaller/squarer bounding box; add noise
            def rank(cand):
                x, r, c, d = cand
                h, w = lay.bounds_after(e.word, r, c, d)
                return x * 50 - h * w * 0.3 - abs(h - w) * 2 + rng.random() * 8
            cands.sort(key=rank, reverse=True)
            x, r, c, d = cands[0] if rng.random() < 0.7 else rng.choice(cands[:3])
            lay.place(e, r, c, d, x)
            progress = True
        pending = still
    return lay, pending


def best_layout(entries, attempts, seed):
    rng = random.Random(seed)
    best, best_left = None, None
    for _ in range(attempts):
        lay, left = build_layout(entries, rng)
        if best is None or lay.score() > best.score():
            best, best_left = lay, left
    return best, best_left


# -----------------------------------------------------------------------------
# Numbering
# -----------------------------------------------------------------------------
def number_grid(lay):
    """Normalize to (0,0) origin, assign standard numbers (left->right,
    top->bottom), and return grid, numbers, across clues, down clues."""
    r0, r1, c0, c1 = lay.copy_bounds()
    rows, cols = r1 - r0 + 1, c1 - c0 + 1
    grid = [[None] * cols for _ in range(rows)]
    for (r, c), ch in lay.cells.items():
        grid[r - r0][c - c0] = ch
    starts = {}  # (r,c) -> list of (direction, entry)
    for e, r, c, d in lay.placed:
        starts.setdefault((r - r0, c - c0), []).append((d, e))
    numbers, across, down, n = {}, [], [], 0
    for r in range(rows):
        for c in range(cols):
            if (r, c) in starts:
                n += 1
                numbers[(r, c)] = n
                for d, e in starts[(r, c)]:
                    (across if d == ACROSS else down).append((n, e))
    return grid, numbers, sorted(across, key=lambda t: t[0]), sorted(down, key=lambda t: t[0])


# -----------------------------------------------------------------------------
# PDF output
# -----------------------------------------------------------------------------
PAGE_W, PAGE_H = letter
MARGIN = 0.6 * 72


def draw_header(cv, title, subtitle, y):
    cv.setFont("Helvetica-Bold", 24)
    cv.drawCentredString(PAGE_W / 2, y, title)
    y -= 22
    if subtitle:
        cv.setFont("Helvetica-Oblique", 12)
        cv.drawCentredString(PAGE_W / 2, y, subtitle)
        y -= 18
    return y - 6


def draw_grid(cv, grid, numbers, top_y, max_h, fill_letters):
    """Draw the grid centred horizontally below top_y. Returns bottom y."""
    rows, cols = len(grid), len(grid[0])
    cell = min((PAGE_W - 2 * MARGIN) / cols, max_h / rows, 30)
    gw, gh = cell * cols, cell * rows
    x0 = (PAGE_W - gw) / 2
    y_top = top_y
    cv.setLineWidth(0.8)
    for r in range(rows):
        for c in range(cols):
            x = x0 + c * cell
            y = y_top - (r + 1) * cell
            ch = grid[r][c]
            if ch is None:
                if SHOW_BLACK_SQUARES:
                    cv.setFillGray(0)
                    cv.rect(x, y, cell, cell, stroke=1, fill=1)
                continue
            cv.setFillGray(1)
            cv.rect(x, y, cell, cell, stroke=1, fill=1)
            cv.setFillGray(0)
            if (r, c) in numbers:
                cv.setFont("Helvetica", max(5, cell * 0.28))
                cv.drawString(x + cell * 0.07, y + cell * 0.70, str(numbers[(r, c)]))
            if fill_letters:
                cv.setFont("Helvetica-Bold", cell * 0.55)
                cv.drawCentredString(x + cell / 2, y + cell * 0.22, ch)
    return y_top - gh


class ClueWriter:
    """Writes clue text in two columns, flowing onto new pages when needed."""

    def __init__(self, cv, top_y, title):
        self.cv, self.title = cv, title
        self.col_w = (PAGE_W - 2 * MARGIN - 24) / 2
        self.col = 0
        self.top = top_y
        self.y = top_y
        self.font_size = 10.5
        self.lead = 13.5
        self.section = ""      # current heading, repeated as "(cont.)" after a break

    def _x(self):
        return MARGIN + self.col * (self.col_w + 24)

    def _need(self, h):
        if self.y - h < MARGIN:
            if self.col == 0:
                self.col, self.y = 1, self.top
            else:  # new page
                self.cv.showPage()
                self.cv.setFont("Helvetica-Bold", 14)
                self.cv.drawCentredString(PAGE_W / 2, PAGE_H - MARGIN, self.title + " (clues continued)")
                self.top = self.y = PAGE_H - MARGIN - 28
                self.col = 0
            if self.section:  # remind the reader which list this is
                self.cv.setFont("Helvetica-Bold", 13)
                self.cv.drawString(self._x(), self.y, self.section + " (cont.)")
                self.y -= self.lead + 3

    def heading(self, text):
        self.section = ""
        self._need(self.lead * 3)
        self.section = text
        self.cv.setFont("Helvetica-Bold", 13)
        self.cv.drawString(self._x(), self.y, text)
        self.y -= self.lead + 3

    def clue(self, num, text):
        num_w = 22
        lines = simpleSplit(text, "Helvetica", self.font_size, self.col_w - num_w)
        self._need(self.lead * len(lines))
        x = self._x()
        self.cv.setFont("Helvetica-Bold", self.font_size)
        self.cv.drawRightString(x + num_w - 6, self.y, str(num))
        self.cv.setFont("Helvetica", self.font_size)
        for ln in lines:
            self.cv.drawString(x + num_w, self.y, ln)
            self.y -= self.lead
        self.y -= 2.5

    def gap(self):
        self.y -= self.lead * 0.8


def make_pdf(path, grid, numbers, across, down):
    cv = pdf_canvas.Canvas(path, pagesize=letter)
    cv.setTitle(TITLE)

    # ---- Page 1: puzzle ----
    y = draw_header(cv, TITLE, SUBTITLE, PAGE_H - MARGIN - 14)
    rows = len(grid)
    # give the grid ~55% of the remaining height (less if it's a short grid)
    max_h = min((y - MARGIN) * 0.58, rows * 30)
    y = draw_grid(cv, grid, numbers, y, max_h, fill_letters=False) - 26

    # Across and Down side by side if they fit, flowing otherwise
    w = ClueWriter(cv, y, TITLE)
    w.heading("ACROSS")
    for n, e in across:
        w.clue(n, e.clue_text())
    # start Down in the right column if Across is in the left one
    if w.col == 0:
        w.col, w.y = 1, w.top
    else:
        w.gap()
    w.heading("DOWN")
    for n, e in down:
        w.clue(n, e.clue_text())
    cv.showPage()

    # ---- Answer key ----
    if INCLUDE_ANSWER_KEY:
        y = draw_header(cv, TITLE + " - Answer Key", "", PAGE_H - MARGIN - 14)
        max_h = min((y - MARGIN) * 0.6, rows * 30)
        y = draw_grid(cv, grid, numbers, y, max_h, fill_letters=True) - 26
        w = ClueWriter(cv, y, TITLE + " - Answer Key")
        w.heading("ACROSS")
        for n, e in across:
            w.clue(n, e.raw.upper())
        if w.col == 0:
            w.col, w.y = 1, w.top
        else:
            w.gap()
        w.heading("DOWN")
        for n, e in down:
            w.clue(n, e.raw.upper())
        cv.showPage()
    cv.save()


# -----------------------------------------------------------------------------
# HTML output (playable page)
# -----------------------------------------------------------------------------
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#f7f3ea">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>__TITLE_ESC__</title>
<style>
  :root {
    --paper: #f7f3ea;
    --ink: #1c1917;
    --muted: #6b645b;
    --line: #2a2724;
    --cell-bg: #fffdf8;
    --word: #f3e2a0;
    --sel: #e8b84a;
    --wrong-bg: #f8d4d0;
    --wrong: #9b1c1c;
    --wine: #7a2e3a;
    --wine-dark: #5c222b;
    --bar: #1c1917;
    --ok: #2f6b3a;
    --shadow: 0 1px 2px rgba(28,25,23,.06), 0 8px 24px rgba(28,25,23,.06);
    --ui: "Segoe UI", system-ui, -apple-system, Roboto, Helvetica, Arial, sans-serif;
    --serif: Georgia, "Palatino Linotype", Palatino, "Times New Roman", serif;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    font-family: var(--ui);
    background: var(--paper);
    color: var(--ink);
    min-height: 100dvh;
    -webkit-tap-highlight-color: transparent;
  }
  body.locked { overflow: hidden; }
  .wrap {
    max-width: 1100px;
    margin: 0 auto;
    padding: 16px 16px 48px;
    padding-left: max(16px, env(safe-area-inset-left));
    padding-right: max(16px, env(safe-area-inset-right));
  }
  header.page-head { text-align: center; margin: 4px 0 12px; }
  header.page-head h1 {
    font-family: var(--serif);
    font-weight: 700;
    font-size: clamp(1.5rem, 4vw, 2.15rem);
    letter-spacing: -0.02em;
    margin: 0 0 4px;
    line-height: 1.15;
  }
  header.page-head .sub {
    font-family: var(--serif);
    font-style: italic;
    color: var(--muted);
    margin: 0;
    font-size: 1.02rem;
  }
  .tools {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
    justify-content: center;
    margin: 0 0 12px;
  }
  .tools button, .tools summary {
    appearance: none;
    font: 600 13px/1 var(--ui);
    border: 1px solid #cfc6b6;
    background: #fff;
    color: var(--ink);
    padding: 8px 12px;
    border-radius: 999px;
    cursor: pointer;
    box-shadow: 0 1px 0 rgba(28,25,23,.04);
  }
  .tools button:hover, .tools summary:hover { border-color: #a89f90; background: #fff; }
  .tools button:active, .tools summary:active { transform: translateY(1px); }
  #btn-check {
    background: var(--wine);
    color: #fff;
    border-color: var(--wine-dark);
  }
  #btn-check:hover { background: var(--wine-dark); }
  .tools .progress {
    font-size: 12px;
    color: var(--muted);
    margin-left: 4px;
    font-variant-numeric: tabular-nums;
  }
  .tools .progress.done { color: var(--ok); font-weight: 700; }
  .menu { position: relative; }
  .menu summary { list-style: none; }
  .menu summary::-webkit-details-marker { display: none; }
  .menu summary::after { content: " ▾"; font-size: 10px; opacity: .7; }
  .menu .panel {
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    background: #fff;
    border: 1px solid #ddd4c6;
    border-radius: 10px;
    min-width: 132px;
    box-shadow: var(--shadow);
    z-index: 40;
    overflow: hidden;
    padding: 4px;
  }
  .menu .panel button {
    display: block;
    width: 100%;
    border: 0;
    box-shadow: none;
    border-radius: 8px;
    text-align: left;
    padding: 8px 10px;
  }
  .menu .panel button:hover { background: #f3eee4; }

  .clue-bar {
    position: sticky;
    top: 0;
    z-index: 30;
    display: flex;
    align-items: stretch;
    gap: 0;
    background: var(--bar);
    color: #fff;
    border-radius: 10px;
    overflow: hidden;
    min-height: 52px;
    box-shadow: 0 6px 16px rgba(28,25,23,.12);
    margin-bottom: 12px;
  }
  #btn-dir {
    flex: 0 0 auto;
    border: 0;
    background: #2d2926;
    color: #f3e2a0;
    font: 800 11px/1.1 var(--ui);
    letter-spacing: .08em;
    text-transform: uppercase;
    padding: 8px 12px;
    min-width: 64px;
    cursor: pointer;
  }
  #btn-dir:hover { background: #3a3531; }
  .clue-bar .clue-copy {
    flex: 1;
    padding: 8px 12px;
    font-size: 14px;
    line-height: 1.35;
    display: flex;
    align-items: center;
  }
  .clue-bar .clue-copy b { margin-right: 8px; font-variant-numeric: tabular-nums; }

  .play { display: block; }
  .board-wrap {
    display: flex;
    justify-content: center;
    width: 100%;
    margin: 0 auto 18px;
  }
  .board {
    --cell: min(40px, calc((100vw - 32px) / var(--cols)));
    display: grid;
    grid-template-columns: repeat(var(--cols), var(--cell));
    grid-template-rows: repeat(var(--rows), var(--cell));
    user-select: none;
    -webkit-user-select: none;
  }
  .cell {
    position: relative;
    background: transparent;
    pointer-events: none;
  }
  .cell.open {
    background: var(--cell-bg);
    box-shadow: inset 0 0 0 1px var(--line);
    pointer-events: auto;
    cursor: pointer;
    touch-action: manipulation;
  }
  .cell.open.black { background: #111; }
  .cell .num {
    position: absolute;
    top: 0px;
    left: 1px;
    font-size: max(9px, calc(var(--cell) * 0.32));
    font-weight: 700;
    line-height: 1;
    color: var(--ink);
    pointer-events: none;
    z-index: 1;
  }
  .cell .glyph {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    width: 100%;
    font-weight: 750;
    font-size: max(12px, calc(var(--cell) * 0.52));
    letter-spacing: 0;
    padding-top: 8%;
    pointer-events: none;
    text-transform: uppercase;
  }
  .cell.in-word { background: var(--word); }
  .cell.selected { background: var(--sel); z-index: 1; box-shadow: inset 0 0 0 2px var(--ink); }
  .cell.wrong { background: var(--wrong-bg); color: var(--wrong); }
  .cell.wrong.in-word { background: #f1c4a8; }
  .cell.wrong.selected { background: #e8b84a; }

  .clues {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px 32px;
  }
  .clues h2 {
    font-family: var(--serif);
    font-size: 1.05rem;
    letter-spacing: .06em;
    text-transform: uppercase;
    margin: 0 0 8px;
    padding-bottom: 4px;
    border-bottom: 2px solid var(--ink);
  }
  .clues ol { list-style: none; margin: 0; padding: 0; }
  .clues li {
    display: grid;
    grid-template-columns: 28px 1fr;
    gap: 6px;
    padding: 5px 6px;
    margin: 0 -6px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 14px;
    line-height: 1.35;
  }
  .clues li:hover { background: #ece5d6; }
  .clues li.active { background: var(--word); }
  .clues li .n { font-weight: 700; text-align: right; font-variant-numeric: tabular-nums; }
  .clues li.filled .t { opacity: .55; text-decoration: line-through; text-decoration-thickness: 1px; }

  #kb {
    position: fixed;
    left: 0;
    top: 0;
    width: 1px;
    height: 1px;
    opacity: 0;
    border: 0;
    padding: 0;
    margin: 0;
    font-size: 16px;
    background: transparent;
    color: transparent;
    caret-color: transparent;
    z-index: 50;
  }

  .modal {
    position: fixed;
    inset: 0;
    background: rgba(28,25,23,.45);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
    z-index: 80;
    opacity: 0;
    pointer-events: none;
    transition: opacity .25s ease;
  }
  .modal.show { opacity: 1; pointer-events: auto; }
  .modal .card {
    background: var(--paper);
    color: var(--ink);
    max-width: 420px;
    width: 100%;
    border-radius: 16px;
    padding: 32px 28px 24px;
    text-align: center;
    box-shadow: 0 20px 50px rgba(28,25,23,.28);
  }
  .modal .heart { color: var(--wine); font-size: 28px; margin-bottom: 8px; }
  .modal h2 {
    font-family: var(--serif);
    font-size: 1.8rem;
    margin: 0 0 8px;
  }
  .modal p { margin: 0 0 18px; color: var(--muted); font-family: var(--serif); font-style: italic; font-size: 1.05rem; }
  .modal button {
    appearance: none;
    border: 0;
    background: var(--wine);
    color: #fff;
    font: 600 14px var(--ui);
    padding: 10px 18px;
    border-radius: 999px;
    cursor: pointer;
  }

  @media (min-width: 900px) {
    .wrap { padding-top: 28px; }
    .play {
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 28px;
      align-items: start;
    }
    .board-wrap { margin-bottom: 0; }
    .board { --cell: min(38px, calc((48vw - 48px) / var(--cols)), calc((100dvh - 200px) / var(--rows))); }
  }
  @media (max-width: 640px) {
    .wrap { padding: 10px 10px 40px; }
    header.page-head { margin-bottom: 8px; }
    .clues { grid-template-columns: 1fr; gap: 16px; }
    .board { --cell: min(28px, calc((100vw - 20px) / var(--cols))); }
    .tools button, .tools summary { padding: 7px 10px; font-size: 12px; }
  }

  @media print {
    @page { margin: 0.5in; size: letter; }
    body { background: #fff !important; }
    .tools, .clue-bar, #kb, .modal, #btn-dir { display: none !important; }
    .wrap { max-width: none; padding: 0; }
    header.page-head { margin-bottom: 16px; }
    .cell .glyph { display: none !important; }
    .cell.in-word, .cell.selected, .cell.wrong { background: #fff !important; color: #000 !important; box-shadow: inset 0 0 0 1px #000 !important; }
    .clues li.active, .clues li:hover { background: transparent !important; }
    .clues li.filled .t { opacity: 1; text-decoration: none !important; }
    .play { display: block !important; }
    .board-wrap { margin-bottom: 22px; }
    .board { --cell: min(28px, calc((100vw - 1in) / var(--cols))); break-inside: avoid; }
    .clues { break-inside: avoid; }
  }
</style>
</head>
<body>
  <div class="wrap">
    <header class="page-head">
      <h1 id="title"></h1>
      <p class="sub" id="subtitle"></p>
    </header>
    <div class="tools">
      <button type="button" id="btn-check">Check</button>
      <details class="menu" id="menu-reveal">
        <summary>Reveal</summary>
        <div class="panel">
          <button type="button" id="btn-reveal-letter">Letter</button>
          <button type="button" id="btn-reveal-word">Word</button>
          <button type="button" id="btn-reveal-puzzle">Puzzle</button>
        </div>
      </details>
      <details class="menu" id="menu-clear">
        <summary>Clear</summary>
        <div class="panel">
          <button type="button" id="btn-clear-word">Word</button>
          <button type="button" id="btn-clear-puzzle">Puzzle</button>
        </div>
      </details>
      <button type="button" id="btn-print">Print</button>
      <span class="progress" id="progress"></span>
    </div>
    <div class="clue-bar" id="clue-bar">
      <button type="button" id="btn-dir" aria-label="Switch direction">Across</button>
      <div class="clue-copy" id="clue-copy">Tap a square to begin.</div>
    </div>
    <div class="play">
      <div class="board-wrap">
        <div class="board" id="board" aria-label="Crossword grid"></div>
      </div>
      <div class="clues" id="clues"></div>
    </div>
  </div>

  <input id="kb" type="text" inputmode="text" autocomplete="off" autocorrect="off"
    autocapitalize="characters" spellcheck="false" maxlength="1" aria-label="Type a letter">

  <div class="modal" id="win" role="dialog" aria-modal="true" aria-labelledby="win-title">
    <div class="card">
      <div class="heart">♥</div>
      <h2 id="win-title">You solved it!</h2>
      <p id="win-msg"></p>
      <button type="button" id="win-close">Close</button>
    </div>
  </div>

<script>
const P = __PUZZLE_JSON__;
(function () {
  const $ = (id) => document.getElementById(id);
  const boardEl = $("board");
  const kb = $("kb");
  const rows = P.rows, cols = P.cols;
  const words = P.words;
  const open = P.open;
  const nums = P.nums;
  const fill = Array.from({ length: rows }, () => Array(cols).fill(""));
  const wrong = Array.from({ length: rows }, () => Array(cols).fill(false));
  const cellEls = {};
  let cur = null; // { r, c, word }
  let celebrated = false;

  const decode = (w) => atob(w.a).toUpperCase();

  function wordsAt(r, c) {
    return words.filter((w) => w.cells.some(([rr, cc]) => rr === r && cc === c));
  }
  function wordIndex(w, r, c) {
    return w.cells.findIndex(([rr, cc]) => rr === r && cc === c);
  }
  function keyOf(r, c) { return r + "," + c; }

  function load() {
    try {
      const raw = localStorage.getItem(P.storageKey);
      if (!raw) return;
      const data = JSON.parse(raw);
      if (data && data.cells) {
        for (const [k, v] of Object.entries(data.cells)) {
          const [r, c] = k.split(",").map(Number);
          if (open[r] && open[r][c] && typeof v === "string") fill[r][c] = v.toUpperCase().replace(/[^A-Z]/g, "").slice(0, 1);
        }
      }
    } catch (e) { /* private mode etc. */ }
  }
  function save() {
    try {
      const cells = {};
      for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
          if (fill[r][c]) cells[keyOf(r, c)] = fill[r][c];
        }
      }
      localStorage.setItem(P.storageKey, JSON.stringify({ cells }));
    } catch (e) { /* ignore */ }
  }

  function isSolved() {
    for (const w of words) {
      const ans = decode(w);
      for (let i = 0; i < w.cells.length; i++) {
        const [r, c] = w.cells[i];
        if (fill[r][c] !== ans[i]) return false;
      }
    }
    return true;
  }
  function filledCount() {
    let n = 0, t = 0;
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        if (!open[r][c]) continue;
        t++;
        if (fill[r][c]) n++;
      }
    }
    return [n, t];
  }
  function wordComplete(w) {
    return w.cells.every(([r, c]) => fill[r][c]);
  }

  function renderCell(r, c) {
    const el = cellEls[keyOf(r, c)];
    if (!el || !open[r][c]) return;
    el.classList.toggle("in-word", !!(cur && cur.word.cells.some(([rr, cc]) => rr === r && cc === c)));
    el.classList.toggle("selected", !!(cur && cur.r === r && cur.c === c));
    el.classList.toggle("wrong", wrong[r][c]);
    el.querySelector(".glyph").textContent = fill[r][c] || "";
  }
  function renderAll() {
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) renderCell(r, c);
    }
    // clues
    document.querySelectorAll(".clues li").forEach((li) => {
      const w = words.find((x) => x.id === li.dataset.id);
      li.classList.toggle("active", !!(cur && cur.word.id === li.dataset.id));
      li.classList.toggle("filled", !!(w && wordComplete(w)));
    });
    const [n, t] = filledCount();
    const pg = $("progress");
    if (isSolved()) {
      pg.textContent = "Solved!";
      pg.classList.add("done");
    } else {
      pg.textContent = n + " / " + t;
      pg.classList.remove("done");
    }
    updateClueBar();
  }

  function updateClueBar() {
    const copy = $("clue-copy");
    const dirBtn = $("btn-dir");
    if (!cur) {
      copy.textContent = "Tap a square to begin.";
      dirBtn.textContent = "Across";
      return;
    }
    dirBtn.textContent = cur.word.dir === "across" ? "Across" : "Down";
    copy.innerHTML = "<b>" + cur.word.num + (cur.word.dir === "across" ? "A" : "D") + "</b> " + escapeHtml(cur.word.clue);
  }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (ch) => ({ "&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;" }[ch]));
  }

  function placeKb() {
    if (!cur) return;
    const el = cellEls[keyOf(cur.r, cur.c)];
    if (!el) return;
    const rec = el.getBoundingClientRect();
    kb.style.left = rec.left + "px";
    kb.style.top = rec.top + "px";
    kb.style.width = Math.max(rec.width, 8) + "px";
    kb.style.height = Math.max(rec.height, 8) + "px";
  }
  function focusKb() {
    placeKb();
    try { kb.focus({ preventScroll: true }); } catch (e) { kb.focus(); }
    try { kb.setSelectionRange(0, kb.value.length); } catch (e) {}
  }

  function selectCell(r, c, dir) {
    if (!open[r] || !open[r][c]) return;
    const here = wordsAt(r, c);
    if (!here.length) return;
    let w = dir ? here.find((x) => x.dir === dir) : null;
    if (!w) w = here[0];
    cur = { r, c, word: w };
    renderAll();
    placeKb();
    const el = cellEls[keyOf(r, c)];
    if (el) {
      const rec = el.getBoundingClientRect();
      const bar = $("clue-bar").getBoundingClientRect();
      if (rec.top < bar.bottom + 8 || rec.bottom > window.innerHeight - 8) {
        el.scrollIntoView({ block: "center", inline: "nearest", behavior: "smooth" });
      }
    }
  }

  function toggleDir() {
    if (!cur) return;
    const here = wordsAt(cur.r, cur.c);
    const other = here.find((w) => w.id !== cur.word.id);
    if (other) selectCell(cur.r, cur.c, other.dir);
    focusKb();
  }

  function typeLetter(ch) {
    if (!cur) return;
    ch = ch.toUpperCase();
    if (!/^[A-Z]$/.test(ch)) return;
    fill[cur.r][cur.c] = ch;
    wrong[cur.r][cur.c] = false;
    save();
    const idx = wordIndex(cur.word, cur.r, cur.c);
    if (idx < cur.word.cells.length - 1) {
      const [nr, nc] = cur.word.cells[idx + 1];
      selectCell(nr, nc, cur.word.dir);
    } else {
      // jump to next unfilled cell in this word, else next word
      const empty = cur.word.cells.find(([r, c]) => !fill[r][c]);
      if (empty) selectCell(empty[0], empty[1], cur.word.dir);
      else {
        renderAll();
        maybeWin();
      }
    }
    focusKb();
    maybeWin();
  }

  function backspace() {
    if (!cur) return;
    if (fill[cur.r][cur.c]) {
      fill[cur.r][cur.c] = "";
      wrong[cur.r][cur.c] = false;
      save();
      renderAll();
      focusKb();
      return;
    }
    const idx = wordIndex(cur.word, cur.r, cur.c);
    if (idx > 0) {
      const [nr, nc] = cur.word.cells[idx - 1];
      fill[nr][nc] = "";
      wrong[nr][nc] = false;
      save();
      selectCell(nr, nc, cur.word.dir);
    } else {
      renderAll();
    }
    focusKb();
  }

  function move(dr, dc) {
    if (!cur) return;
    if (dr === 0 && dc !== 0) {
      if (cur.word.dir !== "across") {
        const across = wordsAt(cur.r, cur.c).find((w) => w.dir === "across");
        if (across) { selectCell(cur.r, cur.c, "across"); focusKb(); return; }
      }
    }
    if (dc === 0 && dr !== 0) {
      if (cur.word.dir !== "down") {
        const down = wordsAt(cur.r, cur.c).find((w) => w.dir === "down");
        if (down) { selectCell(cur.r, cur.c, "down"); focusKb(); return; }
      }
    }
    let r = cur.r + dr, c = cur.c + dc;
    while (r >= 0 && r < rows && c >= 0 && c < cols) {
      if (open[r][c]) {
        const prefer = (dc !== 0) ? "across" : (dr !== 0) ? "down" : cur.word.dir;
        selectCell(r, c, prefer);
        focusKb();
        return;
      }
      r += dr; c += dc;
    }
    focusKb();
  }

  function maybeWin() {
    if (!isSolved()) return;
    renderAll();
    if (celebrated) return;
    celebrated = true;
    $("win").classList.add("show");
  }

  function check() {
    for (const w of words) {
      const ans = decode(w);
      for (let i = 0; i < w.cells.length; i++) {
        const [r, c] = w.cells[i];
        if (fill[r][c] && fill[r][c] !== ans[i]) wrong[r][c] = true;
        else if (fill[r][c] === ans[i]) wrong[r][c] = false;
      }
    }
    renderAll();
    maybeWin();
    focusKb();
  }

  function revealLetter() {
    if (!cur) return;
    const w = cur.word;
    const i = wordIndex(w, cur.r, cur.c);
    fill[cur.r][cur.c] = decode(w)[i];
    wrong[cur.r][cur.c] = false;
    save();
    renderAll();
    maybeWin();
    focusKb();
  }
  function revealWord() {
    if (!cur) return;
    const w = cur.word, ans = decode(w);
    w.cells.forEach(([r, c], i) => { fill[r][c] = ans[i]; wrong[r][c] = false; });
    save();
    renderAll();
    maybeWin();
    focusKb();
  }
  function revealPuzzle() {
    if (!confirm("Reveal the whole puzzle?")) return;
    for (const w of words) {
      const ans = decode(w);
      w.cells.forEach(([r, c], i) => { fill[r][c] = ans[i]; wrong[r][c] = false; });
    }
    save();
    renderAll();
    maybeWin();
  }
  function clearWord() {
    if (!cur) return;
    cur.word.cells.forEach(([r, c]) => { fill[r][c] = ""; wrong[r][c] = false; });
    save();
    renderAll();
    focusKb();
  }
  function clearPuzzle() {
    if (!confirm("Clear the whole puzzle?")) return;
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) { fill[r][c] = ""; wrong[r][c] = false; }
    }
    celebrated = false;
    save();
    renderAll();
    focusKb();
  }

  function onKey(e) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const k = e.key;
    if (k === "Backspace") { e.preventDefault(); backspace(); }
    else if (k === "ArrowLeft") { e.preventDefault(); move(0, -1); }
    else if (k === "ArrowRight") { e.preventDefault(); move(0, 1); }
    else if (k === "ArrowUp") { e.preventDefault(); move(-1, 0); }
    else if (k === "ArrowDown") { e.preventDefault(); move(1, 0); }
    else if (k === " " || k === "Enter") { e.preventDefault(); toggleDir(); }
    else if (k === "Tab") {
      e.preventDefault();
      const list = words.filter((w) => w.dir === (cur ? cur.word.dir : "across"));
      if (!list.length) return;
      const i = cur ? list.findIndex((w) => w.id === cur.word.id) : -1;
      const next = list[(i + (e.shiftKey ? list.length - 1 : 1)) % list.length];
      const empty = next.cells.find(([r, c]) => !fill[r][c]) || next.cells[0];
      selectCell(empty[0], empty[1], next.dir);
      focusKb();
    } else if (k.length === 1 && /[a-zA-Z]/.test(k)) {
      e.preventDefault();
      typeLetter(k);
    }
  }

  // Build board
  boardEl.style.setProperty("--rows", rows);
  boardEl.style.setProperty("--cols", cols);
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const el = document.createElement("div");
      el.className = "cell" + (open[r][c] ? " open" : (P.black ? " open black" : ""));
      el.dataset.r = r;
      el.dataset.c = c;
      const nk = keyOf(r, c);
      if (nums[nk]) {
        const n = document.createElement("span");
        n.className = "num";
        n.textContent = nums[nk];
        el.appendChild(n);
      }
      const g = document.createElement("span");
      g.className = "glyph";
      el.appendChild(g);
      if (open[r][c]) {
        el.addEventListener("pointerdown", () => {
          // Focus inside the same user gesture so iOS/Android open the keyboard.
          try { kb.focus({ preventScroll: true }); } catch (e) { kb.focus(); }
          const here = wordsAt(r, c);
          if (cur && cur.r === r && cur.c === c && here.length > 1) {
            toggleDir();
          } else {
            const prefer = cur && here.find((w) => w.dir === cur.word.dir);
            selectCell(r, c, (prefer || here[0]).dir);
            focusKb();
          }
        });
      }
      boardEl.appendChild(el);
      cellEls[nk] = el;
    }
  }

  // Clue lists
  const cluesRoot = $("clues");
  function makeList(title, dir) {
    const sec = document.createElement("section");
    const h = document.createElement("h2");
    h.textContent = title;
    sec.appendChild(h);
    const ol = document.createElement("ol");
    words.filter((w) => w.dir === dir).forEach((w) => {
      const li = document.createElement("li");
      li.dataset.id = w.id;
      li.innerHTML = "<span class=\"n\">" + w.num + "</span><span class=\"t\"></span>";
      li.querySelector(".t").textContent = w.clue;
      li.addEventListener("click", () => {
        const empty = w.cells.find(([r, c]) => !fill[r][c]) || w.cells[0];
        selectCell(empty[0], empty[1], w.dir);
        focusKb();
      });
      ol.appendChild(li);
    });
    sec.appendChild(ol);
    cluesRoot.appendChild(sec);
  }
  makeList("Across", "across");
  makeList("Down", "down");

  $("title").textContent = P.title;
  $("subtitle").textContent = P.subtitle || "";
  $("subtitle").style.display = P.subtitle ? "" : "none";
  $("win-msg").textContent = P.subtitle ? P.subtitle : "Every word in its place.";

  load();
  renderAll();
  // Start on the first across clue
  if (words.length) {
    const first = words.find((w) => w.dir === "across") || words[0];
    selectCell(first.cells[0][0], first.cells[0][1], first.dir);
  }

  kb.addEventListener("keydown", onKey);
  document.addEventListener("keydown", (e) => {
    const tag = (e.target && e.target.tagName) || "";
    if (e.target === kb) return;
    if (tag === "INPUT" || tag === "TEXTAREA") return;
    onKey(e);
  });
  kb.addEventListener("input", () => {
    const v = (kb.value || "").toUpperCase().replace(/[^A-Z]/g, "");
    kb.value = "";
    if (v) typeLetter(v.slice(-1));
  });
  kb.addEventListener("compositionend", () => {
    const v = (kb.value || "").toUpperCase().replace(/[^A-Z]/g, "");
    kb.value = "";
    if (v) typeLetter(v.slice(-1));
  });

  $("btn-dir").addEventListener("click", (e) => { e.preventDefault(); toggleDir(); });
  $("btn-check").addEventListener("click", check);
  $("btn-reveal-letter").addEventListener("click", () => { closeMenus(); revealLetter(); });
  $("btn-reveal-word").addEventListener("click", () => { closeMenus(); revealWord(); });
  $("btn-reveal-puzzle").addEventListener("click", () => { closeMenus(); revealPuzzle(); });
  $("btn-clear-word").addEventListener("click", () => { closeMenus(); clearWord(); });
  $("btn-clear-puzzle").addEventListener("click", () => { closeMenus(); clearPuzzle(); });
  $("btn-print").addEventListener("click", () => window.print());
  $("win-close").addEventListener("click", () => $("win").classList.remove("show"));
  $("win").addEventListener("click", (e) => { if (e.target.id === "win") $("win").classList.remove("show"); });

  function closeMenus() {
    document.querySelectorAll("details.menu").forEach((d) => { d.open = false; });
  }
  document.addEventListener("click", (e) => {
    document.querySelectorAll("details.menu").forEach((d) => {
      if (!d.contains(e.target)) d.open = false;
    });
  });
  window.addEventListener("resize", placeKb);
  window.addEventListener("scroll", placeKb, { passive: true });

  // If a previously saved puzzle is already complete, mark it solved quietly
  if (isSolved()) {
    celebrated = true;
    $("progress").textContent = "Solved!";
    $("progress").classList.add("done");
  }
})();
</script>
</body>
</html>
"""


def make_html(path, grid, numbers, across, down):
    """Write a single self-contained HTML page for the same layout as the PDF."""
    rows, cols = len(grid), len(grid[0])
    pos_by_num = {n: (r, c) for (r, c), n in numbers.items()}

    def walk(r, c, direction):
        cells, letters = [], []
        dr, dc = (0, 1) if direction == "across" else (1, 0)
        while 0 <= r < rows and 0 <= c < cols and grid[r][c] is not None:
            cells.append([r, c])
            letters.append(grid[r][c])
            r, c = r + dr, c + dc
        return cells, "".join(letters)

    words = []
    for direction, clues in (("across", across), ("down", down)):
        for n, e in clues:
            r, c = pos_by_num[n]
            cells, letters = walk(r, c, direction)
            words.append({
                "id": f"{direction[0].upper()}{n}",
                "dir": direction,
                "num": n,
                "clue": e.clue_text(),
                "cells": cells,
                "a": base64.b64encode(letters.encode("ascii")).decode("ascii"),
            })

    # A short, stable key so different puzzles don't overwrite each other,
    # without putting the raw answers in the page as plain text.
    fingerprint = base64.b64encode(
        (TITLE + "|" + "|".join(w["a"] for w in words)).encode("utf-8")
    ).decode("ascii")[:24]
    data = {
        "title": TITLE,
        "subtitle": SUBTITLE,
        "rows": rows,
        "cols": cols,
        "black": bool(SHOW_BLACK_SQUARES),
        "open": [[ch is not None for ch in row] for row in grid],
        "nums": {f"{r},{c}": n for (r, c), n in numbers.items()},
        "words": words,
        "storageKey": "cw:" + fingerprint,
    }
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e")
    page = (
        HTML_TEMPLATE
        .replace("__TITLE_ESC__", html_lib.escape(TITLE, quote=True))
        .replace("__PUZZLE_JSON__", payload)
    )
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="Make a printable custom crossword PDF and a playable HTML page."
    )
    ap.add_argument("--seed", type=int, default=None, help="random seed for a repeatable layout")
    ap.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS, help="layouts to try")
    ap.add_argument("--out", default=DEFAULT_OUTPUT, help="output PDF path")
    ap.add_argument("--html", default=DEFAULT_HTML, help="playable HTML page path")
    ap.add_argument("--no-html", action="store_true", help="do not write the HTML page")
    args = ap.parse_args()

    entries, seen = [], set()
    for ans, clue in WORDS:
        e = Entry(ans, clue)
        if len(e.word) < 2:
            print(f"Skipping '{ans}': answers need at least 2 letters.")
        elif e.word in seen:
            print(f"Skipping duplicate answer '{ans}'.")
        else:
            seen.add(e.word)
            entries.append(e)
    if not entries:
        sys.exit("No usable words in WORDS - add some (ANSWER, CLUE) pairs.")

    seed = args.seed if args.seed is not None else random.randrange(10**6)
    lay, left = best_layout(entries, max(1, args.attempts), seed)
    grid, numbers, across, down = number_grid(lay)
    make_pdf(args.out, grid, numbers, across, down)
    print(f"Saved {args.out}")
    if not args.no_html:
        make_html(args.html, grid, numbers, across, down)
        print(f"Saved {args.html}")
    print(f"  grid {len(grid[0])} x {len(grid)}, {len(lay.placed)}/{len(entries)} words placed, "
          f"{lay.intersections} crossings, seed {seed} (use --seed {seed} to recreate)")
    if left:
        print("  Could NOT fit these words (try more --attempts, another --seed, or add "
              "words sharing their letters):")
        for e in left:
            print(f"    - {e.raw}")


if __name__ == "__main__":
    main()
