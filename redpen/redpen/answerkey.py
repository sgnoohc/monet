"""Read the expected answers off an answer-key PDF.

The key is the same form with worked solutions printed on it, so its answer
boxes sit lower than the blank quiz the students wrote on — on one real
quiz by up to 0.0155 of the page height, and by a different amount at the top of the
page than the bottom.  A single offset will not do.

So the boxes are detected on both documents, paired in order down the page, and
a piecewise-linear y-map is built from the pairs.  Zone rectangles defined on
the blank are pushed through that map to find the same box on the key.
"""
import numpy as np
from PIL import Image

from . import ocr, render


def rules(png, x0=0.745, x1=0.905, dark=190, cover=0.85):
    """y positions (as page fractions) of horizontal rules in the answer column."""
    a = np.array(Image.open(png).convert("L"))
    H, W = a.shape
    d = (a[:, int(x0 * W):int(x1 * W)] < dark).mean(axis=1)
    rows = [y for y in range(H) if d[y] > cover]
    groups = []
    for y in rows:
        if groups and y - groups[-1][-1] <= 3:
            groups[-1].append(y)
        else:
            groups.append([y])
    return [float(np.mean(g)) / H for g in groups]


def pair_rules(a, b, skip=0.05):
    """Monotonic pairing of two rule lists that tolerates extras on either side.

    The key carries lines the blank does not (a drawn graph axis, say), so a
    strict zip is not safe; this is a small edit-distance alignment instead.
    """
    n, m = len(a), len(b)
    INF = float("inf")
    dp = [[INF] * (m + 1) for _ in range(n + 1)]
    bt = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            if dp[i][j] == INF:
                continue
            if i < n and j < m:
                c = dp[i][j] + abs(a[i] - b[j])
                if c < dp[i + 1][j + 1]:
                    dp[i + 1][j + 1] = c; bt[i + 1][j + 1] = ("m", i, j)
            if i < n and dp[i][j] + skip < dp[i + 1][j]:
                dp[i + 1][j] = dp[i][j] + skip; bt[i + 1][j] = ("a", i, j)
            if j < m and dp[i][j] + skip < dp[i][j + 1]:
                dp[i][j + 1] = dp[i][j] + skip; bt[i][j + 1] = ("b", i, j)
    pairs, i, j = [], n, m
    while bt[i][j]:
        kind, pi, pj = bt[i][j]
        if kind == "m":
            pairs.append((a[pi], b[pj]))
        i, j = pi, pj
    pairs.reverse()
    return pairs


def ymap(src_rules, dst_rules, min_frac=0.6):
    """Piecewise-linear map from template page fractions onto the key's."""
    pairs = pair_rules(src_rules, dst_rules)
    if len(pairs) < 2 or len(pairs) < min_frac * min(len(src_rules), len(dst_rules)):
        return None, pairs
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]

    def f(y):
        if y <= xs[0]:
            return y + (ys[0] - xs[0])
        if y >= xs[-1]:
            return y + (ys[-1] - xs[-1])
        i = max(i for i in range(len(xs)) if xs[i] <= y)
        if i >= len(xs) - 1:
            return y + (ys[-1] - xs[-1])
        t = (y - xs[i]) / (xs[i + 1] - xs[i]) if xs[i + 1] > xs[i] else 0.0
        return ys[i] + t * (ys[i + 1] - ys[i])
    return f, pairs


def align(cfg, key_pdf, dpi=200, log=print):
    """Per-page y-maps from the blank template's coordinates onto the key."""
    tpl = None
    from . import config
    tpl = config.path_of(cfg, "template")
    cache = render.cache_dir(cfg["_dir"], "keyalign")
    maps = {}
    for page in range(1, cfg["pages_per_student"] + 1):
        t_png = render.render_page(tpl, page, dpi, cache)
        k_png = render.render_page(key_pdf, page, dpi, cache)
        tr, kr = rules(t_png), rules(k_png)
        m, pairs = ymap(tr, kr)
        if m is None:
            log(f"  page {page}: only {len(pairs)} of {len(tr)}/{len(kr)} rules could be "
                "paired — not aligning this page")
            maps[page] = (lambda y: y), False
        else:
            shifts = [abs(b - a) for a, b in pairs]
            log(f"  page {page}: {len(pairs)} rules paired "
                f"(template {len(tr)}, key {len(kr)}), max shift "
                f"{max(shifts):.4f} of page height")
            maps[page] = m, True
    return maps


def read(cfg, key_pdf, dpi=300, log=print, only_empty=True):
    """OCR each answer zone on the key.  Returns {part_id: text}."""
    from . import config
    maps = align(cfg, key_pdf, log=log)
    cache = render.cache_dir(cfg["_dir"], "keyalign")
    zmap = {z["id"]: z for z in cfg["zones"]}
    out = {}
    for p in cfg["parts"]:
        if only_empty and p.get("key"):
            continue
        texts = []
        for zid in p["zones"]:
            z = zmap.get(zid)
            if not z or z["id"] == cfg.get("name_zone"):
                continue
            f, okmap = maps.get(z["page"], ((lambda y: y), False))
            x, y, w, h = z["rect"]
            y2 = f(y); h2 = max(f(y + h) - y2, h * 0.5)
            png = render.render_page(key_pdf, z["page"], dpi, cache)
            crop = render.crop_rect(png, [x, y2, w, h2], pad=0.002)
            tmp = os.path.join(cache, f"_key_{p['id']}_{zid}.png")
            crop.save(tmp)
            got = ocr.read(tmp)
            texts.append(" ".join(got).strip())
        if texts:
            out[p["id"]] = " / ".join(t for t in texts if t)
    return out


import os  # noqa: E402
