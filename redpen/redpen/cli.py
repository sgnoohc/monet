#!/usr/bin/env python3
"""redpen — define zones on a quiz template, split bulk scans by student, grade in the browser.

Everything runs on this machine.  poppler renders the PDFs, Apple's Vision
framework reads the handwritten names on-device, the zone editor is served only
on 127.0.0.1, and the grading page is a local HTML file.  No student work is
uploaded anywhere and no language model is involved.

  redpen new   quiz.src.json                 start a quiz
  redpen compose quiz.src.json               write it in a form, live preview
  redpen build quiz.src.json                 -> quiz.pdf, key.pdf, zones, rubric
  redpen init  quiz.json --template key.pdf --roster roster.csv
  redpen zones quiz.json                     draw zones + set the rubric
  redpen run   quiz.json --scan bulk.pdf     split, OCR, match, crop
  redpen verify quiz.json                    confirm every sheet's owner
  redpen readkey quiz.json --key key.pdf --apply    expected answers
  redpen autograde quiz.json                 preliminary right/wrong
  redpen recrop quiz.json                    re-cut zones after a tweak
  redpen grade quiz.json                     build the grading page
  redpen canvas quiz.json grades.csv         CSV for the Canvas gradebook
"""
import argparse, os, subprocess, sys

from . import __version__
from . import (answerkey, autograde, canvas, composer, config, gradepage, matching,
               ocr, quizdoc, render, reviewpage, split, stats, typstbuild, zoneeditor)
from . import app as appmod


def _load(path):
    try:
        return config.load(path)
    except (OSError, config.ConfigError) as err:
        sys.exit(f"error: {err}")


def _rel(target, base):
    r = os.path.relpath(target, base)
    return target if r.startswith("../../..") else r


def cmd_init(a):
    out = os.path.abspath(a.config)
    base = os.path.dirname(out)
    if os.path.exists(out) and not a.force:
        sys.exit(f"error: {out} exists (use --force)")
    tpl = os.path.abspath(a.template)
    if not os.path.exists(tpl):
        sys.exit(f"error: no such template: {tpl}")
    pages = a.pages or render.page_count(tpl)
    cfg = config.new(_rel(tpl, base), pages, title=a.title, dpi=a.dpi)
    if a.roster:
        cfg["roster"] = _rel(os.path.abspath(a.roster), base)
    cfg["_path"], cfg["_dir"] = out, base
    config.save(cfg, out)
    print(f"wrote {out}")
    print(f"  template   {os.path.basename(tpl)} ({pages} pages per student)")
    if a.roster:
        r = matching.load_roster(config.path_of(cfg, "roster"))
        print(f"  roster     {len(r)} students")
    print(f"\nnext:  redpen zones {os.path.basename(out)}")


def cmd_zones(a):
    cfg = _load(a.config)
    if not config.path_of(cfg, "template"):
        sys.exit("error: config has no template pdf")
    zoneeditor.serve(cfg, open_browser=not a.no_browser)


def cmd_run(a):
    cfg = _load(a.config)
    if not cfg.get("name_zone"):
        sys.exit("error: no name zone defined — run 'redpen zones' first")
    if not config.path_of(cfg, "roster"):
        sys.exit("error: no roster configured")
    scans = [os.path.abspath(s) for s in a.scan]
    for s in scans:
        if not os.path.exists(s):
            sys.exit(f"error: no such scan: {s}")
    out_dir = os.path.abspath(a.out) if a.out else cfg["_dir"]
    os.makedirs(out_dir, exist_ok=True)

    print(f"OCR engine: {ocr.engine_name()}")
    try:
        sheets, roster = split.gather(cfg, scans, log=print)
    except RuntimeError as err:
        sys.exit(f"error: {err}")
    print(f"matching {len(sheets)} sheets against {len(roster)} students ...")
    try:
        sheets = split.resolve(cfg, sheets, roster, log=print)
    except ValueError as err:
        sys.exit(f"error: {err}")
    rows = split.write_outputs(cfg, sheets, out_dir, log=print)

    flagged = [r for r in rows if r["review"]]
    missing = split.reconcile(sheets, roster)
    print(f"\n{len(rows)} sheets written to {out_dir}/students")
    if flagged:
        print(f"{len(flagged)} need review -> {out_dir}/needs_review")
        for r in flagged:
            print(f"    sheet {r['sheet']:>3}  {r['file_key']:<24} {r['review']}")
    if missing:
        print(f"{len(missing)} on the roster with no sheet:")
        for m in missing:
            print(f"    {m['display']}")
    print(f"\nreport: {os.path.join(out_dir,'split_report.csv')}")
    print(f"next:   redpen grade {os.path.basename(cfg['_path'])}")


