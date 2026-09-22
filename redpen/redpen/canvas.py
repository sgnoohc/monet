"""Turn a grading-page export into a CSV the Canvas gradebook will import.

Canvas matches an uploaded row to a student by its own ``ID`` column, so the
roster export — which is a Canvas gradebook export — is the source of truth for
every identity column, and the graded CSV supplies only the score.

Two details decide whether the upload lands where you meant it to:

* The assignment column keeps the ``(12345)`` suffix Canvas writes on it.
  Without the id Canvas cannot tell the column from a new assignment of the
  same name, and silently creates a second one.
* Students with no graded sheet are left out rather than written blank, so an
  absentee keeps whatever Canvas already holds until you decide otherwise.
  ``--missing zero`` writes the zero instead.
"""
import csv, os, re

from . import matching
from .stats import TOTAL

HEAD = ["Student", "ID", "SIS User ID", "SIS Login ID", "Section"]
ASSIGN = re.compile(r"^(.*?)\s*\((\d+)\)\s*$")
POINTS = "Points Possible"
YES = ("yes", "true", "1")


class CanvasError(Exception):
    pass


def _num(v):
    """Scores as Canvas likes them: 8 rather than 8.0, and '' for nothing."""
    s = str(v if v is not None else "").strip()
    if not s:
        return ""
    try:
        f = float(s)
    except ValueError:
        return s
    return str(int(f)) if f.is_integer() else str(f)


def _fold(s):
    """Letters only, accent-free, lowercase — so name order is the only variable."""
    return re.sub(r"[^a-z]", "", matching.fold(s or "").lower())


def gradebook(cfg, path_of, override=""):
    """The export the upload is built against.

    Deliberately not the roster.  The roster is chosen at 'init', to match
    handwritten names, and is usually taken before the assignment exists in
    Canvas — it cannot be expected to carry the assignment's code.  Point
    ``canvas_gradebook`` at an export taken after you made the assignment and
    the code is there; until then this falls back to the roster, which is
    right for a course whose assignment was already set up.
    """
    if override:
        return os.path.abspath(override), "--gradebook"
    if cfg.get("canvas_gradebook"):
        return path_of(cfg, "canvas_gradebook"), "canvas_gradebook"
    return path_of(cfg, "roster"), "roster"


# ---- the roster's own assignment columns ---------------------------------

def assignments(roster_path):
    """Assignment columns of a Canvas export: [{header, name, id, points}]."""
    with open(roster_path, newline="") as f:
        rows = csv.reader(f)
        head = next(rows, [])
        second = next(rows, [])
    out = []
    for i, h in enumerate(head):
        m = ASSIGN.match(h.strip())
        if not m:
            continue
        pts = second[i].strip() if len(second) > i else ""
        if second and second[0].strip().lower() != POINTS.lower():
            pts = ""
        out.append({"header": h.strip(), "name": m.group(1).strip(),
                    "id": m.group(2), "points": pts})
    return out


def column(roster_path, wanted):
    """Resolve an assignment name against the roster's columns.

    Returns ``(header, existing)``.  A unique match reuses Canvas's own header,
    id and all, so the scores land on the assignment that is already there.
    Anything else passes through unchanged and Canvas creates a new assignment.
    """
    want = (wanted or "").strip()
    if not want:
        raise CanvasError("no assignment name — pass --assignment")
    if ASSIGN.match(want):                     # already "Name (12345)"
        return want, True
    cands = assignments(roster_path) if os.path.exists(roster_path) else []
    for pick in ([c for c in cands if c["name"].lower() == want.lower()],
                 [c for c in cands if want.lower() in c["name"].lower()]):
        if len(pick) == 1:
            return pick[0]["header"], True
        if len(pick) > 1:
            raise CanvasError(f"{want!r} matches {len(pick)} roster columns: "
                              + ", ".join(c["header"] for c in pick)
                              + " — name one of them exactly")
    return want, False


def points_of(roster_path, header):
    """The roster's Points Possible for a column, or '' if it is a new one."""
    for c in assignments(roster_path):
        if c["header"] == header:
            return c["points"]
    return ""


# ---- the graded export ----------------------------------------------------

