"""Roster loading, name scoring, and globally optimal sheet->student assignment.

Matching a handwritten name against a known class list is a 40-way choice, not
open-ended recognition, and every student sits exactly one sheet.  Solving it as
an assignment problem (rather than picking each sheet's best guess
independently) repairs the ambiguous reads: once the confident sheets claim
their names, the leftovers have only one plausible home.
"""
import csv, difflib, re, unicodedata

SKIP = {"points possible", "student", "name", "students", "student name"}


def fold(s):
    """Accent-free ASCII, so 'Renée' and 'Renee' agree and filenames stay portable."""
    return "".join(c for c in unicodedata.normalize("NFKD", s or "")
                   if not unicodedata.combining(c))


def load_roster(path, name_col=0, id_col=1, drop_test=True):
    out = []
    with open(path, newline="") as f:
        for row in csv.reader(f):
            if not row or len(row) <= name_col:
                continue
            raw = row[name_col].strip()
            if not raw or raw.lower() in SKIP:
                continue
            if drop_test and re.fullmatch(r"student,\s*test", raw, re.I):
                continue
            last, sep, first = raw.partition(",")
            if not sep:                       # "First Last" in the roster
                bits = raw.split()
                first, last = " ".join(bits[:-1]), bits[-1] if bits else raw
            sid = row[id_col].strip() if id_col is not None and len(row) > id_col else ""
            out.append({"display": raw, "first": first.strip(), "last": last.strip(),
                        "id": sid, "key": file_key(first, last)})
    return out


def file_key(first, last):
    """Last_First, accent-free and filename-safe."""
    f = re.sub(r"[^A-Za-z]", "", fold(first))
    l = re.sub(r"[^A-Za-z]", "", fold(last))
    return f"{l}_{f}" if f else (l or "student")


def custom_words(roster):
    w = set()
    for r in roster:
        w.update([r["first"], r["last"], fold(r["first"]), fold(r["last"]),
                  f"{r['first']} {r['last']}", f"{r['last']} {r['first']}"])
    return {x for x in w if x}


def _toks(s):
    return [t for t in re.split(r"[^A-Za-z]+", fold(s).lower()) if len(t) > 1]


def score(candidates, r):
    """Similarity in [0,1] between OCR candidates and one roster entry."""
    forms = [f"{r['first']} {r['last']}", f"{r['last']} {r['first']}",
             r["last"], r["first"]]
    best = 0.0
    for c in candidates:
        ct = _toks(c)
        if not ct:
            continue
        joined = " ".join(ct)
        for f in forms:
            ft = _toks(f)
            if not ft:
                continue
            best = max(best, difflib.SequenceMatcher(None, joined, " ".join(ft)).ratio())
            for a in ct:                      # a surname alone is strong evidence
                for b in ft:
                    if len(b) > 3:
                        best = max(best, 0.92 * difflib.SequenceMatcher(None, a, b).ratio())
    return best


def hungarian(cost):
    """Minimum-cost assignment, O(n^2 m).  rows <= cols.  Returns {row: col}."""
    n, m = len(cost), len(cost[0])
    INF = float("inf")
    u = [0.0] * (n + 1); v = [0.0] * (m + 1)
    p = [0] * (m + 1); way = [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i; j0 = 0
        minv = [INF] * (m + 1); used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0 = p[j0]; delta = INF; j1 = -1
            for j in range(1, m + 1):
                if used[j]:
                    continue
                cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur; way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]; j1 = j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta; v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]; p[j0] = p[j1]; j0 = j1
            if j0 == 0:
                break
    return {p[j] - 1: j - 1 for j in range(1, m + 1) if p[j]}


def assign(sheet_candidates, roster):
    """[[ocr strings]] x roster -> list of {roster, score, gap, alternatives}."""
    S = [[score(c, r) for r in roster] for c in sheet_candidates]
    if len(sheet_candidates) > len(roster):
        raise ValueError(f"{len(sheet_candidates)} sheets but only {len(roster)} "
                         "students on the roster")
    pick = hungarian([[1.0 - s for s in row] for row in S])
    out = []
    for i, row in enumerate(S):
        j = pick[i]
        ranked = sorted(range(len(roster)), key=lambda k: -row[k])
        runner = next((k for k in ranked if k != j), None)
        out.append({
            "roster": roster[j],
            "score": row[j],
            "gap": row[j] - (row[runner] if runner is not None else 0.0),
            "alternatives": [{"roster": roster[k], "score": row[k]} for k in ranked[:5]],
        })
    return out