def cmd_verify(a):
    cfg = _load(a.config)
    out_dir = os.path.abspath(a.out) if a.out else cfg["_dir"]
    try:
        reviewpage.read_rows(out_dir)
    except RuntimeError as err:
        sys.exit(f"error: {err}")
    reviewpage.serve(cfg, out_dir, open_browser=not a.no_browser)


def cmd_readkey(a):
    cfg = _load(a.config)
    key = a.key or config.path_of(cfg, "key_pdf")
    if not key:
        sys.exit("error: no key pdf — pass --key, or set key_pdf in the config")
    if not os.path.exists(key):
        sys.exit(f"error: no such key pdf: {key}")
    got = answerkey.read(cfg, key, only_empty=not a.overwrite)
    if not got:
        print("nothing to fill — every part already has a key (use --overwrite to redo)")
        return
    print()
    for p in cfg["parts"]:
        if p["id"] in got:
            print(f"  {p['id']:<8} {got[p['id']][:60]!r}")
            if a.apply:
                p["key"] = got[p["id"]]
    if a.apply:
        if not cfg.get("key_pdf"):
            cfg["key_pdf"] = _rel(os.path.abspath(key), cfg["_dir"])
        config.save(cfg)
        print(f"\nwritten into {os.path.basename(cfg['_path'])} — check them before grading")
    else:
        print("\n(nothing written; re-run with --apply to put these in the config)")


def cmd_autograde(a):
    cfg = _load(a.config)
    out_dir = os.path.abspath(a.out) if a.out else cfg["_dir"]
    missing = [p["id"] for p in cfg["parts"] if p.get("auto", True) and not p.get("key")]
    if missing:
        print(f"warning: no answer key for {', '.join(missing)} — "
              "those parts will read as 'unsure'")
    try:
        dest, tally = autograde.run(cfg, out_dir, log=print)
    except RuntimeError as err:
        sys.exit(f"error: {err}")
    total = sum(tally.values())
    print(f"\nwrote {dest}")
    for k in ("correct", "wrong", "unsure", "skip"):
        if tally.get(k):
            print(f"  {k:<8} {tally[k]:>5}  ({100*tally[k]/total:.0f}%)")
    print("\nthese are suggestions — the grading page shows the text each came from")


def cmd_recrop(a):
    cfg = _load(a.config)
    out_dir = os.path.abspath(a.out) if a.out else cfg["_dir"]
    try:
        split.recrop(cfg, out_dir, log=print)
    except RuntimeError as err:
        sys.exit(f"error: {err}")
    print("zones re-cut — run 'redpen grade' to refresh the page")


def cmd_grade(a):
    cfg = _load(a.config)
    out_dir = os.path.abspath(a.out) if a.out else cfg["_dir"]
    if not cfg["parts"]:
        sys.exit("error: no graded parts defined — set them in 'redpen zones'")
    try:
        dest, n = gradepage.build(cfg, out_dir, dest=a.dest)
    except RuntimeError as err:
        sys.exit(f"error: {err}")
    print(f"wrote {dest}")
    print(f"{n} sheets · {len(cfg['parts'])} parts · "
          f"{gradepage._num(config.total_points(cfg))} points")
    if not a.no_open:
        subprocess.run(["open", dest], check=False)


