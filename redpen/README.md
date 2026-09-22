# redpen

Define the answer zones once on a quiz template, split a bulk scan into
per-student PDFs — names read automatically and matched to your class list —
then grade in the browser.

**Everything runs on your machine.** poppler renders the PDFs, Apple's Vision
framework reads the handwriting on-device, the editors are served only on
`127.0.0.1`, and the grading page is a local HTML file. No student work is
uploaded anywhere, and no language model is involved at any step.

## The app

```bash
./mac/build_app.sh            # -> mac/dist/redpen.app
./mac/build_app.sh --dmg      # -> also a disk image to hand someone
```

One window over the whole term: the quizzes down the side, the step you are on
beside them — compose, build, zones, scan, verify, grade. The composer is the
same page `redpen compose` serves; the zone editor and the verifier are the
same pages too, unchanged.

**Nothing has to be installed to run it.** Python, Pillow, numpy, typst,
poppler and the on-device Vision helper are all inside the bundle, about 81 MB
of it. The build refuses to finish unless every bundled tool runs with
`PATH=/usr/bin:/bin`, so "it works on my machine because I have Homebrew"
cannot pass unnoticed.

The app finds quizzes in folders you point it at — **Folders** in the sidebar.
Your files stay where they are, in OneDrive or wherever you keep them, and the
command line goes on working on exactly the same paths. Nothing is imported and
there is no second copy.

It is ad-hoc signed, not notarized, so the first launch on a **new** Mac needs
right-click → **Open** → **Open** (once). `mac/dist/README-install.txt` says so
for whoever you give it to.

Building it needs the things it bundles: the Xcode command line tools for
`swiftc`, plus `typst`, `poppler` and `pyinstaller`. Running it needs none of
them.

## Install

```bash
brew install poppler                 # pdftoppm, pdfinfo, pdfseparate, pdfunite
brew install typst                   # only to write quizzes; not needed to grade
pip install -e .                     # or: pip install Pillow && python3 -m redpen
```

Xcode command line tools supply `swiftc`, used once to compile the Vision
helper. Without it redpen falls back to tesseract, which is much weaker on
handwriting.

## Use

```bash
redpen app                                  # everything in one window
redpen new     quiz.src.json                # start a quiz
redpen compose quiz.src.json                # write it in a form, live preview
redpen build   quiz.src.json                # -> quiz.pdf, key.pdf, zones, rubric
redpen init  quiz.json --template blank-quiz.pdf --roster roster.csv
redpen zones quiz.json                      # drag zones, set the rubric
redpen run   quiz.json --scan bulk.pdf      # split, OCR names, match roster
redpen verify quiz.json                     # confirm who each sheet belongs to
redpen autograde quiz.json                  # optional: preliminary right/wrong
redpen grade quiz.json                      # grade
redpen canvas quiz.json grades.csv          # CSV for the Canvas gradebook
```

| command | what it does |
|---|---|
| `new` | start a quiz source file |
| `compose` | local browser UI: write the quiz in a form, with a live preview |
| `build` | compile a quiz source into the quiz, the answer key, the zones and the rubric |
| `init` | create a config from the template PDF and roster |
| `zones` | local browser UI: drag zones, name them, set points |
| `run` | split scans, OCR names, match the roster, cut every zone |
| `verify` | confirm or correct who each sheet belongs to |
| `readkey` | read expected answers off an answer-key PDF |
| `autograde` | OCR the answers and mark each part right / wrong / unsure |
| `recrop` | re-cut zones after a tweak, keeping the names already matched |
| `grade` | build the grading page |
| `canvas` | turn an export into a CSV the Canvas gradebook will import |
| `app` | the whole workflow in one window |
| `check` | summarise the config |
| `clean` | drop cached page renders |
| `stats` | statistics and a grade-distribution histogram from an export |

## Writing the quiz

A quiz can be written instead of drawn. `quiz.src.json` holds the questions,
the answers and the marks; `redpen build` turns it into four things that
cannot disagree with each other:

```
quiz.src.json  ──►  quiz.typ      ──►  quiz.pdf        the blank students write on
               ──►  quiz-key.typ  ──►  quiz-key.pdf    the same paper, answers in red
               ──►  quiz.json                          zones, rubric and answer key
```

