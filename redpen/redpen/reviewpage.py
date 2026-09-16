"""Identity review — confirm or correct who each sheet belongs to, before grading.

Served on 127.0.0.1.  Saving renames the per-student PDFs and folders, moves
resolved sheets out of needs_review/, and rewrites split_report.csv, so what
follows always works from corrected identities.
"""
import csv, html, json, os, shutil, socket, threading, webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

from . import config, matching, render
from .ui_review import CSS, JS

e = html.escape
REPORT = "split_report.csv"


def _stem(key, sheet, flagged):
    return f"{key}__sheet{int(sheet):03d}" if flagged else key


def _paths(out_dir, key, sheet, flagged):
    sub = "needs_review" if flagged else "students"
    stem = _stem(key, sheet, flagged)
    return (os.path.join(out_dir, sub, stem + ".pdf"),
            os.path.join(out_dir, sub, stem))


def read_rows(out_dir):
    p = os.path.join(out_dir, REPORT)
    if not os.path.exists(p):
        raise RuntimeError(f"{REPORT} not found — run 'redpen run' first")
    with open(p, newline="") as f:
        return list(csv.DictReader(f))


def write_rows(out_dir, rows):
    p = os.path.join(out_dir, REPORT)
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)


def build_page(cfg, out_dir):
    rows = read_rows(out_dir)
    roster = matching.load_roster(config.path_of(cfg, "roster"),
                                 cfg["roster_name_column"], cfg["roster_id_column"])
    by_key = {r["key"]: r for r in roster}
    used = {r["file_key"] for r in rows}
    unseated = [r for r in roster if r["key"] not in used]

    trs, sheets = [], []
    for r in rows:
        flagged = bool(r["review"])
        _, folder = _paths(out_dir, r["file_key"], r["sheet"], flagged)
        npng = os.path.join(folder, f"{cfg['name_zone']}.png")
        img = render.data_uri(render.crop_rect(npng, [0, 0, 1, 1]), max_px=700) \
              if os.path.exists(npng) else ""
        pages = "".join(
            f'<button class="pg" data-sheet="{r["sheet"]}" data-page="{i}">page {i}</button>'
            for i in range(1, cfg["pages_per_student"] + 1))
        opts = "".join(
            f'<option value="{e(s["key"])}"'
            f'{" selected" if s["key"] == r["file_key"] else ""}>{e(s["display"])}</option>'
            for s in roster)
        why = f'<div class="why">{e(r["review"])}</div>' if flagged else ""
        trs.append(f"""<tr data-sheet="{r['sheet']}" data-flag="{1 if flagged else 0}"
 {'class="flag"' if flagged else ''}>
<td class="n">{r['sheet']}</td>
<td>{'<img src="'+img+'" alt="name as written">' if img else '<span class=n>no crop</span>'}</td>
<td><select class="pick" data-sheet="{r['sheet']}">
 <option value="">— unassigned —</option>{opts}</select>{why}
 <div class="open"><a href="/pdf?sheet={r['sheet']}" target="_blank"
   rel="noopener">whole paper (PDF) &#8599;</a>{pages}</div></td>
<td class="ocr">{e(r['ocr'])}</td>
<td class="n">{r['score']}<br><span style="font-size:11px">gap {r['gap']}</span></td>
</tr>""")
        sheets.append({"sheet": r["sheet"], "key": r["file_key"]})

    missing = ("<p class='sub'>On the roster with no sheet: " +
               ", ".join(e(s["display"]) for s in unseated) + "</p>") if unseated else ""
    n_flag = sum(1 for r in rows if r["review"])
    # nothing flagged means "flagged only" would open on an empty table
    default = "flagged" if n_flag else "all"
    sel = lambda v: " selected" if v == default else ""
    banner = ("" if n_flag else
              "<p class='sub'>Nothing is flagged — every sheet below is already "
              "confirmed. Change any that look wrong and press Apply.</p>")

    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Identity review — {e(cfg['title'])}</title><style>{CSS}</style></head><body>
<div class="bar"><strong>Identity review</strong><span class="muted">{e(cfg['title'])}</span>
 <span class="grow"></span>
 <select id="filt">
  <option value="flagged"{sel("flagged")}>Flagged only ({n_flag})</option>
  <option value="all"{sel("all")}>All sheets ({len(rows)})</option>
  <option value="changed"{sel("changed")}>Changed</option></select>
 <span class="muted" id="stat"></span>
 <button class="pri" id="save">Apply &amp; rename</button>
 <span class="muted" id="msg"></span></div>