def cmd_stats(a):
    try:
        parts, students, out_of = stats.read(a.grades, only_reviewed=a.only_reviewed)
    except (OSError, stats.GradesError) as err:
        sys.exit(f"error: {err}")

    if a.part:
        hit = [p for p in parts if a.part.lower() in p["label"].lower()]
        if not hit:
            sys.exit(f"error: no part matches {a.part!r}. Parts: "
                     + ", ".join(p["label"] for p in parts))
        if len(hit) > 1:
            sys.exit(f"error: {a.part!r} matches {len(hit)} parts: "
                     + ", ".join(p["label"] for p in hit))
        p = hit[0]
        values = [s["scores"][p["col"]] for s in students
                  if s["scores"].get(p["col"]) is not None]
        title, ceiling, table = p["label"], (p["max"] or max(values)), []
    else:
        values = [s["total"] for s in students]
        title, ceiling = (a.title or "Grade distribution"), out_of
        table = stats.part_stats(parts, students)

    st = stats.summary(values)
    hi = a.max if a.max is not None else ceiling
    try:
        edges, counts, under, over = stats.bins(values, nbins=a.nbins, lo=a.min,
                                                hi=hi, width=a.width)
    except stats.GradesError as err:
        sys.exit(f"error: {err}")
    print()
    print(stats.render_text(title, st, edges, counts, under, over, table, ceiling))
    print()
    if a.html:
        with open(a.html, "w") as f:
            f.write(stats.render_html(title, st, edges, counts, under, over,
                                      table, ceiling))
        print(f"wrote {a.html}")
        if not a.no_open:
            subprocess.run(["open", a.html], check=False)


def cmd_canvas(a):
    cfg = _load(a.config)
    roster, src = canvas.gradebook(cfg, config.path_of, a.gradebook)
    if not roster or not os.path.exists(roster):
        sys.exit(f"error: gradebook export not found{': '+roster if roster else ''}"
                 f"\n(from {src} — pass --gradebook to point at a fresh "
                 "Canvas gradebook export)")

    if a.list:
        cols = canvas.assignments(roster)
        print(f"{os.path.basename(roster)}  (from {src})"
              f" — {len(cols)} assignment columns\n")
        for c in cols:
            print(f"  {c['id']:>9}  {c['points'] or '?':>6}  {c['name']}")
        if not cols:
            print("  none — no assignment columns at all, so this is either not a\n"
                  "  Canvas gradebook export or was taken before any assignment\n"
                  "  existed.  Export the gradebook again from Canvas.")
        else:
            print("\nupload into one with:  redpen canvas ... --assignment NAME")
        return
    if not a.grades:
        sys.exit("error: which grades CSV? (or pass --list to see the assignments)")

    try:
        rows, out_of, unreviewed = canvas.read_grades(a.grades,
                                                      only_reviewed=a.only_reviewed)
        header, existing = canvas.column(
            roster, a.assignment or cfg.get("canvas_assignment") or cfg["title"])
    except (OSError, canvas.CanvasError) as err:
        sys.exit(f"error: {err}")
    if not existing and not a.new:
        cols = canvas.assignments(roster)
        print(f"error: {os.path.basename(roster)} has no assignment called "
              f"{header!r} —")
        print("importing this would create a second assignment rather than "
              "filling the\none you mean.  Most likely that export simply "
              "predates the assignment:")
        print("\n  · make the assignment in Canvas, export the gradebook, and "
              "point at it:\n"
              "      redpen canvas ... --gradebook ~/Downloads/<newer export>.csv\n"
              "    then keep it, so the page's button uses it too:\n"
              f'      "canvas_gradebook": "<newer export>.csv"   in '
              f'{os.path.basename(cfg["_path"])}')
        print("  · or name a column that is already there — " +
              (", ".join(repr(c["name"]) for c in cols[:5]) +
               (", ..." if len(cols) > 5 else "") if cols else "it has none")
              + "\n    (redpen canvas ... --list)")
        sys.exit("  · or pass --new, if a brand-new assignment really is what "
                 "you want")

    entries = matching.load_roster(roster, cfg["roster_name_column"],
                                   cfg["roster_id_column"])
    pairs, unmatched, clashes = canvas.match_roster(rows, entries)
    if clashes:
        print("error: more than one sheet graded for the same student —")
        for group in clashes:
            print(f"    {group[0][1]['display']}: sheets "
                  + ", ".join(r["sheet"] or "?" for r, _ in group))
        sys.exit("settle these in 'redpen verify' before uploading")
    if unmatched:
        print(f"error: {len(unmatched)} graded sheets are not on the roster —")
        for r in unmatched:
            print(f"    sheet {r['sheet'] or '?':>3}  {r['name']!r} id={r['id'] or '—'}")
        sys.exit("fix the names in the grading page, re-export, and try again")

    missing = canvas.ungraded(pairs, entries)
    zeros = missing if a.missing == "zero" else []
    was = canvas.points_of(roster, header)
    target = a.out_of if a.out_of is not None else cfg.get("canvas_out_of")
    if target is None and was and float(was) != out_of:
        sys.exit(f"error: the sheets are marked out of {canvas._num(out_of)} but "
                 f"Canvas has {header} out of {was} —\n"
                 f"  · scale the marks across:   --out-of {canvas._num(was)}\n"
                 f"  · or keep them raw and move Canvas to "
                 f"{canvas._num(out_of)}:   --out-of {canvas._num(out_of)}")
    target = out_of if target is None else float(target)
    step = a.round if a.round is not None else (cfg.get("canvas_round") or 0)
    table = canvas.rows_for(pairs, header, target, zeros=zeros,
                            paper=out_of, step=step)
    dest = a.out or os.path.join(os.path.dirname(os.path.abspath(a.grades)),
                                 os.path.splitext(os.path.basename(a.grades))[0]
                                 + "_canvas.csv")
    canvas.write(table, dest)

    print(f"wrote {dest}")
    print(f"  assignment   {header}"
          + ("" if existing else "   (NEW — Canvas will create it)"))
    if target != out_of:
        lo = canvas.scale(min(float(r["total"]) for r, _ in pairs), out_of, target, step)
        hi = canvas.scale(max(float(r["total"]) for r, _ in pairs), out_of, target, step)
        print(f"  out of       {canvas._num(target)}   (scaled from "
              f"{canvas._num(out_of)}: \u00d7{target/out_of:.4g}"
              + (f", to the nearest {canvas._num(step)}" if step else "") + ")")
        print(f"  marks        {canvas._num(lo)} \u2013 {canvas._num(hi)}")
    else:
        print(f"  out of       {canvas._num(target)}"
              + (f"   (Canvas currently has {was} — the upload changes it)"
                 if was and canvas._num(was) != canvas._num(target) else ""))
    print(f"  rows         {len(pairs)} graded"
          + (f" + {len(zeros)} zeros" if zeros else ""))
    if unreviewed:
        print(f"  unreviewed   {unreviewed}"
              + (" (left out)" if a.only_reviewed else " (INCLUDED — still at full marks?)"))
    if missing and not zeros:
        print(f"  no sheet     {len(missing)}, left untouched in Canvas:")
        for m in missing:
            print(f"                 {m['display']}")
    print("\nupload with Grades -> Import in the Canvas course, and check the "
          "preview before confirming")


