"""Summary statistics and a grade-distribution histogram.

Reads a CSV exported by the grading page: the columns between "ID" and
"Total /N" are the parts, each headed "<label> /<max>".
"""
import csv, html, math, os, re

TOTAL = re.compile(r"^\s*Total\s*/\s*([\d.]+)\s*$", re.I)
PART = re.compile(r"^(.*?)\s*/\s*([\d.]+)\s*$")


class GradesError(Exception):
    pass


def _num(s):
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return None


def read(path, only_reviewed=False):
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    if len(rows) < 2:
        raise GradesError(f"{os.path.basename(path)} has no data rows")
    head = rows[0]
    ti = next((i for i, h in enumerate(head) if TOTAL.match(h)), None)
    if ti is None:
        raise GradesError("no 'Total /N' column — is this a grading-page export?")
    out_of = float(TOTAL.match(head[ti]).group(1))
    start = (head.index("ID") + 1) if "ID" in head else 3
    parts = []
    for i in range(start, ti):
        m = PART.match(head[i])
        parts.append({"col": i,
                      "label": (m.group(1) if m else head[i]).strip(),
                      "max": float(m.group(2)) if m else None})
    ri = next((i for i, h in enumerate(head) if h.strip().lower() == "reviewed"), None)
    ni = head.index("Name") if "Name" in head else 1

    students = []
    for r in rows[1:]:
        if not r or len(r) <= ti:
            continue
        tot = _num(r[ti])
        if tot is None:
            continue
        if only_reviewed and ri is not None and r[ri].strip().lower() not in ("yes", "true", "1"):
            continue
        students.append({"name": r[ni] if len(r) > ni else "",
                         "total": tot,
                         "scores": {p["col"]: _num(r[p["col"]]) for p in parts}})
    if not students:
        raise GradesError("no graded rows found"
                          + (" with Reviewed = yes" if only_reviewed else ""))
    return parts, students, out_of


def summary(values):
    v = sorted(values)
    n = len(v)
    mean = sum(v) / n

    def pct(p):
        if n == 1:
            return v[0]
        k = (n - 1) * p
        lo, hi = math.floor(k), math.ceil(k)
        return v[lo] if lo == hi else v[lo] + (v[hi] - v[lo]) * (k - lo)

    var = sum((x - mean) ** 2 for x in v) / (n - 1) if n > 1 else 0.0
    return {"n": n, "mean": mean, "median": pct(0.5), "sd": math.sqrt(var),
            "min": v[0], "max": v[-1], "q1": pct(0.25), "q3": pct(0.75)}


def bins(values, nbins=10, lo=None, hi=None, width=None):
    """Equal-width bins. width overrides nbins. Last bin includes hi."""
    lo = 0.0 if lo is None else float(lo)
    hi = (max(values) if values else 0.0) if hi is None else float(hi)
    if hi <= lo:
        hi = lo + 1.0
    if width:
        width = float(width)
        if width <= 0:
            raise GradesError("--width must be positive")
        nbins = max(1, int(math.ceil((hi - lo) / width - 1e-9)))
        hi = lo + nbins * width
    else:
        nbins = max(1, int(nbins))
        width = (hi - lo) / nbins
    edges = [lo + i * width for i in range(nbins + 1)]
    counts = [0] * nbins
    under = over = 0
    for x in values:
        if x < lo:
            under += 1; continue
        if x > hi:
            over += 1; continue
        i = int((x - lo) / width)
        if i >= nbins:
            i = nbins - 1              # the top edge belongs to the last bin
        counts[i] += 1
    return edges, counts, under, over


def part_stats(parts, students):
    out = []
    for p in parts:
        vals = [s["scores"][p["col"]] for s in students
                if s["scores"].get(p["col"]) is not None]
        if not vals:
            continue
        mx = p["max"] or (max(vals) or 1)
        st = summary(vals)
        out.append({**p, "stats": st, "pct": 100 * st["mean"] / mx if mx else 0,
                    "full": sum(1 for v in vals if abs(v - mx) < 1e-9),
                    "zero": sum(1 for v in vals if v == 0), "n": len(vals)})
    return out


def _fmt(x, nd=1):
    return f"{x:.{nd}f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x)


