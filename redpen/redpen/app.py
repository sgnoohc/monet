"""The redpen app: one window over the whole term's marking.

A single local server.  The sidebar lists the quizzes found in the folders you
point it at; the pane beside it is whichever step you are on.  The composer is
mounted in-process; the zone editor and the verifier are the existing pages,
started on their own loopback ports and shown in a frame, unchanged.

Everything still runs here.  Nothing is uploaded, and the command line keeps
working on exactly the same files.
"""
import json, mimetypes, os, socket, subprocess, threading, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import (autograde, canvas, composer, config, gradepage, library, matching, quizdoc,
               render, reviewpage, split, typstbuild, zoneeditor)
from .ui_app import CSS, JS

_docs = {}          # qid -> the loaded quiz source, kept between requests
_sub = {}           # (qid, kind) -> url of a spawned editor


def page():
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>redpen</title><style>{CSS}</style></head><body>
<div class="wrap">
 <div class="side">
  <div class="brand"><span class="dot"></span>redpen</div>
  <h4>Quizzes</h4>
  <ul class="qs" id="qs"></ul>
  <div class="foot">
   <button id="newquiz" class="pri">New quiz</button>
   <button id="managefolders">Folders</button>
  </div>
 </div>

 <div class="main">
  <div class="top">
   <span class="name" id="qname"></span><span id="qmeta"></span>
   <span class="grow"></span>
   <div class="tabs" id="tabs">
    <button data-t="compose" data-need="src">Compose</button>
    <button data-t="build" data-need="src">Build</button>
    <button data-t="zones" data-need="cfg">Zones</button>
    <button data-t="scan" data-need="cfg">Scan</button>
    <button data-t="verify" data-need="cfg">Verify</button>
    <button data-t="autograde" data-need="cfg">Autograde</button>
    <button data-t="grade" data-need="cfg">Grade</button>
    <button data-t="canvas" data-need="cfg">Canvas</button>
   </div>
  </div>
  <div class="body">
   <iframe id="frame" style="display:none"></iframe>

   <div class="panel hide" id="panel-folders">
    <div class="card">
     <h3>Where your quizzes live</h3>
     <p>Point redpen at the folders you already keep quizzes in. Your files stay
      where they are — nothing is copied, and the command line goes on working
      on the same paths.</p>
     <div class="row"><input type="text" class="path" id="folderpath"
        placeholder="/Users/you/OneDrive/…/Quizzes"><button class="pri" id="addfolder">Add</button><button class="nat" id="browsefolder">Browse…</button></div>
     <div class="sug hint" id="sug"></div>
     <ul class="flist" id="flist"></ul>
    </div>
   </div>

   <div class="panel hide" id="panel-new">
    <div class="card">
     <h3>New quiz</h3>
     <p>A source file is written in the folder you choose, and the composer opens
      on it. Nothing else is created until you press Build.</p>
     <label class="hint">Title
      <input type="text" class="path" id="newtitle"
       placeholder="PHY2060 Quiz 2 — Newton's Laws"></label>
     <label class="hint">Folder <select id="newfolder"></select></label>
     <div class="row" style="margin-top:10px">
      <button class="pri" id="newgo">Create</button>
      <button id="newcancel">Cancel</button>
      <span id="newerr" class="hint"></span></div>
    </div>
   </div>

   <div class="panel hide" id="panel-none">
    <div class="empty"><h2>No quiz selected</h2>
     <p>Pick one on the left, or make a new one.</p></div>
   </div>

   <div class="panel hide" id="panel-step">
    <div class="card">
     <h3 id="step-h"></h3><p id="step-p"></p>
     <div id="step-extra"></div>
     <div class="row"><button class="pri" id="step-go"></button></div>
     <div class="log" id="step-log"></div>
    </div>
   </div>
  </div>
 </div>
