"""PDF -> page PNGs -> zone crops, via poppler.  All local."""
import base64, io, os, re, subprocess, threading
from PIL import Image

CACHE = ".redpen_cache"


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"{cmd[0]}: {(p.stderr or p.stdout).strip()}")
    return p.stdout


def page_count(pdf):
    for line in run(["pdfinfo", pdf]).splitlines():
        if line.startswith("Pages:"):
            return int(line.split()[1])
    raise RuntimeError(f"no page count in {pdf}")


def cache_dir(base, tag):
    d = os.path.join(base, CACHE, tag)
    os.makedirs(d, exist_ok=True)
    return d


def render_page(pdf, page, dpi, outdir, force=False):
    """Render one 1-based page.  Returns the PNG path (cached)."""
    stem = re.sub(r"\W+", "_", os.path.splitext(os.path.basename(pdf))[0])
    dest = os.path.join(outdir, f"{stem}_{dpi}_{page:05d}.png")
    # The cache is keyed by file name, so a scan rebuilt under the same name
    # (re-cropped, re-ordered) must not be served from its predecessor's pages.
    stale = os.path.exists(dest) and os.path.getmtime(dest) < os.path.getmtime(pdf)
    if force or stale or not os.path.exists(dest):
        # One prefix per thread and page: the preview asks for every page at
        # once, and a shared prefix let one request pick up another's file.
        prefix = os.path.join(outdir, f"_tmp{os.getpid()}_{threading.get_ident()}_{page}")
        run(["pdftoppm", "-r", str(dpi), "-png", "-f", str(page), "-l", str(page),
             pdf, prefix])
        made = [f for f in os.listdir(outdir) if f.startswith(os.path.basename(prefix))]
        if not made:
            raise RuntimeError(f"pdftoppm produced nothing for page {page} of {pdf}")
        os.replace(os.path.join(outdir, made[0]), dest)
    return dest


def crop_rect(png, rect, pad=0.0):
    im = Image.open(png)
    W, H = im.size
    x, y, w, h = rect
    px, py = pad * W, pad * H
    return im.crop((max(0, int(x * W - px)), max(0, int(y * H - py)),
                    min(W, int((x + w) * W + px)), min(H, int((y + h) * H + py))))


def data_uri(im, max_px=1000):
    im = im.copy()
    im.thumbnail((max_px, max_px))
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
