"""On-device OCR.

Apple's Vision framework does the reading (a small Swift helper compiled on
first use); tesseract is the fallback when Vision is unavailable.  Both run
locally — no image ever leaves this machine.
"""
import os, re, shutil, subprocess, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SWIFT_SRC = os.path.join(HERE, "vision", "visionocr.swift")
SWIFT_BIN = os.path.join(HERE, "vision", "visionocr")
LABEL = re.compile(r"^\s*[A-Za-z]{0,4}[:]\s*")     # a clipped "Name:" label, not "15."


def vision_available():
    if os.path.exists(SWIFT_BIN):
        return True
    return shutil.which("swiftc") is not None and os.path.exists(SWIFT_SRC)


def _ensure_binary(log=None):
    if os.path.exists(SWIFT_BIN):
        if os.path.getmtime(SWIFT_BIN) >= os.path.getmtime(SWIFT_SRC):
            return True
        # Inside the packaged app there is no compiler and the shipped binary
        # is the only one there will be; a stale mtime is not a reason to fall
        # back to something much worse at handwriting.
        if not shutil.which("swiftc"):
            return True
    if not shutil.which("swiftc"):
        return False
    if log:
        log("compiling the on-device OCR helper (one time) ...")
    p = subprocess.run(["swiftc", "-O", SWIFT_SRC, "-o", SWIFT_BIN],
                       capture_output=True, text=True)
    if p.returncode != 0:
        if log:
            log("  swiftc failed: " + (p.stderr or "").strip().splitlines()[-1:][0]
                if p.stderr else "  swiftc failed")
        return False
    return True


def read_vision(png, custom_words=None, log=None, strip_label=False):
    """Returns a list of recognised strings, best candidate first.

    strip_label only for identity zones, where the crop may clip the printed
    "Name:" caption.  Never for answers: it would eat the "15." of "15.0 s".
    """
    if not _ensure_binary(log=log):
        return []
    cmd = [SWIFT_BIN, png]
    tmp = None
    if custom_words:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
        tmp.write("\n".join(sorted(set(custom_words))))
        tmp.close()
        cmd.append(tmp.name)
    try:
        out = subprocess.run(cmd, capture_output=True, text=True).stdout
    finally:
        if tmp:
            os.unlink(tmp.name)
    lines = []
    for ln in out.splitlines():
        txt = ln.split("\t")[0].strip()
        if strip_label:
            txt = LABEL.sub("", txt)
        if len(txt) > 1 and not re.fullmatch(r"[\W_]+", txt):
            lines.append(txt)
    return lines


def read_tesseract(png, strip_label=False):
    if not shutil.which("tesseract"):
        return []
    with tempfile.TemporaryDirectory() as td:
        p = subprocess.run(["tesseract", png, os.path.join(td, "o"), "--psm", "7"],
                           capture_output=True, text=True)
        if p.returncode != 0:
            return []
        try:
            txt = open(os.path.join(td, "o.txt")).read()
        except FileNotFoundError:
            return []
    txt = " ".join(txt.split())
    if strip_label:
        txt = LABEL.sub("", txt)
    return [txt] if len(txt) > 1 else []


def read(png, custom_words=None, log=None, strip_label=False):
    lines = read_vision(png, custom_words, log=log, strip_label=strip_label)
    return lines or read_tesseract(png, strip_label=strip_label)


def engine_name():
    return "Apple Vision (on-device)" if vision_available() else (
        "tesseract" if shutil.which("tesseract") else "none")