<div class="wrap">
<h1>Confirm who each sheet belongs to</h1>
<p class="sub">Fix any wrong match here — the PDFs and folders are renamed to suit, so
 grading always starts from correct identities. Click a name image to enlarge.</p>
{missing}{banner}
<table>
<colgroup><col class="c-sheet"><col class="c-name"><col class="c-pick"><col><col class="c-score"></colgroup>
<thead><tr><th>Sheet</th><th>Name as written</th><th>Assigned student</th>
<th>OCR read</th><th>Score</th></tr></thead><tbody>{''.join(trs)}</tbody></table>
</div>
<div id="big"><span class="cap" id="bigcap"></span><img id="bigimg" alt="enlarged"></div>
<script>const SHEETS={json.dumps(sheets)};
{JS}</script></body></html>"""


def apply_changes(cfg, out_dir, assign):
    """assign: {sheet_number(str): roster_key}.  Renames on disk, rewrites the report."""
    rows = read_rows(out_dir)
    roster = matching.load_roster(config.path_of(cfg, "roster"),
                                 cfg["roster_name_column"], cfg["roster_id_column"])
    by_key = {r["key"]: r for r in roster}

    wanted = {}
    for r in rows:
        k = assign.get(str(r["sheet"]), r["file_key"])
        if k and k not in by_key:
            raise ValueError(f"unknown student key: {k}")
        wanted[r["sheet"]] = k
    seen = {}
    for sheet, k in wanted.items():
        if k:
            if k in seen:
                raise ValueError(f"two sheets assigned to {k} (sheets {seen[k]} and {sheet})")
            seen[k] = sheet

    # stage everything to temp names first so swaps cannot collide
    staged = []
    for r in rows:
        old_flag = bool(r["review"])
        old_pdf, old_dir = _paths(out_dir, r["file_key"], r["sheet"], old_flag)
        new_key = wanted[r["sheet"]]
        changed = (new_key != r["file_key"])
        # a sheet the user has now confirmed leaves review; one still unassigned stays
        new_flag = (not new_key)
        new_pdf, new_dir = _paths(out_dir, new_key or r["file_key"], r["sheet"], new_flag)
        staged.append((r, old_pdf, old_dir, new_pdf, new_dir, new_key, changed, old_flag, new_flag))

    tmp = os.path.join(out_dir, "._verify_tmp")
    os.makedirs(tmp, exist_ok=True)
    for i, (r, op, od, np_, nd, k, ch, of, nf) in enumerate(staged):
        if os.path.exists(op):
            shutil.move(op, os.path.join(tmp, f"{i}.pdf"))
        if os.path.isdir(od):
            shutil.move(od, os.path.join(tmp, f"{i}"))

    renamed = resolved = 0
    for i, (r, op, od, np_, nd, k, ch, of, nf) in enumerate(staged):
        os.makedirs(os.path.dirname(np_), exist_ok=True)
        sp, sd = os.path.join(tmp, f"{i}.pdf"), os.path.join(tmp, f"{i}")
        if os.path.exists(sp):
            if os.path.exists(np_):
                os.remove(np_)
            shutil.move(sp, np_)
        if os.path.isdir(sd):
            if os.path.isdir(nd):
                shutil.rmtree(nd)
            shutil.move(sd, nd)
        if ch:
            renamed += 1
        if of and not nf:
            resolved += 1
        if k:
            r["file_key"] = k
            r["name"] = by_key[k]["display"]
            r["student_id"] = by_key[k]["id"]
        r["review"] = "" if not nf else (r["review"] or "unassigned")
    shutil.rmtree(tmp, ignore_errors=True)
    write_rows(out_dir, rows)
    return renamed, resolved, {str(r["sheet"]): r["file_key"] for r in rows}


class _H(BaseHTTPRequestHandler):
    cfg = None; out_dir = None

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.end_headers()
        self.wfile.write(b)

    def _sheet_paths(self, n):
        """(pdf, folder) for one sheet number, straight from the report."""
        for r in read_rows(_H.out_dir):
            if str(r["sheet"]) == str(n):
                return _paths(_H.out_dir, r["file_key"], r["sheet"], bool(r["review"]))
        return None, None

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            return self._send(200, build_page(_H.cfg, _H.out_dir))
        if u.path == "/pdf":
            pdf, _ = self._sheet_paths((q.get("sheet") or [""])[0])
            if pdf and os.path.exists(pdf):
                with open(pdf, "rb") as f:
                    return self._send(200, f.read(), "application/pdf")
            return self._send(404, "no pdf for that sheet")
        if u.path == "/page":
            _, folder = self._sheet_paths((q.get("sheet") or [""])[0])
            try:
                n = int((q.get("p") or ["1"])[0])
            except ValueError:
                n = 1
            png = os.path.join(folder or "", f"page{n}.png")
            if folder and os.path.exists(png):
                with open(png, "rb") as f:
                    return self._send(200, f.read(), "image/png")
            return self._send(404, "no such page")
        self._send(404, "not found")

    def do_POST(self):
        if self.path != "/apply":
            return self._send(404, "not found")
        n = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
            renamed, resolved, now = apply_changes(_H.cfg, _H.out_dir,
                                                   data.get("assign", {}))
        except Exception as err:
            return self._send(400, json.dumps({"ok": False, "error": str(err)}),
                              "application/json")
        self._send(200, json.dumps({"ok": True, "renamed": renamed,
                                    "resolved": resolved, "now": now}),
                   "application/json")


def free_port(start=8751):
    for p in range(start, start + 40):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)):
                return p
    raise RuntimeError("no free local port")


def serve(cfg, out_dir, open_browser=True, log=None):
    log = log or (lambda *a: print(*a, flush=True))
    _H.cfg, _H.out_dir = cfg, out_dir
    port = free_port()
    srv = HTTPServer(("127.0.0.1", port), _H)
    url = f"http://127.0.0.1:{port}/"
    log(f"identity review at {url}   (local only)")
    log("fix any wrong matches, press Apply, then Ctrl+C here")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("\nstopped.")
    finally:
        srv.server_close()