def cmd_check(a):
    cfg = _load(a.config)
    tpl = config.path_of(cfg, "template")
    print(f"config     {cfg['_path']}")
    print(f"template   {tpl}"
          f"{'  (missing!)' if tpl and not os.path.exists(tpl) else ''}")
    print(f"pages/stu  {cfg['pages_per_student']}")
    print(f"dpi        {cfg['dpi']} (crops) / {cfg['ocr_dpi']} (name OCR)")
    print(f"name zone  {cfg.get('name_zone') or '-- not set --'}")
    print(f"zones      {len(cfg['zones'])}")
    print(f"parts      {len(cfg['parts'])}  total "
          f"{gradepage._num(config.total_points(cfg))} points")
    r = config.path_of(cfg, "roster")
    if r and os.path.exists(r):
        print(f"roster     {len(matching.load_roster(r, cfg['roster_name_column'], cfg['roster_id_column']))} students")
    else:
        print(f"roster     {'missing: '+r if r else '-- not set --'}")
    book, src = canvas.gradebook(cfg, config.path_of)
    if book and os.path.exists(book):
        try:
            col, existing = canvas.column(book, cfg.get("canvas_assignment") or cfg["title"])
            print(f"canvas     {col}"
                  + ("" if existing else "   (NOT in " + os.path.basename(book)
                     + " — would create it)"))
            if src == "roster":
                print("           codes come from the roster; set canvas_gradebook "
                      "to a newer export")
        except canvas.CanvasError as err:
            print(f"canvas     ambiguous — {err}")
    print(f"ocr        {ocr.engine_name()}")
    for p in cfg["parts"]:
        print(f"  {p['id']:<10} {gradepage._num(p['points']):>5} pts  "
              f"[{', '.join(p['zones'])}]  {p['label']}")


