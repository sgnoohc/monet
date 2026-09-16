"""Serves the template editor on 127.0.0.1 and writes the config back.

The zones are drawn on the blank/answer-key PDF, not on a student's scan, so
the boxes land exactly where the form puts them.
"""
import json, os, socket, threading, webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

from . import config, render
from .ui_zones import CSS, JS


def page_images(cfg):
    pdf = config.path_of(cfg, "template")
    cache = render.cache_dir(cfg["_dir"], "template")
    n = min(cfg["pages_per_student"], render.page_count(pdf))
    out = []
    for p in range(1, n + 1):
        png = render.render_page(pdf, p, 150, cache)
        out.append(render.data_uri(render.crop_rect(png, [0, 0, 1, 1]), max_px=1600))
    return out


def build_page(cfg):
    pages = page_images(cfg)
    state = {"cfg": {k: v for k, v in cfg.items() if not k.startswith("_")}}
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Zones — {cfg['title']}</title><style>{CSS}</style></head><body>
<div class="bar"><strong>Template editor</strong><span class="muted">{cfg['title']}</span>
 <span class="grow"></span>
 <label class="muted">pages/student <input type="number" id="pps" min="1"
   value="{cfg['pages_per_student']}"></label>
 <label class="muted">dpi <input type="number" id="dpi" min="72" step="25"
   value="{cfg['dpi']}"></label>
 <label class="muted">ocr dpi <input type="number" id="odpi" min="150" step="50"
   value="{cfg['ocr_dpi']}"></label>
 <button class="pri" id="save">Save config</button>
 <span id="msg" class="muted"></span></div>
<div class="main">
 <div class="pane">
  <div class="tabs" id="tabs"></div>
  <div class="stage" id="stage"></div>
  <p class="hint">Drag a rectangle on the page — you'll be asked to label it.
   Label the student-name box <b>name</b>; everything else becomes a graded part.
   Click a zone to select, drag to move, corner to resize.
   <kbd>Delete</kbd> removes, <kbd>Esc</kbd> deselects.
   Tick zones in the list to act on several at once.
   <kbd>n</kbd>/<kbd>p</kbd> (or <kbd>]</kbd>/<kbd>[</kbd>) step through the zones.</p>
 </div>
 <div class="side">
  <div class="cols">

   <section class="col">
    <h3>Selected zone</h3>
    <div class="stepper">
     <button id="zprev">&larr; Prev</button><button id="znext">Next zone &rarr;</button>
     <span class="at" id="zat"></span></div>
    <div id="form" class="off">
     <label>id <input id="z_id" type="text"></label>
     <label>page <input id="z_page" type="number" min="1"></label>
     <label class="ck"><input id="z_name" type="checkbox"> this is the student-name zone</label>
     <div id="pform" class="box off">
      <label>part id <input id="z_part" type="text"></label>
      <label>label <input id="p_label" type="text"></label>
      <label>answer key <input id="p_key" type="text"></label>
      <label>points <input id="p_points" type="number" min="0" step="0.5"></label>
      <p class="hint">Give two zones the same <b>part id</b> to grade them as one item.</p>
     </div>
     <button id="z_del" class="danger">Delete this zone</button>
    </div>
    <p id="nameok" class="hint"></p>
   </section>

   <section class="col">
    <h3>Rubric <span class="tot" id="tot"></span></h3>
    <label>target total <input id="target" type="number" min="0" step="1" value="100"></label>
    <ul id="plist" class="list scroll"></ul>
   </section>

   <section class="col wide">
    <h3>Zones</h3>
    <div class="selhdr">
     <button id="selall">All</button><button id="selpage">This page</button>
     <button id="selnone">None</button><span class="count" id="selcount"></span></div>
    <div class="bulk">
     <button id="grpsel" class="needsel">Group as one part</button>
     <button id="ptssel" class="needsel">Set points</button>
     <button id="alignsel" class="needsel">Line up x / width</button>
     <button id="delsel" class="danger needsel">Delete selected</button>
     <button id="delpage" class="danger">Delete page</button>
     <button id="delall" class="danger">Delete all</button>
    </div>
    <ul id="zlist" class="list scroll"></ul>
   </section>

  </div>
 </div>
</div>
<script>const PAGES={json.dumps(pages)};const STATE={json.dumps(state)};
{JS}</script></body></html>"""


class _H(BaseHTTPRequestHandler):
    cfg = None
    saved = False

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, build_page(_H.cfg))
        else:
            self._send(404, "not found")

    def do_POST(self):
        if self.path != "/save":
            return self._send(404, "not found")
        n = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError as e:
            return self._send(400, json.dumps({"ok": False, "error": str(e)}),
                              "application/json")
        cfg = _H.cfg
        for k in ("zones", "parts", "name_zone", "pages_per_student", "dpi", "ocr_dpi"):
            if k in data:
                cfg[k] = data[k]
        try:
            config.validate(cfg)
            config.save(cfg)
        except Exception as e:
            return self._send(400, json.dumps({"ok": False, "error": str(e)}),
                              "application/json")
        _H.saved = True
        self._send(200, json.dumps({"ok": True, "zones": len(cfg["zones"]),
                                    "parts": len(cfg["parts"]),
                                    "points": config.total_points(cfg)}),
                   "application/json")


def free_port(start=8741):
    for p in range(start, start + 40):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)):
                return p
    raise RuntimeError("no free local port")


def serve(cfg, open_browser=True, log=None):
    log = log or (lambda *a: print(*a, flush=True))
    _H.cfg = cfg
    port = free_port()
    srv = HTTPServer(("127.0.0.1", port), _H)        # loopback only
    url = f"http://127.0.0.1:{port}/"
    log(f"template editor at {url}   (local only)")
    log("draw your zones, press Save, then Ctrl+C here")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("\nstopped." + ("  Config saved." if _H.saved else "  Nothing saved."))
    finally:
        srv.server_close()
