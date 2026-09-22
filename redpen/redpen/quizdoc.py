"""The authored quiz: `quiz.src.json`, the one file a quiz is written in.

This is the form's document model, and the input to `typstgen`.  It holds what
a person decides -- the questions, the answers, the marks -- and nothing that
can be derived from them.  Zone rectangles in particular are *not* here: they
come back out of the Typst compile, which is the only thing that knows where a
box actually landed.

Everything downstream is generated, so this file is the only one worth keeping
under version control alongside the PDFs.
"""
import copy, json, os, re

DEFAULTS = {
    "title": "Quiz",
    "course": "",
    "pages": 2,                # target page count; the layout aims to fill them
    "note": "",                # the boxed instruction at the top
    "preamble": "",            # verbatim Typst, for figures a form cannot express
    "problems": [],
}

# A sub-part's default answer box, and the default for a sketch.
# `answer` is what is printed in the box on the key, so it is markup.  `key`
# is what OCR compares a student's writing against, so it is plain text; it
# defaults to `answer` and is only needed when the two differ -- an answer set
# as $times 4$ prints correctly and would never match as a string.
BOX = {"label": "answer", "answer": "", "key": "", "alt": [], "kind": "answer",
       "points": "", "w": "3.4cm", "h": "1.9em"}
SKETCH = {"w": "6.6cm", "h": "4.6cm"}

LETTERS = "abcdefghijklmnopqrstuvwxyz"


class QuizError(Exception):
    pass


def slug(s):
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", s.lower())).strip("_")


def load(path):
    with open(path) as f:
        raw = json.load(f)
    doc = copy.deepcopy(DEFAULTS)
    doc.update(raw)
    doc["_path"] = os.path.abspath(path)
    doc["_dir"] = os.path.dirname(doc["_path"])
    # `text=False`: the composer saves on every pause, so a source can legally
    # hold half an equation.  Refusing to read that back stranded the quiz --
    # it still listed in the sidebar and then would not open, with nothing to
    # be done but edit the JSON by hand.  Unfinished markup is refused when
    # something is actually built from it, which is where it matters.
    validate(doc, text=False)
    return doc


def save(doc, path=None):
    path = path or doc["_path"]
    out = {k: v for k, v in doc.items() if not k.startswith("_")}
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)
    return path


def new(title, pages=2):
    doc = copy.deepcopy(DEFAULTS)
    doc["title"] = title
    doc["pages"] = int(pages)
    return doc


def scan(s):
    """Count what has to come in pairs, ignoring escapes and quoted strings.

    Returns (bracket_depth, stray_close, dollars).  Quoted runs are skipped so
    that `#ieq("a is 0]", $a$)` -- code, where the quotes really are a string
    -- does not read as an unbalanced bracket.
    """
    depth = stray = dollars = 0
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == '"':
            j = s.find('"', i + 1)
            i = n if j < 0 else j + 1
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            if depth == 0:
                stray += 1
            else:
                depth -= 1
        elif c == "$":
            dollars += 1
        i += 1
    return depth, stray, dollars


def trouble(text):
    """Why this field would not compile, or None.

    Separated from `validate` because these are the states a field passes
    through while it is being typed -- half an equation is not a mistake, it
    is a person mid-sentence -- and the composer treats them as "not yet"
    rather than as an error.
    """
    depth, stray, dollars = scan(text or "")
    if stray:
        return "a ] with no matching [ — write a literal bracket as \\]"
    if depth:
        return "an unclosed [ — write a literal bracket as \\["
    if dollars % 2:
        return ("an odd number of $ — maths opens and closes with one, and a "
                "literal dollar sign is \\$")
    return None


def _atref(text):
    """A bare @word is a Typst reference to a label that will not exist."""
    out, i, n = [], 0, len(text or "")
    while i < n:
        c = text[i]
        if c == "\\":
            out.append(text[i:i + 2]); i += 2; continue
        if c == "@" and i + 1 < n and (text[i + 1].isalnum() or text[i + 1] == "_"):
            out.append("\\@"); i += 1; continue
        out.append(c); i += 1
    return "".join(out)


def fields(doc):
    """Every authored text field, with a name for error messages."""
    yield "the instruction note", doc.get("note", "")
    for pi, p in enumerate(doc.get("problems", []), 1):
        if p.get("off"):
            continue          # archived: not on the paper, so not its problem
        yield f"problem {pi} title", p.get("title", "")
        yield f"problem {pi} stem", p.get("stem", "")
        for qi, q in enumerate(p.get("parts", [])):
            at = f"problem {pi}({LETTERS[qi] if qi < len(LETTERS) else qi})"
            yield f"{at} question", q.get("question", "")
            for line in (q.get("solution") or []):
                yield f"{at} solution", line
            for b in (q.get("boxes") or []):
                yield f"{at} answer for {b.get('label', '?')}", b.get("answer", "")


def incomplete(doc):
    """The first field that is mid-edit, as (where, why), or None."""
    for where, text in fields(doc):
        why = trouble(text)
        if why:
            return where, why
    return None