def read_grades(path, only_reviewed=False):
    """Rows of a grading-page export: [{sheet, name, id, total, reviewed}]."""
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    if len(rows) < 2:
        raise CanvasError(f"{os.path.basename(path)} has no data rows")
    head = [h.strip() for h in rows[0]]
    ti = next((i for i, h in enumerate(head) if TOTAL.match(h)), None)
    if ti is None:
        raise CanvasError("no 'Total /N' column — is this a grading-page export?")
    out_of = float(TOTAL.match(head[ti]).group(1))
    col = lambda n: head.index(n) if n in head else None       # noqa: E731
    si, ni, ii, ri = col("Sheet"), col("Name"), col("ID"), col("Reviewed")
    get = lambda r, i: r[i].strip() if i is not None and len(r) > i else ""  # noqa: E731

    out, unreviewed = [], 0
    for r in rows[1:]:
        if not r or len(r) <= ti or not r[ti].strip():
            continue
        rev = get(r, ri).lower() in YES if ri is not None else True
        if not rev:
            unreviewed += 1
            if only_reviewed:
                continue
        out.append({"sheet": get(r, si), "name": get(r, ni), "id": get(r, ii),
                    "total": r[ti].strip(), "reviewed": rev})
    if not out:
        raise CanvasError("no graded rows"
                          + (" marked Reviewed = yes" if only_reviewed else ""))
    return out, out_of, unreviewed


# ---- graded row -> roster entry -------------------------------------------

def match_roster(rows, roster):
    """Pair each graded row with a roster entry.

    Returns ``(pairs, unmatched, clashes)``: pairs in roster order, rows whose
    student could not be found, and students claimed by more than one sheet —
    a duplicate that must be settled in 'verify' before anything is uploaded.
    """
    by_id, by_name = {}, {}
    for r in roster:
        for k in (r.get("id"), r.get("sis_id"), r.get("login")):
            if k:
                by_id.setdefault(k.strip().lower(), r)
        for form in (r["display"], f"{r['first']} {r['last']}",
                     f"{r['last']} {r['first']}"):
            by_name.setdefault(_fold(form), r)

    seen, pairs, unmatched = {}, [], []
    for row in rows:
        hit = by_id.get(row["id"].lower()) if row["id"] else None
        if hit is None:
            hit = by_name.get(_fold(row["name"]))
        if hit is None:
            unmatched.append(row)
            continue
        seen.setdefault(id(hit), []).append((row, hit))

    clashes = [v for v in seen.values() if len(v) > 1]
    order = {id(r): i for i, r in enumerate(roster)}
    for v in seen.values():
        if len(v) == 1:
            pairs.append(v[0])
    pairs.sort(key=lambda p: order.get(id(p[1]), 0))
    return pairs, unmatched, clashes


def ungraded(pairs, roster):
    """Roster students no sheet was graded for."""
    got = {id(r) for _, r in pairs}
    return [r for r in roster if id(r) not in got]


# ---- the upload ------------------------------------------------------------

def scale(raw, paper, target, step=0):
    """A mark out of ``paper`` expressed out of ``target``.

    ``step`` snaps the result to a grid — 0.5 for half marks, 1 for whole ones.
    Rounding happens once, on the scaled figure, so the marks a student can see
    add up to what Canvas shows rather than to a rounded-then-scaled total.
    """
    if paper in (None, 0) or target is None:
        return raw
    v = float(raw) * float(target) / float(paper)
    if step:
        v = round(v / float(step)) * float(step)
    return round(v, 4)


def rows_for(pairs, header, points, zeros=(), paper=None, step=0):
    """The full CSV as a list of rows, Points Possible included.

    ``paper`` is the total the sheets were marked out of; when it differs from
    ``points`` every score is scaled across.
    """
    val = lambda t: _num(scale(t, paper, points, step) if paper else t)  # noqa: E731
    out = [HEAD + [header], [POINTS, "", "", "", "", _num(points)]]
    for row, r in pairs:
        out.append([r["display"], r.get("id", ""), r.get("sis_id", ""),
                    r.get("login", ""), r.get("section", ""), val(row["total"])])
    for r in zeros:
        out.append([r["display"], r.get("id", ""), r.get("sis_id", ""),
                    r.get("login", ""), r.get("section", ""), "0"])
    return out


def write(rows, dest):
    with open(dest, "w", newline="") as f:
        csv.writer(f, quoting=csv.QUOTE_MINIMAL).writerows(rows)
    return dest
