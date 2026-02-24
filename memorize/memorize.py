#!/usr/bin/env python3
"""Interactive line-by-line memorization tool with statistics tracking."""

import argparse
import curses
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TEXT_FILE = os.path.join(SCRIPT_DIR, "text")


def parse_args():
    parser = argparse.ArgumentParser(description="Interactive line-by-line memorization tool.")
    parser.add_argument("file", nargs="?", default=DEFAULT_TEXT_FILE,
                        help="Text file to memorize (default: text)")
    return parser.parse_args()


args = parse_args()
TEXT_FILE = os.path.abspath(args.file)
STATS_FILE = os.path.splitext(TEXT_FILE)[0] + "_stats.json" if TEXT_FILE != DEFAULT_TEXT_FILE else os.path.join(SCRIPT_DIR, "memorize_stats.json")


def load_lines():
    with open(TEXT_FILE, "r") as f:
        lines = [line.rstrip("\n") for line in f.readlines()]
    # Filter out blank lines but keep track of original line numbers
    indexed = [(i + 1, line) for i, line in enumerate(lines) if line.strip()]
    return indexed


def load_stats():
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_stats(stats):
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f, indent=2)


def find_prev_line(all_lines, orig_num):
    """Find the line that comes right before orig_num in the full text."""
    for i, (num, text) in enumerate(all_lines):
        if num == orig_num and i > 0:
            return all_lines[i - 1]
    return None


def word_wrap_lines(text, width):
    """Split text into wrapped display lines."""
    words = text.split()
    result = []
    cur = ""
    for word in words:
        if len(cur) + len(word) + 1 > width:
            result.append(cur)
            cur = word
        else:
            cur = cur + " " + word if cur else word
    if cur:
        result.append(cur)
    return result or [""]


