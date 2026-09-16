# redpen

Define the answer zones once on a quiz template, split a bulk scan into
per-student PDFs — names read automatically and matched to your class list —
then grade in the browser.

**Everything runs on your machine.** poppler renders the PDFs, Apple's Vision
framework reads the handwriting on-device, the editors are served only on
`127.0.0.1`, and the grading page is a local HTML file. No student work is
uploaded anywhere, and no language model is involved at any step.

## Install

```bash
brew install poppler                 # pdftoppm, pdfinfo, pdfseparate, pdfunite
pip install -e .                     # or: pip install Pillow && python3 -m redpen
```

Xcode command line tools supply `swiftc`, used once to compile the Vision
helper. Without it redpen falls back to tesseract, which is much weaker on
handwriting.

## Use

```bash
redpen init  quiz.json --template blank-quiz.pdf --roster roster.csv
redpen zones quiz.json                      # drag zones, set the rubric
redpen run   quiz.json --scan bulk.pdf      # split, OCR names, match roster
redpen verify quiz.json                     # confirm who each sheet belongs to
redpen autograde quiz.json                  # optional: preliminary right/wrong
redpen grade quiz.json                      # grade
```

| command | what it does |
|---|---|
| `init` | create a config from the template PDF and roster |
| `zones` | local browser UI: drag zones, name them, set points |
| `run` | split scans, OCR names, match the roster, cut every zone |
| `verify` | confirm or correct who each sheet belongs to |
| `readkey` | read expected answers off an answer-key PDF |
| `autograde` | OCR the answers and mark each part right / wrong / unsure |
| `recrop` | re-cut zones after a tweak, keeping the names already matched |
| `grade` | build the grading page |
| `check` | summarise the config |
| `clean` | drop cached page renders |
| `stats` | statistics and a grade-distribution histogram from an export |

## Use the blank quiz as the template, not the answer key

Zones are page coordinates, so the template must be the document the students
actually wrote on. An answer key with worked solutions printed on it pushes the
layout down — on the quiz this was built for, the key's boxes sit **0.0155 of
the page height (~34 px at 200 dpi) lower** than the students' sheets, enough to
slice every crop in half. The blank quiz matched the scans to within 0.001.

Nothing will warn you. If crops look shifted, this is why.

## How names are identified

1. The name zone is rendered at `ocr_dpi` (400) and read by Vision, seeded with
   every roster name as `customWords`.
2. Each reading is scored against every roster entry — both name orders, plus
   surname-only matching.
3. The sheet → student mapping is solved as an **assignment problem**: each
   student sits at most one sheet, so once the confident sheets claim their
   names the ambiguous ones have only one plausible home. This is what lifts
   mediocre readings to the right answer — a badly-read sheet still
   lands on the one student nobody else claimed.
4. Anything with a weak score or a thin margin over the runner-up goes to
   `needs_review/` with the reason recorded, and is settled in `verify`.

On a 38-sheet class this gave **38/38 correct**, with two sheets flagged (two
students who share a first name). Both flagged sheets were in fact right — the flag is
caution, not error.

## Preliminary right/wrong

`readkey` lifts the expected answers off an answer key. Because the key's boxes
do not sit where the blank's do, rules are detected on both documents, paired
down the page, and a piecewise-linear map carries each zone across.

`autograde` then reads every student's answer boxes:

- **green** — matches the key; the part is scored **full**
- **red** — clearly a different number; scored **zero**
- **amber** — could not be read confidently; **left at full**, for you to check

The comparison is deliberately shy. Vision renders a trailing unit `s` as `5`
("15 s" comes back "155"), so the expected unit is used to undo exactly that;
anything else that merely resembles the right answer returns amber rather than
red, because a wrongly-green box inflates a grade while a wrongly-amber one only
costs a glance.

Answer key format in `parts[].key`:

```
" / "   (with the spaces) separates the boxes of a multi-box part
" | "   separates acceptable alternatives for one box
```

```json
{ "id": "3a", "key": "80.0 m/s / 400 m", "points": 10 }
{ "id": "3b", "key": "720 m | 726.53 m", "points": 8  }
{ "id": "3d", "key": "...", "points": 14, "auto": false }
```

The spaces around `/` matter — a bare slash also lives inside `m/s`. Set
`"auto": false` on anything OCR should not judge, such as a sketch.

## Statistics and the distribution

```bash
redpen stats grades.csv                       # 10 bins over 0 … paper total
redpen stats grades.csv --nbins 20
redpen stats grades.csv --min 50 --max 100 --nbins 10
redpen stats grades.csv --width 5 --min 60    # 5-point bins; --width overrides --nbins
redpen stats grades.csv --part "sketch"       # one part instead of the total
redpen stats grades.csv --html report.html    # also write a page
```

Prints n, mean, median, standard deviation, min, max and the quartiles, then an
ASCII histogram, then a per-part table sorted by mean percentage — the quickest
way to see which question actually hurt.

Binning is `--nbins` (default 10) between `--min` (default 0) and `--max`
(default the paper's total), or give `--width` for a fixed bin size and the bin
count follows. The top edge belongs to the last bin, so full marks are counted.
Narrowing the range does not silently drop anyone: values outside it are
reported as "N below range, M above".

`--only-reviewed` ignores sheets you have not yet worked through, which is what
you want for a mid-marking sanity check.

## Config

Plain JSON, safe to hand-edit; see [`example/quiz.example.json`](example/quiz.example.json).
Rectangles are fractions of the page (`[x, y, w, h]`, origin top-left), so they
stay valid at any DPI.

**Zones are geometry; parts are grading.** A zone says where to cut, a part says
what it is worth. Listing two zones in one part grades them as a single item.

## Output

```
students/
  Doe_Jane.pdf              the student's pages, extracted losslessly
  Doe_Jane/
    name.png  1a.png … 3d.png  one PNG per zone
    page1.png page2.png        full pages, for the grading page's full-screen view
needs_review/                  same shape, for flagged sheets
split_report.csv               sheet, source, pages, name, id, OCR text, score, gap, flags
```

## The grading page

One student per screen — `Previous`/`Next`, `j`/`k`, or the sidebar list.

- `−` / `+`, a typed value (halves allowed), and `0` / half / `full` chips
- A coloured dot per part shows the OCR verdict and the text it read
- **Full-screen viewer**: click any crop; scroll or `+`/`−` to zoom, drag to pan,
  `←`/`→` between zones, `0` to fit, `Esc` to close
- **`f`** opens the whole page; a link opens the student's own PDF
- Name and ID editable with roster autocomplete, beside the name crop
- **Export CSV**, and **Save/Load progress** as JSON

Progress autosaves to browser storage keyed by the quiz title, and can also be
written to a file. Save progress before moving or regenerating the page.

The page references images by relative path, so keep it next to `students/`.

## Notes

- Page renders cache under `.redpen_cache/`; `clean` clears it.
- A full `run` over 38 two-page sheets takes about 75 s; `recrop` about 7 s.
- `run` refuses a scan whose page count is not a multiple of
  `pages_per_student` — usually a mis-fed sheet.
- Pass `--scan a.pdf --scan b.pdf` for several scans. A student appearing twice
  is flagged rather than silently overwritten.

## Licence

MIT.
