#!/usr/bin/env python3
"""redpen — define zones on a quiz template, split bulk scans by student, grade in the browser.

Everything runs on this machine.  poppler renders the PDFs, Apple's Vision
framework reads the handwritten names on-device, the zone editor is served only
on 127.0.0.1, and the grading page is a local HTML file.  No student work is
uploaded anywhere and no language model is involved.

  redpen init  quiz.json --template key.pdf --roster roster.csv
  redpen zones quiz.json                     draw zones + set the rubric
  redpen run   quiz.json --scan bulk.pdf     split, OCR, match, crop
  redpen verify quiz.json                    confirm every sheet's owner
  redpen readkey quiz.json --key key.pdf --apply    expected answers
  redpen autograde quiz.json                 preliminary right/wrong
  redpen recrop quiz.json                    re-cut zones after a tweak
  redpen grade quiz.json                     build the grading page
"""
import argparse, os, subprocess, sys

from . import answerkey, autograde, config, gradepage, matching, ocr, render, reviewpage, split, zoneeditor


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
    print(f"ocr        {ocr.engine_name()}")
    for p in cfg["parts"]:
        print(f"  {p['id']:<10} {gradepage._num(p['points']):>5} pts  "
              f"[{', '.join(p['zones'])}]  {p['label']}")


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

    p = sub.add_parser("check", help="summarise the config")
    p.add_argument("config"); p.set_defaults(fn=cmd_check)

    p = sub.add_parser("clean", help="drop cached page renders")
    p.add_argument("config"); p.set_defaults(fn=cmd_clean)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