</div>
<script>{JS}</script></body></html>"""


def _notice(head, body):
    return ("<!doctype html><meta charset=utf-8>"
            "<style>body{font:14px -apple-system;padding:26px;color:#444;max-width:520px}"
            "h3{margin:0 0 6px}</style>"
            f"<h3>{head}</h3><p>{body}</p>")


def _doc(q):
    """The quiz source, loaded once and kept so edits accumulate in memory."""
    d = _docs.get(q["id"])
    if d is None or d.get("_path") != q["src"]:
        d = quizdoc.load(q["src"])
        _docs[q["id"]] = d
    return d


def _spawn(q, kind):
    """Start one of the existing editors on its own port, once per quiz."""
    key = (q["id"], kind)
    if key in _sub:
        return _sub[key]
    cfg = config.load(q["config"])
    if kind == "zones":
        port = zoneeditor.free_port()
        zoneeditor._H.cfg = cfg
        srv = zoneeditor.HTTPServer(("127.0.0.1", port), zoneeditor._H)
    else:
        out_dir = cfg["_dir"]
        reviewpage.read_rows(out_dir)           # raises if there is nothing to verify
        port = zoneeditor.free_port()
        reviewpage._H.cfg = cfg
        reviewpage._H.out_dir = out_dir
        srv = zoneeditor.HTTPServer(("127.0.0.1", port), reviewpage._H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _sub[key] = f"http://127.0.0.1:{port}/"
    return _sub[key]


def set_roster(q, body):
    """Point the grading config at the class list.

    Read before it is stored, so a wrong file is refused here rather than
    failing later inside the split with a scan already half-processed.
    """
    given = (body.get("path") or "").strip()
    if not q["config"]:
        return {"ok": False, "error": "no grading config yet — build the quiz first"}
    if not given:
        return {"ok": False, "error": "choose the roster CSV"}
    path = os.path.realpath(os.path.expanduser(given))
    if not os.path.isfile(path):
        return {"ok": False, "error": f"no such file: {given}"}
    cfg = config.load(q["config"])
    try:
        roster = matching.load_roster(path, cfg["roster_name_column"], cfg["roster_id_column"])
    except Exception as err:
        return {"ok": False, "error": f"could not read that as a roster: {err}"}
    if not roster:
        return {"ok": False, "error": "no students in that file"}
    # Relative to the config when it is nearby, as build does for the PDFs, so
    # the course folder can move as a whole; absolute when it is somewhere else.
    rel = os.path.relpath(path, os.path.realpath(cfg["_dir"]))
    climbs = len([s for s in rel.split(os.sep) if s == os.pardir])
    cfg["roster"] = rel if climbs <= 3 else path
    config.save(cfg)
    return {"ok": True, "roster": cfg["roster"], "students": len(roster)}


def run_step(q, name, body):
    """One step of the workflow.  Returns {log: [...]} and maybe a url."""
    log = []
    if name == "build":
        if not q["src"]:
            return {"log": ["this quiz has no source — its zones were drawn by hand"]}
        r = typstbuild.build(_doc(q), log=log.append)
        log.append(f"wrote {os.path.basename(r['config'])}")
        return {"log": log}

    if not q["config"]:
        return {"log": ["no grading config yet — build the quiz first"]}
    cfg = config.load(q["config"])

    if name in ("zones", "verify"):
        return {"url": _spawn(q, name),
                "log": [f"opened the {'zone editor' if name=='zones' else 'verifier'}"]}

    if name == "scan":
        scans = [os.path.abspath(os.path.expanduser(s)) for s in body.get("scans", [])]
        missing = [s for s in scans if not os.path.exists(s)]
        if not scans:
            return {"log": ["give at least one scan PDF"]}
        if missing:
            return {"log": ["no such file: " + m for m in missing]}
        if not cfg.get("name_zone"):
            return {"log": ["no name zone — build or draw the zones first"]}
        if not config.path_of(cfg, "roster"):
            return {"log": ["no roster set — choose the class list above, then Split"]}
        sheets, roster = split.gather(cfg, scans, log=log.append)
        sheets = split.resolve(cfg, sheets, roster, log=log.append)
        rows = split.write_outputs(cfg, sheets, cfg["_dir"], log=log.append)
        flagged = [r for r in rows if r["review"]]
        log.append(f"{len(rows)} sheets written")
        if flagged:
            log.append(f"warning: {len(flagged)} need review — open Verify")
        return {"log": log}

    if name == "autograde":
        # The same pass the CLI runs: OCR every answer box against its key and
        # mark it green / red / amber.  Suggestions only; the grading page
        # shows the text each verdict came from and every mark stays yours.
        if not os.path.exists(os.path.join(cfg["_dir"], "split_report.csv")):
            return {"log": ["nothing split yet — run Scan first"]}
        missing = [p["id"] for p in cfg["parts"] if p.get("auto", True) and not p.get("key")]
        if missing:
            log.append(f"warning: no answer key for {', '.join(missing)} — "
                       "those parts will read as unsure")
        dest, tally = autograde.run(cfg, cfg["_dir"], log=log.append)
        total = sum(tally.values()) or 1
        log.append(f"wrote {os.path.basename(dest)}")
        for k in ("correct", "wrong", "unsure", "skip"):
            if tally.get(k):
                log.append(f"  {k:<8} {tally[k]:>5}  ({100 * tally[k] / total:.0f}%)")
        log.append("suggestions only — the grading page shows the text each came from")
        return {"log": log}

    if name == "grade":
        if not cfg["parts"]:
            return {"log": ["no graded parts — build the quiz, or set them in Zones"]}
        dest, n = gradepage.build(cfg, cfg["_dir"], log=log.append)
        subprocess.run(["open", dest], check=False)
        log.append(f"opened {os.path.basename(dest)} — {n} sheets")
        return {"log": log}

    if name == "canvas":
        subprocess.run(["open", cfg["_dir"]], check=False)
        return {"log": ["The grading page writes the Canvas CSV with its own button.",
                        "Opened the quiz folder so you can find the export."]}
    return {"log": [f"unknown step {name}"]}


class _H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

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

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj), "application/json")

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return {}

    # ---- GET ----
    def do_GET(self):
        # Anything unhandled here would close the socket with no reply, and the
        # page would simply stop working with nothing to read.  An error you
        # can see beats a window that has gone quiet.
        try:
            self._get()
        except Exception as err:
            self._fail(err)

    def _fail(self, err):
        import traceback
        traceback.print_exc()
        msg = f"{type(err).__name__}: {err}".strip()
        if self.path.startswith("/api/") or self.command == "POST":
            self._json({"ok": False, "error": msg, "log": [f"error: {msg}"]}, 200)
        else:
            self._send(200, "<!doctype html><meta charset=utf-8>"
                       "<style>body{font:14px -apple-system;padding:26px;color:#a8201a}</style>"
                       f"<h3>redpen hit a problem</h3><pre>{msg}</pre>")

    def _get(self):
        p = self.path.split("?")[0]
        if p in ("/", "/index.html"):
            return self._send(200, page())
        if p == "/api/library":
            s = library.load_settings()
            quizzes = library.scan(s)
            return self._json({"folders": s["folders"], "quizzes": quizzes,
                               "notes": {f: library.folder_note(f) for f in s["folders"]}
                               if not quizzes else {},
                               "suggestions": library.suggest_folders()
                               if not s["folders"] else []})
        if p.startswith("/q/"):
            return self._quiz_get(p)
        self._send(404, "not found")

    def _quiz_get(self, p):
        parts = p.strip("/").split("/")          # q / <id> / <what> [/ arg]
        q = library.find(parts[1]) if len(parts) > 2 else None
        if not q:
            return self._send(404, "no such quiz")
        what = parts[2]
        if what == "grading":
            # Built fresh on every visit -- it is cheap, and the page holds no
            # state of its own: progress lives in the browser and in the
            # progress file.  Served from under /files/ so the page's relative
            # image paths (students/<name>/1a.png) resolve to the quiz folder.
            if not q["config"]:
                return self._send(404, "no grading config yet — build the quiz first")
            cfg = config.load(q["config"])
            if not os.path.exists(os.path.join(cfg["_dir"], "split_report.csv")):
                return self._send(200, _notice("Nothing split yet",
                                  "Run <b>Scan</b> first; the grading page is built "
                                  "from the sheets it cuts out."))
            if not cfg["parts"]:
                return self._send(200, _notice("No graded parts",
                                  "Build the quiz, or set the parts in <b>Zones</b>."))
            dest, _n = gradepage.build(cfg, cfg["_dir"], log=lambda *a: None)
            rel = os.path.relpath(dest, cfg["_dir"]).replace(os.sep, "/")
            # HTTP/1.1 keep-alive: without a Content-Length the client waits
            # for a body that never comes.
            self.send_response(302)
            self.send_header("Location", f"/q/{q['id']}/files/{rel}")
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        if what == "files":
            # Anything in the quiz folder, and only the quiz folder.
            root = os.path.realpath(q["dir"])
            target = os.path.realpath(os.path.join(root, *parts[3:]))
            if not target.startswith(root + os.sep) or not os.path.isfile(target):
                return self._send(404, "not found")
            return self._file(target)
        if what == "compose":
            if not q["src"]:
                return self._send(404, "this quiz has no source")
            return self._send(200, composer.build_page(_doc(q), base=f"/q/{q['id']}"))
        d = composer.preview_dir(_doc(q)) if q["src"] else None
        if what == "pdf" and d:
            name = f"{q['stem']}.pdf" if parts[3] == "quiz" else f"{q['stem']}-key.pdf"
            return self._file(os.path.join(d, name))
        if what == "png" and d:
            pdf = os.path.join(d, f"{q['stem']}.pdf")
            if not os.path.exists(pdf):
                return self._send(404, "not built yet")
            png = render.render_page(pdf, int(parts[3]), 150,
                                     render.cache_dir(d, "png"), force=True)
            return self._file(png)
        self._send(404, "not found")

    def _file(self, path):
        if not os.path.exists(path):
            return self._send(404, "not found")
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype)

    # ---- POST ----
    def do_POST(self):
        try:
            self._post()
        except Exception as err:
            self._fail(err)

    def _post(self):
        p = self.path.split("?")[0]
        body = self._body()
        if p == "/api/folders":
            s = library.load_settings()
            if body.get("add"):
                d = os.path.realpath(os.path.expanduser(body["add"]))
                if not os.path.isdir(d):
                    return self._json({"ok": False, "error": f"no such folder: {d}"})
                if d not in s["folders"]:
                    s["folders"].append(d)
            if body.get("remove"):
                s["folders"] = [f for f in s["folders"] if f != body["remove"]]
            library.save_settings(s)
            return self._json({"ok": True})
        if p == "/api/new":
            return self._json(self._new(body))
        if p.startswith("/q/"):
            return self._quiz_post(p, body)
        self._send(404, "not found")

    def _new(self, body):
        folder = body.get("folder") or ""
        title = (body.get("title") or "").strip()
        if not os.path.isdir(folder):
            return {"ok": False, "error": "add a quiz folder first"}
        if not title:
            return {"ok": False, "error": "give the quiz a title"}
        stem = quizdoc.slug(title).replace("_", "-") or "quiz"
        path = os.path.join(folder, stem + ".src.json")
        n = 2
        while os.path.exists(path):
            path = os.path.join(folder, f"{stem}-{n}.src.json")
            n += 1
        doc = quizdoc.new(title)
        doc["problems"] = [{
            "title": "First problem", "points": 100, "page": 1,
            "stem": "Say what the situation is.",
            "parts": [{"question": "Ask for something.",
                       "boxes": [{"label": "answer", "answer": ""}], "solution": []}]}]
        doc["_path"], doc["_dir"] = path, folder
        quizdoc.save(doc, path)
        return {"ok": True, "id": library.quiz_id(path)}

    def _quiz_post(self, p, body):
        parts = p.strip("/").split("/")
        q = library.find(parts[1]) if len(parts) > 2 else None
        if not q:
            return self._json({"ok": False, "error": "no such quiz"})
        what = parts[2]
        if what in ("preview", "build") and q["src"]:
            return self._json(composer.post(_doc(q), body, preview=what == "preview"))
        if what == "roster":
            return self._json(set_roster(q, body))
        if what == "step":
            try:
                return self._json({"ok": True, **run_step(q, parts[3], body)})
            except Exception as err:
                return self._json({"ok": False, "error": str(err).strip(),
                                   "log": [f"error: {str(err).strip()}"]})
        self._json({"ok": False, "error": "not found"})


def free_port(start=8761):
    for p in range(start, start + 40):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)):
                return p
    raise RuntimeError("no free local port")


def serve(open_browser=True, port=None, log=None):
    log = log or (lambda *a: print(*a, flush=True))
    # The window reserves a port and hands it over; if something grabbed it in
    # between, find another rather than refusing to start.
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port or free_port()), _H)
    except OSError:
        port = free_port()
        srv = ThreadingHTTPServer(("127.0.0.1", port), _H)   # loopback only
    port = srv.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    log(f"redpen at {url}   (local only)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("\nstopped.")
    finally:
        srv.server_close()
    return url
