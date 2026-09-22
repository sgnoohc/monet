"""Entry point for the packaged app: the same server, started by the window.

Kept apart from `redpen.cli` so PyInstaller has one obvious thing to analyse,
and so the packaged binary cannot be mistaken for the command line tool.
"""
import os, sys


def main():
    # The bundled typst and poppler live beside this binary; put them ahead of
    # anything the user happens to have installed, so the app behaves the same
    # on a machine with no Homebrew at all.
    here = os.path.dirname(os.path.abspath(sys.executable))
    for d in (os.path.join(here, "bin"), here):
        if os.path.isdir(d):
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
    port = None
    for i, a in enumerate(sys.argv):
        if a == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])
    from redpen import app
    app.serve(open_browser=False, port=port)


if __name__ == "__main__":
    main()
