"""Builds the grading page from the split output.

Images are referenced by relative path rather than inlined, so full-page scans
stay viewable without a 40 MB HTML file.  The page therefore has to live beside
the students/ folder it was built from.
"""
import csv, hashlib, html, json, os, shutil

from . import canvas, config, matching, render

e = html.escape


def _num(v):
    return int(v) if float(v).is_integer() else v


def read_report(out_dir):
    path = os.path.join(out_dir, "split_report.csv")
    if not os.path.exists(path):
        raise RuntimeError("split_report.csv not found — run 'redpen run' first")
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load_auto(out_dir):
    p = os.path.join(out_dir, "autograde.json")
    if not os.path.exists(p):
        return {}
    with open(p) as f:
        return json.load(f)


def _canvas(cfg, roster):
    """What the page needs to write a Canvas gradebook upload.

    The identity columns come from the roster rather than the sheets, because
    Canvas matches on its own ids; the page only supplies the score.
    """
    want = cfg.get("canvas_assignment") or cfg["title"]
    existing = False
    book, _ = canvas.gradebook(cfg, config.path_of)
    try:
        col, existing = canvas.column(book, want)
    except (OSError, canvas.CanvasError):
        col = want
    out_of = cfg.get("canvas_out_of")
    # What Canvas itself says the assignment is worth, when it exists already:
    # the natural default for scaling, and a check on a hand-set one.
    try:
        pts = float(canvas.points_of(book, col)) if existing else None
    except (OSError, ValueError, TypeError):
        pts = None
    return {"column": col, "existing": existing, "points": pts,
            "outOf": None if out_of is None else float(out_of),
            "step": float(cfg.get("canvas_round") or 0),
            "roster": [{"n": r["display"], "i": r.get("id", ""),
                        "s": r.get("sis_id", ""), "l": r.get("login", ""),
                        "sec": r.get("section", "")} for r in roster]}


