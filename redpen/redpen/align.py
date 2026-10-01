"""Per-sheet alignment: undo a scan that came through shifted, rotated or resized.

Zones are drawn on the template, so a sheet fed in crooked crops the wrong
strip of paper.  The verifier lets you drag and turn the template's zones
over the raw scan until they sit on the printed boxes; what that records,
per sheet and page, is where the template's frame landed on the scan:

    scan = centre + (dx*W, dy*H) + scale * R(rot) * (template - centre)

rot in degrees, clockwise on screen (y points down); scale > 1 when the scan
came out bigger than the template (a printer or scanner that shrinks or
enlarges the page).  Every crop is then cut from the scan resampled back
into the template's frame, so the zones, the page PNGs and anything read
from them all agree with what you lined up.

Stored in align.json beside split_report.csv, keyed by sheet number (which
survives the renames verify makes).  A fresh split numbers sheets anew and
drops the file.
"""
import json, math, os, shutil

from PIL import Image

from . import render

FILE = "align.json"
IDENTITY = {"dx": 0.0, "dy": 0.0, "rot": 0.0, "scale": 1.0}


def load(out_dir):
    p = os.path.join(out_dir, FILE)
    if not os.path.exists(p):
        return {}
    with open(p) as f:
        return json.load(f)


def save(out_dir, data):
    p = os.path.join(out_dir, FILE)
    # an identity entry is no alignment; keep the file to real ones
    data = {s: {pg: a for pg, a in pages.items() if not is_identity(a)}
            for s, pages in data.items()}
    data = {s: pages for s, pages in data.items() if pages}
    if not data:
        if os.path.exists(p):
            os.remove(p)
        return
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, p)


def clear(out_dir):
    p = os.path.join(out_dir, FILE)
    if os.path.exists(p):
        os.remove(p)


def norm(a):
    """Every field present, as floats; older entries have no scale."""
    a = a or {}
    return {k: float(a.get(k, v)) for k, v in IDENTITY.items()}


def is_identity(a):
    a = norm(a)
    return all(abs(a[k] - v) < 1e-9 for k, v in IDENTITY.items())


def of(data, sheet, page):
    return (data.get(str(sheet)) or {}).get(str(page)) or dict(IDENTITY)


def apply(png, a):
    """The scan at `png`, resampled into the template's frame."""
    im = Image.open(png)
    if is_identity(a):
        return im
    a = norm(a)
    if a["scale"] <= 0:
        raise ValueError(f"scale must be positive, not {a['scale']}")
    im = im.convert("RGB")
    W, H = im.size
    cx, cy = W / 2, H / 2
    t = math.radians(a["rot"])
    c, s = a["scale"] * math.cos(t), a["scale"] * math.sin(t)
    ox, oy = cx + a["dx"] * W, cy + a["dy"] * H
    # PIL maps each output (template) pixel to the input (scan) pixel it reads
    coeffs = (c, -s, ox - (c * cx - s * cy),
              s, c, oy - (s * cx + c * cy))
    return im.transform((W, H), Image.AFFINE, coeffs,
                        resample=Image.BICUBIC, fillcolor=(255, 255, 255))


def crop(png, a, rect, pad=0.0):
    """render.crop_rect, on the aligned page."""
    im = apply(png, a)
    W, H = im.size
    x, y, w, h = rect
    px, py = pad * W, pad * H
    return im.crop((max(0, int(x * W - px)), max(0, int(y * H - py)),
                    min(W, int((x + w) * W + px)), min(H, int((y + h) * H + py))))


def zone_pad(z):
    return 0.0 if z.get("kind") == "answer" and z.get("tight") else 0.004


def cut_sheet(cfg, pdf, first, folder, aligns=None):
    """Write pageN.png and every zone PNG for one sheet into `folder`.

    aligns: {page(str): {dx, dy, rot, scale}} for this sheet, or None."""
    aligns = aligns or {}
    cache = render.cache_dir(cfg["_dir"], "pages")
    for p in range(1, cfg["pages_per_student"] + 1):
        png = render.render_page(pdf, first + p - 1, cfg["dpi"], cache)
        a = aligns.get(str(p))
        dest = os.path.join(folder, f"page{p}.png")
        if is_identity(a):
            shutil.copy2(png, dest)
        else:
            apply(png, a).save(dest)
    for z in cfg["zones"]:
        png = render.render_page(pdf, first + z["page"] - 1, cfg["dpi"], cache)
        crop(png, aligns.get(str(z["page"])), z["rect"], pad=zone_pad(z)).save(
            os.path.join(folder, f"{z['id']}.png"))