def main(stdscr):
    curses.curs_set(0)
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    curses.init_pair(2, curses.COLOR_YELLOW, -1)
    curses.init_pair(3, curses.COLOR_RED, -1)
    curses.init_pair(4, curses.COLOR_CYAN, -1)
    curses.init_pair(5, curses.COLOR_MAGENTA, -1)
    curses.init_pair(6, curses.COLOR_WHITE, curses.COLOR_BLUE)

    lines = load_lines()
    stats = load_stats()
    total = len(lines)
    current = 0
    revealed = False
    mode = "normal"  # "normal", "review", or "test"
    hints_shown = 0  # number of words revealed as hints
    show_word_count = True  # toggle: show word count in hidden hint
    show_prev_lines = False  # toggle: show previous lines above current
    prev_lines_count = 3  # how many previous lines to show
    number_display = "line"  # "line", "item", "both"

    # Build review/test queues from struggling lines
    review_queue = []
    review_idx = 0
    test_queue = []  # list of (prev_orig_num, prev_text, orig_num, text)
    test_idx = 0

    def get_active_lines():
        if mode == "review":
            return review_queue
        if mode == "test":
            return [(orig, text) for (_, _, orig, text) in test_queue]
        return lines

    def format_label(orig_num, item_idx=None):
        """Format a line label based on current number_display mode."""
        if item_idx is None:
            # Find item index from the full lines list
            for i, (num, _) in enumerate(lines):
                if num == orig_num:
                    item_idx = i + 1
                    break
        if number_display == "line":
            return f"L{orig_num}"
        elif number_display == "item":
            return f"#{item_idx}" if item_idx else f"L{orig_num}"
        else:  # both
            return f"L{orig_num}/#{item_idx}" if item_idx else f"L{orig_num}"

    def get_line_key(orig_num):
        return str(orig_num)

    def get_struggle_count(orig_num):
        key = get_line_key(orig_num)
        return stats.get(key, {}).get("struggle", 0)

    def get_confident_count(orig_num):
        key = get_line_key(orig_num)
        return stats.get(key, {}).get("confident", 0)

    def get_views(orig_num):
        key = get_line_key(orig_num)
        return stats.get(key, {}).get("views", 0)

    def mark_struggle(orig_num):
        key = get_line_key(orig_num)
        if key not in stats:
            stats[key] = {"struggle": 0, "confident": 0, "views": 0}
        stats[key]["struggle"] += 1
        save_stats(stats)

    def mark_confident(orig_num):
        key = get_line_key(orig_num)
        if key not in stats:
            stats[key] = {"struggle": 0, "confident": 0, "views": 0}
        stats[key]["confident"] += 1
        save_stats(stats)

    def record_view(orig_num):
        key = get_line_key(orig_num)
        if key not in stats:
            stats[key] = {"struggle": 0, "confident": 0, "views": 0}
        stats[key]["views"] += 1
        save_stats(stats)

    def draw(show_stats_panel=False):
        stdscr.clear()
        height, width = stdscr.getmaxyx()
        active = get_active_lines()

        if not active:
            stdscr.addstr(1, 2, "No lines to display.", curses.A_BOLD)
            if mode == "review":
                stdscr.addstr(2, 2, "No struggling lines found. Press 'n' for normal mode.")
            elif mode == "test":
                stdscr.addstr(2, 2, "No struggling lines to test. Press 'n' for normal mode.")
            stdscr.refresh()
            return

        if mode == "test":
            idx = test_idx
        elif mode == "review":
            idx = review_idx
        else:
            idx = current

        if idx >= len(active):
            msg = "End reached! Press "
            if mode == "test":
                msg += "'x' to restart test or "
            msg += "'n' for normal mode or 'q' to quit."
            stdscr.addstr(1, 2, msg, curses.A_BOLD)
            stdscr.refresh()
            return

        orig_num, line_text = active[idx]
        struggle = get_struggle_count(orig_num)
        confident = get_confident_count(orig_num)
        views = get_views(orig_num)

        # Header
        mode_labels = {"normal": "MEMORIZE", "review": "REVIEW MODE", "test": "TEST MODE"}
        mode_label = mode_labels[mode]
        progress = f"[{idx + 1}/{len(active)}]"
        header = f" {mode_label} {progress} "
        stdscr.addstr(0, 0, header.center(width), curses.color_pair(6) | curses.A_BOLD)

        y = 2

        # Show previous lines if toggled on
        if show_prev_lines and mode == "normal" and idx > 0:
            start = max(0, idx - prev_lines_count)
            for pi in range(start, idx):
                p_orig, p_text = active[pi]
                label = format_label(p_orig, pi + 1) + ": "
                try:
                    stdscr.addstr(y, 2, label, curses.A_DIM)
                    for wl in word_wrap_lines(p_text, width - 4 - len(label)):
                        stdscr.addstr(y, 2 + len(label), wl, curses.A_DIM)
                        y += 1
                except curses.error:
                    pass
            y += 1

        # In test mode, show the preceding line as context
        if mode == "test" and test_queue:
            prev_orig, prev_text, _, _ = test_queue[idx]
            if prev_orig is not None:
                stdscr.addstr(y, 2, f"Previous line ({format_label(prev_orig)}):", curses.color_pair(5) | curses.A_BOLD)
                y += 1
                for wl in word_wrap_lines(prev_text, width - 4):
                    try:
                        stdscr.addstr(y, 4, wl, curses.color_pair(5))
                    except curses.error:
                        pass
                    y += 1
                y += 1
                stdscr.addstr(y, 2, "What comes next?", curses.color_pair(2) | curses.A_BOLD)
                y += 1

        # Line number and stats
        stdscr.addstr(y, 2, f"{format_label(orig_num, idx + 1)}:", curses.color_pair(4) | curses.A_BOLD)

        stat_parts = []
        if struggle > 0:
            stat_parts.append(f"struggling: {struggle}")
        if confident > 0:
            stat_parts.append(f"confident: {confident}")
        stat_parts.append(f"views: {views}")
        stat_str = " | ".join(stat_parts)
        try:
            stdscr.addstr(y, width - len(stat_str) - 3, stat_str, curses.A_DIM)
        except curses.error:
            pass
        y += 1

        # Difficulty indicator
        if struggle > 0 and struggle > confident:
            stdscr.addstr(y, 2, " HARD ", curses.color_pair(3) | curses.A_BOLD)
        elif confident > struggle and confident > 0:
            stdscr.addstr(y, 2, " OK ", curses.color_pair(1) | curses.A_BOLD)
        y += 2

        # The text line
        if revealed:
            for wl in word_wrap_lines(line_text, width - 4):
                try:
                    stdscr.addstr(y, 2, wl, curses.A_BOLD)
                except curses.error:
                    pass
                y += 1
            y += 1
            try:
                stdscr.addstr(y, 2, "[SPACE next, s struggle, c confident, b back, q quit]", curses.A_DIM)
            except curses.error:
                pass
        elif hints_shown > 0:
            # Partial reveal: show first N words, rest as underscores
            words = line_text.split()
            shown_words = words[:hints_shown]
            hidden_count = len(words) - hints_shown
            hint_text = " ".join(shown_words)
            if hidden_count > 0:
                blanks = " ".join("____" for _ in range(hidden_count))
                hint_text += " " + blanks
            for wl in word_wrap_lines(hint_text, width - 4):
                try:
                    stdscr.addstr(y, 2, wl, curses.color_pair(2) | curses.A_BOLD)
                except curses.error:
                    pass
                y += 1
            hint_status = f"[{hints_shown}/{len(words)} words shown — h for more, SPACE to reveal all]"
            y += 1
            try:
                stdscr.addstr(y, 2, hint_status, curses.A_DIM)
            except curses.error:
                pass
        else:
            if show_word_count:
                word_count = len(line_text.split())
                hint = f"[{word_count} words hidden — SPACE to reveal, h for hint]"
            else:
                hint = "[hidden — SPACE to reveal, h for hint]"
            stdscr.addstr(y, 2, hint, curses.color_pair(2))

        # Controls
        controls_y = height - 9
        if controls_y > y + 2:
            stdscr.addstr(controls_y, 2, "Controls:", curses.A_UNDERLINE)
            stdscr.addstr(controls_y + 1, 2, "SPACE  reveal/next line    s  mark as struggling")
            stdscr.addstr(controls_y + 2, 2, "c      mark as confident   h  hint (reveal 1 word)")
            stdscr.addstr(controls_y + 3, 2, "v      review hard lines   x  test mode (hard lines)")
            stdscr.addstr(controls_y + 4, 2, "n      normal mode         g  go to line number")
            stdscr.addstr(controls_y + 5, 2, "t      show stats summary  b  back  f  forward    q  quit")
            wc_status = "ON" if show_word_count else "OFF"
            pl_status = f"ON ({prev_lines_count})" if show_prev_lines else "OFF"
            stdscr.addstr(controls_y + 6, 2, f"w      word count [{wc_status}]     p  prev lines [{pl_status}]  +/- set count")
            stdscr.addstr(controls_y + 7, 2, f"l      label mode [{number_display}]   e  edit line   E  edit file in vim")

        if show_stats_panel:
            draw_stats_panel(height, width)

        stdscr.refresh()

    def draw_stats_panel(height, width):
        panel_w = min(60, width - 4)
        panel_h = min(height - 4, 30)
        start_y = 2
        start_x = max(2, (width - panel_w) // 2)

        for y in range(start_y, start_y + panel_h):
            try:
                stdscr.addstr(y, start_x, " " * panel_w, curses.color_pair(6))
            except curses.error:
                pass

        stdscr.addstr(start_y, start_x, " STATISTICS SUMMARY ".center(panel_w), curses.color_pair(6) | curses.A_BOLD)

        struggling = []
        total_struggles = 0
        total_confident = 0
        for orig_num, text in lines:
            key = get_line_key(orig_num)
            s = stats.get(key, {})
            sc = s.get("struggle", 0)
            cc = s.get("confident", 0)
            total_struggles += sc
            total_confident += cc
            if sc > 0:
                struggling.append((orig_num, sc, cc, text))
        struggling.sort(key=lambda x: -x[1])

        y = start_y + 2
        summary = f"Total marks — struggling: {total_struggles}  confident: {total_confident}"
        try:
            stdscr.addstr(y, start_x + 2, summary[:panel_w - 4])
        except curses.error:
            pass
        y += 1
        try:
            stdscr.addstr(y, start_x + 2, f"Lines with struggles: {len(struggling)}/{total}")
        except curses.error:
            pass
        y += 2

        if struggling:
            try:
                stdscr.addstr(y, start_x + 2, "Top struggling lines:", curses.A_UNDERLINE)
            except curses.error:
                pass
            y += 1
            for orig_num, sc, cc, text in struggling[:panel_h - 9]:
                preview = text[:panel_w - 20]
                entry = f"  {format_label(orig_num)}: s={sc} c={cc} | {preview}"
                try:
                    color = curses.color_pair(3) if sc > cc else curses.color_pair(2)
                    stdscr.addstr(y, start_x + 2, entry[:panel_w - 4], color)
                except curses.error:
                    pass
                y += 1

        try:
            stdscr.addstr(start_y + panel_h - 1, start_x, " Press any key to close ".center(panel_w), curses.color_pair(6))
        except curses.error:
            pass

    def build_review_queue():
        nonlocal review_queue, review_idx
        struggling = []
        for orig_num, text in lines:
            key = get_line_key(orig_num)
            s = stats.get(key, {})
            sc = s.get("struggle", 0)
            cc = s.get("confident", 0)
            if sc > cc:
                struggling.append((sc - cc, orig_num, text))
        struggling.sort(key=lambda x: -x[0])
        review_queue = [(num, text) for _, num, text in struggling]
        review_idx = 0

    def build_test_queue():
        nonlocal test_queue, test_idx
        struggling = []
        for orig_num, text in lines:
            key = get_line_key(orig_num)
            s = stats.get(key, {})
            sc = s.get("struggle", 0)
            cc = s.get("confident", 0)
            if sc > cc:
                prev = find_prev_line(lines, orig_num)
                if prev:
                    prev_num, prev_text = prev
                else:
                    prev_num, prev_text = None, ""
                struggling.append((sc - cc, prev_num, prev_text, orig_num, text))
        struggling.sort(key=lambda x: -x[0])
        test_queue = [(pn, pt, on, t) for (_, pn, pt, on, t) in struggling]
        test_idx = 0

    # Record first view
    if lines:
        record_view(lines[0][0])

    show_stats = False
    draw()

    while True:
        key = stdscr.getch()
        active = get_active_lines()
        if mode == "test":
            idx = test_idx
        elif mode == "review":
            idx = review_idx
        else:
            idx = current

        if show_stats:
            show_stats = False
            draw()
            continue

        if key == ord("q"):
            break

        elif key == ord(" "):
            if not active or idx >= len(active):
                continue
            if not revealed:
                revealed = True
                hints_shown = 0
                draw()
            else:
                # Advance
                if mode == "test":
                    test_idx += 1
                    if test_idx < len(test_queue):
                        record_view(test_queue[test_idx][2])
                elif mode == "review":
                    review_idx += 1
                    if review_idx < len(review_queue):
                        record_view(review_queue[review_idx][0])
                else:
                    current += 1
                    if current < total:
                        record_view(lines[current][0])
                revealed = False
                hints_shown = 0
                draw()

        elif key == ord("h"):
            # Hint: reveal one more word
            if active and idx < len(active) and not revealed:
                orig_num, line_text = active[idx]
                word_count = len(line_text.split())
                hints_shown += 1
                if hints_shown >= word_count:
                    revealed = True
                    hints_shown = 0
                draw()

        elif key == ord("s"):
            if active and idx < len(active):
                orig_num = active[idx][0]
                mark_struggle(orig_num)
                draw()

        elif key == ord("c"):
            if active and idx < len(active):
                orig_num = active[idx][0]
                mark_confident(orig_num)
                draw()

        elif key == ord("b"):
            if mode == "test":
                if test_idx > 0:
                    test_idx -= 1
                    revealed = False
                    hints_shown = 0
                    draw()
            elif mode == "review":
                if review_idx > 0:
                    review_idx -= 1
                    revealed = False
                    hints_shown = 0
                    draw()
            else:
                if current > 0:
                    current -= 1
                    revealed = False
                    hints_shown = 0
                    draw()

        elif key == ord("f"):
            if not active or idx >= len(active):
                continue
            if not revealed:
                revealed = True
                hints_shown = 0
                draw()
            else:
                if mode == "test":
                    if test_idx < len(test_queue) - 1:
                        test_idx += 1
                        record_view(test_queue[test_idx][2])
                elif mode == "review":
                    if review_idx < len(review_queue) - 1:
                        review_idx += 1
                        record_view(review_queue[review_idx][0])
                else:
                    if current < total - 1:
                        current += 1
                        record_view(lines[current][0])
                revealed = False
                hints_shown = 0
                draw()

        elif key == ord("v"):
            mode = "review"
            build_review_queue()
            revealed = False
            hints_shown = 0
            draw()

        elif key == ord("x"):
            mode = "test"
            build_test_queue()
            revealed = False
            hints_shown = 0
            draw()

        elif key == ord("n"):
            mode = "normal"
            revealed = False
            hints_shown = 0
            draw()

        elif key == ord("t"):
            show_stats = True
            draw(show_stats_panel=True)

        elif key == ord("g"):
            stdscr.addstr(0, 0, " Go to line: " + " " * 20, curses.color_pair(6))
            stdscr.refresh()
            curses.echo()
            curses.curs_set(1)
            try:
                inp = stdscr.getstr(0, 14, 6).decode("utf-8").strip()
                target = int(inp)
                for i, (orig_num, _) in enumerate(active):
                    if orig_num == target:
                        if mode == "test":
                            test_idx = i
                        elif mode == "review":
                            review_idx = i
                        else:
                            current = i
                        revealed = False
                        hints_shown = 0
                        break
            except (ValueError, curses.error):
                pass
            curses.noecho()
            curses.curs_set(0)
            draw()

        elif key == ord("w"):
            show_word_count = not show_word_count
            draw()

        elif key == ord("p"):
            show_prev_lines = not show_prev_lines
            draw()

        elif key == ord("l"):
            cycle = {"line": "item", "item": "both", "both": "line"}
            number_display = cycle[number_display]
            draw()

        elif key == ord("+") or key == ord("="):
            prev_lines_count += 1
            draw()

        elif key == ord("-"):
            if prev_lines_count > 1:
                prev_lines_count -= 1
            draw()

        elif key == ord("e"):
            # Edit just the current line in vim
            if active and idx < len(active):
                orig_num, line_text = active[idx]
                with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tf:
                    tf.write(line_text + "\n")
                    tf_path = tf.name
                curses.endwin()
                subprocess.call(["vim", tf_path])
                stdscr = curses.initscr()
                curses.curs_set(0)
                curses.noecho()
                curses.cbreak()
                stdscr.keypad(True)
                curses.start_color()
                curses.use_default_colors()
                curses.init_pair(1, curses.COLOR_GREEN, -1)
                curses.init_pair(2, curses.COLOR_YELLOW, -1)
                curses.init_pair(3, curses.COLOR_RED, -1)
                curses.init_pair(4, curses.COLOR_CYAN, -1)
                curses.init_pair(5, curses.COLOR_MAGENTA, -1)
                curses.init_pair(6, curses.COLOR_WHITE, curses.COLOR_BLUE)
                # Read edited line back
                with open(tf_path, "r") as rf:
                    new_text = rf.read().strip()
                os.unlink(tf_path)
                if new_text and new_text != line_text:
                    # Update the text file
                    with open(TEXT_FILE, "r") as rf:
                        all_text = rf.readlines()
                    all_text[orig_num - 1] = new_text + "\n"
                    with open(TEXT_FILE, "w") as wf:
                        wf.writelines(all_text)
                    # Reload lines
                    lines = load_lines()
                    total = len(lines)
                    if mode == "review":
                        build_review_queue()
                    elif mode == "test":
                        build_test_queue()
                draw()

        elif key == ord("E"):
            # Open the whole file in vim at the current line
            if active and idx < len(active):
                orig_num = active[idx][0]
                curses.endwin()
                subprocess.call(["vim", f"+{orig_num}", TEXT_FILE])
                stdscr = curses.initscr()
                curses.curs_set(0)
                curses.noecho()
                curses.cbreak()
                stdscr.keypad(True)
                curses.start_color()
                curses.use_default_colors()
                curses.init_pair(1, curses.COLOR_GREEN, -1)
                curses.init_pair(2, curses.COLOR_YELLOW, -1)
                curses.init_pair(3, curses.COLOR_RED, -1)
                curses.init_pair(4, curses.COLOR_CYAN, -1)
                curses.init_pair(5, curses.COLOR_MAGENTA, -1)
                curses.init_pair(6, curses.COLOR_WHITE, curses.COLOR_BLUE)
                # Reload lines since file may have changed
                lines = load_lines()
                total = len(lines)
                if current >= total:
                    current = max(0, total - 1)
                if mode == "review":
                    build_review_queue()
                elif mode == "test":
                    build_test_queue()
                draw()

        elif key == curses.KEY_RESIZE:
            draw()


if __name__ == "__main__":
    curses.wrapper(main)