Each answer box reports its own rectangle during the compile, so the zones are
the geometry Typst laid out rather than a rectangle someone dragged over a
picture of it. Two consequences worth having:

- **`zones` and `readkey` are not steps.** The rectangles come out of the
  build, and the expected answers were typed in, so there is nothing to draw
  and nothing to read back off a PDF.
- **The key cannot drift.** Worked solutions are placed out of the flow, so the
  key's boxes land on exactly the same coordinates as the blank's. `build`
  checks it every time and says so:

  ```
  key layout identical to the blank across 14 zones
  all 10 worked solutions fit their writing room
  ```

  A solution too long for the room it was given is reported, not silently
  overprinted:

  ```
  warning: the solution for 1a runs 0.30 in past the next sub-part —
    give that sub-part more room, or shorten the working
  ```

### The composer

```bash
redpen compose quiz.src.json
```

Three columns: the outline on the left, the questions in the middle, the paper
on the right.

- **Outline** — every problem and sub-part with its marks, and a running total
  against a target, so a rubric that does not add up shows while it is being
  written rather than when the marking is done. Click to jump; `+ Add problem`.
- **The form** — a card per problem: title, marks, which page, the stem, then a
  block per sub-part with its question, its answer boxes and its worked
  solution. Add, delete and reorder sub-parts and boxes. Marks left blank are
  split across the sub-parts by box count.
- **The paper** — the compiled PDF, refreshed about half a second after you
  stop typing. **Quiz** and **Key** are the two documents; **Zones** draws
  every harvested rectangle over the page, so you can see exactly what will be
  cut out of a student's scan while you are still writing the question.

The source is saved on every pause, with one `.bak` of what was there when the
session opened. Typing builds only into a cache directory; the **Build** button
is what writes the PDFs you hand out and the grading config.

A mistake is reported rather than thrown: an unbalanced bracket names the
sub-part it is in, and a Typst error comes back as the compiler wrote it.

### The source

```jsonc
{
  "title": "PHY2060 Quiz 1 — Constant Acceleration",
  "pages": 2,
  "note": "Use $g = 10 thin \"m/s\"^2$. *Include units on every answer.*",
  "problems": [{
    "title": "Braking train", "points": 25, "page": 1,
    "stem": "A train moving at 30 m/s brakes uniformly at 2.0 #mss until it stops.",
    "parts": [{
      "question": "Find the time it takes to stop.",
      "boxes": [{ "label": "time", "answer": "15.0 s" }],
      "solution": ["$v = v_0 + a t quad ==> quad t = 15.0 thin \"s\"$"]
    }]
  }]
}
```

Every text field is Typst markup — `$maths$`, `*bold*`, `_italic_` — so there
is no ceiling on what a question can say. `#ieq("spoken reading", $x$)` adds
the screen-reader alt text, and `#mss` is the unit that appears on every other
line.

- **`boxes`** — one per quantity asked for. `label` names it in the margin,
  `answer` is printed in red on the key. `key` overrides what OCR compares
  against, for an answer whose printed form is maths: `"answer": "$times 4$"`
  with `"key": "4"`. `alt` lists other acceptable readings.
- **`kind: "sketch"`** — a tall box beside the question, marked `auto: false`
  so OCR is never given a vote on it.
- **`solution`** — the worked steps, one per line, red on the key only.
- **`points`** — per problem, split across its sub-parts by box count, or set
  per sub-part. The parts of a quiz always add up to the quiz.
- **`preamble`** — verbatim Typst, for a figure a form has no business holding:
  the `vt-graph` in `example/constant-acceleration.src.json` is a drawn
  velocity-time sketch dropped into an answer box as `"raw": "#vt-graph(6.6cm, 4.6cm)"`.

Writing room is shared out between sub-parts in proportion to their marks, so
there are no measured constants to maintain: move a problem to another page
with `"page": 2` and the rest reflow.

`build` rewrites only what the source decides — the zones, the rubric, the
template and the page count. The roster, the Canvas assignment and its codes,
the DPIs and the review thresholds are settings of the *marking* and are kept.

