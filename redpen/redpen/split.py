"""Split bulk scans into per-student PDFs plus zone PNGs."""
import csv, os, shutil, subprocess

from . import config, matching, ocr, render


def sheets_in(pdf, per):
    n = render.page_count(pdf)
    if n % per:
        raise RuntimeError(f"{os.path.basename(pdf)} has {n} pages, not a multiple of "
                           f"pages_per_student={per} — a sheet was probably mis-fed")
    return n // per


def gather(cfg, scans, log=print):
    """Read every sheet's name zone.  Returns a list of sheet records."""
    per = cfg["pages_per_student"]
    zmap = {z["id"]: z for z in cfg["zones"]}
    nz = zmap.get(cfg.get("name_zone"))
    if not nz:
        raise RuntimeError("no name zone is defined — set one in the template editor")
    roster = matching.load_roster(config.path_of(cfg, "roster"),
                                 cfg["roster_name_column"], cfg["roster_id_column"])
    if not roster:
        raise RuntimeError("the roster is empty")
    words = matching.custom_words(roster)
    cache = render.cache_dir(cfg["_dir"], "pages")

    sheets = []
    for pdf in scans:
        n = sheets_in(pdf, per)
        log(f"  {os.path.basename(pdf)}: {n} sheets")
        for k in range(n):
            first = k * per + 1
            png = render.render_page(pdf, first + nz["page"] - 1, cfg["ocr_dpi"], cache)
            crop = render.crop_rect(png, nz["rect"], pad=0.004)
            tmp = os.path.join(cache, f"_name_{len(sheets):04d}.png")
            crop.save(tmp)
            cands = ocr.read(tmp, words, log=log, strip_label=True)
            sheets.append({"pdf": pdf, "index": k, "first_page": first,
                           "pages": [first + i for i in range(per)],
                           "ocr": cands, "name_png": tmp})
    return sheets, roster


def resolve(cfg, sheets, roster, log=print):
    res = matching.assign([s["ocr"] for s in sheets], roster)
    taken = {}
    for s, r in zip(sheets, res):
        s.update(r)
        s["review"] = []
        if r["score"] < cfg["review_score"]:
            s["review"].append(f"weak read ({r['score']:.2f})")
        if r["gap"] < cfg["review_gap"]:
            s["review"].append(f"close call ({r['gap']:.2f} over "
                               f"{r['alternatives'][1]['roster']['key']})"
                               if len(r["alternatives"]) > 1 else "close call")
        key = r["roster"]["key"]
        if key in taken:
            s["review"].append(f"same student as sheet {taken[key] + 1}")
            sheets[taken[key]].setdefault("review", []).append("duplicate student")
        else:
            taken[key] = sheets.index(s)
    return sheets


def write_outputs(cfg, sheets, out_dir, log=print):
    students = os.path.join(out_dir, "students")
    review = os.path.join(out_dir, "needs_review")
    for d in (students, review):
        os.makedirs(d, exist_ok=True)
    cache = render.cache_dir(cfg["_dir"], "pages")
    zones = cfg["zones"]
    per = cfg["pages_per_student"]
    rows = []

    for n, s in enumerate(sheets, 1):
        key = s["roster"]["key"]
        flagged = bool(s["review"])
        stem = key if not flagged else f"{key}__sheet{n:03d}"
        dest_dir = review if flagged else students
        pdf_out = os.path.join(dest_dir, stem + ".pdf")
        folder = os.path.join(dest_dir, stem)
        if os.path.exists(folder):
            shutil.rmtree(folder)
        os.makedirs(folder, exist_ok=True)

        _extract(s["pdf"], s["pages"], pdf_out)

        for p in range(1, per + 1):
            page_png = render.render_page(s["pdf"], s["first_page"] + p - 1,
                                            cfg["dpi"], cache)
            shutil.copy2(page_png, os.path.join(folder, f"page{p}.png"))
        for z in zones:
            page_png = render.render_page(s["pdf"], s["first_page"] + z["page"] - 1,
                                            cfg["dpi"], cache)
            pad = 0.0 if z.get("kind") == "answer" and z.get("tight") else 0.004
            render.crop_rect(page_png, z["rect"], pad=pad).save(
                os.path.join(folder, f"{z['id']}.png"))

        rows.append({
            "sheet": n, "source": os.path.basename(s["pdf"]),
            "pages": f"{s['pages'][0]}-{s['pages'][-1]}",
            "name": s["roster"]["display"], "file_key": key,
            "student_id": s["roster"]["id"],
            "ocr": " | ".join(s["ocr"]),
            "score": round(s["score"], 3), "gap": round(s["gap"], 3),
            "review": "; ".join(s["review"]),
        })
        log(f"  {n:>3}/{len(sheets)}  {stem}{'   [review]' if flagged else ''}")

    with open(os.path.join(out_dir, "split_report.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return rows


def _extract(pdf, pages, dest):
    """Lossless page extraction with poppler."""
    outdir = os.path.dirname(dest)
    tmp = os.path.join(outdir, f"_pg{os.getpid()}_%d.pdf")
    render.run(["pdfseparate", "-f", str(pages[0]), "-l", str(pages[-1]), pdf, tmp])
    parts = [tmp.replace("%d", str(p)) for p in pages]
    parts = [p for p in parts if os.path.exists(p)]
    if len(parts) == 1:
        os.replace(parts[0], dest)
    else:
        render.run(["pdfunite", *parts, dest])
        for p in parts:
            os.remove(p)


def recrop(cfg, out_dir, log=print):
    """Re-cut every zone using the identities already in split_report.csv.

    Lets you nudge a zone in the template editor and see the result without
    re-reading a single name."""
    import csv as _csv
    report = os.path.join(out_dir, "split_report.csv")
    if not os.path.exists(report):
        raise RuntimeError("split_report.csv not found — run 'redpen run' first")
    with open(report, newline="") as f:
        rows = list(_csv.DictReader(f))
    cache = render.cache_dir(cfg["_dir"], "pages")
    per = cfg["pages_per_student"]
    scans = {}
    for r in rows:
        key, flagged = r["file_key"], bool(r["review"])
        stem = key if not flagged else f"{key}__sheet{int(r['sheet']):03d}"
        folder = os.path.join(out_dir, "needs_review" if flagged else "students", stem)
        if not os.path.isdir(folder):
            log(f"  !! {stem}: folder missing, skipped"); continue
        pdf = scans.setdefault(r["source"], _find_scan(cfg, out_dir, r["source"]))
        first = int(r["pages"].split("-")[0])
        for p_i in range(1, per + 1):
            png = render.render_page(pdf, first + p_i - 1, cfg["dpi"], cache)
            shutil.copy2(png, os.path.join(folder, f"page{p_i}.png"))
        for z in cfg["zones"]:
            png = render.render_page(pdf, first + z["page"] - 1, cfg["dpi"], cache)
            render.crop_rect(png, z["rect"], pad=0.004).save(
                os.path.join(folder, f"{z['id']}.png"))
    log(f"  re-cut {len(cfg['zones'])} zones for {len(rows)} sheets")
    return rows


def _find_scan(cfg, out_dir, basename):
    for d in (cfg["_dir"], out_dir):
        p = os.path.join(d, basename)
        if os.path.exists(p):
            return p
    raise RuntimeError(f"cannot find the original scan {basename}")


def reconcile(sheets, roster):
    seen = {s["roster"]["key"] for s in sheets}
    return [r for r in roster if r["key"] not in seen]