def build(cfg, out_dir, dest=None, log=print):
    rows = read_report(out_dir)
    auto = load_auto(out_dir)
    parts = cfg["parts"]
    zmap = {z["id"]: z for z in cfg["zones"]}
    name_zone = cfg.get("name_zone")
    roster = matching.load_roster(config.path_of(cfg, "roster"),
                                 cfg["roster_name_column"], cfg["roster_id_column"])
    per = cfg["pages_per_student"]
    canvas_data = _canvas(cfg, roster)
    key_pages = _key_pages(cfg, out_dir, log)

    students, cards, navs = [], [], []
    for r in rows:
        key = r["file_key"]
        flagged = bool(r.get("review"))
        folder = ("needs_review/" if flagged else "students/") + \
                 (f"{key}__sheet{int(r['sheet']):03d}" if flagged else key)
        pages = [f"{folder}/page{p}.png" for p in range(1, per + 1)]
        students.append({"k": key if not flagged else f"{key}__{r['sheet']}",
                         "sheet": int(r["sheet"]), "name": r["name"], "id": r["student_id"],
                         "pages": pages, "flags": r.get("review", "")})
        k = students[-1]["k"]

        stem = os.path.basename(folder)
        av = auto.get(stem, {})
        blocks = []
        for p in parts:
            # only worth offering once autograde has read the answers
            simbtn = (f'<button class="simbtn" data-pid="{e(p["id"])}" title="Other '
                      f'students whose read answer is like this one (g)">similar</button>'
                      if auto else "")
            v = (av.get(p["id"]) or {})
            verdict = v.get("verdict", "")
            start = 0 if verdict == "wrong" else p["points"]   # red starts at zero
            vclass = f" v-{verdict}" if verdict in ("correct", "wrong", "unsure") else ""
            read = (f'<div class="read"><span class="vtag">{verdict}</span> read: '
                    f'<b>{e(v.get("ocr") or "—")}</b></div>') if verdict else ""
            shots = "".join(
                f'<img src="{folder}/{e(zid)}.png" alt="{e(zid)}" '
                f'data-label="{e(p["label"])} — {e(zid)}" loading="lazy">'
                for zid in p["zones"] if zid in zmap)
            mx = p["points"]; half = round(mx / 2 * 2) / 2
            blocks.append(f"""<div class="part{vclass}" id="p_{e(k)}_{e(p['id'])}">
<div class="pl"><div class="t">{e(p['label'])}</div>
{'<div class="k">key: '+e(p['key'])+'</div>' if p['key'] else ''}{read}</div>
<div class="shots">{shots}</div>
<div class="sc"><div class="spin">
 <button data-pid="{e(p['id'])}" data-step="-1">−</button>
 <input type="number" id="in_{e(k)}_{e(p['id'])}" data-pid="{e(p['id'])}" step="0.5"
        min="0" max="{_num(mx)}" value="{_num(start)}">
 <button data-pid="{e(p['id'])}" data-step="1">+</button>
 <span class="of of_{e(p['id'])}">/ {_num(mx)}</span></div>
<div class="chips" data-pid="{e(p['id'])}"></div>
<button class="notebtn" data-pid="{e(p['id'])}">note</button>{simbtn}
<div class="mist hide" data-pid="{e(p['id'])}">
 <input type="text" class="mistin" list="ml_{e(p['id'])}"
        placeholder="mistake, Enter to add"><span class="tags"></span></div></div></div>""")

        namepng = f'<img src="{folder}/{e(name_zone)}.png" alt="name" ' \
                  f'data-label="name as written" loading="lazy">' if name_zone else ""
        pagebtns = "".join(f'<button class="pagebtn">page {i}</button>'
                           for i in range(1, per + 1))
        pdf_href = folder + ".pdf"          # the student's own split PDF
        pagebtns += (f'<a class="paper" href="{pdf_href}" target="_blank" '
                     f'rel="noopener">whole paper (PDF) &#8599;</a>')
        flagbadge = (f'<span class="badge flag">{e(r["review"])}</span>' if flagged else
                     f'<span class="badge">sheet {r["sheet"]}</span>')
        cards.append(f"""<section class="stu" id="s_{e(k)}" data-k="{e(k)}">
<div class="shd"><span class="nm" id="nm_{e(k)}">{e(r['name'])}</span>
{flagbadge}<span class="tot" id="t_{e(k)}"></span></div>
<div class="idrow">{namepng}
 <input type="text" id="f_name_{e(k)}" list="roster_names" value="{e(r['name'])}"
        placeholder="name">
 <input type="text" id="f_sid_{e(k)}" list="roster_ids" value="{e(r['student_id'])}"
        placeholder="ID">
 <span class="pagelinks">{pagebtns}</span></div>
{''.join(blocks)}
<div class="foot"><input type="text" class="cmt" id="cmt_{e(k)}"
      placeholder="Comment (exported with the scores)">
 <button class="rst">Reset this sheet</button></div></section>""")

        navs.append(f'<li id="n_{e(k)}"{" class=flag" if flagged else ""}>'
                    f'<span class="who">{e(r["name"])}</span><span class="s"></span></li>')
        students[-1]["stem"] = stem

    # The quick-mark pickers are drawn by the page: they follow the saved state.
    maxin = ('<div class="ptrow all"><span class="pn">All parts</span><span></span>'
             '<div class="qm" id="qmall"></div></div>' +
             "".join(f'<div class="ptrow"><span class="pn">{e(p["label"])}</span>'
                     f'<label>out of <input type="number" id="mx_{e(p["id"])}" '
                     f'min="0" step="0.5" value="{_num(p["points"])}"></label>'
                     f'<div class="qm" data-pid="{e(p["id"])}"></div></div>' for p in parts))
    dl = ("".join(f'<datalist id="ml_{e(p["id"])}"></datalist>' for p in parts) +
          '<datalist id="roster_names">' +
          "".join(f'<option value="{e(r["display"])}">' for r in roster) + "</datalist>"
          '<datalist id="roster_ids">' +
          "".join(f'<option value="{e(r["id"])}">' for r in roster if r["id"]) + "</datalist>")
    store = "".join(c if c.isalnum() else "_" for c in cfg["title"]).strip("_") or "quiz"
    stamp = hashlib.sha1(json.dumps(
        {k: {pid: pv.get("verdict") for pid, pv in v.items()} for k, v in auto.items()},
        sort_keys=True).encode()).hexdigest()[:12] if auto else ""
    autonote = ("" if not auto else
                " <b>Dots are an OCR suggestion</b>: green scored full, red scored zero, "
                "amber left at full because the reading was unclear — check those.")

    doc = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(cfg['title'])} — grading</title><style>{CSS}</style></head><body>
<div class="bar"><div class="in"><strong>{e(cfg['title'])}</strong>
 <span class="stat" id="prog"></span><span class="grow"></span>
 <select id="filt"><option value="all">All sheets</option>
  <option value="unreviewed">Not yet reviewed</option>
  <option value="partial">Partial credit</option>
  <option value="zero">Has a zero</option>
  <option value="flagged">Flagged at split</option>
  <option value="mistake">Has a mistake note</option></select>
 <button id="openstats">Stats</button>
 <button id="resetAll">Reset all</button>
 <button id="savef">Save progress</button>
 <label class="muted" style="cursor:pointer">Load progress
  <input type="file" id="loadf" accept="application/json" style="display:none"></label>
 <button class="pri" id="exp">Export CSV</button>
 <button class="pri" id="expcanvas">Canvas CSV</button>
 <span class="stat" id="saved"></span></div></div>