def validate(doc, text=True):
    """Check and normalise a quiz source.

    `text` also checks that the authored markup could compile.  Off while
    loading, on when building: the difference between "someone is typing" and
    "this is meant to be a finished paper".
    """
    if doc["pages"] < 1:
        raise QuizError("pages must be at least 1")
    if not doc["problems"]:
        raise QuizError("the quiz has no problems")
    if text and not live(doc):
        raise QuizError("every problem is archived — there is no paper to build")

    where = []            # for error messages

    def text_ok(s, what):
        why = trouble(s) if text else None
        if why:
            raise QuizError(f"{' '.join(where)}: {what} has {why}")

    text_ok(doc.get("note", ""), "the instruction note")

    for pi, p in enumerate(doc["problems"], 1):
        where[:] = [f"problem {pi}"]
        p.setdefault("title", "")
        p.setdefault("stem", "")
        p.setdefault("parts", [])
        p["direct"] = bool(p.get("direct", False))
        p["off"] = bool(p.get("off", False))
        p["points"] = float(p.get("points", 0))
        page = int(p.get("page", 0) or 0)
        if page and not (1 <= page <= doc["pages"]):
            raise QuizError(f"problem {pi}: page {page} is outside 1..{doc['pages']}")
        p["page"] = page
        # An archived problem is still normalised -- the form has to render it
        # -- but its markup is not checked: it is not on the paper, and
        # archiving is precisely the way out of a problem that will not
        # compile.  Numbering here is the position in the form, which is where
        # someone has to go to find it.
        ok = (lambda s, what: None) if p["off"] else text_ok
        ok(p["title"], "the title")
        ok(p["stem"], "the stem")
        if not p["parts"]:
            raise QuizError(f"problem {pi} has no sub-parts")
        if len(p["parts"]) > len(LETTERS):
            raise QuizError(f"problem {pi} has more than {len(LETTERS)} sub-parts")
        if p["direct"] and len(p["parts"]) != 1:
            raise QuizError(f"problem {pi} asks for the answer directly but has "
                            f"{len(p['parts'])} sub-parts — delete the extra ones, "
                            "or give it lettered sub-parts again")

        for qi, q in enumerate(p["parts"]):
            where[:] = [f"problem {pi}({LETTERS[qi]})"]
            q.setdefault("question", "")
            q.setdefault("solution", [])
            q.setdefault("raw", "")
            q["gap"] = float(q.get("gap", 1.0) or 1.0)
            if isinstance(q["solution"], str):
                q["solution"] = [l for l in q["solution"].split("\n\n") if l.strip()]
            ok(q["question"], "the question")
            for line in q["solution"]:
                ok(line, "a solution line")
            if not q.get("boxes"):
                raise QuizError(f"{where[0]} has no answer boxes")

            seen = set()
            for b in q["boxes"]:
                merged = copy.deepcopy(BOX)
                if b.get("kind") == "sketch":
                    merged.update(SKETCH)
                merged.update(b)
                b.clear()
                b.update(merged)
                if b["kind"] not in ("answer", "sketch"):
                    raise QuizError(f"{where[0]}: box kind must be answer or sketch, "
                                    f"not {b['kind']!r}")
                if not b["label"]:
                    raise QuizError(f"{where[0]}: a box has no label")
                if b["label"] in seen:
                    raise QuizError(f"{where[0]}: two boxes are both labelled "
                                    f"{b['label']!r} — labels name the quantity and "
                                    "must differ")
                seen.add(b["label"])
                ok(b.get("answer", ""), f"the answer for {b['label']!r}")
                b["alt"] = [a for a in b.get("alt", []) if str(a).strip()]
    where[:] = []
    return doc


# ---- Derived facts -------------------------------------------------
# Ids, marks and answer-key strings are computed, never stored: storing them
# would let them drift from the questions they describe.

def part_id(pi, qi):
    return f"{pi}{LETTERS[qi]}"


def zone_id(pi, qi, q, b):
    """One box in a part is the part; several are suffixed by their label."""
    pid = part_id(pi, qi)
    return pid if len(q["boxes"]) == 1 else f"{pid}_{slug(b['label'])}"


def _n(v):
    """A marks field: a number, or None when it was left blank."""
    t = str(v).strip() if v is not None else ""
    if t == "":
        return None
    try:
        return float(t)
    except ValueError:
        return None


def part_total(q):
    """What a sub-part is worth, if it says so itself.

    Either set on the sub-part, or implied by every one of its boxes carrying
    its own marks -- which is how a two-answer question gets marked out of
    something other than half and half.
    """
    v = _n(q.get("points"))
    if v is not None:
        return v
    got = [_n(b.get("points")) for b in q.get("boxes", [])]
    if got and all(g is not None for g in got):
        return sum(got)
    return None


def split_boxes(q):
    """Whether this sub-part's boxes are marked one by one."""
    return any(_n(b.get("points")) is not None for b in q.get("boxes", []))


