"""Serves the quiz composer on 127.0.0.1: write the quiz, watch it build.

The form edits `quiz.src.json` -- the questions, the answers and the marks --
and every pause in typing regenerates the paper into a cache directory, so the
preview is the real Typst layout rather than an approximation of it.  Only the
Build button writes the PDFs you hand out and the grading config.
"""
import json, os, shutil, socket, threading, webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

from . import quizdoc, render, typstbuild
from .ui_compose import CSS, JS

PREVIEW = "compose"


def preview_dir(doc):
    return render.cache_dir(doc["_dir"], PREVIEW)


def build_page(doc, base=""):
    """The composer page.  `base` mounts it under a prefix inside the app."""
    state = {"doc": {k: v for k, v in doc.items() if not k.startswith("_")},
             "base": base}
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Compose — {doc['title']}</title><style>{CSS}</style></head><body>
<div class="bar"><strong>Composer</strong>
 <span class="muted">{os.path.basename(doc['_path'])}</span>
 <span class="grow"></span>
 <span class="muted">target</span><input type="number" id="target" min="0" step="5" value="100">
 <button class="pri" id="build" title="write the PDFs and the grading config">Build</button>
 <span id="msg" class="muted"></span></div>
<div class="main">

 <div class="col left">
  <h3>Outline</h3>
  <div class="tally" id="tally"></div>
  <ul class="tree" id="outline"></ul>
  <button class="add" data-act="addprob">+ Add problem</button>

  <h3>The paper</h3>
  <label>title <input type="text" data-doc="title" value="{_a(doc['title'])}"></label>
  <label>pages <input type="number" data-doc="pages" data-num="1" min="1"
    value="{doc['pages']}"></label>
  <label>instructions
   <textarea data-doc="note" rows="3"
     placeholder="The boxed note at the top.">{_a(doc.get('note',''))}</textarea></label>
  <label>Typst preamble <span class="tiny">verbatim, for a drawn figure</span>
   <textarea class="mono" data-doc="preamble" rows="2"
     >{_a(doc.get('preamble',''))}</textarea></label>

  <h3>Build</h3>
  <div id="status" class="hint"></div>
 </div>

 <div class="col" id="form"></div>

 <div class="split" id="split" title="drag to resize the paper"></div>

 <div class="prev">
  <div class="tabs">
   <button data-v="quiz" class="on">Quiz</button>
   <button data-v="key">Key</button>
   <button data-v="zones">Zones</button>
   <span class="grow"></span>
   <span class="tiny">updates as you type</span>
  </div>
  <div class="pane" id="pane"></div>
 </div>

</div>
<script>const STATE={json.dumps(state)};
{JS}</script></body></html>"""


def _a(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


class _H(BaseHTTPRequestHandler):
    doc = None
    backed_up = False

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj), "application/json")

    def _file(self, path, ctype):
        if not os.path.exists(path):
            return self._send(404, "not built yet")
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype)

    def _fail(self, err):
        import traceback
        traceback.print_exc()
        msg = f"{type(err).__name__}: {err}".strip()
        if self.command == "POST":
            self._json(200, {"ok": False, "error": msg})
        else:
            self._send(200, "<!doctype html><meta charset=utf-8>"
                       "<style>body{font:14px -apple-system;padding:26px;color:#a8201a}</style>"
                       f"<h3>redpen hit a problem</h3><pre>{msg}</pre>")

    # ---- GET ----
    def do_GET(self):
        try:
            self._get()
        except Exception as err:
            self._fail(err)

    def _get(self):
        path = self.path.split("?")[0]
        doc = _H.doc
        d = preview_dir(doc)
        stem = _stem(doc)
        if path in ("/", "/index.html"):
            return self._send(200, build_page(doc))
        if path == "/pdf/quiz":
            return self._file(os.path.join(d, f"{stem}.pdf"), "application/pdf")
        if path == "/pdf/key":
            return self._file(os.path.join(d, f"{stem}-key.pdf"), "application/pdf")
        if path.startswith("/png/"):
            try:
                n = int(path.rsplit("/", 1)[1])
            except ValueError:
                return self._send(404, "no such page")
            pdf = os.path.join(d, f"{stem}.pdf")
            if not os.path.exists(pdf):
                return self._send(404, "not built yet")
            png = render.render_page(pdf, n, 150, render.cache_dir(d, "png"),
                                     force=True)
            return self._file(png, "image/png")
        self._send(404, "not found")

    # ---- POST ----
    def do_POST(self):
        try:
            self._post()
        except Exception as err:
            self._fail(err)

    def _post(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            raw = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError as e:
            return self._json(400, {"ok": False, "error": str(e)})
        if self.path not in ("/preview", "/build"):
            return self._send(404, "not found")
        self._json(200, post(_H.doc, raw, preview=self.path == "/preview"))


_backed_up = set()


def post(doc, raw, preview=True):
    """Save the edited source and rebuild.  Shared by the standalone composer
    and the app window, so both behave identically."""
    keep = {k: v for k, v in doc.items() if k.startswith("_")}
    merged = dict(raw)
    merged.update(keep)

    # Half an equation is not a mistake, it is someone mid-sentence.  A
    # preview of a field still being typed waits rather than flashing a
    # compiler error; only the explicit Build insists.
    pending = quizdoc.incomplete(merged)
    if not (pending and preview):
        try:
            quizdoc.validate(merged)
        except quizdoc.QuizError as err:
            return {"ok": False, "error": str(err)}

    # The source is the thing worth not losing, so it is written on every
    # pause -- with one copy of what was there when the session opened.
    src = doc["_path"]
    if src not in _backed_up:
        if os.path.exists(src):
            shutil.copy2(src, src + ".bak")
        _backed_up.add(src)
    doc.clear()
    doc.update(merged)
    quizdoc.save(doc)
    if pending and preview:
        return {"ok": True, "pending": f"{pending[0]}: {pending[1]}"}

    log = []
    try:
        if preview:
            r = typstbuild.generate(doc, preview_dir(doc), log=log.append)
        else:
            r = typstbuild.build(doc, log=log.append)
            typstbuild.generate(doc, preview_dir(doc), log=lambda *a: None)
            log.append(f"wrote {os.path.basename(r['config'])}")
    except Exception as err:            # a Typst error is a typo, not a crash
        return {"ok": False, "error": str(err).strip()}
    return {"ok": True, "zones": r["zones"], "pages": r["pages"],
            "log": [l.strip() for l in log if l.strip()]}


def _stem(doc):
    import re
    return re.sub(r"\.src\.json$|\.json$", "",
                  os.path.basename(doc["_path"])) or "quiz"


def free_port(start=8751):
    for p in range(start, start + 40):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)):
                return p
    raise RuntimeError("no free local port")


def serve(doc, open_browser=True, log=None):
    log = log or (lambda *a: print(*a, flush=True))
    _H.doc = doc
    port = free_port()
    srv = HTTPServer(("127.0.0.1", port), _H)        # loopback only
    url = f"http://127.0.0.1:{port}/"
    log(f"composer at {url}   (local only)")
    log(f"editing {doc['_path']}  —  saved as you type, Ctrl+C here to stop")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("\nstopped.")
    finally:
        srv.server_close()
