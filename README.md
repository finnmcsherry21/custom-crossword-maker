# Custom Crossword Maker

Make personalized, printable crosswords — for example, a puzzle all about a family member's life. You type in your answers and clues; the script figures out how the words cross, numbers the grid, and writes a letter-size PDF (puzzle + answer key) plus a playable web page you can fill in on a phone or computer.

![Sample puzzle](docs/preview.png)

A hosted playable version of the current puzzle is at [finnmcsherry21.github.io/custom-crossword-maker](https://finnmcsherry21.github.io/custom-crossword-maker/).

## Setup

```bash
pip install -r requirements.txt
```

(On some Linux setups: `pip install --break-system-packages reportlab`.)

## Usage

1. Open `crossword_maker.py` and edit the config at the top:
   - `TITLE` and `SUBTITLE` (a dedication line)
   - `WORDS`: a list of `(ANSWER, CLUE)` pairs, e.g. `("SAN LUIS OBISPO", "City where Mom went to college")`. Spaces and punctuation are stripped for the grid, and clues show word lengths like `(3,4,6)`.
2. Run:

```bash
python3 crossword_maker.py
```

This writes:

- `crossword.pdf` — the printable puzzle, then the answer key
- `docs/index.html` — a self-contained page you can open in a browser or host on GitHub Pages (from the `/docs` folder). Tap or click a square, type to fill, Check to mark mistakes, and Reveal or Clear a letter, word, or the whole puzzle. Progress is saved in the browser. The Print button prints a blank puzzle with its clues.

### Options

| Flag | What it does |
| --- | --- |
| `--seed 42` | Reproduce the same layout every time |
| `--attempts 3000` | Search harder for a tighter grid |
| `--out mom.pdf` | Choose the output PDF file name |
| `--html puzzle.html` | Choose the output HTML file name |
| `--no-html` | Skip writing the playable HTML page |

### Settings (top of the script)

- `SHOW_WORD_LENGTHS` — show `(3,4,6)` after clues
- `SHOW_BLACK_SQUARES` — fill empty cells black (off = only letter boxes drawn)
- `INCLUDE_ANSWER_KEY` — add the answer key page to the PDF
- `DEFAULT_ATTEMPTS`, `DEFAULT_OUTPUT`, `DEFAULT_HTML`

## Tips

- 10–25 words that share common letters fit best.
- If a word can't be placed, the script tells you; rerun or try a different `--seed`.
- The PDF and the website always use the same layout from that run.