def box_points(q, total):
    """Marks per box: explicit where given, the rest sharing what is left."""
    boxes = q.get("boxes", [])
    n = len(boxes)
    fixed = {i: _n(b.get("points")) for i, b in enumerate(boxes)
             if _n(b.get("points")) is not None}
    out = [0.0] * n
    for i, v in fixed.items():
        out[i] = v
    free = [i for i in range(n) if i not in fixed]
    if free:
        left = float(total) - sum(fixed.values())
        acc = 0.0
        for k, i in enumerate(free):
            out[i] = (round(left - acc, 3) if k == len(free) - 1
                      else round(left / len(free) * 2) / 2)
            acc += out[i]
    return out


def part_points(p):
    """Marks per sub-part: explicit where given, else split by box count.

    The split is exact -- the remainder lands on the last sub-part -- so the
    parts of a problem always add up to the problem, and the parts of a quiz
    to the quiz.  A rubric that does not sum is a real marking error, not a
    rounding curiosity.
    """
    parts = p["parts"]
    fixed = {i: part_total(q) for i, q in enumerate(parts)
             if part_total(q) is not None}
    left = float(p["points"]) - sum(fixed.values())
    free = [i for i in range(len(parts)) if i not in fixed]
    out = [0.0] * len(parts)
    for i, v in fixed.items():
        out[i] = v
    if free:
        weights = [len(parts[i]["boxes"]) for i in free]
        total = sum(weights) or 1
        acc = 0.0
        for n, i in enumerate(free):
            if n == len(free) - 1:
                out[i] = round(left - acc, 3)
            else:
                v = round(left * weights[n] / total * 2) / 2
                out[i] = v
                acc += v
    return out


def box_key(b):
    """What OCR should compare against for one box."""
    return str(b.get("key") or b.get("answer") or "").strip()


def key_string(q):
    """redpen's answer-key syntax: ' / ' between boxes, ' | ' between variants."""
    out = []
    for b in q["boxes"]:
        variants = [box_key(b)] + [str(a).strip() for a in b["alt"]]
        out.append(" | ".join(v for v in variants if v))
    return " / ".join(out)


def gradable(q):
    """Whether OCR should be given a vote on this sub-part.

    A sketch, obviously not.  Nor an answer still carrying Typst markup: it
    prints correctly but could never match a string read off the paper, and a
    key that cannot match marks every correct answer wrong.
    """
    if any(b["kind"] == "sketch" for b in q["boxes"]):
        return False
    keys = [box_key(b) for b in q["boxes"]]
    if not any(keys):
        return False
    return not any("$" in k or "#" in k for k in keys)


def graded_items(pi, qi, q, points):
    """The rubric rows this sub-part becomes.

    Normally one -- several boxes of one question are marked together.  When
    the boxes carry their own marks they become rows of their own, so a
    two-answer question can be worth 10 for one and 4 for the other.
    """
    pid = part_id(pi, qi)
    if not split_boxes(q):
        return [{"id": pid,
                 "zones": [zone_id(pi, qi, q, b) for b in q["boxes"]],
                 "labels": ", ".join(b["label"] for b in q["boxes"]),
                 "key": key_string(q),
                 "points": points,
                 "auto": gradable(q)}]
    each = box_points(q, points)
    out = []
    for i, b in enumerate(q["boxes"]):
        zid = zone_id(pi, qi, q, b)
        out.append({"id": zid,
                    "zones": [zid],
                    "labels": b["label"],
                    "key": " | ".join(v for v in
                                      [box_key(b)] + [str(a).strip() for a in b["alt"]] if v),
                    "points": each[i],
                    "auto": gradable({"boxes": [b]})})
    return out


def live(doc):
    """The problems actually on the paper, in order.

    An archived problem keeps its place in the source and in the form but is
    invisible to everything downstream: it is not laid out, not numbered, and
    has no zones and no rubric rows.  Numbering closes over the gap, because a
    paper running 1, 2, 4 reads as a printing mistake rather than a choice --
    which does mean archiving a problem renumbers the ones after it, and so
    changes the part ids a already-graded quiz was scanned against.
    """
    return [p for p in doc["problems"] if not p.get("off")]


def total_points(doc):
    return sum(float(p["points"]) for p in live(doc))


def pages_of(doc):
    """Assign every problem on the paper to a page: as authored, else evenly
    by count.  The result lines up with `live(doc)`, not with `problems`.

    Six problems over two pages is three and three, whatever they are worth.
    Marks used to decide this, which meant adding a mark somewhere could move
    a problem to another page -- surprising, and impossible to aim.  A page
    pinned on a problem is obeyed, and the problems after it carry on from
    there.
    """
    n = doc["pages"]
    probs = live(doc)
    given = [p["page"] for p in probs]
    if all(given):
        return given
    m = len(probs)
    # How many problems each page should hold; the remainder lands on the
    # earlier pages, so a short page is the last one.
    quota = [m // n + (1 if k < m % n else 0) for k in range(n)]
    out, page, acc = [], 1, 0
    for g in given:
        if g:
            page, acc = g, 0
        elif acc and acc >= quota[page - 1] and page < n:
            page += 1
            acc = 0
        out.append(page)
        acc += 1
    return out
