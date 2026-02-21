#!/usr/bin/env python3
"""Interactive du viewer TUI - browse disk usage like a file manager.
Uses raw ANSI escape codes instead of curses for compatibility."""

import os
import signal
import struct
import sys
import termios
import tty


def human_readable(size_kb):
    """Convert KB integer to human-readable string like '1.23 GB'."""
    if size_kb < 1024:
        return "%d KB" % size_kb
    elif size_kb < 1024 * 1024:
        return "%.2f MB" % (size_kb / 1024.0)
    elif size_kb < 1024 * 1024 * 1024:
        return "%.2f GB" % (size_kb / (1024.0 * 1024))
    else:
        return "%.2f TB" % (size_kb / (1024.0 * 1024 * 1024))


SORT_SIZE_DESC = 0
SORT_SIZE_ASC = 1
SORT_NAME_ASC = 2
SORT_NAME_DESC = 3

SORT_LABELS = [
    "Size (largest first)",
    "Size (smallest first)",
    "Name A-Z",
    "Name Z-A",
]


def sort_children(children, mode):
    if mode == SORT_SIZE_DESC:
        return sorted(children, key=lambda n: n.size_kb, reverse=True)
    elif mode == SORT_SIZE_ASC:
        return sorted(children, key=lambda n: n.size_kb)
    elif mode == SORT_NAME_ASC:
        return sorted(children, key=lambda n: n.name.lower())
    else:
        return sorted(children, key=lambda n: n.name.lower(), reverse=True)


class Node(object):
    __slots__ = ('name', 'size_kb', 'children', 'parent', 'path')

    def __init__(self, name, parent=None, path=''):
        self.name = name
        self.size_kb = 0
        self.children = {}
        self.parent = parent
        self.path = path


class DuTree(object):
    """Parse du.txt and build a tree."""

    def __init__(self, filename):
        self.root = Node('.', path='.')
        self._parse(filename)

    def _parse(self, filename):
        with open(filename, 'r') as f:
            for line in f:
                line = line.rstrip('\n')
                if not line:
                    continue
                parts = line.split(None, 1)
                if len(parts) < 2:
                    continue
                try:
                    size_kb = int(parts[0])
                except ValueError:
                    continue
                path = parts[1]

                segments = path.split('/')
                node = self.root
                for i, seg in enumerate(segments):
                    if i == 0 and seg == '.':
                        continue
                    if seg not in node.children:
                        child_path = '/'.join(segments[:i + 1])
                        child = Node(seg, parent=node, path=child_path)
                        node.children[seg] = child
                    node = node.children[seg]

                node.size_kb = size_kb


# ANSI escape helpers
ESC = '\033'
CSI = ESC + '['

def _write(s):
    sys.stdout.write(s)

def _flush():
    sys.stdout.flush()

def clear_screen():
    _write(CSI + '2J')

def move_cursor(row, col):
    _write(CSI + '%d;%dH' % (row, col))

def hide_cursor():
    _write(CSI + '?25l')

def show_cursor():
    _write(CSI + '?25h')

def reset_attr():
    _write(CSI + '0m')

def bold():
    _write(CSI + '1m')

def underline():
    _write(CSI + '4m')

def reverse_video():
    _write(CSI + '7m')

def dim():
    _write(CSI + '2m')

def get_terminal_size():
    try:
        result = struct.unpack('hh', fcntl_ioctl_tiocgwinsz())
        return result[1], result[0]  # cols, rows
    except Exception:
        pass
    try:
        cols = int(os.environ.get('COLUMNS', 80))
        rows = int(os.environ.get('LINES', 24))
        return cols, rows
    except Exception:
        return 80, 24

def fcntl_ioctl_tiocgwinsz():
    import fcntl
    return fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, b'\x00' * 4)