def cmd_new(a):
    out = os.path.abspath(a.source)
    if os.path.exists(out) and not a.force:
        sys.exit(f"error: {out} exists (use --force)")
    doc = quizdoc.new(a.title or os.path.splitext(os.path.basename(out))[0],
                      pages=a.pages)
    doc["problems"] = [{
        "title": "First problem", "points": 100, "page": 1,
        "stem": "Say what the situation is.",
        "parts": [{"question": "Ask for something.",
                   "boxes": [{"label": "answer", "answer": ""}],
                   "solution": []}],
    }]
    doc["_path"], doc["_dir"] = out, os.path.dirname(out)
    quizdoc.save(doc, out)
    print(f"wrote {out}")
    print(f"\nnext:  redpen build {os.path.basename(out)}")


def cmd_app(a):
    appmod.serve(open_browser=not a.no_browser, port=a.port)


def cmd_compose(a):
    try:
        doc = quizdoc.load(a.source)
    except (OSError, ValueError, quizdoc.QuizError) as err:
        sys.exit(f"error: {err}")
    if not typstbuild.have_typst():
        sys.exit("error: typst is not installed — brew install typst")
    composer.serve(doc, open_browser=not a.no_browser)


def cmd_build(a):
    try:
        doc = quizdoc.load(a.source)
    except (OSError, ValueError, quizdoc.QuizError) as err:
        sys.exit(f"error: {err}")
    outdir = os.path.abspath(a.out) if a.out else doc["_dir"]
    print(f"building {doc['title']}")
    try:
        r = typstbuild.build(doc, outdir=outdir, log=print, config_path=a.config)
    except (typstbuild.BuildError, config.ConfigError) as err:
        sys.exit(f"error: {err}")
    cfg = r["cfg"]
    named = [z for z in cfg["zones"] if z["kind"] == "name"]
    print(f"\n{len(cfg['zones']) - len(named)} answer zones over {r['pages']} pages"
          f"{', name zone found' if named else ', NO NAME ZONE'}")
    print(f"{len(cfg['parts'])} graded parts, {config.total_points(cfg):g} points")
    print(f"\nwrote {os.path.relpath(r['config'], outdir)}  "
          f"{os.path.relpath(r['quiz_pdf'], outdir)}  "
          f"{os.path.relpath(r['key_pdf'], outdir)}")
    print(f"next:   redpen run {os.path.basename(r['config'])} --scan bulk.pdf")


def cmd_clean(a):
    cfg = _load(a.config)
    import shutil
    d = os.path.join(cfg["_dir"], render.CACHE)
    if os.path.isdir(d):
        shutil.rmtree(d); print(f"removed {d}")
    else:
        print("nothing cached")


