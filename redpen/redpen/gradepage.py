"""Builds the grading page from the split output.

Images are referenced by relative path rather than inlined, so full-page scans
stay viewable without a 40 MB HTML file.  The page therefore has to live beside
the students/ folder it was built from.
"""
import csv, hashlib, html, json, os

from . import config, matching

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


def build(cfg, out_dir, dest=None, log=print):
    rows = read_report(out_dir)
    auto = load_auto(out_dir)
    parts = cfg["parts"]
    zmap = {z["id"]: z for z in cfg["zones"]}
    name_zone = cfg.get("name_zone")
    roster = matching.load_roster(config.path_of(cfg, "roster"),
                                 cfg["roster_name_column"], cfg["roster_id_column"])
    per = cfg["pages_per_student"]

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
            chips = "".join(
                f'<button data-pid="{e(p["id"])}" data-kind="{kind}" data-v="{val}">{txt}</button>'
                for kind, val, txt in (("zero", 0, "0"), ("half", half, _num(half)),
                                       ("full", mx, "full")))
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
<div class="chips">{chips}</div></div></div>""")

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

    maxin = "".join(f'<label>{e(p["label"])}<input type="number" id="mx_{e(p["id"])}" '
                    f'min="0" step="0.5" value="{_num(p["points"])}"></label>' for p in parts)
    dl = ('<datalist id="roster_names">' +
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
  <option value="flagged">Flagged at split</option></select>
 <button id="resetAll">Reset all</button>
 <button id="savef">Save progress</button>
 <label class="muted" style="cursor:pointer">Load progress
  <input type="file" id="loadf" accept="application/json" style="display:none"></label>
 <button class="pri" id="exp">Export CSV</button>
 <span class="stat" id="saved"></span></div></div>
<div class="layout">
 <nav class="nav"><ol>{''.join(navs)}</ol></nav>
 <main>
  <p class="hint"><kbd>j</kbd>/<kbd>k</kbd> next/previous student ·
   <kbd>←</kbd><kbd>→</kbd> or <kbd>1</kbd>–<kbd>9</kbd> pick a part ·
   <kbd>h</kbd>/<kbd>l</kbd> −1/+1 · <kbd>0</kbd> zero ·
   <kbd>v</kbd> view answers full screen · <kbd>f</kbd> view the whole page ·
   click any crop to zoom.{autonote}</p>
  <details class="pts"><summary>Points per part — total <span id="mxtot"></span></summary>
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
 <span class="grow"></span><span id="vlabel"></span></div>
 <div class="vstage" id="vstage"><img id="vimg" alt="full view"></div></div>
{dl}
<script>const DATA={json.dumps(students)};
const AUTO={json.dumps({s["stem"]: auto.get(s["stem"], {}) for s in students})};
const AUTO_STAMP={json.dumps(stamp)};
const PARTS={json.dumps([{'id':p['id'],'label':p['label'],'points':p['points']} for p in parts])};
const STORE={json.dumps(store)};
{JS}</script></body></html>"""

    dest = dest or os.path.join(out_dir, f"{store}_grading.html")
    with open(dest, "w") as f:
        f.write(doc)
    return dest, len(students)


from .ui_grade import CSS, JS   # noqa: E402  (kept last to keep the file readable)