<div class="layout">
 <nav class="nav"><div class="navsort"><select id="sortby" title="Order of this list, and of next/previous">
  <option value="sheet">Sheet order</option>
  <option value="last">Last name A → Z</option><option value="-last">Last name Z → A</option>
  <option value="first">First name A → Z</option><option value="-first">First name Z → A</option>
  <option value="-score">Score high → low</option><option value="score">Score low → high</option>
  <option value="todo">Not reviewed first</option></select>
  <button id="resort" title="Sort again with the marks as they are now">&#8635;</button></div>
  <ol>{''.join(navs)}</ol></nav>
 <main>
  <p class="hint"><kbd>J</kbd>/<kbd>K</kbd> next/previous student ·
   <kbd>j</kbd>/<kbd>k</kbd> or <kbd>1</kbd>–<kbd>9</kbd> next/previous part ·
   <kbd>h</kbd>/<kbd>l</kbd> down/up a quick mark · <kbd>H</kbd>/<kbd>L</kbd> −1/+1 ·
   <kbd>0</kbd> zero · <kbd>m</kbd> note a mistake ·
   <kbd>v</kbd> view answers full screen · <kbd>f</kbd> view the whole page (<kbd>k</kbd> there shows the key beside it) ·
   <kbd>g</kbd> similar answers ·
   <kbd>s</kbd> score stats ·
   click any crop to zoom.{autonote}</p>
  <details class="pts"><summary>Points per part — total <span id="mxtot"></span></summary>
   <p class="hint" style="margin:8px 0 0">Quick marks are the buttons beside every
    student's score. Switch percentages on and off, or choose <b>custom</b> and type
    the marks, e.g. <code>0, 5, 10, 12, 15</code>.</p>
   <div class="ptsgrid">{maxin}</div></details>
  <div class="pager"><button class="prev">&larr; Previous</button>
   <button class="next">Next &rarr;</button><span class="pos"></span></div>
  {''.join(cards)}
  <div class="pager"><button class="prev">&larr; Previous</button>
   <button class="next">Next &rarr;</button><span class="pos"></span></div>
 </main>
</div>
<div id="viewer"><div class="vbar">
 <button id="vclose">Close (Esc)</button>
 <button id="vprev">←</button><button id="vnext">→</button>
 <span id="vcount" class="vhint"></span>
 <button id="vout">−</button><button id="vin">+</button><button id="vfit">Fit</button>
 <span id="vzoom" class="vhint"></span>
 <button id="vkeybtn" title="Show the answer key's page beside this one (K)">Key</button>
 <span class="grow"></span><span id="vlabel"></span></div>
 <div class="vstage" id="vstage"><div id="vbox"><img id="vimg" alt="full view">
  <img id="vkey" alt="answer key"></div></div></div>
<div id="stats"><div class="in">
 <div class="hd"><h2>Score distribution</h2><span class="grow"></span>
  <select id="stscope"><option value="all">All sheets</option>
   <option value="reviewed">Reviewed only</option></select>
  <span class="binset"><select id="stunit" title="Bin the totals in points or in percent of the paper">
    <option value="pts">points</option><option value="pct">percent</option></select>
   <label>from <input type="number" id="stlo" step="any"></label>
   <label>to <input type="number" id="sthi" step="any"></label>
   <label>bins <input type="number" id="stn" min="1" max="200" step="1"></label>
   <button id="stfit" title="Keep the range at the lowest .. highest score, following the marks as they change">fit data</button>
   <button id="streset" title="0 to the full marks (or 0 – 100%), 10 bins">reset</button></span>
  <button id="stclose">Close (Esc)</button></div>
 <p class="sub" id="stsub"></p>
 <div class="tiles" id="sttiles"></div>
 <div class="curve" id="stcurve"><div class="crow2">
  <label class="ck"><input type="checkbox" id="cvon"> Curve to a target mean of</label>
  <input type="number" id="cvtarget" min="0" max="100" step="any" style="width:76px">%
  <label>round curved totals to <select id="cvstep">
   <option value="0">no rounding</option><option value="0.01">0.01</option>
   <option value="0.1">0.1</option><option value="0.25">0.25</option>
   <option value="0.5">0.5</option><option value="1">1 point</option></select></label>
  <select id="cvmode" title="How a curved total between two steps is rounded">
   <option value="nearest">to the nearest</option><option value="up">always up</option></select>
  <span class="hint" id="cvnote"></span></div>
  <div class="cvtab" id="cvtab"></div></div>
 <div class="chartbox"><h3>Total score</h3>
  <div class="cap" id="stcap">Students per score range</div>
  <div id="sthist"></div><div class="binlist" id="stbin"></div>
  <details class="tbl"><summary>As a table</summary><table id="sttable"></table></details></div>
 <div class="parts"><h3>By part</h3>
  <div class="legend"><span><i style="background:var(--sq0)"></i>zero</span>
   <span><i style="background:var(--sq1)"></i>partial</span>
   <span><i style="background:var(--sq2)"></i>full marks</span></div>
  <table id="stparts"></table></div>
 <div class="parts"><h3>Common mistakes</h3>
  <div class="cap" style="font-size:12px;color:var(--mut);margin-bottom:6px">From the notes
   on each part, most frequent first. Click a name to go to that answer.</div>
  <div id="stmist"></div></div>
