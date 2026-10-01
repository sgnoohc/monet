# scansplit

Drop in a bulk scan and a Canvas roster; get one `LastName_FirstName.pdf` per
student, named from the handwriting on each sheet.

**Everything runs on your Mac.** PDFKit reads and writes the PDFs and Apple's
Vision framework reads the names, on-device. Nothing is uploaded.

## Build

```bash
./build.sh              # -> dist/scansplit.app
./build.sh --install    # -> also copies it to /Applications
```

One Swift file, no dependencies beyond the Xcode command line tools
(`xcode-select --install`). The app is universal (Apple silicon and Intel),
needs macOS 14 or later, and is ad-hoc signed — on another Mac the first launch
is right-click → **Open**.

## Use

1. **Bulk scan** — drop the PDF on the left box (or click to choose it).
2. **Canvas roster** — drop the CSV on the right box. A Canvas gradebook export
   works as it is: the `Points Possible` row and the test student are skipped.
   A people list, or any CSV with a `Name` column or `First Name` / `Last Name`
   columns, works too.
3. **Pages per student** — the scan must divide evenly, or it says so (usually a
   mis-fed sheet).
4. **Name region → Select…** — the window opens out to show the scan; drag a
   box around where students write their name, on whichever page of their set
   holds it. The box is read as you draw it, with who it matches, and you can
   step through students to check it catches everyone's writing. **Done**
   returns to the panel.
5. **Save to → Choose…** — the folder the PDFs go in.
6. **Read names** — the window opens out into the review list; check it and
   **Save**. **Back** returns to the panel.

It is all one window: the small panel, which grows for choosing the region and
for the review, and shrinks back again.

Both files can also be dropped on the Dock icon together. The pages per
student, the name region and the folder are remembered, so next week's
worksheet is drop, drop, **Read names**.

### The review

One row per sheet: the name crop as the student wrote it, what Vision read, and
the student it was matched to, in a menu you can change.

- **green** — a confident match, with its score
- **orange, Check** — a weak read, or a close call between two students (two
  Michaels, say). Usually right; the flag is caution. The reason is shown.
- **red, Two sheets** — you have given two sheets to one student; saving waits
  until you fix it
- **Unmatched** — saved as `Unmatched_sheet07.pdf`, so no sheet is ever dropped

Above the list: the students with no sheet — the absentees, or a sheet read as
someone else.

## How names are matched

The same method as [redpen](../redpen), ported to Swift:

1. The name region is rendered at 400 dpi and read by Vision, primed with every
   roster name so a scrawl is read as a name on the list.
2. Each reading is scored against every student — both name orders, plus the
   surname alone.
3. Sheets are matched to students as an **assignment problem**: each student
   sits at most one sheet, so once the confident sheets claim their names, a
   badly read one lands on the student nobody else claimed.
4. A score under 0.55, or a lead over the runner-up under 0.10, is flagged.

The student PDFs are the scan's own pages, copied as they are — no re-rendering
or re-compression.

## Command line

The app binary runs the same pipeline without a window, which is handy for
checking a region or scripting:

```bash
B=dist/scansplit.app/Contents/MacOS/scansplit
$B --scan bulk.pdf --roster roster.csv --pages 2 --rect 0.45,0.11,0.45,0.07 \
   [--name-page 1] [--out DIR] [--crops DIR]
```

`--rect` is `x,y,w,h` as fractions of the page, origin top-left. Without
`--out` it only reports; `--crops` saves each sheet's name crop as a PNG.
