"""Preliminary right/wrong marking from OCR.

Each answer zone is read on-device and compared with the expected answer for
its part.  The result is a suggestion, not a grade: handwriting OCR is good but
not certain, so every verdict is shown next to the text it was based on, and a
part that cannot be read confidently is marked 'unsure' rather than guessed.

Key format
    " / "  (with spaces) separates the zones of a multi-box part, in zone order.
           The spaces matter: a bare "/" also appears inside units like m/s.
    " | "  separates acceptable alternatives for one box
e.g.  "12.0 s / 216 m"        two boxes
      "720 m | 726.53 m"      either value accepted
"""
import json, os, re

from . import ocr

NUM = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def numbers(s):
    out = []
    for m in NUM.finditer((s or "").replace(",", "")):
        try:
            out.append(float(m.group()))
        except ValueError:
            pass
    return out


def units(s):
    t = (s or "").lower()
    t = re.sub(r"[^a-z/]", " ", t)
    return {w for w in t.split() if w and w not in ("x", "e")}


def close(a, b, rel=0.02, absol=0.05):
    return abs(a - b) <= max(absol, rel * max(abs(a), abs(b)))


# Vision reliably renders a trailing unit letter as the digit it looks like:
# "15 s" comes back "155", "400 m" occasionally "4000".  We know which unit to
# expect from the key, so undo exactly that, rather than mangling text blindly.
UNIT_TWIN = {"s": "5", "o": "0", "l": "1", "i": "1", "b": "6", "z": "2", "g": "9"}


def _digits(x):
    return re.sub(r"\D", "", f"{x:g}")


def _unit_twin_match(student_text, want, unit):
    """True if the student's number is `want` with the unit read as a digit."""
    first = (unit or "").strip().lower()[:1]
    twin = UNIT_TWIN.get(first)
    if not twin:
        return False
    for m in NUM.finditer(student_text or ""):
        tok = m.group()
        if tok.endswith(twin) and len(re.sub(r"\D", "", tok)) > 1:
            try:
                trimmed = float(tok[:-1].rstrip("."))
            except ValueError:
                continue
            if close(trimmed, want):
                return True
    return False


def _near(student_nums, want):
    """Could this plausibly be `want` misread — a stray or missing digit?"""
    w = _digits(want)
    if not w:
        return False
    for s in student_nums:
        d = _digits(s)
        if d and (w in d or d in w):
            return True
    return False


def compare_one(student, expected):
    """-> 'correct' | 'wrong' | 'unsure' for a single box.

    Conservative on purpose: anything that might be the right answer misread
    comes back 'unsure' rather than 'wrong', because a wrongly-green box
    inflates a grade while a wrongly-amber one only costs a glance.
    """
    if not (student or "").strip():
        return "unsure"
    alts = [a.strip() for a in expected.split("|")] if expected else []
    if not any(alts):
        return "unsure"

    sn = numbers(student)
    for alt in alts:
        en = numbers(alt)
        if not en:                                   # non-numeric key: compare words
            if units(alt) and units(alt) <= units(student):
                return "correct"
            continue
        unit = re.sub(r"[\d.\s]+", " ", alt).strip()
        if all(any(close(e, s) for s in sn) or _unit_twin_match(student, e, unit)
               for e in en):
            return "correct"
    if not sn:
        return "unsure"
    for alt in alts:
        en = numbers(alt)
        if en and all(_near(sn, e) for e in en):
            return "unsure"
    return "wrong"


def compare_part(part, texts):
    """texts: per-zone OCR strings, in the part's zone order."""
    # split on " / " with spaces: a bare "/" also lives inside units like m/s
    raw = part.get("key") or ""
    exp = [e.strip() for e in raw.split(" / ")] if " / " in raw else ([raw.strip()] if raw else [])
    if len(exp) < len(texts):
        exp += [""] * (len(texts) - len(exp))
    verdicts = [compare_one(t, e) for t, e in zip(texts, exp)]
    if not verdicts:
        return "unsure"
    if all(v == "correct" for v in verdicts):
        return "correct"
    if all(v == "wrong" for v in verdicts):
        return "wrong"
    return "unsure"


def run(cfg, out_dir, log=print):
    import csv
    report = os.path.join(out_dir, "split_report.csv")
    if not os.path.exists(report):
        raise RuntimeError("split_report.csv not found — run 'redpen run' first")
    with open(report, newline="") as f:
        rows = list(csv.DictReader(f))
    zmap = {z["id"]: z for z in cfg["zones"]}
    result = {}
    for n, r in enumerate(rows, 1):
        flagged = bool(r["review"])
        stem = (f"{r['file_key']}__sheet{int(r['sheet']):03d}" if flagged else r["file_key"])
        folder = os.path.join(out_dir, "needs_review" if flagged else "students", stem)
        per_part = {}
        for p in cfg["parts"]:
            if p.get("auto") is False:
                per_part[p["id"]] = {"ocr": "", "verdict": "skip"}
                continue
            texts = []
            for zid in p["zones"]:
                png = os.path.join(folder, f"{zid}.png")
                texts.append(" ".join(ocr.read(png)) if os.path.exists(png) else "")
            per_part[p["id"]] = {"ocr": " / ".join(texts).strip(" /"),
                                 "verdict": compare_part(p, texts)}
        result[stem] = per_part
        if n % 5 == 0 or n == len(rows):
            log(f"  {n}/{len(rows)} sheets read")
    dest = os.path.join(out_dir, "autograde.json")
    with open(dest, "w") as f:
        json.dump(result, f, indent=1)
    tally = {}
    for v in result.values():
        for pv in v.values():
            tally[pv["verdict"]] = tally.get(pv["verdict"], 0) + 1
    return dest, tally