def main():
    ap = argparse.ArgumentParser(prog="redpen", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"redpen {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="create a config from a template PDF")
    p.add_argument("config"); p.add_argument("--template", required=True)
    p.add_argument("--roster"); p.add_argument("--pages", type=int)
    p.add_argument("--title"); p.add_argument("--dpi", type=int, default=200)
    p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_init)

    p = sub.add_parser("zones", help="draw zones and set the rubric (local browser UI)")
    p.add_argument("config"); p.add_argument("--no-browser", action="store_true")
    p.set_defaults(fn=cmd_zones)

    p = sub.add_parser("run", help="split scans, OCR names, match the roster, crop zones")
    p.add_argument("config"); p.add_argument("--scan", nargs="+", required=True)
    p.add_argument("--out"); p.set_defaults(fn=cmd_run)

    p = sub.add_parser("verify", help="confirm/correct who each sheet belongs to")
    p.add_argument("config"); p.add_argument("--out")
    p.add_argument("--no-browser", action="store_true"); p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("readkey", help="read expected answers off an answer-key PDF")
    p.add_argument("config"); p.add_argument("--key")
    p.add_argument("--apply", action="store_true", help="write them into the config")
    p.add_argument("--overwrite", action="store_true", help="replace keys already set")
    p.set_defaults(fn=cmd_readkey)

    p = sub.add_parser("autograde", help="OCR the answers and mark them right/wrong")
    p.add_argument("config"); p.add_argument("--out"); p.set_defaults(fn=cmd_autograde)

    p = sub.add_parser("recrop", help="re-cut zones after editing them, keeping the names")
    p.add_argument("config"); p.add_argument("--out"); p.set_defaults(fn=cmd_recrop)

    p = sub.add_parser("grade", help="build the grading page")
    p.add_argument("config"); p.add_argument("--out"); p.add_argument("--dest")
    p.add_argument("--no-open", action="store_true"); p.set_defaults(fn=cmd_grade)

    p = sub.add_parser("stats", help="statistics and grade distribution from an export")
    p.add_argument("grades", help="CSV exported by the grading page")
    p.add_argument("--nbins", type=int, default=10, help="number of bins (default 10)")
    p.add_argument("--min", type=float, default=0.0, help="low edge (default 0)")
    p.add_argument("--max", type=float, help="high edge (default: the paper's total)")
    p.add_argument("--width", type=float, help="bin width; overrides --nbins")
    p.add_argument("--part", help="histogram one part instead of the total")
    p.add_argument("--only-reviewed", action="store_true",
                   help="ignore sheets not yet marked reviewed")
    p.add_argument("--title")
    p.add_argument("--html", help="also write an HTML report")
    p.add_argument("--no-open", action="store_true")
    p.set_defaults(fn=cmd_stats)

    p = sub.add_parser("canvas", help="build a CSV for the Canvas gradebook import")
    p.add_argument("config")
    p.add_argument("grades", nargs="?", help="CSV exported by the grading page")
    p.add_argument("--assignment", help="Canvas assignment column (default: the quiz title)")
    p.add_argument("--list", action="store_true",
                   help="list the roster's assignment columns and their Canvas ids")
    p.add_argument("--new", action="store_true",
                   help="allow creating an assignment Canvas does not have yet")
    p.add_argument("--gradebook", help="Canvas gradebook export holding the assignment "
                   "column (default: canvas_gradebook, else the roster)")
    p.add_argument("--out-of", type=float, dest="out_of",
                   help="scale every mark to this Canvas total (default: the paper's)")
    p.add_argument("--round", type=float,
                   help="snap scaled marks to this step (0.5 = half marks)")
    p.add_argument("--missing", choices=("skip", "zero"), default="skip",
                   help="students with no graded sheet (default: skip)")
    p.add_argument("--only-reviewed", action="store_true",
                   help="leave out sheets not yet marked reviewed")
    p.add_argument("-o", "--out", help="where to write the CSV")
    p.set_defaults(fn=cmd_canvas)

    p = sub.add_parser("new", help="start a quiz source file")
    p.add_argument("source", help="quiz.src.json to create")
    p.add_argument("--title"); p.add_argument("--pages", type=int, default=2)
    p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_new)

    p = sub.add_parser("app", help="the whole workflow in one window")
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--port", type=int, help="serve on this port instead of the first free one")
    p.set_defaults(fn=cmd_app)

    p = sub.add_parser("compose", help="write the quiz in a form (local browser UI)")
    p.add_argument("source", help="quiz.src.json")
    p.add_argument("--no-browser", action="store_true"); p.set_defaults(fn=cmd_compose)

    p = sub.add_parser("build", help="compile a quiz source into the quiz, key and config")
    p.add_argument("source", help="quiz.src.json")
    p.add_argument("--out", help="where to write (default: beside the source)")
    p.add_argument("--config", help="grading config to write (default: <stem>.json)")
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("check", help="summarise the config")
    p.add_argument("config"); p.set_defaults(fn=cmd_check)

    p = sub.add_parser("clean", help="drop cached page renders")
    p.add_argument("config"); p.set_defaults(fn=cmd_clean)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
