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


def new(template, pages, title=None, dpi=200):
    cfg = copy.deepcopy(DEFAULTS)
    cfg["template"] = template
    cfg["pages_per_student"] = int(pages)
    cfg["title"] = title or os.path.splitext(os.path.basename(template))[0]
    cfg["dpi"] = int(dpi)
    return cfg