A worked example, the quiz this was built against, is in
[`example/constant-acceleration.src.json`](example/constant-acceleration.src.json).

## Use the blank quiz as the template, not the answer key

This applies to quizzes whose zones you draw by hand. A quiz built from a
source has its zones taken from the blank's own compile, so it cannot happen.

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

## Uploading to Canvas

The grading page's **Canvas CSV** button writes the upload straight from the
browser; `redpen canvas` does the same from an already-exported CSV:

```bash
redpen canvas quiz.json --list                            # what codes exist
redpen canvas quiz.json grades.csv --assignment "Quiz 1"  # -> grades_canvas.csv
redpen canvas quiz.json grades.csv --out-of 20            # scale 100 -> 20
redpen canvas quiz.json grades.csv --out-of 20 --round 0.5
redpen canvas quiz.json grades.csv --missing zero         # 0 for absentees
redpen canvas quiz.json grades.csv --only-reviewed
```

### The roster is not where the assignment code comes from

The roster is chosen at `init`, to match handwritten names, and is normally
exported **before** the assignment exists in Canvas — so it cannot be expected
to carry the code, and a quiz you have only just made will not be in it.

That is what `canvas_gradebook` is for: a **second, later** export, taken once
the assignment exists.

```jsonc
"roster":           "../2026-09-10T1638_Grades-PHY2060.csv",  // names, at init
"canvas_gradebook": "../2026-10-02T0904_Grades-PHY2060.csv",  // codes, at upload
"canvas_assignment": "Quiz 1"
```

Set it once and both `redpen canvas` and the page's button use it; `--gradebook`
overrides it for a one-off. Left unset it falls back to the roster, which is
right when the assignment was already set up before you started. Either way
`--list` prints what codes that file actually has, and `check` says which file
the codes are coming from.

Then **Grades → Import** in the Canvas course, and read the preview before
confirming.

Canvas matches a row to a student by its own `ID`, so every identity column —
`Student, ID, SIS User ID, SIS Login ID, Section` — is copied out of the
gradebook export and the graded CSV supplies only the score. A bare name list
has no ids to upload against, and the button will say so.

Two things decide whether the scores land where you meant:

- **The `(12345)` on the column header.** Canvas writes the assignment's id
  there, and that id is what ties the upload to the assignment that already
  exists. `--assignment "Quiz 1"` matches the roster's columns by name and
  reuses the whole header, id included; `--list` prints the codes the export
  knows about. A name matching nothing would make Canvas **create a second
  assignment**, so that is refused unless you pass `--new`; an ambiguous name
  is refused outright. Set it once as `"canvas_assignment"` in the config.

  The code lives in whichever export `canvas_gradebook` names — see above; it
  is deliberately not tied to the roster.
- **Who is left out.** A student with no graded sheet is omitted, so Canvas
  keeps whatever it already holds for them — an absentee is a decision, not a
  zero. `--missing zero` writes the zeros instead, and either way they are
  listed. Sheets whose name is on no roster entry, or two sheets claiming one
  student, stop the export: fix them in `verify` or on the grading page.

### Marking out of 100, uploading out of something else

A paper marked out of 100 does not have to be worth 100 in the gradebook.
`--out-of X` scales every mark across and sends `X` as `Points Possible`:

```
out of       20   (scaled from 100: ×0.2, to the nearest 0.5)
marks        14 – 20
```

`--round` snaps the result to a grid — `0.5` for half marks, `1` for whole
ones. Rounding is applied once, to the scaled figure, so what Canvas shows is
what the student's parts add up to. Set them once as `"canvas_out_of"` and
`"canvas_round"` and the page's button scales identically; it says so in the
confirmation before it writes anything.

Because Canvas's own points-possible is in the gradebook export, redpen can
see a mismatch you did not ask for, and stops rather than guessing:

```
error: the sheets are marked out of 100 but Canvas has Quiz 1 (7350412) out of 20.00 —
  · scale the marks across:   --out-of 20
  · or keep them raw and move Canvas to 100:   --out-of 100
```

Comments are not carried — the Canvas gradebook import does not accept them.

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
- **Export CSV**, **Canvas CSV**, and **Save/Load progress** as JSON

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