</div></div>
<div id="tip"></div>
<aside id="sim"><div class="simhd"><strong id="simtitle"></strong><span class="grow"></span>
 <button id="simback" title="Back to the answer this list was made from">back</button>
 <button id="simclose" title="Close (Esc)">&times;</button></div>
 <div class="hint simhint"><kbd>[</kbd> <kbd>]</kbd> hop through the list ·
  <kbd>f</kbd> their page · <kbd>g</kbd> re-group on the sheet you are on</div>
 <div id="simbody"></div></aside>
<div id="cdlg"><div class="box">
 <h3>Export for Canvas</h3>
 <p class="hint" id="ccol"></p>
 <div class="crow"><label>Canvas total <input type="number" id="ctot" min="0" step="any"></label>
  <label>scale factor × <input type="number" id="cfac" min="0" step="any"></label></div>
 <div class="crow"><label>round to <select id="cstep"><option value="0">no rounding</option>
  <option value="0.01">0.01</option><option value="0.1">0.1</option>
  <option value="0.25">0.25</option><option value="0.5">0.5</option>
  <option value="1">1</option></select></label>
  <select id="cmode" title="How a score between two steps is rounded">
   <option value="nearest">to the nearest</option><option value="up">always up</option></select>
  <span class="grow"></span><button id="cpaper" title="Upload the marks as they are">no scaling</button></div>
 <p class="hint" id="cnote"></p>
 <div class="cprev" id="cprev"></div>
 <div class="crow" style="justify-content:flex-end;margin-top:14px">
  <button id="ccancel">Cancel</button><button class="pri" id="cgo">Export Canvas CSV</button></div>
</div></div>
{dl}
<script>const DATA={json.dumps(students)};
const AUTO={json.dumps({s["stem"]: auto.get(s["stem"], {}) for s in students})};
const AUTO_STAMP={json.dumps(stamp)};
const PARTS={json.dumps([{'id':p['id'],'label':p['label'],'points':p['points'],
                          'page':min((zmap[z]['page'] for z in p['zones'] if z in zmap), default=1)}
                         for p in parts])};
const STORE={json.dumps(store)};
const CANVAS={json.dumps(canvas_data)};
const KEY={json.dumps(key_pages)};
{JS}</script></body></html>"""

    dest = dest or os.path.join(out_dir, f"{store}_grading.html")
    with open(dest, "w") as f:
        f.write(doc)
    return dest, len(students)


def _key_pages(cfg, out_dir, log=print):
    """The answer key's pages as PNGs beside the page, for the viewer.

    Relative hrefs, like the students' pages, so the grading page and its
    folder move together.  Empty when there is no key PDF."""
    key = config.path_of(cfg, "key_pdf")
    if not key or not os.path.exists(key):
        return []
    dest = os.path.join(out_dir, "key")
    os.makedirs(dest, exist_ok=True)
    cache = render.cache_dir(cfg["_dir"], "pages")
    out = []
    try:
        for p in range(1, render.page_count(key) + 1):
            png = render.render_page(key, p, cfg["dpi"], cache)
            shutil.copy2(png, os.path.join(dest, f"page{p}.png"))
            out.append(f"key/page{p}.png")
    except RuntimeError as err:
        log(f"warning: could not render the answer key: {err}")
        return []
    return out


from .ui_grade import CSS, JS   # noqa: E402  (kept last to keep the file readable)
