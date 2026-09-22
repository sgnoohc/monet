"""The quizzes the app knows about, and where it keeps its own settings.

The library is a view over folders you already have -- your quizzes stay in
OneDrive, or wherever you keep them, under the names you gave them, and the
command line goes on working on exactly the same files.  Nothing is imported
and there is no second copy to get out of step.
"""
import glob, hashlib, json, os, time

APP = "redpen"
SETTINGS = {
    "folders": [],          # absolute paths the sidebar lists quizzes from
    "last": "",             # id of the quiz open when the app last closed
}


def support_dir():
    d = os.path.expanduser(f"~/Library/Application Support/{APP}")
    os.makedirs(d, exist_ok=True)
    return d


def settings_path():
    return os.path.join(support_dir(), "settings.json")


def load_settings():
    s = dict(SETTINGS)
    try:
        with open(settings_path()) as f:
            s.update(json.load(f))
    except (OSError, ValueError):
        pass
    s["folders"] = [f for f in s["folders"] if isinstance(f, str)]
    return s


def save_settings(s):
    path = settings_path()
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump({k: s.get(k, v) for k, v in SETTINGS.items()}, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    return path


def quiz_id(path):
    """Stable across runs, and safe in a URL."""
    return hashlib.sha1(os.path.abspath(path).encode()).hexdigest()[:12]


def _is_config(path):
    """A redpen grading config, as opposed to any other JSON lying about."""
    try:
        with open(path) as f:
            d = json.load(f)
        return isinstance(d, dict) and ("zones" in d or "parts" in d)
    except (OSError, ValueError):
        return False


def _read(path, keys):
    try:
        with open(path) as f:
            d = json.load(f)
        return {k: d.get(k) for k in keys}
    except (OSError, ValueError):
        return {}


def scan_folder(folder):
    """Every quiz in one folder, keyed by stem.

    A quiz is a stem with a source, a grading config, or both: one written in
    the composer has both, one whose zones were drawn by hand has only the
    config, and both belong in the list.
    """
    folder = os.path.abspath(os.path.expanduser(folder))
    found = {}
    if not os.path.isdir(folder):
        return []
    for src in sorted(glob.glob(os.path.join(folder, "*.src.json"))):
        stem = os.path.basename(src)[: -len(".src.json")]
        found.setdefault(stem, {})["src"] = src
    for cfg in sorted(glob.glob(os.path.join(folder, "*.json"))):
        if cfg.endswith(".src.json") or not _is_config(cfg):
            continue
        stem = os.path.basename(cfg)[: -len(".json")]
        found.setdefault(stem, {})["config"] = cfg

    out = []
    for stem, paths in sorted(found.items()):
        src, cfg = paths.get("src"), paths.get("config")
        meta = _read(src, ("title", "pages", "problems")) if src else {}
        cmeta = _read(cfg, ("title", "parts", "roster")) if cfg else {}
        pdf = os.path.join(folder, stem + ".pdf")
        parts = cmeta.get("parts") or []
        out.append({
            "id": quiz_id(src or cfg),
            "stem": stem,
            "dir": folder,
            "title": meta.get("title") or cmeta.get("title") or stem,
            "src": src,
            "config": cfg,
            "pdf": pdf if os.path.exists(pdf) else "",
            "problems": len([q for q in (meta.get("problems") or [])
                             if not q.get("off")]),
            "parts": len(parts),
            "points": round(sum(float(p.get("points", 0)) for p in parts), 2),
            "graded": os.path.isdir(os.path.join(folder, "students")),
            "authored": bool(src),
            "mtime": max([os.path.getmtime(p) for p in (src, cfg) if p] or [0]),
        })
    return out


def folder_note(folder):
    """Why a folder you added is showing nothing.

    Pointing redpen at a folder of quizzes it did not make is the obvious first
    move, and an empty list with no explanation looks like a bug rather than a
    fact about the folder.
    """
    folder = os.path.abspath(os.path.expanduser(folder))
    if not os.path.isdir(folder):
        return "that folder is not there any more"
    if scan_folder(folder):
        return ""
    pdfs = len(glob.glob(os.path.join(folder, "*.pdf")))
    typs = len(glob.glob(os.path.join(folder, "*.typ")))
    if pdfs or typs:
        bits = []
        if pdfs:
            bits.append(f"{pdfs} PDF" + ("s" if pdfs != 1 else ""))
        if typs:
            bits.append(f"{typs} Typst file" + ("s" if typs != 1 else ""))
        return (f"{' and '.join(bits)} here, but no redpen quiz yet — "
                "New quiz writes one, or `redpen init` draws zones on a PDF "
                "you already have")
    return "nothing here yet"


def scan(settings=None):
    s = settings or load_settings()
    seen, out = set(), []
    for folder in s["folders"]:
        for q in scan_folder(folder):
            if q["id"] in seen:
                continue
            seen.add(q["id"])
            out.append(q)
    out.sort(key=lambda q: -q["mtime"])
    return out


def find(qid, settings=None):
    for q in scan(settings):
        if q["id"] == qid:
            return q
    return None


def suggest_folders():
    """Places a quiz folder is likely to be, offered when there are none yet."""
    home = os.path.expanduser("~")
    pats = [
        os.path.join(home, "OneDrive*", "**", "Quiz*"),
        os.path.join(home, "Documents", "**", "Quiz*"),
        os.path.join(home, "Desktop", "**", "Quiz*"),
    ]
    out = []
    for p in pats:
        for d in glob.glob(p, recursive=True):
            if os.path.isdir(d) and len(out) < 12:
                if glob.glob(os.path.join(d, "*.json")) or glob.glob(os.path.join(d, "*.typ")):
                    out.append(d)
    return sorted(set(out))