def render_text(title, st, edges, counts, under, over, parts, out_of, width=46):
    L = []
    L.append(f"{title}   n = {st['n']}   out of {_fmt(out_of)}")
    L.append("")
    L.append(f"  mean   {st['mean']:6.2f}      min    {st['min']:6.2f}")
    L.append(f"  median {st['median']:6.2f}      max    {st['max']:6.2f}")
    L.append(f"  stdev  {st['sd']:6.2f}      Q1–Q3  {st['q1']:.1f}–{st['q3']:.1f}")
    L.append("")
    top = max(counts) if counts else 0
    L.append("  distribution")
    for i, c in enumerate(counts):
        a, b = edges[i], edges[i + 1]
        last = (i == len(counts) - 1)
        rng = f"{a:6.1f} – {b:<6.1f}{']' if last else ')'}"
        bar = "█" * int(round(width * c / top)) if top else ""
        pc = 100 * c / st["n"] if st["n"] else 0
        L.append(f"  {rng} {c:>4}  {pc:4.0f}%  {bar}")
    if under or over:
        L.append(f"  ({under} below range, {over} above)")
    if parts:
        L.append("")
        L.append("  by part                          out of   mean    %   full  zero")
        for p in sorted(parts, key=lambda p: p["pct"]):
            L.append(f"  {p['label'][:30]:<30} {_fmt(p['max']):>6} "
                     f"{p['stats']['mean']:6.2f} {p['pct']:4.0f}% "
                     f"{p['full']:>5} {p['zero']:>5}")
    return "\n".join(L)


def render_html(title, st, edges, counts, under, over, parts, out_of):
    from .ui_style import TOKENS
    e = html.escape
    top = max(counts) if counts else 1
    bars = "".join(
        f'<div class="bar"><div class="col" style="height:{100*c/top:.1f}%" '
        f'title="{c} student(s)"></div>'
        f'<div class="lab">{edges[i]:.0f}–{edges[i+1]:.0f}</div>'
        f'<div class="cnt">{c or ""}</div></div>'
        for i, c in enumerate(counts))
    rows = "".join(
        f'<tr><td>{e(p["label"])}</td><td class="n">{_fmt(p["max"])}</td>'
        f'<td class="n">{p["stats"]["mean"]:.2f}</td><td class="n">{p["pct"]:.0f}%</td>'
        f'<td class="n">{p["full"]}</td><td class="n">{p["zero"]}</td></tr>'
        for p in sorted(parts, key=lambda p: p["pct"]))
    card = lambda k, v: f'<div class="card"><div class="k">{k}</div><div class="v">{v}</div></div>'
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><style>{TOKENS}
.wrap{{max-width:900px;margin:0 auto;padding-block:26px;padding-left:16px;padding-right:16px}}
h1{{font-size:21px;margin:0 0 3px}} .sub{{color:var(--mut);margin:0 0 18px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:10px;
 margin-bottom:22px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}}
.card .k{{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut)}}
.card .v{{font-size:20px;font-variant-numeric:tabular-nums;margin-top:3px}}
.chart{{display:flex;align-items:flex-end;gap:5px;height:230px;background:var(--card);
 border:1px solid var(--line);border-radius:10px;padding:14px 12px 0}}
.bar{{flex:1;display:flex;flex-direction:column;justify-content:flex-end;height:100%}}
.bar .col{{background:var(--acc);border-radius:4px 4px 0 0;min-height:2px}}
.bar .cnt{{font-size:11px;text-align:center;color:var(--mut);height:15px;
 font-variant-numeric:tabular-nums;order:-1}}
.bar .lab{{font-size:10.5px;text-align:center;color:var(--mut);padding:5px 0 10px;
 white-space:nowrap}}
table{{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);
 border-radius:10px;margin-top:22px}}
th,td{{padding:7px 10px;text-align:left;border-bottom:1px solid var(--line2);font-size:13px}}
th{{background:var(--bg);color:var(--mut);font-size:11.5px;text-transform:uppercase;
 letter-spacing:.04em}}
td.n,th.n{{text-align:right;font-variant-numeric:tabular-nums}}
tr:last-child td{{border-bottom:none}}
</style></head><body><div class="wrap">
<h1>{e(title)}</h1>
<p class="sub">{st['n']} graded, out of {_fmt(out_of)}
{f' · {under} below and {over} above the plotted range' if under or over else ''}</p>
<div class="cards">
{card('mean', f"{st['mean']:.1f}")}{card('median', f"{st['median']:.1f}")}
{card('stdev', f"{st['sd']:.1f}")}{card('min', f"{st['min']:.0f}")}
{card('max', f"{st['max']:.0f}")}{card('Q1–Q3', f"{st['q1']:.0f}–{st['q3']:.0f}")}
</div>
<div class="chart">{bars}</div>
<table><thead><tr><th>Part</th><th class="n">out of</th><th class="n">mean</th>
<th class="n">%</th><th class="n">full</th><th class="n">zero</th></tr></thead>
<tbody>{rows}</tbody></table>
</div></body></html>"""