def read_key():
    """Read a single keypress, handling escape sequences."""
    ch = sys.stdin.read(1)
    if ch == ESC:
        ch2 = sys.stdin.read(1)
        if ch2 == '[':
            ch3 = sys.stdin.read(1)
            if ch3 == 'A':
                return 'UP'
            elif ch3 == 'B':
                return 'DOWN'
            elif ch3 == 'C':
                return 'RIGHT'
            elif ch3 == 'D':
                return 'LEFT'
            elif ch3 == '5':
                sys.stdin.read(1)  # consume ~
                return 'PGUP'
            elif ch3 == '6':
                sys.stdin.read(1)  # consume ~
                return 'PGDN'
            elif ch3 == 'H':
                return 'HOME'
            elif ch3 == 'F':
                return 'END'
            else:
                return 'ESC'
        elif ch2 == '':
            return 'ESC'
        else:
            return 'ESC'
    elif ch == '\x7f' or ch == '\x08':
        return 'BACKSPACE'
    elif ch == '\n' or ch == '\r':
        return 'ENTER'
    elif ch == '':
        return 'ESC'
    else:
        return ch


class DuViewer(object):
    """ANSI TUI for browsing du tree."""

    def __init__(self, tree):
        self.tree = tree
        self.current_dir = tree.root
        self.virtual_root = tree.root
        self.cursor_pos = 0
        self.scroll_offset = 0
        self.sort_mode = SORT_SIZE_DESC
        self.display_list = []
        self._history = []
        self._width = 80
        self._height = 24
        self._needs_redraw = True
        self._rebuild_display()

    def _rebuild_display(self):
        children = list(self.current_dir.children.values())
        self.display_list = sort_children(children, self.sort_mode)
        if len(self.display_list) == 0:
            self.cursor_pos = 0
        elif self.cursor_pos >= len(self.display_list):
            self.cursor_pos = len(self.display_list) - 1
        self._needs_redraw = True

    def _update_size(self):
        self._width, self._height = get_terminal_size()

    def run(self):
        old_settings = termios.tcgetattr(sys.stdin.fileno())
        try:
            tty.setraw(sys.stdin.fileno())
            # Set stdin to non-canonical mode but allow reading
            hide_cursor()
            _flush()

            # Handle SIGWINCH for terminal resize
            def on_resize(signum, frame):
                self._update_size()
                self._needs_redraw = True
                self._draw()

            old_handler = signal.signal(signal.SIGWINCH, on_resize)

            self._update_size()
            while True:
                if self._needs_redraw:
                    self._draw()
                key = read_key()
                if self._handle_key(key):
                    break
        finally:
            signal.signal(signal.SIGWINCH, old_handler if old_handler else signal.SIG_DFL)
            show_cursor()
            reset_attr()
            clear_screen()
            move_cursor(1, 1)
            _flush()
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_settings)

    def _draw(self):
        self._update_size()
        width = self._width
        height = self._height

        clear_screen()

        if height < 3 or width < 20:
            move_cursor(1, 1)
            _write("Terminal too small")
            _flush()
            self._needs_redraw = False
            return

        # Header (row 1)
        path_str = self.current_dir.path or '.'
        header = "Path: %s  [Sort: %s]" % (path_str, SORT_LABELS[self.sort_mode])
        move_cursor(1, 1)
        bold()
        _write(header[:width])
        reset_attr()

        # Column header (row 2)
        col_header = "%10s  %s" % ("SIZE", "NAME")
        move_cursor(2, 1)
        underline()
        _write(col_header[:width])
        reset_attr()

        # Content area
        content_start = 3
        content_height = height - 3  # rows 3..height-1
        if content_height < 1:
            content_height = 1

        # Ensure scroll_offset keeps cursor visible
        if self.cursor_pos < self.scroll_offset:
            self.scroll_offset = self.cursor_pos
        if self.cursor_pos >= self.scroll_offset + content_height:
            self.scroll_offset = self.cursor_pos - content_height + 1

        if len(self.display_list) == 0:
            move_cursor(content_start, 1)
            dim()
            _write("  (empty)")
            reset_attr()
        else:
            n = len(self.display_list)
            for i in range(content_height):
                idx = self.scroll_offset + i
                if idx >= n:
                    break
                node = self.display_list[idx]
                row = content_start + i

                size_str = human_readable(node.size_kb)
                if idx == n - 1:
                    connector = "+-- "
                else:
                    connector = "|-- "
                name = node.name
                if len(node.children) > 0:
                    name += "/"

                line = "%10s  %s%s" % (size_str, connector, name)

                move_cursor(row, 1)
                if idx == self.cursor_pos:
                    reverse_video()
                    padded = line[:width].ljust(width)
                    _write(padded)
                    reset_attr()
                else:
                    _write(line[:width])

        # Status bar (last row)
        n_items = len(self.display_list)
        status = "[q]uit [jk]move [l/Enter]enter [h]back [i]go-in [o]go-out [s]ort  %d items" % n_items
        move_cursor(height, 1)
        bold()
        _write(status[:width])
        reset_attr()

        _flush()
        self._needs_redraw = False

    def _handle_key(self, key):
        n = len(self.display_list)

        if key in ('q', 'ESC'):
            return True

        if key in ('j', 'DOWN'):
            if self.cursor_pos < n - 1:
                self.cursor_pos += 1
                self._needs_redraw = True

        elif key in ('k', 'UP'):
            if self.cursor_pos > 0:
                self.cursor_pos -= 1
                self._needs_redraw = True

        elif key == 'PGDN':
            old = self.cursor_pos
            self.cursor_pos = min(n - 1, self.cursor_pos + 20) if n > 0 else 0
            if self.cursor_pos != old:
                self._needs_redraw = True

        elif key == 'PGUP':
            old = self.cursor_pos
            self.cursor_pos = max(0, self.cursor_pos - 20)
            if self.cursor_pos != old:
                self._needs_redraw = True

        elif key == 'g':
            if self.cursor_pos != 0:
                self.cursor_pos = 0
                self.scroll_offset = 0
                self._needs_redraw = True

        elif key == 'G':
            if n > 0 and self.cursor_pos != n - 1:
                self.cursor_pos = n - 1
                self._needs_redraw = True

        elif key in ('l', 'RIGHT', 'ENTER'):
            if n > 0:
                selected = self.display_list[self.cursor_pos]
                if len(selected.children) > 0:
                    self._history.append((self.current_dir, self.cursor_pos, self.scroll_offset))
                    self.current_dir = selected
                    self.cursor_pos = 0
                    self.scroll_offset = 0
                    self._rebuild_display()

        elif key in ('h', 'LEFT', 'BACKSPACE'):
            if self.current_dir != self.virtual_root and self.current_dir.parent is not None:
                old_name = self.current_dir.name
                if self._history:
                    parent, pos, scroll = self._history.pop()
                    self.current_dir = parent
                    self.cursor_pos = pos
                    self.scroll_offset = scroll
                else:
                    self.current_dir = self.current_dir.parent
                    self.cursor_pos = 0
                    self.scroll_offset = 0
                self._rebuild_display()
                for i, node in enumerate(self.display_list):
                    if node.name == old_name:
                        self.cursor_pos = i
                        break

        elif key == 'i':
            if n > 0:
                selected = self.display_list[self.cursor_pos]
                if len(selected.children) > 0:
                    self.virtual_root = selected
                    self.current_dir = selected
                    self.cursor_pos = 0
                    self.scroll_offset = 0
                    self._history = []
                    self._rebuild_display()

        elif key == 'o':
            self.virtual_root = self.tree.root
            self.current_dir = self.tree.root
            self.cursor_pos = 0
            self.scroll_offset = 0
            self._history = []
            self._rebuild_display()

        elif key == 's':
            self.sort_mode = (self.sort_mode + 1) % 4
            old_name = None
            if n > 0:
                old_name = self.display_list[self.cursor_pos].name
            self._rebuild_display()
            if old_name:
                for i, node in enumerate(self.display_list):
                    if node.name == old_name:
                        self.cursor_pos = i
                        break

        return False


def main():
    if len(sys.argv) > 1:
        filename = sys.argv[1]
    else:
        filename = "du.txt"

    sys.stderr.write("Loading %s...\n" % filename)
    tree = DuTree(filename)
    sys.stderr.write("Loaded %d top-level entries. Starting viewer.\n" % len(tree.root.children))

    viewer = DuViewer(tree)
    viewer.run()


if __name__ == '__main__':
    main()
