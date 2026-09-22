"""Compile a generated quiz, harvest its zones, and write the grading config.

The zones are not drawn by hand and not detected from pixels: each answer box
reports its own rectangle during the compile, so the geometry redpen crops with
is the geometry Typst laid out.  That removes the whole class of mis-crop the
README warns about, and makes `readkey` unnecessary -- the expected answers
were typed into the source, so they are written straight into the config.
"""
import json, os, subprocess

from . import config, quizdoc, render, typstgen

# Content sits between the page margins; a solution reaching past this is
# running off the paper.
PAGE_BOTTOM = 0.95


class BuildError(Exception):
    pass


def _typst(args, cwd):
    p = subprocess.run(["typst"] + args, capture_output=True, text=True, cwd=cwd)
    if p.returncode != 0:
        raise BuildError((p.stderr or p.stdout).strip())
    return p.stdout


def have_typst():
    try:
        subprocess.run(["typst", "--version"], capture_output=True)
        return True
    except OSError:
        return False


def compile_pdf(typ, pdf):
    d = os.path.dirname(os.path.abspath(typ))
    _typst(["compile", os.path.basename(typ), os.path.basename(pdf)], cwd=d)
    return pdf


def harvest(typ, label):
    """The values of every `<label>` metadata in the document, in page order."""
    d = os.path.dirname(os.path.abspath(typ))
    out = _typst(["eval", f"query(<{label}>).map(it => it.value)",
                  "--in", os.path.basename(typ), "--format", "json"], cwd=d)
    return json.loads(out)


def _dedupe(zones):
    """Keep the first sighting of each id.

    The name line lives in the running header, so it reports itself once per
    page; only the first is a zone.
    """
    seen, out = set(), []
    for z in zones:
        if z["id"] in seen:
            continue
        seen.add(z["id"])
        out.append(z)
    return out


def check_drift(quiz_zones, key_zones, log):
    """The key's boxes must land exactly where the blank's do."""
    a = {z["id"]: z for z in quiz_zones}
    b = {z["id"]: z for z in key_zones}
    missing = sorted(set(a) - set(b)) + sorted(set(b) - set(a))
    if missing:
        log(f"  warning: the quiz and key disagree on zones: {', '.join(missing)}")
        return None
    worst, where = 0.0, ""
    for zid, z in a.items():
        d = max(abs(z["x"] - b[zid]["x"]), abs(z["y"] - b[zid]["y"]),
                abs(z["w"] - b[zid]["w"]), abs(z["h"] - b[zid]["h"]))
        if d > worst:
            worst, where = d, zid
    if worst < 1e-9:
        log(f"  key layout identical to the blank across {len(a)} zones")
    else:
        log(f"  warning: key drifts from the blank by {worst:.5f} of the page "
            f"(worst at {where}) — zones are cut from the blank, so a large "
            "drift means the key cannot be read beside a student's paper")
    return worst


def check_overflow(works, parts, log):
    """Worked solutions are placed out of the flow, so they can overprint.

    Each one is checked against whatever comes next on its page: the following
    sub-part, or the bottom of the paper.
    """
    tops = {}
    for p in parts:
        tops.setdefault(p["page"], []).append(p["y"])
    for v in tops.values():
        v.sort()
    bad = []
    for w in works:
        bottom = w["y"] + w["h"]
        nxt = [y for y in tops.get(w["page"], []) if y > w["y"] + 1e-6]
        limit = min(nxt) if nxt else PAGE_BOTTOM
        what = "the next sub-part" if nxt else "the bottom of the page"
        if bottom > limit + 1e-4:
            bad.append((w["id"], (bottom - limit), what))
    for zid, over, what in bad:
        log(f"  warning: the solution for {zid} runs {over * 11:.2f} in past "
            f"{what} — give that sub-part more room, or shorten the working")
    if not bad and works:
        log(f"  all {len(works)} worked solutions fit their writing room")
    return bad


