"""Config for redpen: zone geometry + grading scheme, as plain JSON.

Rectangles are fractions of the page ([x, y, w, h], origin top-left), so a
config survives any change of render DPI or paper size.
"""
import copy, json, os

DEFAULTS = {
    "title": "Quiz",
    "template": "",            # the BLANK quiz the students wrote on
    "key_pdf": "",             # optional answer key, for reading expected answers
    "pages_per_student": 1,
    "dpi": 200,                # render dpi for zone crops shown while grading
    "ocr_dpi": 400,            # render dpi for the name zone (higher = better OCR)
    "roster": "",
    "roster_name_column": 0,
    "roster_id_column": 1,
    "name_zone": None,         # id of the zone holding the student's name
    "canvas_assignment": "",   # Canvas assignment column to upload into (default: title)
    "canvas_gradebook": "",    # gradebook export holding that column (default: roster)
    "canvas_out_of": None,     # scale scores to this Canvas total (default: the paper's)
    "canvas_round": 0,         # snap scaled scores to this step (0.5 = half marks)
    "zones": [],               # {id, page, rect, kind: name|answer}
    "parts": [],               # {id, label, key, points, zones: [...]}
    "review_gap": 0.10,        # assignment margin below which a sheet is reviewed
    "review_score": 0.55,      # absolute score below which a sheet is reviewed
}


class ConfigError(Exception):
    pass


def load(path):
    with open(path) as f:
        raw = json.load(f)
    cfg = copy.deepcopy(DEFAULTS)
    cfg.update(raw)
    cfg["_path"] = os.path.abspath(path)
    cfg["_dir"] = os.path.dirname(cfg["_path"])
    validate(cfg)
    return cfg


def save(cfg, path=None):
    path = path or cfg["_path"]
    out = {k: v for k, v in cfg.items() if not k.startswith("_")}
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(out, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    return path


def validate(cfg):
    if cfg["pages_per_student"] < 1:
        raise ConfigError("pages_per_student must be at least 1")
    seen = set()
    for z in cfg["zones"]:
        for k in ("id", "page", "rect"):
            if k not in z:
                raise ConfigError(f"zone is missing '{k}': {z}")
        if z["id"] in seen:
            raise ConfigError(f"duplicate zone id: {z['id']}")
        seen.add(z["id"])
        if not (1 <= z["page"] <= cfg["pages_per_student"]):
            raise ConfigError(f"zone {z['id']}: page {z['page']} is outside "
                              f"1..{cfg['pages_per_student']}")
        r = z["rect"]
        if len(r) != 4 or r[2] <= 0 or r[3] <= 0:
            raise ConfigError(f"zone {z['id']}: rect must be [x, y, w, h] with w, h > 0")
        z.setdefault("kind", "answer")
    if cfg["name_zone"] and cfg["name_zone"] not in seen:
        raise ConfigError(f"name_zone '{cfg['name_zone']}' is not a zone")
    for p in cfg["parts"]:
        if "id" not in p:
            raise ConfigError(f"part is missing 'id': {p}")
        p.setdefault("label", p["id"])
        p.setdefault("key", "")
        p["points"] = float(p.get("points", 1))
        p.setdefault("auto", True)
        p["zones"] = [z for z in p.get("zones", []) if z in seen]
    return cfg


def answer_zones(cfg):
    return [z for z in cfg["zones"] if z["id"] != cfg.get("name_zone")]


def total_points(cfg):
    return sum(p["points"] for p in cfg["parts"])


def path_of(cfg, key):
    v = cfg.get(key) or ""
    if not v:
        return ""
    return v if os.path.isabs(v) else os.path.normpath(os.path.join(cfg["_dir"], v))


def store_name(title):
    """The grading page's file stem and browser-storage key for a quiz."""
    return "".join(c if c.isalnum() else "_" for c in title or "").strip("_") or "quiz"


# Which grading config the students/ folder beside it was split for.  Quizzes
# that share a folder share its split output, so without this every quiz in
# the folder looked scanned as soon as one of them was.
SPLIT_MARK = "split.json"


def split_owner(out_dir):
    """Basename of the config the last split in `out_dir` used, or None."""
    try:
        with open(os.path.join(out_dir, SPLIT_MARK)) as f:
            return json.load(f).get("config") or None
    except (OSError, ValueError, AttributeError):
        return None


def mark_split(cfg, out_dir):
    with open(os.path.join(out_dir, SPLIT_MARK), "w") as f:
        json.dump({"config": os.path.basename(cfg["_path"])}, f)
        f.write("\n")


def split_is_for(cfg, out_dir):
    """Whether the split output in `out_dir` belongs to this quiz.

    A split made before the marker existed is taken to be this quiz's when it
    is the only config there, or when its grading page was built.
    """
    if not os.path.exists(os.path.join(out_dir, "split_report.csv")):
        return False
    owner = split_owner(out_dir)
    if owner:
        return owner == os.path.basename(cfg["_path"])
    return os.path.exists(os.path.join(out_dir, store_name(cfg.get("title")) + "_grading.html"))


def new(template, pages, title=None, dpi=200):
    cfg = copy.deepcopy(DEFAULTS)
    cfg["template"] = template
    cfg["pages_per_student"] = int(pages)
    cfg["title"] = title or os.path.splitext(os.path.basename(template))[0]
    cfg["dpi"] = int(dpi)
    return cfg
