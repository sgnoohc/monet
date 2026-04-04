#!/usr/bin/env python3
"""Curses-based email TUI for UF GatorMail — mutt-like terminal reader."""

import curses
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from fetch_mail import (get_token_cache, save_token_cache, authenticate,
                        connect_imap, fetch_email_list, fetch_email_body,
                        set_flag)

# ─── Color pairs ─────────────────────────────────────────────────────────────

C_GREEN = 1
C_RED = 2
C_YELLOW = 3
C_CYAN = 4
C_STATUS_BAR = 5
C_BLUE = 6
C_DIM = 7


def _init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(C_GREEN, curses.COLOR_GREEN, -1)
    curses.init_pair(C_RED, curses.COLOR_RED, -1)
    curses.init_pair(C_YELLOW, curses.COLOR_YELLOW, -1)
    curses.init_pair(C_CYAN, curses.COLOR_CYAN, -1)
    curses.init_pair(C_STATUS_BAR, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(C_BLUE, curses.COLOR_BLUE, -1)
    curses.init_pair(C_DIM, curses.COLOR_WHITE, -1)


LEFT, RIGHT = 0, 1


# ─── MailBrowser ─────────────────────────────────────────────────────────────

class MailBrowser:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.stdscr.keypad(True)
        curses.curs_set(0)
        _init_colors()

        # Auth
        self.cache = get_token_cache()
        self.token, self.username = authenticate(self.cache)
        save_token_cache(self.cache)

        # IMAP
        self.imap = connect_imap(self.token, self.username)
        self.unread_filter = False
        self.emails = []
        self._fetch_list()

        # State
        self.focus = LEFT
        self.list_cursor = 0
        self.list_scroll = 0
        self.body_lines = []
        self.body_scroll = 0
        self.body_uid = None

        self._calc_dimensions()

    def _calc_dimensions(self):
        self.max_y, self.max_x = self.stdscr.getmaxyx()
        self.left_w = max(20, min(50, self.max_x * 40 // 100))
        self.right_w = self.max_x - self.left_w - 3
        self.content_h = self.max_y - 4  # borders + status

    def _safe_addstr(self, y, x, text, attr=0):
        try:
            self.stdscr.addnstr(y, x, text, self.max_x - x - 1, attr)
        except curses.error:
            pass

    # ─── IMAP operations ─────────────────────────────────────────────────

    def _reconnect(self):
        try:
            self.imap.noop()
        except Exception:
            self.cache = get_token_cache()
            self.token, self.username = authenticate(self.cache)
            save_token_cache(self.cache)
            self.imap = connect_imap(self.token, self.username)

    def _fetch_list(self):
        self._reconnect()
        self.emails = fetch_email_list(
            self.imap, unread=self.unread_filter, top=100)

    def _fetch_body(self, uid):
        self._reconnect()
        return fetch_email_body(self.imap, uid)

    def _toggle_seen(self, uid, currently_read):
        self._reconnect()
        # Need read-write access to change flags
        self.imap.select("INBOX", readonly=False)
        set_flag(self.imap, uid, "\\Seen", enable=not currently_read)
        # Back to readonly
        self.imap.select("INBOX", readonly=True)

    # ─── Drawing ─────────────────────────────────────────────────────────

    def draw(self):
        self.stdscr.erase()
        if self.max_y < 6 or self.max_x < 40:
            self._safe_addstr(0, 0, "Terminal too small")
            return

        w = self.max_x
        lw = self.left_w

        # Top border
        top = "┌" + "─" * lw + "┬" + "─" * (w - lw - 3) + "┐"
        self._safe_addstr(0, 0, top[:w])

        # Titles
        title = f" Inbox ({len(self.emails)})"
        if self.unread_filter:
            title += " [unread]"
        self._safe_addstr(0, 2, title, curses.A_BOLD)

        rtitle = " Body"
        if self.body_uid and self.body_lines:
            cur = self.emails[self.list_cursor] if self.list_cursor < len(self.emails) else None
            if cur:
                rtitle = f" {cur['subject'][:self.right_w - 4]}"
        self._safe_addstr(0, lw + 3, rtitle[:self.right_w - 2], curses.A_BOLD)

        # Vertical borders for content rows
        for y in range(1, self.max_y - 2):
            self._safe_addstr(y, 0, "│")
            self._safe_addstr(y, lw + 1, "│")
            if lw + 2 + self.right_w < w:
                self._safe_addstr(y, lw + 2 + self.right_w, "│")

        # Bottom border
        bot_y = self.max_y - 2
        bot = "└" + "─" * lw + "┴" + "─" * (w - lw - 3) + "┘"
        self._safe_addstr(bot_y, 0, bot[:w])

        # Left panel: email list
        self._draw_email_list()

        # Right panel: email body
        self._draw_body()

        # Status bar
        self._draw_status_bar()

    def _draw_email_list(self):
        if not self.emails:
            self._safe_addstr(1, 1, "No emails.".ljust(self.left_w), curses.A_DIM)
            self._safe_addstr(2, 1, "Press 'r' to refresh.".ljust(self.left_w), curses.A_DIM)
            return

        for i in range(self.content_h):
            idx = self.list_scroll + i
            if idx >= len(self.emails):
                break
            y = i + 1
            em = self.emails[idx]

            # Unread dot
            dot = "● " if not em["isRead"] else "  "

            # From: extract name or email
            frm = em["from"]
            if "<" in frm:
                frm = frm.split("<")[0].strip().strip('"')
            if not frm:
                frm = em["from"]

            # Date: compact
            date = em["date"]
            # Try to parse and shorten
            for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%d %b %Y %H:%M:%S %z",
                        "%a, %d %b %Y %H:%M:%S %Z"):
                try:
                    from datetime import datetime
                    dt = datetime.strptime(date.strip(), fmt)
                    date = dt.strftime("%m/%d %H:%M")
                    break
                except (ValueError, ImportError):
                    continue
            else:
                date = date[:11]

            subj = em["subject"] or "(no subject)"

            # Build line
            avail = self.left_w - 2  # padding
            date_w = len(date)
            # dot(2) + subject + gap(1) + from + gap(1) + date
            from_w = min(15, max(8, avail // 4))
            subj_w = avail - 2 - from_w - 1 - date_w - 1
            if subj_w < 5:
                subj_w = avail - 2 - date_w - 1
                from_w = 0

            line = dot
            line += subj[:subj_w].ljust(subj_w)
            if from_w > 0:
                line += " " + frm[:from_w].ljust(from_w)
            line += " " + date

            # Attributes
            is_selected = (idx == self.list_cursor)
            attr = 0
            if is_selected and self.focus == LEFT:
                attr = curses.A_REVERSE
            elif is_selected:
                attr = curses.A_REVERSE | curses.A_DIM
            if not em["isRead"]:
                attr |= curses.A_BOLD

            self._safe_addstr(y, 1, line[:self.left_w].ljust(self.left_w), attr)

    def _draw_body(self):
        x0 = self.left_w + 2
        if not self.body_lines:
            self._safe_addstr(1, x0, "Press Enter to read an email.", curses.A_DIM)
            return

        for i in range(self.content_h):
            li = self.body_scroll + i
            if li >= len(self.body_lines):
                break
            y = i + 1
            line = self.body_lines[li]
            self._safe_addstr(y, x0, line[:self.right_w])

    def _draw_status_bar(self):
        bar_y = self.max_y - 1
        w = self.max_x

        pos = ""
        if self.emails:
            pos = f" {self.list_cursor + 1}/{len(self.emails)}"

        if self.focus == LEFT:
            hints = " j/k:nav Enter:read u:unread r:refresh m:mark g/G:top/end q:quit"
        else:
            hints = " J/K:scroll h/Esc:back u:unread r:refresh m:mark q:quit"

        bar = (pos + hints).ljust(w)
        self._safe_addstr(bar_y, 0, bar[:w], curses.color_pair(C_STATUS_BAR))

    # ─── Actions ─────────────────────────────────────────────────────────

    def _open_email(self):
        if not self.emails:
            return
        em = self.emails[self.list_cursor]
        uid = em["uid"]
        if uid != self.body_uid:
            body = self._fetch_body(uid)
            # Wrap lines to fit right panel
            self.body_lines = []
            for raw_line in body.splitlines():
                while len(raw_line) > self.right_w - 1:
                    self.body_lines.append(raw_line[:self.right_w - 1])
                    raw_line = raw_line[self.right_w - 1:]
                self.body_lines.append(raw_line)
            self.body_uid = uid
            self.body_scroll = 0
        self.focus = RIGHT

    def _scroll_list(self, delta):
        if not self.emails:
            return
        self.list_cursor = max(0, min(len(self.emails) - 1, self.list_cursor + delta))
        # Keep cursor visible
        if self.list_cursor < self.list_scroll:
            self.list_scroll = self.list_cursor
        elif self.list_cursor >= self.list_scroll + self.content_h:
            self.list_scroll = self.list_cursor - self.content_h + 1

    def _scroll_body(self, delta):
        max_scroll = max(0, len(self.body_lines) - self.content_h)
        self.body_scroll = max(0, min(max_scroll, self.body_scroll + delta))

    def _toggle_mark(self):
        if not self.emails:
            return
        em = self.emails[self.list_cursor]
        self._toggle_seen(em["uid"], em["isRead"])
        em["isRead"] = not em["isRead"]

    def _refresh(self):
        self._fetch_list()
        self.list_cursor = min(self.list_cursor, max(0, len(self.emails) - 1))
        self.list_scroll = 0
        self.body_lines = []
        self.body_uid = None
        self.body_scroll = 0

    def _toggle_unread_filter(self):
        self.unread_filter = not self.unread_filter
        self._refresh()

    # ─── Main loop ───────────────────────────────────────────────────────

    def run(self):
        while True:
            self._calc_dimensions()
            self.draw()

            try:
                key = self.stdscr.getch()
            except curses.error:
                continue

            if key == curses.KEY_RESIZE:
                self._calc_dimensions()
                continue

            if key == ord("q"):
                break

            # Navigation
            if key in (ord("j"), curses.KEY_DOWN):
                if self.focus == LEFT:
                    self._scroll_list(1)
                else:
                    self._scroll_body(1)
            elif key in (ord("k"), curses.KEY_UP):
                if self.focus == LEFT:
                    self._scroll_list(-1)
                else:
                    self._scroll_body(-1)
            elif key == ord("J"):
                if self.focus == RIGHT:
                    self._scroll_body(self.content_h // 2)
                else:
                    self._scroll_list(self.content_h // 2)
            elif key == ord("K"):
                if self.focus == RIGHT:
                    self._scroll_body(-self.content_h // 2)
                else:
                    self._scroll_list(-self.content_h // 2)
            elif key in (curses.KEY_NPAGE,):
                if self.focus == RIGHT:
                    self._scroll_body(self.content_h)
                else:
                    self._scroll_list(self.content_h)
            elif key in (curses.KEY_PPAGE,):
                if self.focus == RIGHT:
                    self._scroll_body(-self.content_h)
                else:
                    self._scroll_list(-self.content_h)

            # Open email
            elif key in (10, 13, ord("l"), curses.KEY_RIGHT):
                self._open_email()

            # Back to list
            elif key in (ord("h"), 27, curses.KEY_LEFT):  # h, Esc, left
                self.focus = LEFT

            # Toggle unread filter
            elif key == ord("u"):
                self._toggle_unread_filter()

            # Refresh
            elif key == ord("r"):
                self._refresh()

            # Toggle read/unread
            elif key == ord("m"):
                self._toggle_mark()

            # Top/bottom of list
            elif key == ord("g"):
                self.list_cursor = 0
                self.list_scroll = 0
            elif key == ord("G"):
                if self.emails:
                    self.list_cursor = len(self.emails) - 1
                    self.list_scroll = max(0, len(self.emails) - self.content_h)

    def cleanup(self):
        try:
            self.imap.logout()
        except Exception:
            pass


def main():
    curses.set_escdelay(25)

    def _run(stdscr):
        browser = MailBrowser(stdscr)
        try:
            browser.run()
        finally:
            browser.cleanup()

    curses.wrapper(_run)


if __name__ == "__main__":
    main()