def generate(doc, outdir, log=print, src=None):
    """Generate, compile, harvest and check -- everything but the config.

    The composer calls this on every keystroke, into a cache directory, so a
    live preview never touches the grading config or the PDFs you hand out.
    """
    if not have_typst():
        raise BuildError("typst is not installed — brew install typst")
    # Loading is lenient so a half-typed source can be reopened; building is
    # not, and this is the one place every build passes through.
    try:
        quizdoc.validate(doc)
    except quizdoc.QuizError as err:
        raise BuildError(str(err))
    src = src or os.path.basename(doc.get("_path", "quiz.src.json"))
    paths = typstgen.write(doc, outdir=outdir, src=src)
    stem = paths["stem"]

    quiz_pdf = os.path.join(outdir, f"{stem}.pdf")
    key_pdf = os.path.join(outdir, f"{stem}-key.pdf")
    compile_pdf(paths["quiz"], quiz_pdf)
    compile_pdf(paths["key"], key_pdf)

    zones = _dedupe(harvest(paths["quiz"], "zone"))
    check_drift(zones, _dedupe(harvest(paths["key"], "zone")), log)
    check_overflow(harvest(paths["key"], "work"),
                   harvest(paths["key"], "partpos"), log)

    pages = render.page_count(quiz_pdf)
    if pages != doc["pages"]:
        log(f"  warning: the quiz wants {doc['pages']} pages but came out "
            f"{pages} — the layout could not fit what is there")
    return {"quiz_pdf": quiz_pdf, "key_pdf": key_pdf, "zones": zones,
            "pages": pages, **paths}


def build(doc, outdir=None, log=print, config_path=None):
    """Generate, compile, harvest, and write the grading config."""
    outdir = outdir or doc["_dir"]
    r = generate(doc, outdir, log=log)
    log(f"  compiled {os.path.basename(r['quiz_pdf'])} and "
        f"{os.path.basename(r['key_pdf'])}")

    cfg_path = config_path or os.path.join(outdir, f"{r['stem']}.json")
    cfg = write_config(doc, r["zones"], cfg_path, r["stem"], r["quiz_pdf"],
                       r["key_pdf"], r["pages"], log)
    return {"config": cfg_path, "cfg": cfg, **r}


def write_config(doc, zones, cfg_path, stem, quiz_pdf, key_pdf, pages, log):
    """Merge the generated geometry into the grading config.

    Only what the quiz source decides is rewritten.  The roster, the Canvas
    assignment and its codes, the DPIs and the review thresholds are settings
    of the *marking*, not of the paper, and a rebuild must never quietly drop
    them -- losing a Canvas assignment code would upload a term's marks into a
    newly invented column.
    """
    if os.path.exists(cfg_path):
        cfg = config.load(cfg_path)
        log(f"  merging into {os.path.basename(cfg_path)}, keeping roster and "
            "Canvas settings")
    else:
        cfg = config.new(f"{stem}.pdf", pages, title=doc["title"])
        cfg["_path"] = os.path.abspath(cfg_path)
        cfg["_dir"] = os.path.dirname(cfg["_path"])

    base = cfg["_dir"]
    cfg["title"] = doc["title"]
    cfg["template"] = os.path.relpath(quiz_pdf, base)
    cfg["key_pdf"] = os.path.relpath(key_pdf, base)
    cfg["pages_per_student"] = pages
    cfg["zones"] = [{"id": z["id"], "page": z["page"],
                     "rect": [round(z["x"], 6), round(z["y"], 6),
                              round(z["w"], 6), round(z["h"], 6)],
                     "kind": "name" if z["kind"] == "name" else "answer"}
                    for z in zones]
    named = [z["id"] for z in zones if z["kind"] == "name"]
    cfg["name_zone"] = named[0] if named else None
    cfg["parts"] = parts_of(doc, {z["id"] for z in zones})
    config.validate(cfg)
    config.save(cfg, cfg_path)
    return cfg


def parts_of(doc, zone_ids):
    """The rubric.  One row per sub-part, or one per box where the boxes carry
    their own marks."""
    out = []
    # `live`, and numbered the same way `typstgen` numbers them: the rubric's
    # part ids have to be the ids the zones were emitted under.
    for pi, p in enumerate(quizdoc.live(doc), 1):
        pts = quizdoc.part_points(p)
        for qi, q in enumerate(p["parts"]):
            for item in quizdoc.graded_items(pi, qi, q, pts[qi]):
                zs = [z for z in item["zones"] if z in zone_ids]
                out.append({"id": item["id"],
                            "label": f"{item['id']}  {item['labels']}",
                            "key": item["key"],
                            "points": item["points"],
                            "zones": zs,
                            "auto": item["auto"]})
    return out
