#!/usr/bin/env python3
"""
crossword_maker.py - build a printable, personalized crossword puzzle.

QUICK START
    1. pip install reportlab        (Mac/Linux may need: pip3 install reportlab)
    2. Edit the CONFIG section just below: title, dedication, answers & clues.
    3. python3 crossword_maker.py   ->  writes crossword.pdf (puzzle + answer key)

Optional flags:
    --seed 42          make the layout reproducible (same seed = same puzzle)
    --attempts 3000    try more random layouts (slower, often tighter grids)
    --out mom.pdf      choose the output file name

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

# =============================================================================
# ========================  END OF CONFIG - CODE BELOW  =======================
# =============================================================================

import argparse
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
# Main
# -----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Make a printable custom crossword PDF.")
    ap.add_argument("--seed", type=int, default=None, help="random seed for a repeatable layout")
    ap.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS, help="layouts to try")
    ap.add_argument("--out", default=DEFAULT_OUTPUT, help="output PDF path")
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
    print(f"  grid {len(grid[0])} x {len(grid)}, {len(lay.placed)}/{len(entries)} words placed, "
          f"{lay.intersections} crossings, seed {seed} (use --seed {seed} to recreate)")
    if left:
        print("  Could NOT fit these words (try more --attempts, another --seed, or add "
              "words sharing their letters):")
        for e in left:
            print(f"    - {e.raw}")


if __name__ == "__main__":
    main()
