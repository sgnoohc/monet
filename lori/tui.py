#!/usr/bin/env python3
"""Curses TUI project browser for lori."""

import copy
import curses
import datetime
import re
import subprocess
import sys
from collections import namedtuple

from lori import (load_projects, save_projects, parse_date, today, fmt_date,
                  load_schedule, load_config, save_config,
                  expand_events_for_date,
                  calc_free_time, parse_time, fmt_time, save_schedule,
                  day_name_to_int, get_work_hours, convert_event_time)
import json
import os
import tempfile
import textwrap
import unicodedata

import yaml

from fetch_mail import (get_token_cache, save_token_cache, authenticate,
                        connect_imap, fetch_email_list, fetch_email_body,
                        set_flag, search_uids)

# ─── Data structures ─────────────────────────────────────────────────────────

DetailItem = namedtuple("DetailItem", ["kind", "index", "text", "selectable"])
# kind: "header" | "info" | "milestone" | "task" | "notes" | "blank"
# index: position in project["milestones"] or project["tasks"], or None
# selectable: whether cursor can land on this row

LEFT, RIGHT = 0, 1
VIEW_PROJECTS, VIEW_TODAY, VIEW_WEEK, VIEW_MONTH = 0, 1, 2, 3
VIEW_SCHED_DAY, VIEW_SCHED_WEEK, VIEW_SCHED_MONTH, VIEW_SCHED_NDAY = 4, 5, 6, 7
VIEW_MAIL_INBOX = 8

MODE_TASKS, MODE_CALENDAR, MODE_MAIL = 0, 1, 2
_TASK_VIEWS = [VIEW_PROJECTS, VIEW_TODAY, VIEW_WEEK, VIEW_MONTH]
_CAL_VIEWS = [VIEW_SCHED_DAY, VIEW_SCHED_NDAY, VIEW_SCHED_WEEK, VIEW_SCHED_MONTH]
_MAIL_VIEWS = [VIEW_MAIL_INBOX]

# ─── Color pairs ──────────────────────────────────────────────────────────────

C_GREEN = 1
C_RED = 2
C_YELLOW = 3
C_CYAN = 4
C_STATUS_BAR = 5
C_BLUE = 6
C_MAGENTA = 7
C_NONWORK = 8
C_MAIL_FROM = 9
C_MAIL_DATE = 10
C_RPANEL_BG = 11        # subtle background for focused right panel
C_RPANEL_CYAN = 12
C_RPANEL_FROM = 13
C_RPANEL_DATE = 14


def _init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(C_GREEN, curses.COLOR_GREEN, -1)
    curses.init_pair(C_RED, curses.COLOR_RED, -1)
    curses.init_pair(C_YELLOW, curses.COLOR_YELLOW, -1)
    curses.init_pair(C_CYAN, curses.COLOR_CYAN, -1)
    curses.init_pair(C_STATUS_BAR, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(C_BLUE, curses.COLOR_BLUE, -1)
    curses.init_pair(C_MAGENTA, curses.COLOR_MAGENTA, -1)
    if curses.COLORS >= 256:
        curses.init_pair(C_NONWORK, 240, 236)  # gray on dark gray
    else:
        curses.init_pair(C_NONWORK, curses.COLOR_BLACK, curses.COLOR_BLUE)
    curses.init_pair(C_MAIL_FROM, curses.COLOR_CYAN, -1)
    curses.init_pair(C_MAIL_DATE, curses.COLOR_YELLOW, -1)
    if curses.COLORS >= 256:
        curses.init_pair(C_RPANEL_BG, -1, 235)
        curses.init_pair(C_RPANEL_CYAN, curses.COLOR_CYAN, 235)
        curses.init_pair(C_RPANEL_FROM, curses.COLOR_CYAN, 235)
        curses.init_pair(C_RPANEL_DATE, curses.COLOR_YELLOW, 235)
    else:
        curses.init_pair(C_RPANEL_BG, -1, curses.COLOR_BLACK)
        curses.init_pair(C_RPANEL_CYAN, curses.COLOR_CYAN, curses.COLOR_BLACK)
        curses.init_pair(C_RPANEL_FROM, curses.COLOR_CYAN, curses.COLOR_BLACK)
        curses.init_pair(C_RPANEL_DATE, curses.COLOR_YELLOW, curses.COLOR_BLACK)


# ─── String width helpers (East Asian wide chars) ────────────────────────────

def _char_width(ch):
    """Return display width of a character (2 for wide/fullwidth, 1 otherwise)."""
    w = unicodedata.east_asian_width(ch)
    return 2 if w in ("W", "F") else 1


def _str_width(s):
    """Return display width of a string, accounting for wide characters."""
    return sum(_char_width(ch) for ch in s)


def _sanitize_text(s):
    """Replace tabs with spaces and strip control chars for safe curses display."""
    s = s.replace("\t", "    ")
    # Strip all C0 control chars except newline (null bytes cause addnstr to stop early)
    return "".join(ch for ch in s if ch == "\n" or ch >= " ")


_URL_RE = re.compile(r'https?://\S{40,}')


def _shorten_urls(text):
    """Replace long URLs with [link:N] placeholders, return (text, links_list)."""
    links = []
    def _repl(m):
        links.append(m.group(0))
        return f"[link:{len(links)}]"
    shortened = _URL_RE.sub(_repl, text)
    return shortened, links


def _wc_truncate(s, width):
    """Truncate string to fit within `width` display columns."""
    w = 0
    for i, ch in enumerate(s):
        cw = _char_width(ch)
        if w + cw > width:
            return s[:i]
        w += cw
    return s


def _wc_ljust(s, width):
    """Left-justify string to `width` display columns with space padding."""
    sw = _str_width(s)
    if sw >= width:
        return _wc_truncate(s, width)
    return s + " " * (width - sw)


# ─── Task helpers ────────────────────────────────────────────────────────────

def _task_text(t):
    """Extract display text from a task (string or dict)."""
    return t if isinstance(t, str) else t.get("desc", str(t))


def _task_due(t):
    """Extract due date string from a task, or None."""
    if isinstance(t, dict):
        return t.get("due")
    return None


def _task_done(t):
    """Return whether a task is marked done."""
    if isinstance(t, dict):
        return t.get("done", False)
    return False


def _task_to_dict(t):
    """Ensure a task is a dict (promote plain strings)."""
    if isinstance(t, str):
        return {"desc": t}
    return t


# ─── Mail threading helpers ───────────────────────────────────────────────────

import re as _re

def _normalize_subject(subj):
    """Strip Re:/Fwd:/FW: prefixes, lowercase, collapse whitespace."""
    s = _re.sub(r'^(\s*(Re|Fwd|FW|Fw)\s*:\s*)+', '', subj or '', flags=_re.IGNORECASE)
    return _re.sub(r'\s+', ' ', s).strip().lower()


def _has_reply_prefix(subj):
    """Return True if subject starts with Re:/Fwd:/FW:."""
    return bool(_re.match(r'\s*(Re|Fwd|FW|Fw)\s*:', subj or '', flags=_re.IGNORECASE))


def _build_mail_threads(emails):
    """Group emails into conversation threads.

    Returns list of thread dicts sorted by latest date descending.
    """
    if not emails:
        return []

    # Union-Find
    parent = {}
    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    uid_by_mid = {}  # message-id -> uid
    for em in emails:
        mid = em.get("messageId", "")
        if mid:
            uid_by_mid[mid] = em["uid"]

    # Link via In-Reply-To and References
    for em in emails:
        uid = em["uid"]
        irt = em.get("inReplyTo", "")
        if irt and irt in uid_by_mid:
            union(uid, uid_by_mid[irt])
        for ref in em.get("references", []):
            if ref in uid_by_mid:
                union(uid, uid_by_mid[ref])

    # Subject-based fallback for singletons
    groups = {}
    for em in emails:
        root = find(em["uid"])
        groups.setdefault(root, []).append(em)

    # Subject-based fallback: group singletons via normalized subject
    # Only merge when at least one email has a reply prefix
    norm_map = {}  # normalized subject -> root uid
    # First pass: register multi-member groups and reply-prefix singletons
    for root, members in list(groups.items()):
        if len(members) > 1:
            ns = _normalize_subject(members[0].get("subject", ""))
            if ns:
                if ns in norm_map:
                    union(root, norm_map[ns])
                else:
                    norm_map[ns] = root
        elif _has_reply_prefix(members[0].get("subject", "")):
            ns = _normalize_subject(members[0].get("subject", ""))
            if ns:
                if ns in norm_map:
                    union(root, norm_map[ns])
                else:
                    norm_map[ns] = root
    # Second pass: merge non-reply singletons into existing norm_map groups
    for root, members in list(groups.items()):
        if len(members) == 1 and not _has_reply_prefix(members[0].get("subject", "")):
            ns = _normalize_subject(members[0].get("subject", ""))
            if ns and ns in norm_map:
                union(root, norm_map[ns])

    # Rebuild groups after subject-based merging
    groups = {}
    for em in emails:
        root = find(em["uid"])
        groups.setdefault(root, []).append(em)

    # Parse dates for sorting
    def _parse_date(date_str):
        for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%d %b %Y %H:%M:%S %z",
                    "%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S"):
            try:
                from datetime import datetime as _dt
                return _dt.strptime(date_str.strip(), fmt)
            except (ValueError, TypeError):
                continue
        return None

    def _date_sort_key(date_str):
        """Return a float timestamp for sorting, 0.0 if unparseable."""
        dt = _parse_date(date_str)
        if dt is None:
            return 0.0
        try:
            return dt.timestamp()
        except (OSError, ValueError, OverflowError):
            return 0.0

    threads = []
    for root, members in groups.items():
        # Sort within thread chronologically (oldest first)
        members.sort(key=lambda e: _date_sort_key(e.get("date", "")))

        subj = _normalize_subject(members[-1].get("subject", "")) or "(no subject)"
        # Use the raw subject of the latest email for display
        display_subj = members[-1].get("subject", "") or "(no subject)"
        # Strip Re:/Fwd: for clean display
        display_subj = _re.sub(r'^(\s*(Re|Fwd|FW|Fw)\s*:\s*)+', '', display_subj,
                               flags=_re.IGNORECASE).strip() or display_subj

        uids = {e["uid"] for e in members}
        unread = sum(1 for e in members if not e.get("isRead", True))

        # From summary: unique sender names, max 3
        seen_names = []
        for e in members:
            frm = e.get("from", "")
            if "<" in frm:
                frm = frm.split("<")[0].strip().strip('"')
            if frm and frm not in seen_names:
                seen_names.append(frm)
        if len(seen_names) > 3:
            from_summary = ", ".join(seen_names[:3]) + "…"
        else:
            from_summary = ", ".join(seen_names) if seen_names else ""

        threads.append({
            "subject": display_subj,
            "norm_subject": subj,
            "emails": members,
            "uids": uids,
            "latest_date": members[-1].get("date", ""),
            "unread_count": unread,
            "from_summary": from_summary,
            "_sort_key": _date_sort_key(members[-1].get("date", "")),
        })

    # Sort threads by latest date descending
    threads.sort(key=lambda t: t["_sort_key"], reverse=True)
    for t in threads:
        del t["_sort_key"]

    return threads


# ─── ProjectBrowser ──────────────────────────────────────────────────────────

class ProjectBrowser:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.stdscr.keypad(True)
        curses.curs_set(0)
        _init_colors()

        self.projects = load_projects()
        self.show_all = False  # False = active only
        self.view_mode = VIEW_PROJECTS
        self.mode = MODE_TASKS
        self.sort_by_due = False
        self.timeline_items = []

        self.schedule = load_schedule()
        self.config = load_config()
        self.sched_date = today()
        self.sched_day_items = []
        self.sched_week_data = []
        self.sched_month_data = []
        self.sched_nday_count = self.config.get("nday_count", 3)
        self.sched_nday_data = []
        self.nday_event_cursor = 0
        self.week_event_cursor = 0
        self.clipboard_event = None   # deepcopy of source schedule entry
        self.clipboard_mode = None    # "one" or "all"
        self.week_start_sunday = self.config.get("week_start", "monday").lower() == "sunday"
        self._undo_stack = []

        self._rebuild_filtered()

        self.left_cursor = 0
        self.left_scroll = 0
        self.right_cursor = 0
        self.right_scroll = 0
        self.focus = LEFT

        self.detail_items = []
        self._rebuild_detail()

        # Mail state (lazy-loaded)
        self.mail_imap = None
        self.mail_emails = []
        self.mail_body_lines = []
        self.mail_body_uid = None
        self.mail_body_scroll = 0
        self.mail_unread_filter = False
        self.mail_selected = set()
        self._mail_loaded_count = 0
        self._mail_body_cache = {}  # uid -> body text
        self._mail_body_pending = False
        self._mail_left_w_offset = 0  # user adjustment for left pane width
        self._left_w_offset = 0      # user adjustment for task/project pane width
        self._right_panel_hidden = False  # \ toggle to hide right panel
        self._mail_search_query = ""   # current search string

        # Threading state
        self.mail_threads = []              # derived thread list
        self.mail_threaded = True           # True=threaded, False=flat
        self.mail_thread_body_lines = []    # conversation view for right panel
        self.mail_thread_body_scroll = 0
        self.mail_thread_body_idx = None    # index of thread shown in right panel
        self._mail_expanded = set()         # set of expanded thread indices
        self._mail_display_rows = []        # flat list of display rows (thread + email)

        # Conversation view state
        self._conv_emails = []              # list of email dicts in conversation order (newest first)
        self._conv_pos = 0                  # index of focused email in _conv_emails
        self._conv_collapsed = set()        # indices of collapsed emails (header-only)
        self._conv_quotes_shown = set()     # indices where quoted text is expanded
        self._conv_line_map = []            # list of (email_idx, line_type) per line
        self._mail_raw_mode = False         # False=processed (collapse blank runs), True=raw

        self._cmd_params = {}               # pre-filled params from command palette

        self._calc_dimensions()

    # ─── Filtering ────────────────────────────────────────────────────────

    def _rebuild_filtered(self):
        if self.show_all:
            self.filtered = list(self.projects)
        else:
            self.filtered = [p for p in self.projects if p.get("status") == "active"]

        if self.sort_by_due and self.view_mode == VIEW_PROJECTS:
            def _earliest_due(proj):
                earliest = None
                for ms in proj.get("milestones", []):
                    if ms.get("done"):
                        continue
                    due = ms.get("due")
                    if due:
                        try:
                            d = parse_date(due)
                            if earliest is None or d < earliest:
                                earliest = d
                        except ValueError:
                            pass
                return earliest if earliest is not None else datetime.date.max
            self.filtered.sort(key=_earliest_due)

        if self.view_mode in (VIEW_TODAY, VIEW_WEEK, VIEW_MONTH):
            self._rebuild_timeline()
        elif self.view_mode == VIEW_SCHED_DAY:
            self._rebuild_schedule_day()
        elif self.view_mode == VIEW_SCHED_WEEK:
            self._rebuild_schedule_week()
        elif self.view_mode == VIEW_SCHED_MONTH:
            self._rebuild_schedule_month()
        elif self.view_mode == VIEW_SCHED_NDAY:
            self._rebuild_schedule_nday()
        elif self.view_mode == VIEW_MAIL_INBOX:
            pass  # mail list managed by _mail_fetch_list()

    def _rebuild_timeline(self):
        td = today()
        if self.view_mode == VIEW_TODAY:
            cutoff = td
        elif self.view_mode == VIEW_WEEK:
            cutoff = td + datetime.timedelta(days=7)
        else:  # VIEW_MONTH
            cutoff = td + datetime.timedelta(days=30)

        items = []
        source = self.filtered if self.filtered else []
        for proj in source:
            for i, ms in enumerate(proj.get("milestones", [])):
                if ms.get("done"):
                    continue
                due = ms.get("due")
                if due:
                    try:
                        due_date = parse_date(due)
                    except ValueError:
                        due_date = None
                    if due_date and due_date <= cutoff:
                        items.append({"kind": "milestone", "milestone": ms,
                                      "project": proj, "due_date": due_date,
                                      "ms_index": i})
                # Milestone sub-tasks with due dates
                for j, t in enumerate(ms.get("tasks", [])):
                    if _task_done(t):
                        continue
                    t_due = _task_due(t)
                    if not t_due:
                        continue
                    try:
                        t_due_date = parse_date(t_due)
                    except ValueError:
                        continue
                    if t_due_date <= cutoff:
                        items.append({"kind": "ms_task", "task": t,
                                      "milestone": ms, "project": proj,
                                      "due_date": t_due_date,
                                      "ms_index": i, "task_index": j})

            # Standalone tasks with due dates
            for i, t in enumerate(proj.get("tasks", [])):
                if _task_done(t):
                    continue
                t_due = _task_due(t)
                if not t_due:
                    continue
                try:
                    t_due_date = parse_date(t_due)
                except ValueError:
                    continue
                if t_due_date <= cutoff:
                    items.append({"kind": "task", "task": t,
                                  "project": proj, "due_date": t_due_date,
                                  "task_index": i})

        items.sort(key=lambda x: x["due_date"])
        self.timeline_items = items

    def _rebuild_schedule_day(self):
        events = expand_events_for_date(self.schedule, self.sched_date)
        free_slots, total_free = calc_free_time(events, self.config, self.sched_date)

        items = []

        # Add events
        for ev in events:
            start = ev.get("start") or ev.get("depart") or ""
            end = ev.get("end") or ""
            title = ev.get("title", "???")
            s_str = fmt_time(parse_time(start)) if start else "??:??"
            e_str = fmt_time(parse_time(end)) if end else "??:??"

            ev_type = ev.get("type", "")
            tag = f"  [{ev_type}]" if ev_type else ""
            text = f"  {s_str}-{e_str}  {title}{tag}"

            sort_time = parse_time(start) if start else datetime.time(23, 59)
            items.append({
                "kind": "event", "event": ev, "text": text,
                "free_minutes": 0, "selectable": True,
                "_sort": sort_time,
            })

        # Add free gaps
        ref = self.sched_date
        for s, e in free_slots:
            mins = (datetime.datetime.combine(ref, e) -
                    datetime.datetime.combine(ref, s)).seconds // 60
            hrs = mins / 60
            if hrs >= 0.1:
                text = f"  ── free {hrs:.1f}h ──"
                items.append({
                    "kind": "free", "event": None, "text": text,
                    "free_minutes": mins, "selectable": False,
                    "_sort": s,
                })

        items.sort(key=lambda x: x["_sort"])
        for item in items:
            item.pop("_sort", None)

        self.sched_day_items = items

    def _rebuild_schedule_week(self):
        d = self.sched_date
        if self.week_start_sunday:
            # Sunday = 6 in weekday(), so offset to make Sunday day 0
            offset = (d.weekday() + 1) % 7
            week_start = d - datetime.timedelta(days=offset)
        else:
            week_start = d - datetime.timedelta(days=d.weekday())

        self.sched_week_data = []
        for i in range(7):
            day = week_start + datetime.timedelta(days=i)
            events = expand_events_for_date(self.schedule, day)
            free_slots, total_free = calc_free_time(events, self.config, day)
            self.sched_week_data.append({
                "date": day,
                "events": events,
                "free_hours": total_free / 60,
                "count": len(events),
            })

    def _rebuild_schedule_nday(self):
        self.sched_nday_data = []
        for i in range(self.sched_nday_count):
            day = self.sched_date + datetime.timedelta(days=i)
            events = expand_events_for_date(self.schedule, day)
            free_slots, total_free = calc_free_time(events, self.config, day)
            self.sched_nday_data.append({
                "date": day,
                "events": events,
                "free_hours": total_free / 60,
                "count": len(events),
            })

    def _rebuild_schedule_month(self):
        import calendar
        d = self.sched_date
        first = d.replace(day=1)
        num_days = calendar.monthrange(d.year, d.month)[1]

        self.sched_month_data = []
        current_week_key = None
        for i in range(num_days):
            day = first + datetime.timedelta(days=i)
            if self.week_start_sunday:
                offset = (day.weekday() + 1) % 7
                wk_start = day - datetime.timedelta(days=offset)
            else:
                wk_start = day - datetime.timedelta(days=day.weekday())
            wk_end = wk_start + datetime.timedelta(days=6)
            week_key = wk_start
            if week_key != current_week_key:
                current_week_key = week_key
                week_num = day.isocalendar()[1]
                label = f"W{week_num}: {wk_start.strftime('%b %d')} – {wk_end.strftime('%b %d')}"
                self.sched_month_data.append({
                    "kind": "week_header",
                    "text": label,
                    "selectable": False,
                })
            events = expand_events_for_date(self.schedule, day)
            free_slots, total_free = calc_free_time(events, self.config, day)
            self.sched_month_data.append({
                "kind": "day",
                "date": day,
                "events": events,
                "free_hours": total_free / 60,
                "count": len(events),
                "selectable": True,
            })

    # ─── Detail items ─────────────────────────────────────────────────────

    def _rebuild_detail(self):
        self.detail_items = []

        if self.view_mode == VIEW_MAIL_INBOX:
            return  # mail body handled separately

        if self.view_mode == VIEW_SCHED_DAY:
            self._rebuild_detail_sched_day()
            self._snap_right_cursor()
            return
        if self.view_mode == VIEW_SCHED_NDAY:
            self._rebuild_detail_sched_nday()
            self._snap_right_cursor()
            return
        if self.view_mode == VIEW_SCHED_WEEK:
            self._rebuild_detail_sched_week_ev()
            self._snap_right_cursor()
            return
        if self.view_mode == VIEW_SCHED_MONTH:
            self._rebuild_detail_sched_week()
            self._snap_right_cursor()
            return

        if self.view_mode in (VIEW_TODAY, VIEW_WEEK, VIEW_MONTH):
            # Timeline view: show parent project of selected item
            if not self.timeline_items:
                return
            idx = min(self.left_cursor, len(self.timeline_items) - 1)
            proj = self.timeline_items[idx]["project"]
        elif not self.filtered:
            return
        else:
            proj = self.filtered[self.left_cursor]

        # Title (editable)
        self.detail_items.append(DetailItem("field", "name", f"Title: {proj.get('name', '???')}", True))

        # Category & status
        cat = proj.get("category", "")
        status = proj.get("status", "active")
        self.detail_items.append(DetailItem("field", "category", f"Category: {cat or '—'}", True))
        self.detail_items.append(DetailItem("field", "status", f"Status: {status}", True))

        # Deadline
        dl = proj.get("deadline")
        if dl:
            try:
                dl_date = parse_date(dl)
                delta = (dl_date - today()).days
                self.detail_items.append(DetailItem("field", "deadline",
                    f"Deadline: {fmt_date(dl_date)} ({delta}d)", True))
            except ValueError:
                self.detail_items.append(DetailItem("field", "deadline", f"Deadline: {dl}", True))
        else:
            self.detail_items.append(DetailItem("field", "deadline", "Deadline: —", True))

        # Description
        desc = proj.get("description", "")
        if desc:
            self.detail_items.append(DetailItem("blank", None, "", False))
            self.detail_items.append(DetailItem("field", "description", "Description", True))
            for dline in textwrap.wrap(desc, width=60):
                self.detail_items.append(DetailItem("info", None, f"  {dline}", False))
        else:
            self.detail_items.append(DetailItem("blank", None, "", False))
            self.detail_items.append(DetailItem("field", "description", "Description: —", True))

        # Milestones
        milestones = proj.get("milestones", [])
        if milestones:
            self.detail_items.append(DetailItem("blank", None, "", False))
            self.detail_items.append(DetailItem("header", None, "Milestones", False))
            for i, ms in enumerate(milestones):
                name = ms.get("name", "???")
                due = ms.get("due")
                done = ms.get("done", False)
                comp = ms.get("completed_date", "")
                if done:
                    mark = "✓"
                    date_str = f"  ({comp})" if comp else ""
                    text = f"  {mark} {name}{date_str}"
                else:
                    mark = "○"
                    if due:
                        try:
                            due_d = parse_date(due)
                            date_str = f"  ({fmt_date(due_d)})"
                        except ValueError:
                            date_str = f"  ({due})"
                    else:
                        date_str = ""
                    text = f"  {mark} {name}{date_str}"
                self.detail_items.append(DetailItem("milestone", i, text, True))
                # Tasks nested under this milestone
                for j, t in enumerate(ms.get("tasks", [])):
                    t_text = _task_text(t)
                    t_due = _task_due(t)
                    t_done = _task_done(t)
                    t_due_str = ""
                    if t_done:
                        comp = t.get("completed_date", "") if isinstance(t, dict) else ""
                        t_mark = "✓"
                        t_due_str = f"  ({comp})" if comp else ""
                    else:
                        t_mark = "·"
                        if t_due:
                            t_due_str = f"  ({fmt_date(parse_date(t_due))})"
                    self.detail_items.append(DetailItem("ms_task", (i, j), f"      {t_mark} {t_text}{t_due_str}", True))

        # Tasks
        tasks = proj.get("tasks", [])
        if tasks:
            self.detail_items.append(DetailItem("blank", None, "", False))
            self.detail_items.append(DetailItem("header", None, "Tasks", False))
            for i, t in enumerate(tasks):
                t_text = _task_text(t)
                t_due = _task_due(t)
                t_done = _task_done(t)
                t_due_str = ""
                if t_done:
                    comp = t.get("completed_date", "") if isinstance(t, dict) else ""
                    t_mark = "✓"
                    t_due_str = f"  ({comp})" if comp else ""
                else:
                    t_mark = "·"
                    if t_due:
                        t_due_str = f"  ({fmt_date(parse_date(t_due))})"
                text = f"  {t_mark} {t_text}{t_due_str}"
                self.detail_items.append(DetailItem("task", i, text, True))

        # Notes
        notes = proj.get("notes", "")
        if notes:
            self.detail_items.append(DetailItem("blank", None, "", False))
            self.detail_items.append(DetailItem("header", None, "Notes", False))
            for line in str(notes).split("\n"):
                self.detail_items.append(DetailItem("notes", None, f"  {line}", False))

        # Snap right_cursor to first selectable
        self._snap_right_cursor()

    def _format_recurring_info(self, ev):
        rec = ev.get("recurring")
        if not rec:
            return None
        if rec == "monthly":
            dow = ev.get("day_of_week")
            if dow:
                wom = ev.get("week_of_month", 1)
                ordinals = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th", -1: "last"}
                rec_info = f"Recurring: monthly ({ordinals.get(wom, str(wom))} {dow.title()})"
            else:
                dom = ev.get("day_of_month", 1)
                rec_info = f"Recurring: monthly (day {dom})"
            interval = ev.get("interval")
            if interval and interval > 1:
                rec_info += f" every {interval} months"
            return rec_info
        rec_info = f"Recurring: {rec}"
        days = ev.get("days")
        day = ev.get("day")
        if days:
            rec_info += f" ({', '.join(days)})"
        elif day:
            rec_info += f" ({day})"
        interval = ev.get("interval")
        if interval and interval > 1:
            rec_info += f" every {interval} {'weeks' if rec == 'weekly' else 'days'}"
        return rec_info

    def _rebuild_detail_sched_day(self):
        if not self.sched_day_items:
            return
        idx = min(self.left_cursor, len(self.sched_day_items) - 1)
        item = self.sched_day_items[idx]
        if item["kind"] != "event" or not item["event"]:
            return

        ev = item["event"]
        self.detail_items.append(DetailItem("header", None, ev.get("title", "???"), False))
        self.detail_items.append(DetailItem("blank", None, "", False))

        ev_type = ev.get("type", "meeting")
        self.detail_items.append(DetailItem("info", None, f"Type: {ev_type}", False))

        start = ev.get("start") or ev.get("depart") or ""
        end = ev.get("end") or ""
        if start:
            ev_tz = ev.get("timezone")
            local_tz = self.config.get("timezone")
            if ev_tz and local_tz and ev_tz != local_tz:
                s_local = convert_event_time(start, ev_tz, local_tz)
                time_str = fmt_time(s_local)
                if end:
                    e_local = convert_event_time(end, ev_tz, local_tz)
                    time_str += f" - {fmt_time(e_local)}"
                time_str += f"  ({fmt_time(parse_time(start))} {ev_tz})"
            else:
                time_str = fmt_time(parse_time(start))
                if end:
                    time_str += f" - {fmt_time(parse_time(end))}"
            self.detail_items.append(DetailItem("info", None, f"Time: {time_str}", False))

        loc = ev.get("location") or ""
        if loc:
            loc_label = f"Location: {loc}"
            if "://" in loc:
                loc_label += "  (o to open)"
            self.detail_items.append(DetailItem("info", None, loc_label, False))

        if ev.get("type") == "travel":
            fr = ev.get("from", "")
            to = ev.get("to", "")
            if fr:
                self.detail_items.append(DetailItem("info", None, f"From: {fr}", False))
            if to:
                self.detail_items.append(DetailItem("info", None, f"To: {to}", False))

        rec_info = self._format_recurring_info(ev)
        if rec_info:
            self.detail_items.append(DetailItem("info", None, rec_info, False))

        if ev.get("timezone"):
            self.detail_items.append(DetailItem("info", None, f"Timezone: {ev['timezone']}", False))

        if ev.get("private"):
            self.detail_items.append(DetailItem("info", None, "Visibility: private", False))

    def _rebuild_detail_sched_nday(self):
        if not self.sched_nday_data:
            return
        idx = min(self.left_cursor, len(self.sched_nday_data) - 1)
        day_data = self.sched_nday_data[idx]
        d = day_data["date"]
        events = day_data["events"]

        self.detail_items.append(DetailItem("header", None,
            d.strftime("%A, %B %d"), False))
        self.detail_items.append(DetailItem("info", None,
            f"Free: {day_data['free_hours']:.1f}h  Events: {day_data['count']}", False))
        self.detail_items.append(DetailItem("blank", None, "", False))

        if not events:
            self.detail_items.append(DetailItem("info", None, "No events", False))
            return

        ei = min(self.nday_event_cursor, len(events) - 1)
        ev = events[ei]

        self.detail_items.append(DetailItem("info", None,
            f"Event {ei + 1}/{len(events)}", False))
        self.detail_items.append(DetailItem("blank", None, "", False))

        self.detail_items.append(DetailItem("header", None, ev.get("title", "???"), False))

        ev_type = ev.get("type", "meeting")
        self.detail_items.append(DetailItem("info", None, f"Type: {ev_type}", False))

        start = ev.get("start") or ev.get("depart") or ""
        end = ev.get("end") or ""
        if start:
            ev_tz = ev.get("timezone")
            local_tz = self.config.get("timezone")
            if ev_tz and local_tz and ev_tz != local_tz:
                s_local = convert_event_time(start, ev_tz, local_tz)
                time_str = fmt_time(s_local)
                if end:
                    e_local = convert_event_time(end, ev_tz, local_tz)
                    time_str += f" - {fmt_time(e_local)}"
                time_str += f"  ({fmt_time(parse_time(start))} {ev_tz})"
            else:
                time_str = fmt_time(parse_time(start))
                if end:
                    time_str += f" - {fmt_time(parse_time(end))}"
            self.detail_items.append(DetailItem("info", None, f"Time: {time_str}", False))

        loc = ev.get("location") or ""
        if loc:
            loc_label = f"Location: {loc}"
            if "://" in loc:
                loc_label += "  (o to open)"
            self.detail_items.append(DetailItem("info", None, loc_label, False))

        if ev.get("type") == "travel":
            fr = ev.get("from", "")
            to = ev.get("to", "")
            if fr:
                self.detail_items.append(DetailItem("info", None, f"From: {fr}", False))
            if to:
                self.detail_items.append(DetailItem("info", None, f"To: {to}", False))

        rec_info = self._format_recurring_info(ev)
        if rec_info:
            self.detail_items.append(DetailItem("info", None, rec_info, False))

        if ev.get("timezone"):
            self.detail_items.append(DetailItem("info", None, f"Timezone: {ev['timezone']}", False))

        if ev.get("private"):
            self.detail_items.append(DetailItem("info", None, "Visibility: private", False))

    def _rebuild_detail_sched_week_ev(self):
        if not self.sched_week_data:
            return
        idx = min(self.left_cursor, len(self.sched_week_data) - 1)
        day_data = self.sched_week_data[idx]
        d = day_data["date"]
        events = day_data["events"]

        self.detail_items.append(DetailItem("header", None,
            d.strftime("%A, %B %d"), False))
        self.detail_items.append(DetailItem("info", None,
            f"Free: {day_data['free_hours']:.1f}h  Events: {day_data['count']}", False))
        self.detail_items.append(DetailItem("blank", None, "", False))

        if not events:
            self.detail_items.append(DetailItem("info", None, "No events", False))
            return

        ei = min(self.week_event_cursor, len(events) - 1)
        ev = events[ei]

        self.detail_items.append(DetailItem("info", None,
            f"Event {ei + 1}/{len(events)}", False))
        self.detail_items.append(DetailItem("blank", None, "", False))

        self.detail_items.append(DetailItem("header", None, ev.get("title", "???"), False))

        ev_type = ev.get("type", "meeting")
        self.detail_items.append(DetailItem("info", None, f"Type: {ev_type}", False))

        start = ev.get("start") or ev.get("depart") or ""
        end = ev.get("end") or ""
        if start:
            ev_tz = ev.get("timezone")
            local_tz = self.config.get("timezone")
            if ev_tz and local_tz and ev_tz != local_tz:
                s_local = convert_event_time(start, ev_tz, local_tz)
                time_str = fmt_time(s_local)
                if end:
                    e_local = convert_event_time(end, ev_tz, local_tz)
                    time_str += f" - {fmt_time(e_local)}"
                time_str += f"  ({fmt_time(parse_time(start))} {ev_tz})"
            else:
                time_str = fmt_time(parse_time(start))
                if end:
                    time_str += f" - {fmt_time(parse_time(end))}"
            self.detail_items.append(DetailItem("info", None, f"Time: {time_str}", False))

        loc = ev.get("location") or ""
        if loc:
            loc_label = f"Location: {loc}"
            if "://" in loc:
                loc_label += "  (o to open)"
            self.detail_items.append(DetailItem("info", None, loc_label, False))

        if ev.get("type") == "travel":
            fr = ev.get("from", "")
            to = ev.get("to", "")
            if fr:
                self.detail_items.append(DetailItem("info", None, f"From: {fr}", False))
            if to:
                self.detail_items.append(DetailItem("info", None, f"To: {to}", False))

        rec_info = self._format_recurring_info(ev)
        if rec_info:
            self.detail_items.append(DetailItem("info", None, rec_info, False))

        if ev.get("timezone"):
            self.detail_items.append(DetailItem("info", None, f"Timezone: {ev['timezone']}", False))

        if ev.get("private"):
            self.detail_items.append(DetailItem("info", None, "Visibility: private", False))

    def _rebuild_detail_sched_week(self):
        data = self.sched_month_data
        if not data:
            return
        idx = min(self.left_cursor, len(data) - 1)
        day_data = data[idx]
        if day_data.get("kind") == "week_header":
            return
        d = day_data["date"]

        self.detail_items.append(DetailItem("header", None,
            d.strftime("%A, %B %d"), False))
        self.detail_items.append(DetailItem("info", None,
            f"Free: {day_data['free_hours']:.1f}h  Events: {day_data['count']}", False))
        self.detail_items.append(DetailItem("blank", None, "", False))

        if day_data["events"]:
            self.detail_items.append(DetailItem("header", None, "Events", False))
            for ev in day_data["events"]:
                start = ev.get("start") or ev.get("depart") or ""
                title = ev.get("title", "???")
                s_str = fmt_time(parse_time(start)) if start else "??:??"
                end = ev.get("end") or ""
                e_str = fmt_time(parse_time(end)) if end else ""
                time_range = f"{s_str}-{e_str}" if e_str else s_str
                text = f"  {time_range}  {title}"
                self.detail_items.append(DetailItem("info", None, text, False))

        # Free slots
        free_slots, _ = calc_free_time(day_data["events"], self.config, d)
        if free_slots:
            self.detail_items.append(DetailItem("blank", None, "", False))
            self.detail_items.append(DetailItem("header", None, "Free Time", False))
            for s, e in free_slots:
                mins = (datetime.datetime.combine(d, e) -
                        datetime.datetime.combine(d, s)).seconds // 60
                text = f"  {fmt_time(s)}-{fmt_time(e)}  ({mins / 60:.1f}h)"
                self.detail_items.append(DetailItem("info", None, text, False))

    def _snap_right_cursor(self):
        """Move right_cursor to nearest selectable item, or 0 if none."""
        if not self.detail_items:
            self.right_cursor = 0
            return
        # Try to keep current position if valid
        if 0 <= self.right_cursor < len(self.detail_items) and self.detail_items[self.right_cursor].selectable:
            return
        # Find first selectable
        for i, item in enumerate(self.detail_items):
            if item.selectable:
                self.right_cursor = i
                return
        self.right_cursor = 0

    # ─── Dimensions ───────────────────────────────────────────────────────

    def _calc_dimensions(self):
        self.max_y, self.max_x = self.stdscr.getmaxyx()
        if self._right_panel_hidden:
            self.left_w = self.max_x - 3  # full width minus borders
            self.right_w = 0
            self.content_h = self.max_y - 4
            return
        # Left panel width: 70% for schedule grid views, 40% for mail, 35% otherwise
        if self.view_mode in (VIEW_SCHED_DAY, VIEW_SCHED_WEEK, VIEW_SCHED_NDAY):
            self.left_w = max(40, min(self.max_x * 70 // 100, self.max_x - 25))
        elif self.view_mode == VIEW_MAIL_INBOX:
            base = max(20, self.max_x * 40 // 100)
            self.left_w = max(20, min(self.max_x - 25, base + self._mail_left_w_offset))
        else:
            base = max(20, min(40, self.max_x * 35 // 100))
            self.left_w = max(20, min(self.max_x - 25, base + self._left_w_offset))
        self.right_w = self.max_x - self.left_w - 3  # 3 for borders
        self.content_h = self.max_y - 4  # top border + title + bottom border + status

    # ─── Drawing ──────────────────────────────────────────────────────────

    def draw(self):
        self.stdscr.erase()
        if self.max_y < 8 or self.max_x < 40:
            msg = "Terminal too small"
            try:
                self.stdscr.addstr(self.max_y // 2, max(0, (self.max_x - len(msg)) // 2), msg)
            except curses.error:
                pass
            self.stdscr.refresh()
            return

        # Auto-show right panel when it has focus
        if self._right_panel_hidden and self.focus == RIGHT:
            self._right_panel_hidden = False
            self._calc_dimensions()

        self._draw_left_panel()
        if not self._right_panel_hidden:
            self._draw_right_panel()
        self._draw_borders()
        self._draw_status_bar()
        self.stdscr.refresh()

    def _draw_borders(self):
        h, w = self.max_y, self.max_x
        lw = self.left_w

        if self._right_panel_hidden:
            top = "┌" + "─" * lw + "┐"
            self._safe_addstr(0, 0, top)
        else:
            # Top border — ┐ at col w-2 to align with right │ border
            top = "┌" + "─" * lw + "┬" + "─" * max(0, w - lw - 4) + "┐"
            self._safe_addstr(0, 0, top)

        # Left panel title
        if self.view_mode == VIEW_SCHED_DAY:
            filter_label = self.sched_date.strftime("%a %b %d")
        elif self.view_mode == VIEW_SCHED_NDAY:
            filter_label = f"{self.sched_nday_count}-Day View"
        elif self.view_mode == VIEW_SCHED_WEEK:
            filter_label = "Schedule"
        elif self.view_mode == VIEW_SCHED_MONTH:
            filter_label = self.sched_date.strftime("%B %Y")
        elif self.view_mode == VIEW_MAIL_INBOX:
            if self.mail_threaded:
                n_threads = len(self.mail_threads)
                n_msgs = len(self.mail_emails)
                filter_label = f"Inbox ({n_threads} threads, {n_msgs} msgs)"
            else:
                filter_label = f"Inbox ({len(self.mail_emails)})"
            if self.mail_unread_filter:
                filter_label += " [unread]"
        elif self.view_mode == VIEW_TODAY:
            filter_label = "Today"
        elif self.view_mode == VIEW_WEEK:
            filter_label = "This Week"
        elif self.view_mode == VIEW_MONTH:
            filter_label = "This Month"
        elif self.sort_by_due:
            filter_label = "All Projects (by due)" if self.show_all else "Projects (by due)"
        else:
            filter_label = "All Projects" if self.show_all else "Projects"
        title = f" {filter_label} "
        self._safe_addstr(0, 2, _wc_truncate(title, lw - 1), curses.A_BOLD)

        # Right panel title
        if self.view_mode == VIEW_SCHED_DAY:
            if self.sched_day_items:
                idx = min(self.left_cursor, len(self.sched_day_items) - 1)
                item = self.sched_day_items[idx]
                if item["kind"] == "event" and item["event"]:
                    rtitle = f" {item['event'].get('title', 'Event Details')} "
                else:
                    rtitle = " Event Details "
            else:
                rtitle = " Event Details "
        elif self.view_mode == VIEW_SCHED_NDAY:
            if self.sched_nday_data:
                idx = min(self.left_cursor, len(self.sched_nday_data) - 1)
                d = self.sched_nday_data[idx]["date"]
                rtitle = f" {d.strftime('%a %b %d')} "
            else:
                rtitle = " Details "
        elif self.view_mode == VIEW_SCHED_WEEK:
            if self.sched_week_data:
                idx = min(self.left_cursor, len(self.sched_week_data) - 1)
                d = self.sched_week_data[idx]["date"]
                rtitle = f" {d.strftime('%a %b %d')} "
            else:
                rtitle = " Details "
        elif self.view_mode == VIEW_SCHED_MONTH:
            if self.sched_month_data:
                idx = min(self.left_cursor, len(self.sched_month_data) - 1)
                entry = self.sched_month_data[idx]
                if entry.get("kind") == "week_header":
                    rtitle = f" {entry['text']} "
                else:
                    rtitle = f" {entry['date'].strftime('%a %b %d')} "
            else:
                rtitle = " Details "
        elif self.view_mode == VIEW_MAIL_INBOX:
            if self._conv_emails and self.mail_body_uid == "__conv__":
                # Conversation view title
                pos = self._conv_pos + 1
                total = len(self._conv_emails)
                rtitle = f" Email {pos} of {total} "
            elif self.mail_body_uid and self.mail_threaded and self._mail_display_rows and self.left_cursor < len(self._mail_display_rows):
                row = self._mail_display_rows[self.left_cursor]
                if row["type"] == "email":
                    rtitle = " Email "
                else:
                    n = len(row["thread"]["emails"])
                    rtitle = f" Thread ({n} emails) " if n > 1 else " Thread "
            elif self.mail_body_uid and not self.mail_threaded and self.mail_emails and self.left_cursor < len(self.mail_emails):
                rtitle = " Email "
            else:
                rtitle = " Body "
        elif self.view_mode in (VIEW_TODAY, VIEW_WEEK, VIEW_MONTH):
            if self.timeline_items:
                idx = min(self.left_cursor, len(self.timeline_items) - 1)
                proj = self.timeline_items[idx]["project"]
                rtitle = f" {proj['name']} "
            else:
                rtitle = " Details "
        elif self.filtered:
            proj = self.filtered[self.left_cursor]
            rtitle = f" {proj['name']} "
        else:
            rtitle = " Details "
        if not self._right_panel_hidden:
            self._safe_addstr(0, lw + 3, _wc_truncate(rtitle, self.right_w - 2), curses.A_BOLD)

        # Vertical borders for content rows
        for y in range(1, min(h - 2, 1 + self.content_h)):
            self._safe_addstr(y, 0, "│")
            if self._right_panel_hidden:
                self._safe_addstr(y, lw + 1, "│")
            else:
                self._safe_addstr(y, lw + 1, "│")
                self._safe_addstr(y, w - 2, "│")

        # Bottom border of content
        bot_y = min(h - 2, 1 + self.content_h)
        if self._right_panel_hidden:
            bot = "├" + "─" * lw + "┤"
        else:
            bot = "├" + "─" * lw + "┴" + "─" * max(0, w - lw - 4) + "┤"
        self._safe_addstr(bot_y, 0, bot)

        # Status bar border
        if bot_y + 2 < h:
            final = "└" + "─" * (w - 3) + "┘"
            self._safe_addstr(bot_y + 2, 0, final)

    def _draw_left_panel(self):
        if self.view_mode == VIEW_MAIL_INBOX:
            self._draw_left_panel_mail()
            return
        if self.view_mode == VIEW_SCHED_DAY:
            self._draw_left_panel_sched_day()
            return
        if self.view_mode == VIEW_SCHED_NDAY:
            self._draw_left_panel_sched_nday()
            return
        if self.view_mode == VIEW_SCHED_WEEK:
            self._draw_left_panel_sched_week()
            return
        if self.view_mode == VIEW_SCHED_MONTH:
            self._draw_left_panel_sched_month()
            return
        if self.view_mode in (VIEW_TODAY, VIEW_WEEK, VIEW_MONTH):
            self._draw_left_panel_timeline()
            return

        if not self.filtered:
            self._safe_addstr(2, 2, "No projects.", curses.A_DIM)
            self._safe_addstr(3, 2, "Press 'a' to add one.", curses.A_DIM)
            return

        # Adjust scroll
        if self.left_cursor < self.left_scroll:
            self.left_scroll = self.left_cursor
        if self.left_cursor >= self.left_scroll + self.content_h:
            self.left_scroll = self.left_cursor - self.content_h + 1

        for i in range(self.content_h):
            idx = self.left_scroll + i
            if idx >= len(self.filtered):
                break
            proj = self.filtered[idx]
            y = 1 + i

            # Status icon
            st = proj.get("status", "active")
            if st == "active":
                icon = "●"
            elif st == "paused":
                icon = "◌"
            else:
                icon = "✓"

            name = proj.get("name", "???")
            text = f" {icon} {name}"
            text = text[:self.left_w]

            attr = curses.A_NORMAL
            if idx == self.left_cursor:
                if self.focus == LEFT:
                    attr = curses.A_REVERSE | curses.A_BOLD
                else:
                    attr = curses.A_BOLD
            self._safe_addstr(y, 1, text.ljust(self.left_w), attr)

    def _draw_left_panel_timeline(self):
        if not self.timeline_items:
            labels = {VIEW_TODAY: "today", VIEW_WEEK: "this week", VIEW_MONTH: "this month"}
            msg = f"Nothing due {labels.get(self.view_mode, '')}."
            self._safe_addstr(2, 2, msg, curses.A_DIM)
            return

        # Adjust scroll
        if self.left_cursor < self.left_scroll:
            self.left_scroll = self.left_cursor
        if self.left_cursor >= self.left_scroll + self.content_h:
            self.left_scroll = self.left_cursor - self.content_h + 1

        td = today()
        for i in range(self.content_h):
            idx = self.left_scroll + i
            if idx >= len(self.timeline_items):
                break
            entry = self.timeline_items[idx]
            y = 1 + i

            due_date = entry["due_date"]
            proj_name = entry["project"].get("name", "???")
            date_str = due_date.strftime("%b %d")
            kind = entry.get("kind", "milestone")
            if kind == "milestone":
                item_name = entry["milestone"].get("name", "???")
                text = f" {date_str}  {item_name} [{proj_name}]"
            elif kind == "ms_task":
                item_name = _task_text(entry["task"])
                ms_name = entry["milestone"].get("name", "")
                text = f" {date_str}  {item_name} [{proj_name}/{ms_name}]"
            else:  # standalone task
                item_name = _task_text(entry["task"])
                text = f" {date_str}  · {item_name} [{proj_name}]"
            text = text[:self.left_w]

            # Color by urgency
            delta = (due_date - td).days
            if delta < 0:
                color = curses.color_pair(C_RED)
            elif delta <= 7:
                color = curses.color_pair(C_YELLOW)
            else:
                color = 0

            attr = curses.A_NORMAL
            if idx == self.left_cursor:
                if self.focus == LEFT:
                    attr = curses.A_REVERSE | curses.A_BOLD
                else:
                    attr = curses.A_BOLD
            self._safe_addstr(y, 1, text.ljust(self.left_w), attr | color)

    def _get_day_grid_range(self, day_date):
        """Return (start_hour, end_hour) for the time grid on a given day."""
        day_idx = day_date.weekday()
        slots = get_work_hours(self.config, day_idx)
        # Default from work hours
        start_h = min(s for s, e in slots) if slots else 8
        end_h = max(e for s, e in slots) if slots else 18

        # Expand range for events outside work hours
        events = expand_events_for_date(self.schedule, day_date)
        local_tz = self.config.get("timezone")
        for ev in events:
            s_str = ev.get("start") or ev.get("depart")
            e_str = ev.get("end")
            ev_tz = ev.get("timezone")
            if s_str:
                if ev_tz and local_tz and ev_tz != local_tz:
                    t = convert_event_time(s_str, ev_tz, local_tz)
                else:
                    t = parse_time(s_str)
                start_h = min(start_h, t.hour)
            if e_str:
                if ev_tz and local_tz and ev_tz != local_tz:
                    t = convert_event_time(e_str, ev_tz, local_tz)
                else:
                    t = parse_time(e_str)
                end_h = max(end_h, t.hour + (1 if t.minute > 0 else 0))

        return (start_h, end_h)

    def _build_day_grid(self, start_h, end_h):
        """Build a grid of 15-min slots with overlap support.
        Returns list of lists: grid[slot] = [(item, col, total_cols, is_first, is_last), ...]"""
        n_slots = (end_h - start_h) * 4

        # Compute slot ranges for each event
        ev_spans = []
        for item in self.sched_day_items:
            if item["kind"] != "event":
                continue
            ev = item["event"]
            s_str = ev.get("start") or ev.get("depart")
            e_str = ev.get("end")
            if not s_str:
                continue
            ev_tz = ev.get("timezone")
            local_tz = self.config.get("timezone")
            if ev_tz and local_tz and ev_tz != local_tz:
                s_t = convert_event_time(s_str, ev_tz, local_tz)
            else:
                s_t = parse_time(s_str)
            if e_str:
                if ev_tz and local_tz and ev_tz != local_tz:
                    e_t = convert_event_time(e_str, ev_tz, local_tz)
                else:
                    e_t = parse_time(e_str)
            else:
                dt = datetime.datetime.combine(datetime.date.today(), s_t) + datetime.timedelta(hours=1)
                e_t = dt.time()
            s_mins = (s_t.hour - start_h) * 60 + s_t.minute
            e_mins = (e_t.hour - start_h) * 60 + e_t.minute
            s_slot = max(0, s_mins // 15)
            e_slot = min(n_slots, max(s_slot + 1, (e_mins + 14) // 15))
            ev_spans.append((s_slot, e_slot, item))

        ev_spans.sort(key=lambda x: (x[0], -(x[1] - x[0])))

        if not ev_spans:
            return [[] for _ in range(n_slots)]

        # Greedy column assignment
        col_ends = []
        ev_col = {}
        for s, e, item in ev_spans:
            placed = False
            for c in range(len(col_ends)):
                if col_ends[c] <= s:
                    col_ends[c] = e
                    ev_col[id(item)] = c
                    placed = True
                    break
            if not placed:
                ev_col[id(item)] = len(col_ends)
                col_ends.append(e)

        # Per-slot event lists for overlap detection
        slot_items = [[] for _ in range(n_slots)]
        for s, e, item in ev_spans:
            for si in range(s, e):
                if 0 <= si < n_slots:
                    slot_items[si].append(item)

        # Union-Find to group overlapping events
        par = {id(it): id(it) for _, _, it in ev_spans}
        def find(x):
            while par[x] != x:
                par[x] = par[par[x]]
                x = par[x]
            return x
        def union(a, b):
            a, b = find(a), find(b)
            if a != b:
                par[a] = b

        for si in range(n_slots):
            if len(slot_items[si]) > 1:
                fid = id(slot_items[si][0])
                for it in slot_items[si][1:]:
                    union(fid, id(it))

        # total_cols per group = max column + 1
        group_max = {}
        for s, e, item in ev_spans:
            g = find(id(item))
            group_max[g] = max(group_max.get(g, 0), ev_col[id(item)] + 1)

        # Build grid
        grid = [[] for _ in range(n_slots)]
        for s, e, item in ev_spans:
            col = ev_col[id(item)]
            total = group_max[find(id(item))]
            first = True
            for si in range(s, e):
                if 0 <= si < n_slots:
                    is_last = (si == e - 1)
                    grid[si].append((item, col, total, first, is_last))
                    first = False

        for si in range(n_slots):
            grid[si].sort(key=lambda x: x[1])

        return grid

    def _draw_left_panel_sched_day(self):
        if not self.sched_day_items:
            self._safe_addstr(2, 2, "No events.", curses.A_DIM)
            return

        start_h, end_h = self._get_day_grid_range(self.sched_date)
        grid = self._build_day_grid(start_h, end_h)
        n_slots = len(grid)

        # Find selected event
        sel_item = None
        if self.sched_day_items:
            sel_idx = min(self.left_cursor, len(self.sched_day_items) - 1)
            sel_item = self.sched_day_items[sel_idx]

        # Find slot range of selected event for scrolling
        sel_first_slot = 0
        sel_last_slot = 0
        if sel_item and sel_item["kind"] == "event":
            found = False
            for si in range(n_slots):
                for entry in grid[si]:
                    if entry[0] is sel_item:
                        if not found:
                            sel_first_slot = si
                            found = True
                        sel_last_slot = si
                        break

        # Scroll grid
        grid_scroll = getattr(self, '_day_grid_scroll', 0)
        if sel_first_slot < grid_scroll:
            grid_scroll = sel_first_slot
        if sel_last_slot >= grid_scroll + self.content_h:
            grid_scroll = sel_last_slot - self.content_h + 1
        grid_scroll = max(0, min(grid_scroll, max(0, n_slots - self.content_h)))
        self._day_grid_scroll = grid_scroll

        lw = self.left_w
        label_w = 5
        bar_w = lw - label_w - 1

        # Precompute work-hour slots
        work_slots = get_work_hours(self.config, self.sched_date.weekday())

        for i in range(self.content_h):
            si = grid_scroll + i
            if si >= n_slots:
                break
            y = 1 + i

            # Time label
            quarter = si % 4
            hour = start_h + si // 4
            slot_min = (si % 4) * 15
            if quarter == 0:
                label = f"{hour:02d}  "
            elif quarter == 2:
                label = " 30 "
            else:
                label = "    "

            is_hour_boundary = (quarter == 0)
            slot_time = hour * 60 + slot_min
            is_work = any(s * 60 <= slot_time < e * 60 for s, e in work_slots)
            if is_work:
                label_attr = curses.A_DIM
            else:
                label_attr = curses.color_pair(C_NONWORK)
            self._safe_addstr(y, 1, label, label_attr)

            entries = grid[si]

            if not entries:
                # Free slot
                if is_work:
                    line = " " * bar_w
                    if is_hour_boundary and si > 0:
                        line = "┄" * bar_w
                    self._safe_addstr(y, 1 + label_w, line, curses.A_DIM)
                else:
                    line = " " * bar_w
                    self._safe_addstr(y, 1 + label_w, line,
                                      curses.color_pair(C_NONWORK))
            else:
                total_cols = max(e[2] for e in entries)
                col_map = {}
                for item, col, tc, is_first, is_last in entries:
                    col_map[col] = (item, is_first, is_last)

                gap = 1 if total_cols > 1 else 0

                for c in range(total_cols):
                    cx0 = 1 + label_w + (bar_w * c) // total_cols
                    cx1 = 1 + label_w + (bar_w * (c + 1)) // total_cols
                    cell_w = cx1 - cx0 - gap
                    if cell_w < 1:
                        cell_w = 1

                    if c in col_map:
                        item, is_first, is_last = col_map[c]
                        ev = item["event"]
                        ev_type = ev.get("type", "")
                        title = ev.get("title", "")

                        is_private = ev.get("private", False)
                        if ev_type == "blocked":
                            fill_ch = "░"
                            color = curses.color_pair(C_BLUE)
                        elif ev_type == "travel":
                            fill_ch = "▓"
                            color = curses.color_pair(C_CYAN)
                        elif is_private:
                            fill_ch = "█"
                            color = curses.color_pair(C_MAGENTA)
                        else:
                            fill_ch = "█"
                            color = curses.color_pair(C_GREEN)

                        attr = curses.A_NORMAL
                        if item is sel_item:
                            if self.focus == LEFT:
                                attr = curses.A_REVERSE | curses.A_BOLD
                            else:
                                attr = curses.A_BOLD

                        if total_cols > 1 and cell_w >= 4:
                            # Boxed layout for overlapping events
                            inner = cell_w - 2
                            if is_first:
                                title_text = f" {title} "
                                if len(title_text) > inner:
                                    title_text = title_text[:inner - 1] + "…"
                                bar = "┌" + title_text.ljust(inner, "─") + "┐"
                            elif is_last:
                                bar = "└" + "─" * inner + "┘"
                            else:
                                bar = "│" + fill_ch * inner + "│"
                            self._safe_addstr(y, cx0, bar[:cell_w], attr | color)
                        else:
                            # Full-width layout (no overlap)
                            if is_first:
                                title_text = f" {title} "
                                if len(title_text) > cell_w:
                                    title_text = title_text[:cell_w - 1] + "…"
                                bar = title_text.ljust(cell_w, fill_ch)
                            elif is_last:
                                # Bottom border
                                bar = "─" * cell_w
                            else:
                                bar = fill_ch * cell_w
                            self._safe_addstr(y, cx0, bar[:cell_w], attr | color)
                    else:
                        # Empty column at this slot
                        if is_hour_boundary and si > 0:
                            fill = "┄" * cell_w
                        else:
                            fill = "·" * cell_w
                        self._safe_addstr(y, cx0, fill, curses.A_DIM)

        # Current time marker
        if self.sched_date == today():
            now = datetime.datetime.now()
            now_mins = now.hour * 60 + now.minute
            now_slot = (now_mins - start_h * 60) // 15
            if 0 <= now_slot < n_slots:
                now_row = now_slot - grid_scroll
                if 0 <= now_row < self.content_h:
                    y = 1 + now_row
                    time_label = now.strftime("%H:%M")
                    self._safe_addstr(y, 0, time_label,
                                      curses.color_pair(C_RED) | curses.A_BOLD)

    def _get_week_grid_range(self):
        """Return (start_hour, end_hour) across all 7 days of the week."""
        start_h, end_h = 23, 0
        local_tz = self.config.get("timezone")
        for entry in self.sched_week_data:
            d = entry["date"]
            day_idx = d.weekday()
            slots = get_work_hours(self.config, day_idx)
            if slots:
                start_h = min(start_h, min(s for s, e in slots))
                end_h = max(end_h, max(e for s, e in slots))
            for ev in entry["events"]:
                s_str = ev.get("start") or ev.get("depart")
                e_str = ev.get("end")
                ev_tz = ev.get("timezone")
                if s_str:
                    if ev_tz and local_tz and ev_tz != local_tz:
                        t = convert_event_time(s_str, ev_tz, local_tz)
                    else:
                        t = parse_time(s_str)
                    start_h = min(start_h, t.hour)
                if e_str:
                    if ev_tz and local_tz and ev_tz != local_tz:
                        t = convert_event_time(e_str, ev_tz, local_tz)
                    else:
                        t = parse_time(e_str)
                    end_h = max(end_h, t.hour + (1 if t.minute > 0 else 0))
        if start_h > end_h:
            start_h, end_h = 8, 18
        return (start_h, end_h)

    def _draw_multiday_grid(self, data, scroll_attr, selected_ev=None):
        """Shared renderer for week and N-day views. data = list of day entries.
        scroll_attr = attribute name for persisting grid scroll position.
        selected_ev = specific event to highlight (for nday event cursor)."""
        if not data:
            self._safe_addstr(2, 2, "No data.", curses.A_DIM)
            return

        n_days = len(data)
        td = today()
        lw = self.left_w
        label_w = 5
        col_w = max(3, (lw - label_w) // n_days)

        # Compute hour range across all days
        start_h, end_h = 23, 0
        local_tz = self.config.get("timezone")
        for entry in data:
            d = entry["date"]
            slots = get_work_hours(self.config, d.weekday())
            if slots:
                start_h = min(start_h, min(s for s, e in slots))
                end_h = max(end_h, max(e for s, e in slots))
            for ev in entry["events"]:
                s_str = ev.get("start") or ev.get("depart")
                e_str = ev.get("end")
                ev_tz = ev.get("timezone")
                if s_str:
                    if ev_tz and local_tz and ev_tz != local_tz:
                        t = convert_event_time(s_str, ev_tz, local_tz)
                    else:
                        t = parse_time(s_str)
                    start_h = min(start_h, t.hour)
                if e_str:
                    if ev_tz and local_tz and ev_tz != local_tz:
                        t = convert_event_time(e_str, ev_tz, local_tz)
                    else:
                        t = parse_time(e_str)
                    end_h = max(end_h, t.hour + (1 if t.minute > 0 else 0))
        if start_h > end_h:
            start_h, end_h = 8, 18

        # Wide terminal: 15-min slots with titles. Narrow: 1-hour compact.
        show_titles = col_w >= 10
        if show_titles:
            slots_per_hour = 4
        else:
            slots_per_hour = 1
        n_slots = (end_h - start_h) * slots_per_hour

        # Build per-day event slot maps with overlap support
        day_grids = []
        for entry in data:
            # Compute slot ranges for each event
            ev_spans = []
            for ev in entry["events"]:
                s_str = ev.get("start") or ev.get("depart")
                e_str = ev.get("end")
                if not s_str:
                    continue
                ev_tz = ev.get("timezone")
                local_tz = self.config.get("timezone")
                if ev_tz and local_tz and ev_tz != local_tz:
                    s_t = convert_event_time(s_str, ev_tz, local_tz)
                else:
                    s_t = parse_time(s_str)
                if e_str:
                    if ev_tz and local_tz and ev_tz != local_tz:
                        e_t = convert_event_time(e_str, ev_tz, local_tz)
                    else:
                        e_t = parse_time(e_str)
                else:
                    dt = datetime.datetime.combine(entry["date"], s_t) + datetime.timedelta(hours=1)
                    e_t = dt.time()
                s_mins = (s_t.hour - start_h) * 60 + s_t.minute
                e_mins = (e_t.hour - start_h) * 60 + e_t.minute
                if slots_per_hour == 4:
                    s_slot = max(0, s_mins // 15)
                    e_slot = min(n_slots, max(s_slot + 1, (e_mins + 14) // 15))
                else:
                    s_slot = max(0, s_mins // 60)
                    e_slot = min(n_slots, max(s_slot + 1, (e_mins + 59) // 60))
                ev_spans.append((s_slot, e_slot, ev))

            ev_spans.sort(key=lambda x: (x[0], -(x[1] - x[0])))

            # Greedy column assignment
            col_ends = []
            ev_col = {}
            for s, e, ev in ev_spans:
                placed = False
                for c in range(len(col_ends)):
                    if col_ends[c] <= s:
                        col_ends[c] = e
                        ev_col[id(ev)] = c
                        placed = True
                        break
                if not placed:
                    ev_col[id(ev)] = len(col_ends)
                    col_ends.append(e)

            # Union-Find to group overlapping events
            slot_evs = [[] for _ in range(n_slots)]
            for s, e, ev in ev_spans:
                for si in range(s, e):
                    if 0 <= si < n_slots:
                        slot_evs[si].append(ev)

            par = {id(ev): id(ev) for _, _, ev in ev_spans}
            def find(x):
                while par[x] != x:
                    par[x] = par[par[x]]
                    x = par[x]
                return x
            def union(a, b):
                a, b = find(a), find(b)
                if a != b:
                    par[a] = b

            for si in range(n_slots):
                if len(slot_evs[si]) > 1:
                    fid = id(slot_evs[si][0])
                    for ev in slot_evs[si][1:]:
                        union(fid, id(ev))

            group_max = {}
            for s, e, ev in ev_spans:
                g = find(id(ev))
                group_max[g] = max(group_max.get(g, 0), ev_col[id(ev)] + 1)

            # Build grid: grid[slot] = [(ev, col, total_cols, is_first, is_last), ...]
            grid = [[] for _ in range(n_slots)]
            for s, e, ev in ev_spans:
                col = ev_col[id(ev)]
                total = group_max[find(id(ev))]
                first = True
                for si in range(s, e):
                    if 0 <= si < n_slots:
                        is_last = (si == e - 1)
                        grid[si].append((ev, col, total, first, is_last))
                        first = False
            for si in range(n_slots):
                grid[si].sort(key=lambda x: x[1])

            day_grids.append(grid)

        # Row 0: day headers
        self._safe_addstr(1, 1, " " * label_w, curses.A_DIM)
        for di, entry in enumerate(data):
            d = entry["date"]
            if col_w >= 10:
                day_label = d.strftime("%a %b %d")
            elif col_w >= 6:
                day_label = d.strftime("%a %d")
            else:
                day_label = d.strftime("%a")[:col_w]
            cell = day_label[:col_w].center(col_w)

            attr = curses.A_BOLD
            if di == self.left_cursor and self.focus == LEFT:
                attr = curses.A_REVERSE | curses.A_BOLD
            elif di == self.left_cursor:
                attr = curses.A_BOLD | curses.A_UNDERLINE
            elif d == td:
                attr = curses.A_BOLD | curses.color_pair(C_CYAN)

            x = 1 + label_w + di * col_w
            self._safe_addstr(1, x, cell, attr)

        # Scroll grid to keep selected event visible
        grid_scroll = getattr(self, scroll_attr, 0)
        avail_rows = self.content_h - 1
        if selected_ev is not None:
            di = min(self.left_cursor, n_days - 1)
            if 0 <= di < len(day_grids):
                sel_first = sel_last = None
                for si in range(n_slots):
                    for entry in day_grids[di][si]:
                        if entry[0] is selected_ev:
                            if sel_first is None:
                                sel_first = si
                            sel_last = si
                            break
                if sel_first is not None:
                    if sel_first < grid_scroll:
                        grid_scroll = sel_first
                    if sel_last >= grid_scroll + avail_rows:
                        grid_scroll = sel_last - avail_rows + 1
        if n_slots > avail_rows:
            grid_scroll = max(0, min(grid_scroll, n_slots - avail_rows))
        else:
            grid_scroll = 0
        setattr(self, scroll_attr, grid_scroll)

        # Precompute work-hour slots per day
        day_work_slots = []
        for entry in data:
            day_work_slots.append(get_work_hours(self.config, entry["date"].weekday()))

        # Slot rows
        for ri in range(avail_rows):
            si = grid_scroll + ri
            if si >= n_slots:
                break
            y = 2 + ri

            # Time label
            if slots_per_hour == 4:
                quarter = si % 4
                hour = start_h + si // 4
                slot_min = quarter * 15
                if quarter == 0:
                    label = f" {hour:02d}  "
                elif quarter == 2:
                    label = "  30 "
                else:
                    label = "     "
                is_hour_boundary = (quarter == 0)
            else:
                hour = start_h + si
                slot_min = 0
                label = f" {hour:02d}  "
                is_hour_boundary = True
            slot_time = hour * 60 + slot_min
            # Label uses non-work color if no day has this as work time
            any_work = any(any(s * 60 <= slot_time < e * 60 for s, e in ws) for ws in day_work_slots)
            if any_work:
                label_attr = curses.A_DIM
            else:
                label_attr = curses.color_pair(C_NONWORK)
            self._safe_addstr(y, 1, label[:label_w], label_attr)

            for di in range(n_days):
                x = 1 + label_w + di * col_w
                slot_entries = day_grids[di][si] if si < len(day_grids[di]) else []

                if not slot_entries:
                    is_work = any(s * 60 <= slot_time < e * 60 for s, e in day_work_slots[di])
                    if is_work:
                        fill = " " * col_w
                        if is_hour_boundary and si > 0:
                            fill = "┄" * col_w
                        self._safe_addstr(y, x, fill[:col_w], curses.A_DIM)
                    else:
                        fill = " " * col_w
                        self._safe_addstr(y, x, fill[:col_w],
                                          curses.color_pair(C_NONWORK))
                else:
                    for ev, col, total_cols, is_first, is_last in slot_entries:
                        sub_w = max(1, col_w // total_cols)
                        if col == total_cols - 1:
                            sub_w = col_w - col * (col_w // total_cols)
                        sub_x = x + col * (col_w // total_cols)

                        ev_type = ev.get("type", "")
                        ev_private = ev.get("private", False)
                        title = ev.get("title", "")

                        if ev_type == "blocked":
                            fill_ch = "░"
                            color = curses.color_pair(C_BLUE)
                        elif ev_type == "travel":
                            fill_ch = "▓"
                            color = curses.color_pair(C_CYAN)
                        elif ev_private:
                            fill_ch = "█"
                            color = curses.color_pair(C_MAGENTA)
                        else:
                            fill_ch = "█"
                            color = curses.color_pair(C_GREEN)

                        attr = curses.A_NORMAL
                        if selected_ev is not None:
                            if di == self.left_cursor and ev is selected_ev:
                                attr = curses.A_REVERSE
                            elif di == self.left_cursor:
                                attr = curses.A_BOLD
                        else:
                            if di == self.left_cursor and self.focus == LEFT:
                                attr = curses.A_BOLD

                        if show_titles and sub_w >= 6:
                            inner = max(1, sub_w - 2)
                            if is_first:
                                t = f" {title} "
                                if len(t) > inner:
                                    t = t[:inner - 1] + "…"
                                bar = "┌" + t.ljust(inner, "─") + "┐"
                            elif is_last:
                                bar = "└" + "─" * inner + "┘"
                            else:
                                bar = "│" + fill_ch * inner + "│"
                            self._safe_addstr(y, sub_x, bar[:sub_w], attr | color)
                        else:
                            fill = fill_ch * sub_w
                            self._safe_addstr(y, sub_x, fill[:sub_w], attr | color)

        # Current time marker
        td = today()
        now = datetime.datetime.now()
        now_mins = now.hour * 60 + now.minute
        if slots_per_hour == 4:
            now_slot = (now_mins - start_h * 60) // 15
        else:
            now_slot = (now_mins - start_h * 60) // 60
        if 0 <= now_slot < n_slots:
            now_row = now_slot - grid_scroll
            if 0 <= now_row < avail_rows:
                y = 2 + now_row
                time_label = now.strftime("%H:%M")
                self._safe_addstr(y, 1, time_label[:label_w],
                                  curses.color_pair(C_RED) | curses.A_BOLD)
                for di, entry in enumerate(data):
                    if entry["date"] == td:
                        x = 1 + label_w + di * col_w
                        marker = "─" * col_w
                        self._safe_addstr(y, x, marker,
                                          curses.color_pair(C_RED))

    def _draw_left_panel_sched_week(self):
        selected_ev = None
        if self.sched_week_data:
            idx = min(self.left_cursor, len(self.sched_week_data) - 1)
            events = self.sched_week_data[idx]["events"]
            if events:
                ei = min(self.week_event_cursor, len(events) - 1)
                selected_ev = events[ei]
        self._draw_multiday_grid(self.sched_week_data, '_week_grid_scroll', selected_ev)

    def _draw_left_panel_sched_nday(self):
        selected_ev = None
        if self.sched_nday_data:
            idx = min(self.left_cursor, len(self.sched_nday_data) - 1)
            events = self.sched_nday_data[idx]["events"]
            if events:
                ei = min(self.nday_event_cursor, len(events) - 1)
                selected_ev = events[ei]
        self._draw_multiday_grid(self.sched_nday_data, '_nday_grid_scroll', selected_ev)

    def _draw_left_panel_sched_month(self):
        if not self.sched_month_data:
            self._safe_addstr(2, 2, "No data.", curses.A_DIM)
            return

        if self.left_cursor < self.left_scroll:
            self.left_scroll = self.left_cursor
        if self.left_cursor >= self.left_scroll + self.content_h:
            self.left_scroll = self.left_cursor - self.content_h + 1

        td = today()
        work_day_hrs = 9.0

        for i in range(self.content_h):
            idx = self.left_scroll + i
            if idx >= len(self.sched_month_data):
                break
            entry = self.sched_month_data[idx]
            y = 1 + i

            if entry["kind"] == "week_header":
                text = f" ─ {entry['text']} "
                text = text[:self.left_w]
                self._safe_addstr(y, 1, text.ljust(self.left_w),
                                  curses.A_DIM | curses.color_pair(C_CYAN))
                continue

            d = entry["date"]
            date_str = d.strftime("%a %d")
            free_h = entry["free_hours"]
            count = entry["count"]

            bar_len = 7
            free_blocks = round(free_h / work_day_hrs * bar_len)
            free_blocks = max(0, min(bar_len, free_blocks))
            bar = "█" * free_blocks + "░" * (bar_len - free_blocks)

            today_mark = " ◄" if d == td else ""
            text = f"  {date_str}  {bar} {free_h:4.1f}h ({count}){today_mark}"
            text = text[:self.left_w]

            attr = curses.A_NORMAL
            if idx == self.left_cursor:
                if self.focus == LEFT:
                    attr = curses.A_REVERSE | curses.A_BOLD
                else:
                    attr = curses.A_BOLD

            self._safe_addstr(y, 1, text.ljust(self.left_w), attr)

    def _draw_right_panel(self):
        x_offset = self.left_w + 2
        max_w = max(0, self.right_w - 1)  # leave 1 col for right │ border

        if self.view_mode == VIEW_MAIL_INBOX:
            if not self.mail_body_lines:
                self._safe_addstr(1, x_offset, "Press Enter to read an email.", curses.A_DIM)
                return
            # Conversation view (multi-email thread)
            if self._conv_line_map and len(self._conv_line_map) == len(self.mail_body_lines):
                rfocused = (self.focus == RIGHT)
                bg = curses.color_pair(C_RPANEL_BG) if rfocused else 0
                for i in range(self.content_h):
                    li = self.mail_body_scroll + i
                    if li >= len(self.mail_body_lines):
                        # Fill remaining lines with background
                        if rfocused:
                            self._safe_addstr(1 + i, x_offset, " " * max_w, bg, max_n=max_w)
                        continue
                    line = self.mail_body_lines[li]
                    # Pad to exact display width so curses overwrites full area
                    line = _wc_ljust(_wc_truncate(line, max_w), max_w)
                    eidx, ltype = self._conv_line_map[li]
                    is_focused = (eidx == self._conv_pos)
                    attr = 0
                    color = bg
                    if ltype in ("box_top", "box_bot", "collapsed_top", "collapsed_bot"):
                        color = curses.color_pair(C_RPANEL_CYAN if rfocused else C_CYAN)
                        if is_focused:
                            attr = curses.A_BOLD
                        else:
                            attr = curses.A_DIM
                    elif ltype == "header":
                        if line.lstrip("│ ").startswith("Subject:"):
                            attr = curses.A_BOLD
                        elif line.lstrip("│ ").startswith("From:"):
                            color = curses.color_pair(C_RPANEL_FROM if rfocused else C_MAIL_FROM)
                        elif line.lstrip("│ ").startswith("Date:"):
                            color = curses.color_pair(C_RPANEL_DATE if rfocused else C_MAIL_DATE)
                        else:
                            attr = curses.A_DIM
                    elif ltype == "separator":
                        attr = curses.A_DIM
                    elif ltype == "body":
                        attr = 0
                    elif ltype == "quote":
                        attr = curses.A_DIM
                    elif ltype == "quote_hidden":
                        attr = curses.A_DIM
                    # spacer: default (bg only)
                    self._safe_addstr(1 + i, x_offset, line, attr | color, max_n=max_w)
                return
            # Single-email fallback (flat mode or single-email thread)
            for i in range(self.content_h):
                li = self.mail_body_scroll + i
                if li >= len(self.mail_body_lines):
                    break
                line = self.mail_body_lines[li]
                # Pad to exact display width
                line = _wc_ljust(_wc_truncate(line, max_w), max_w)
                attr = 0
                if line.startswith("Subject:"):
                    attr = curses.A_BOLD
                elif line.startswith(("From:", "To:", "Cc:", "Date:")):
                    attr = curses.A_DIM
                elif line.startswith("─"):
                    attr = curses.A_DIM
                self._safe_addstr(1 + i, x_offset, line, attr, max_n=max_w)
            return

        if self.view_mode == VIEW_PROJECTS and not self.filtered:
            return
        if not self.detail_items:
            self._safe_addstr(2, x_offset + 1, "No details.", curses.A_DIM)
            return

        # Adjust scroll
        if self.right_cursor < self.right_scroll:
            self.right_scroll = self.right_cursor
        if self.right_cursor >= self.right_scroll + self.content_h:
            self.right_scroll = self.right_cursor - self.content_h + 1

        if self.view_mode in (VIEW_SCHED_DAY, VIEW_SCHED_NDAY, VIEW_SCHED_WEEK, VIEW_SCHED_MONTH):
            milestones = []
        elif self.view_mode in (VIEW_TODAY, VIEW_WEEK, VIEW_MONTH):
            if not self.timeline_items:
                return
            idx = min(self.left_cursor, len(self.timeline_items) - 1)
            proj = self.timeline_items[idx]["project"]
            milestones = proj.get("milestones", [])
        else:
            proj = self.filtered[self.left_cursor]
            milestones = proj.get("milestones", [])

        for i in range(self.content_h):
            idx = self.right_scroll + i
            if idx >= len(self.detail_items):
                break
            item = self.detail_items[idx]
            y = 1 + i

            text = item.text[:max_w]
            attr = curses.A_NORMAL
            color = 0

            if item.kind == "header":
                attr = curses.A_BOLD
                color = curses.color_pair(C_CYAN)
            elif item.kind == "field" and item.index == "description":
                attr = curses.A_BOLD
                color = curses.color_pair(C_CYAN)
            elif item.kind == "milestone":
                ms = milestones[item.index] if item.index is not None and item.index < len(milestones) else {}
                done = ms.get("done", False)
                if done:
                    color = curses.color_pair(C_GREEN)
                else:
                    due = ms.get("due")
                    if due:
                        try:
                            due_d = parse_date(due)
                            delta = (due_d - today()).days
                            if delta < 0:
                                color = curses.color_pair(C_RED)
                            elif delta <= 7:
                                color = curses.color_pair(C_YELLOW)
                        except ValueError:
                            pass

            elif item.kind in ("task", "ms_task"):
                t_obj = None
                if item.kind == "task":
                    tasks_list = proj.get("tasks", [])
                    if item.index is not None and item.index < len(tasks_list):
                        t_obj = tasks_list[item.index]
                elif item.kind == "ms_task" and item.index is not None:
                    mi, ti = item.index
                    if mi < len(milestones):
                        ms_tasks = milestones[mi].get("tasks", [])
                        if ti < len(ms_tasks):
                            t_obj = ms_tasks[ti]
                if t_obj is not None:
                    if _task_done(t_obj):
                        color = curses.color_pair(C_GREEN)
                    else:
                        t_due = _task_due(t_obj)
                        if t_due:
                            try:
                                due_d = parse_date(t_due)
                                delta = (due_d - today()).days
                                if delta < 0:
                                    color = curses.color_pair(C_RED)
                                elif delta <= 7:
                                    color = curses.color_pair(C_YELLOW)
                            except ValueError:
                                pass

            # Highlight selectable row if cursor is on it
            if idx == self.right_cursor and item.selectable and self.focus == RIGHT:
                attr = curses.A_REVERSE | curses.A_BOLD

            self._safe_addstr(y, x_offset + 1, text.ljust(max_w - 1), attr | color)

    def _draw_status_bar(self):
        bar_y = min(self.max_y - 2, 2 + self.content_h)
        w = self.max_x - 3

        _undo_hint = "  u undo" if self._undo_stack else ""
        if self.view_mode == VIEW_MAIL_INBOX:
            if self.focus == LEFT:
                items = self._mail_display_rows if self.mail_threaded else self.mail_emails
                pos = f" {self.left_cursor + 1}/{len(items)}" if items else ""
                thread_label = "t:flat" if self.mail_threaded else "t:thread"
                hints = pos + f" j/k:nav  Enter:expand/read  /:search  n/N:next/prev  x:select  X:all  T:tasks  S:tldr  #:del  e:archive  s:star  m:mark  {thread_label}  ,:settings  q:quit"
            else:
                raw_label = "w:raw" if not self._mail_raw_mode else "w:compact"
                if self._conv_emails:
                    hints = f" j/k:scroll  J/K:page  n/p:next/prev email  o:toggle quotes  \\:expand/collapse  S:tldr  {raw_label}  h:back"
                else:
                    hints = f" j/k:scroll  J/K:page  {raw_label}  h/Esc:back  q:quit"
            self._safe_addstr(bar_y, 1, hints[:w].ljust(w), curses.color_pair(C_STATUS_BAR))
            return

        if self.focus == LEFT:
            if self.view_mode == VIEW_SCHED_DAY:
                hints = " ↑↓ navigate  h/l day  t today  a add  e edit  x delete  y copy  p paste  o open" + _undo_hint + "  v view  c tasks  M mail  q quit"
            elif self.view_mode == VIEW_SCHED_NDAY:
                hints = f" j/k events  h/l day  Enter drill  a add  e edit  x del  y copy  p paste  o open  +/- days ({self.sched_nday_count})  t today" + _undo_hint + "  v view  c tasks  M mail  q quit"
            elif self.view_mode == VIEW_SCHED_WEEK:
                hints = " j/k events  h/l day  Enter drill  a add  e edit  x del  y copy  p paste  o open  t today" + _undo_hint + "  v view  c tasks  M mail  q quit"
            elif self.view_mode == VIEW_SCHED_MONTH:
                hints = " ↑↓ navigate  Enter day  h/l month  t today" + _undo_hint + "  v view  c tasks  M mail  q quit"
            elif self.view_mode in (VIEW_TODAY, VIEW_WEEK, VIEW_MONTH):
                hints = " ↑↓ navigate  Enter/→ details  d done  r reschedule  x delete" + _undo_hint + "  i inbox  v view  c cal  M mail  q quit"
            else:
                hints = " ↑↓ navigate  Enter/→ details  v view  s sort  a add  x delete  A archive  D claude" + _undo_hint + "  f filter  i inbox  c cal  M mail  q quit"
        else:
            # Context-sensitive hints for right panel
            parts = [" j/k navigate  h/l in/out"]
            if self.detail_items and 0 <= self.right_cursor < len(self.detail_items):
                item = self.detail_items[self.right_cursor]
                if item.kind == "milestone":
                    proj = self._current_project()
                    ms = proj.get("milestones", [])[item.index] if proj else {}
                    if ms.get("done"):
                        parts.append("d undone")
                    else:
                        parts.append("d done  r reschedule")
                    parts.append("x delete")
                elif item.kind in ("task", "ms_task"):
                    proj = self._current_project()
                    t_obj = None
                    if proj and item.kind == "task":
                        tasks_list = proj.get("tasks", [])
                        if 0 <= item.index < len(tasks_list):
                            t_obj = tasks_list[item.index]
                    elif proj and item.kind == "ms_task" and item.index is not None:
                        mi, ti = item.index
                        ms_list = proj.get("milestones", [])
                        if mi < len(ms_list):
                            ms_tasks = ms_list[mi].get("tasks", [])
                            if ti < len(ms_tasks):
                                t_obj = ms_tasks[ti]
                    if t_obj is not None and _task_done(t_obj):
                        parts.append("d undone  x delete  J/K reorder")
                    else:
                        parts.append("d done  r reschedule  x delete  J/K reorder")
                    if proj and proj.get("name", "").lower() == "inbox":
                        parts.append("m move")
            if self._undo_stack:
                parts.append("u undo")
            parts.append("a add  n notes  D claude  q quit")
            hints = "  ".join(parts)

        hints = hints[:w]
        self._safe_addstr(bar_y, 1, hints.ljust(w), curses.color_pair(C_STATUS_BAR))

    def _safe_addstr(self, y, x, text, attr=0, max_n=0):
        try:
            avail = self.max_x - x - 1
            if max_n > 0:
                avail = min(avail, max_n)
            if avail <= 0:
                return
            # Clip by display width then write
            text = _wc_truncate(text, avail)
            self.stdscr.addstr(y, x, text, attr)
        except curses.error:
            pass

    def _show_loading(self, msg, progress=None):
        """Draw a centered bordered loading box and refresh immediately.

        progress: optional (current, total) tuple to show a progress bar.
        """
        h, w = self.max_y, self.max_x
        box_w = min(max(len(msg) + 12, 50), w - 4)
        if box_w < 20:
            box_w = w - 2
        inner = box_w - 4

        has_prog = progress is not None
        box_h = 8 if has_prog else 7
        sy = max(0, (h - box_h) // 2)
        sx = max(0, (w - box_w) // 2)

        # Clear the box area
        for cy in range(sy, min(h, sy + box_h)):
            self._safe_addstr(cy, sx, " " * box_w)

        title = "Loading"
        dashes = max(1, box_w - 5 - len(title))
        blank = "│" + " " * (box_w - 2) + "│"

        self._safe_addstr(sy, sx, "┌─ " + title + " " + "─" * dashes + "┐")
        self._safe_addstr(sy + 1, sx, blank)
        self._safe_addstr(sy + 2, sx, blank)
        self._safe_addstr(sy + 3, sx,
                          "│  " + msg[:inner].ljust(inner) + "│")
        row = 4
        if has_prog:
            cur, tot = progress
            tot = max(tot, 1)
            label = f"{cur}/{tot}"
            bar_w = inner - len(label) - 1 if len(label) + 2 <= inner else inner
            filled = int(bar_w * cur / tot)
            bar = "█" * filled + "░" * (bar_w - filled)
            if bar_w < inner:
                bar = bar + " " + label
            self._safe_addstr(sy + row, sx,
                              "│  " + bar[:inner].ljust(inner) + "│")
            row += 1
        self._safe_addstr(sy + row, sx, blank)
        self._safe_addstr(sy + row + 1, sx, blank)
        self._safe_addstr(sy + row + 2, sx, "└" + "─" * (box_w - 2) + "┘")
        self.stdscr.refresh()

    # ─── Navigation ───────────────────────────────────────────────────────

    def _move_left(self, delta):
        count = self._left_item_count()
        if count == 0:
            return
        new_pos = max(0, min(count - 1, self.left_cursor + delta))

        # Skip non-selectable items (free gaps in day view, week headers in month view)
        items = None
        if self.view_mode == VIEW_SCHED_DAY and self.sched_day_items:
            items = self.sched_day_items
        elif self.view_mode == VIEW_SCHED_MONTH and self.sched_month_data:
            items = self.sched_month_data
        if items:
            step = 1 if delta > 0 else -1
            while 0 <= new_pos < count and not items[new_pos].get("selectable", True):
                new_pos += step
            new_pos = max(0, min(count - 1, new_pos))
            if 0 <= new_pos < count and not items[new_pos].get("selectable", True):
                step = -step
                while 0 <= new_pos < count and not items[new_pos].get("selectable", True):
                    new_pos += step
                new_pos = max(0, min(count - 1, new_pos))

        self.left_cursor = new_pos
        self.right_cursor = 0
        self.right_scroll = 0
        self._rebuild_detail()

    def _move_right(self, delta):
        if not self.detail_items:
            return
        cur = self.right_cursor
        step = 1 if delta > 0 else -1
        for _ in range(abs(delta)):
            nxt = cur + step
            while 0 <= nxt < len(self.detail_items):
                if self.detail_items[nxt].selectable:
                    cur = nxt
                    break
                nxt += step

        self.right_cursor = cur

    # ─── Modal dialogs ───────────────────────────────────────────────────

    def _modal_input(self, title, prompt, body_lines=None, default=""):
        """Show a centered floating dialog with text input. Returns '' on Escape."""
        curses.flushinp()
        self.draw()
        curses.curs_set(1)
        buf = default

        while True:
            h, w = self.stdscr.getmaxyx()
            box_w = min(max(50, w // 2), w - 4)
            if box_w < 20:
                box_w = w - 2
            inner = box_w - 4
            blank = "│" + " " * (box_w - 2) + "│"

            lines = body_lines or []
            max_body = max(0, h - 9)
            displayed = lines[:max_body]
            n = len(displayed)
            box_h = 7 + n
            box_h = min(box_h, h - 2)

            sy = max(0, (h - box_h) // 2)
            sx = max(0, (w - box_w) // 2)

            # Top border
            t = title[:inner]
            dashes = max(1, box_w - 5 - len(t))
            self._safe_addstr(sy, sx, "┌─ " + t + " " + "─" * dashes + "┐")

            row = 1
            self._safe_addstr(sy + row, sx, blank)
            row += 1

            for line in displayed:
                self._safe_addstr(sy + row, sx,
                                  "│  " + line[:inner].ljust(inner) + "│")
                row += 1

            if displayed:
                self._safe_addstr(sy + row, sx, blank)
                row += 1

            # Input line
            full = prompt + buf
            if len(full) <= inner:
                vis = full.ljust(inner)
                cx = sx + 3 + len(full)
            else:
                vis = full[len(full) - inner:]
                cx = sx + 3 + inner
            self._safe_addstr(sy + row, sx, "│  " + vis + "│")
            cy = sy + row
            row += 1

            self._safe_addstr(sy + row, sx, blank)
            row += 1

            # Bottom border
            esc = " Esc cancel "
            ld = max(1, box_w - 2 - len(esc) - 4)
            self._safe_addstr(sy + row, sx,
                              "└" + "─" * ld + esc + "─" * 4 + "┘")

            try:
                self.stdscr.move(cy, cx)
            except curses.error:
                pass
            self.stdscr.refresh()

            try:
                ch = self.stdscr.getch()
            except curses.error:
                continue

            if ch == 27:
                curses.curs_set(0)
                return ""
            elif ch in (curses.KEY_ENTER, 10, 13):
                curses.curs_set(0)
                return buf
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                buf = buf[:-1]
            elif ch == curses.KEY_RESIZE:
                self._calc_dimensions()
                self.draw()
            elif 32 <= ch <= 126:
                buf += chr(ch)

    def _modal_confirm(self, title, message):
        """Show a centered floating y/n dialog. Returns True on y, False on n/Esc."""
        curses.flushinp()
        self.draw()
        while True:
            h, w = self.stdscr.getmaxyx()
            box_w = min(max(len(message) + 12, 50), w - 4)
            if box_w < 20:
                box_w = w - 2
            inner = box_w - 4
            blank = "│" + " " * (box_w - 2) + "│"

            box_h = 8
            sy = max(0, (h - box_h) // 2)
            sx = max(0, (w - box_w) // 2)

            t = title[:inner]
            dashes = max(1, box_w - 5 - len(t))
            self._safe_addstr(sy, sx, "┌─ " + t + " " + "─" * dashes + "┐")
            self._safe_addstr(sy + 1, sx, blank)
            self._safe_addstr(sy + 2, sx, blank)

            self._safe_addstr(sy + 3, sx,
                              "│  " + message[:inner].ljust(inner) + "│")

            self._safe_addstr(sy + 4, sx, blank)

            yn = "(y) yes  (n) no"
            pad = max(0, inner - len(yn))
            self._safe_addstr(sy + 5, sx,
                              "│  " + (" " * pad + yn)[:inner] + "│")
            self._safe_addstr(sy + 6, sx, blank)
            self._safe_addstr(sy + 7, sx, "└" + "─" * (box_w - 2) + "┘")

            self.stdscr.refresh()

            try:
                ch = self.stdscr.getch()
            except curses.error:
                continue

            if ch in (ord("y"), ord("Y")):
                return True
            elif ch in (ord("n"), ord("N"), 27):
                return False
            elif ch == curses.KEY_RESIZE:
                self._calc_dimensions()
                self.draw()

    def _modal_choice(self, title, message, choices):
        """Show a choice dialog. choices = list of (key, label) pairs.
        Returns the key of the chosen option, or None on Esc."""
        curses.flushinp()
        self.draw()
        valid_keys = {ord(k.lower()): k for k, label in choices}
        n_lines = 1 + len(choices) + 1  # message + choices + esc
        while True:
            h, w = self.stdscr.getmaxyx()
            box_w = min(max(55, w // 2), w - 4)
            if box_w < 20:
                box_w = w - 2
            inner = box_w - 4
            blank = "│" + " " * (box_w - 2) + "│"

            box_h = n_lines + 6  # top border + padding + inner + padding + bottom border
            sy = max(0, (h - box_h) // 2)
            sx = max(0, (w - box_w) // 2)

            t = title[:inner]
            dashes = max(1, box_w - 5 - len(t))
            self._safe_addstr(sy, sx, "┌─ " + t + " " + "─" * dashes + "┐")

            row = sy + 1
            self._safe_addstr(row, sx, blank)
            row += 1
            self._safe_addstr(row, sx,
                              "│  " + message[:inner].ljust(inner) + "│")
            row += 1
            self._safe_addstr(row, sx, blank)
            row += 1
            for key, label in choices:
                line = f"({key}) {label}"
                self._safe_addstr(row, sx,
                                  "│  " + line[:inner].ljust(inner) + "│")
                row += 1
            esc_line = "(Esc) cancel"
            self._safe_addstr(row, sx,
                              "│  " + esc_line[:inner].ljust(inner) + "│")
            row += 1
            self._safe_addstr(row, sx, blank)
            row += 1
            self._safe_addstr(row, sx, "└" + "─" * (box_w - 2) + "┘")

            self.stdscr.refresh()

            try:
                ch = self.stdscr.getch()
            except curses.error:
                continue

            if ch == 27:
                return None
            if ch in valid_keys:
                return valid_keys[ch]
            if ch == curses.KEY_RESIZE:
                self._calc_dimensions()
                self.draw()

    def _modal_scroll_text(self, title, text_lines):
        """Show a scrollable read-only text popup. Press q/Esc to close."""
        curses.flushinp()
        scroll = 0
        prev_inner = 0
        wrapped = list(text_lines)
        while True:
            self.draw()
            h, w = self.stdscr.getmaxyx()
            box_w = min(max(60, w * 3 // 4), w - 4)
            inner = box_w - 4
            # Re-wrap when width changes
            if inner != prev_inner:
                prev_inner = inner
                wrapped = []
                for raw in text_lines:
                    while len(raw) > inner:
                        # Try to break at a space
                        brk = raw.rfind(" ", 0, inner)
                        if brk <= 0:
                            brk = inner
                        wrapped.append(raw[:brk])
                        raw = raw[brk:].lstrip()
                    wrapped.append(raw)
            box_h = min(len(wrapped) + 4, h - 2)
            view_h = box_h - 4
            if view_h < 1:
                view_h = 1
                box_h = 5
            sy = max(0, (h - box_h) // 2)
            sx = max(0, (w - box_w) // 2)
            blank = "│" + " " * (box_w - 2) + "│"

            t = title[:inner]
            dashes = max(1, box_w - 5 - len(t))
            self._safe_addstr(sy, sx, "┌─ " + t + " " + "─" * dashes + "┐")
            self._safe_addstr(sy + 1, sx, blank)

            max_scroll = max(0, len(wrapped) - view_h)
            scroll = max(0, min(scroll, max_scroll))
            for vi in range(view_h):
                li = scroll + vi
                if li < len(wrapped):
                    ln = wrapped[li][:inner]
                else:
                    ln = ""
                self._safe_addstr(sy + 2 + vi, sx,
                                  "│  " + ln.ljust(inner)[:inner] + "│")

            self._safe_addstr(sy + 2 + view_h, sx, blank)
            hint = "j/k scroll  q/Esc close"
            self._safe_addstr(sy + 3 + view_h, sx,
                              "└─ " + hint[:box_w - 5] + " " + "─" * max(1, box_w - 5 - len(hint) - 1) + "┘")

            self.stdscr.refresh()
            try:
                ch = self.stdscr.getch()
            except curses.error:
                continue
            if ch in (27, ord("q")):
                return
            elif ch in (ord("j"), curses.KEY_DOWN):
                scroll = min(max_scroll, scroll + 1)
            elif ch in (ord("k"), curses.KEY_UP):
                scroll = max(0, scroll - 1)
            elif ch in (ord("J"), ord(" ")):
                scroll = min(max_scroll, scroll + view_h)
            elif ch in (ord("K"),):
                scroll = max(0, scroll - view_h)
            elif ch == ord("g"):
                scroll = 0
            elif ch == ord("G"):
                scroll = max_scroll
            elif ch == curses.KEY_RESIZE:
                self._calc_dimensions()

    def _modal_input_time(self, title, prompt, body_lines=None):
        """Prompt for a time value, re-prompting on invalid input."""
        extra = body_lines or []
        while True:
            val = self._modal_input(title, prompt, extra)
            if not val:
                return ""
            try:
                parse_time(val)
                return val
            except ValueError:
                extra = (body_lines or []) + [f"Invalid time: '{val}'"]

    def _modal_input_date(self, title, prompt, default=None, body_lines=None):
        """Prompt for a date value, re-prompting on invalid input."""
        hint = ["Shortcuts: today, tomorrow, +3, -1, mon..sun"]
        extra = (body_lines or []) + hint
        while True:
            val = self._modal_input(title, prompt, extra)
            if not val:
                return default or ""
            try:
                parse_date(val)
                return val
            except ValueError:
                extra = (body_lines or []) + [f"Invalid date: '{val}'"]

    _DAY_ABBREV = {"M": "monday", "T": "tuesday", "W": "wednesday",
                    "R": "thursday", "F": "friday", "S": "saturday",
                    "s": "sunday"}
    _DAY_FULL = {"monday", "tuesday", "wednesday", "thursday",
                 "friday", "saturday", "sunday"}

    def _parse_days(self, val):
        """Parse day string like 'MWF' or 'monday,wednesday'. Returns list or None."""
        s = val.strip()
        # Try letter codes: MWF, MTWRF, etc.
        if s and all(c in self._DAY_ABBREV for c in s):
            return [self._DAY_ABBREV[c] for c in s]
        # Try comma-separated full names
        names = [d.strip().lower() for d in s.split(",") if d.strip()]
        if names and all(n in self._DAY_FULL for n in names):
            return names
        return None

    def _modal_input_days(self, title, prompt, body_lines=None):
        """Prompt for day names, re-prompting on invalid input."""
        extra = body_lines or []
        while True:
            val = self._modal_input(title, prompt, extra)
            if not val:
                return ""
            if val.strip().lower() == "all":
                return "all"
            parsed = self._parse_days(val)
            if parsed:
                return ",".join(parsed)
            extra = (body_lines or []) + [f"Invalid: '{val}'"]

    def _modal_input_int(self, title, prompt, default="1", body_lines=None):
        """Prompt for an integer, re-prompting on invalid input."""
        extra = body_lines or []
        while True:
            val = self._modal_input(title, prompt, extra)
            if not val:
                return default
            try:
                int(val)
                return val
            except ValueError:
                extra = (body_lines or []) + [f"Not a number: '{val}'"]

    def _prompt_monthly_pattern(self, ev, dialog_title):
        """Prompt user for monthly recurrence sub-pattern and populate ev fields."""
        import datetime
        ordinals = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th", -1: "last"}
        cur_date = self.sched_date
        cur_wom = (cur_date.day - 1) // 7 + 1
        cur_dow = cur_date.strftime("%A").lower()
        mpat = self._modal_input(dialog_title, "Monthly pattern [2]: ", [
            "Monthly pattern:",
            f"  1 = same day each month (e.g. {cur_date.day}th)",
            f"  2 = same weekday (e.g. {ordinals.get(cur_wom, str(cur_wom))} {cur_dow.title()})",
        ]) or "2"
        if mpat == "1":
            dom = self._modal_input_int(dialog_title,
                f"Day of month [{cur_date.day}]: ",
                str(cur_date.day),
                ["Day number (1-31)"])
            ev["day_of_month"] = int(dom)
        else:
            default_str = f"{cur_wom} {cur_dow}"
            wom_input = self._modal_input(dialog_title,
                f"Week & day [{default_str}]: ", [
                f"  {ordinals.get(cur_wom, str(cur_wom))} {cur_dow.title()}",
                "Format: N dayname  (e.g. 3 wednesday)",
                "  N = 1-5 or -1 for last",
            ]) or default_str
            parts = wom_input.strip().split(None, 1)
            if len(parts) == 2:
                ev["week_of_month"] = int(parts[0])
                ev["day_of_week"] = parts[1].lower()
            else:
                ev["week_of_month"] = cur_wom
                ev["day_of_week"] = cur_dow
        interval = self._modal_input_int(dialog_title,
            "Interval [1]: ", "1", [
            "Repeat every N months",
            "  1 = every, 2 = every other, etc.",
        ])
        if interval != "1":
            ev["interval"] = int(interval)
            ev["start_date"] = self._modal_input_date(
                dialog_title,
                f"Anchor [{self.sched_date}]: ",
                str(self.sched_date),
                ["First occurrence month (YYYY-MM-DD)"],
            )

    # ─── Actions ──────────────────────────────────────────────────────────

    def _current_detail_item(self):
        if not self.detail_items or self.right_cursor >= len(self.detail_items):
            return None
        return self.detail_items[self.right_cursor]

    def _current_project(self):
        if self.view_mode in (VIEW_TODAY, VIEW_WEEK, VIEW_MONTH):
            if not self.timeline_items:
                return None
            idx = min(self.left_cursor, len(self.timeline_items) - 1)
            return self.timeline_items[idx]["project"]
        if self.view_mode == VIEW_PROJECTS:
            if not self.filtered:
                return None
            return self.filtered[self.left_cursor]
        return None

    def _get_or_create_inbox(self):
        for p in self.projects:
            if p.get("name", "").lower() == "inbox":
                return p
        inbox = {"name": "Inbox", "category": "admin", "status": "active",
                 "milestones": [], "tasks": []}
        self.projects.append(inbox)
        return inbox

    def _push_undo(self):
        self._undo_stack.append((copy.deepcopy(self.projects), copy.deepcopy(self.schedule)))
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)

    def _pop_undo(self):
        if not self._undo_stack:
            return False
        self.projects, self.schedule = self._undo_stack.pop()
        save_projects(self.projects)
        save_schedule(self.schedule)
        self._rebuild_filtered()
        # Clamp left cursor
        if self.view_mode in (VIEW_TODAY, VIEW_WEEK, VIEW_MONTH):
            if self.left_cursor >= len(self.timeline_items):
                self.left_cursor = max(0, len(self.timeline_items) - 1)
        elif self.view_mode == VIEW_PROJECTS:
            if self.left_cursor >= len(self.filtered):
                self.left_cursor = max(0, len(self.filtered) - 1)
        elif self.view_mode == VIEW_SCHED_DAY:
            if self.left_cursor >= len(self.sched_day_items):
                self.left_cursor = max(0, len(self.sched_day_items) - 1)
        elif self.view_mode == VIEW_SCHED_WEEK:
            if self.left_cursor >= 7:
                self.left_cursor = 6
            if self.sched_week_data:
                events = self.sched_week_data[min(self.left_cursor, len(self.sched_week_data) - 1)]["events"]
                self.week_event_cursor = min(self.week_event_cursor, max(0, len(events) - 1))
        elif self.view_mode == VIEW_SCHED_NDAY:
            if self.left_cursor >= len(self.sched_nday_data):
                self.left_cursor = max(0, len(self.sched_nday_data) - 1)
            if self.sched_nday_data:
                events = self.sched_nday_data[self.left_cursor]["events"]
                self.nday_event_cursor = min(self.nday_event_cursor, max(0, len(events) - 1))
        elif self.view_mode == VIEW_SCHED_MONTH:
            if self.left_cursor >= len(self.sched_month_data):
                self.left_cursor = max(0, len(self.sched_month_data) - 1)
        self._rebuild_detail()
        return True

    def _save_and_rebuild(self):
        self._push_undo()
        save_projects(self.projects)
        self._rebuild_filtered()
        # Clamp left cursor
        if self.view_mode in (VIEW_TODAY, VIEW_WEEK, VIEW_MONTH):
            if self.left_cursor >= len(self.timeline_items):
                self.left_cursor = max(0, len(self.timeline_items) - 1)
        elif self.view_mode == VIEW_PROJECTS:
            if self.left_cursor >= len(self.filtered):
                self.left_cursor = max(0, len(self.filtered) - 1)
        self._rebuild_detail()

    def _save_schedule_and_rebuild(self):
        self._push_undo()
        save_schedule(self.schedule)
        self._rebuild_filtered()
        if self.view_mode == VIEW_SCHED_DAY:
            if self.left_cursor >= len(self.sched_day_items):
                self.left_cursor = max(0, len(self.sched_day_items) - 1)
        elif self.view_mode == VIEW_SCHED_WEEK:
            if self.left_cursor >= 7:
                self.left_cursor = 6
            if self.sched_week_data:
                events = self.sched_week_data[min(self.left_cursor, len(self.sched_week_data) - 1)]["events"]
                self.week_event_cursor = min(self.week_event_cursor, max(0, len(events) - 1))
        elif self.view_mode == VIEW_SCHED_NDAY:
            if self.left_cursor >= len(self.sched_nday_data):
                self.left_cursor = max(0, len(self.sched_nday_data) - 1)
            if self.sched_nday_data:
                events = self.sched_nday_data[self.left_cursor]["events"]
                self.nday_event_cursor = min(self.nday_event_cursor, max(0, len(events) - 1))
        elif self.view_mode == VIEW_SCHED_MONTH:
            if self.left_cursor >= len(self.sched_month_data):
                self.left_cursor = max(0, len(self.sched_month_data) - 1)
        self._rebuild_detail()

    def action_done(self):
        item = self._current_detail_item()
        proj = self._current_project()
        if not item or not proj:
            return

        if item.kind == "milestone":
            ms = proj["milestones"][item.index]
            if ms.get("done"):
                ms.pop("done", None)
                ms.pop("completed_date", None)
                self._save_and_rebuild()
                return
            ms["done"] = True
            ms["completed_date"] = str(today())
            self._save_and_rebuild()

        elif item.kind == "task":
            tasks = proj.get("tasks", [])
            if 0 <= item.index < len(tasks):
                t = _task_to_dict(tasks[item.index])
                tasks[item.index] = t
                if t.get("done"):
                    t.pop("done", None)
                    t.pop("completed_date", None)
                else:
                    t["done"] = True
                    t["completed_date"] = str(today())
                self._save_and_rebuild()

        elif item.kind == "ms_task":
            ms_idx, t_idx = item.index
            ms = proj["milestones"][ms_idx]
            tasks = ms.get("tasks", [])
            if 0 <= t_idx < len(tasks):
                t = _task_to_dict(tasks[t_idx])
                tasks[t_idx] = t
                if t.get("done"):
                    t.pop("done", None)
                    t.pop("completed_date", None)
                else:
                    t["done"] = True
                    t["completed_date"] = str(today())
                self._save_and_rebuild()

    def action_undone(self):
        item = self._current_detail_item()
        proj = self._current_project()
        if not item or not proj or item.kind != "milestone":
            return

        ms = proj["milestones"][item.index]
        if not ms.get("done"):
            return
        ms.pop("done", None)
        ms.pop("completed_date", None)
        self._save_and_rebuild()

    def action_move_task(self, direction):
        """Move a task up (-1) or down (+1) in its list."""
        item = self._current_detail_item()
        proj = self._current_project()
        if not item or not proj:
            return
        if item.kind == "task":
            tasks = proj.get("tasks", [])
            idx = item.index
            new_idx = idx + direction
            if new_idx < 0 or new_idx >= len(tasks):
                return
            tasks[idx], tasks[new_idx] = tasks[new_idx], tasks[idx]
            self._save_and_rebuild()
            for i, di in enumerate(self.detail_items):
                if di.kind == "task" and di.index == new_idx:
                    self.right_cursor = i
                    break
        elif item.kind == "ms_task":
            ms_idx, t_idx = item.index
            ms = proj["milestones"][ms_idx]
            tasks = ms.get("tasks", [])
            new_idx = t_idx + direction
            if new_idx < 0 or new_idx >= len(tasks):
                return
            tasks[t_idx], tasks[new_idx] = tasks[new_idx], tasks[t_idx]
            self._save_and_rebuild()
            for i, di in enumerate(self.detail_items):
                if di.kind == "ms_task" and di.index == (ms_idx, new_idx):
                    self.right_cursor = i
                    break

    def action_delete(self):
        item = self._current_detail_item()
        proj = self._current_project()
        if not item or not proj:
            return

        if item.kind == "milestone":
            name = proj["milestones"][item.index].get("name", "")
            if not self._modal_confirm("Delete", f"Delete milestone '{name}'?"):
                return
            proj["milestones"].pop(item.index)
            self._save_and_rebuild()
            self._snap_right_cursor()

        elif item.kind == "task":
            tasks = proj.get("tasks", [])
            if 0 <= item.index < len(tasks):
                desc = _task_text(tasks[item.index])
                if not self._modal_confirm("Delete", f"Delete task '{desc}'?"):
                    return
                tasks.pop(item.index)
                self._save_and_rebuild()
                self._snap_right_cursor()

        elif item.kind == "ms_task":
            ms_idx, t_idx = item.index
            ms = proj["milestones"][ms_idx]
            tasks = ms.get("tasks", [])
            if 0 <= t_idx < len(tasks):
                desc = _task_text(tasks[t_idx])
                if not self._modal_confirm("Delete", f"Delete task '{desc}'?"):
                    return
                tasks.pop(t_idx)
                self._save_and_rebuild()
                self._snap_right_cursor()

    def action_reschedule(self):
        item = self._current_detail_item()
        proj = self._current_project()
        if not item or not proj:
            return

        if item.kind in ("task", "ms_task"):
            # Reschedule task due date
            if item.kind == "task":
                tasks = proj.get("tasks", [])
                if not (0 <= item.index < len(tasks)):
                    return
                t = tasks[item.index]
                current_due = _task_due(t) or "none"
                new_date_str = self._cmd_params.pop("date", None) or self._modal_input_date("Reschedule Task",
                    f"New due date ({current_due}): ",
                    body_lines=[f"Task: {_task_text(t)}"])
                if not new_date_str:
                    return
                # Convert plain string to dict if needed
                if isinstance(t, str):
                    tasks[item.index] = {"desc": t, "due": new_date_str}
                else:
                    t["due"] = new_date_str
            else:  # ms_task
                ms_idx, t_idx = item.index
                ms = proj["milestones"][ms_idx]
                tasks = ms.get("tasks", [])
                if not (0 <= t_idx < len(tasks)):
                    return
                t = tasks[t_idx]
                current_due = _task_due(t) or "none"
                new_date_str = self._cmd_params.pop("date", None) or self._modal_input_date("Reschedule Task",
                    f"New due date ({current_due}): ",
                    body_lines=[f"Task: {_task_text(t)}"])
                if not new_date_str:
                    return
                if isinstance(t, str):
                    tasks[t_idx] = {"desc": t, "due": new_date_str}
                else:
                    t["due"] = new_date_str
            self._save_and_rebuild()
            return

        if item.kind != "milestone":
            return

        ms = proj["milestones"][item.index]
        if ms.get("done"):
            return

        new_date_str = self._modal_input("Reschedule",
            f"New date ({ms.get('due', 'none')}): ",
            [f"Milestone: {ms['name']}"])
        if not new_date_str:
            return
        try:
            new_date = parse_date(new_date_str)
        except ValueError:
            return

        old_due = ms.get("due")
        if old_due:
            try:
                old_date = parse_date(old_due)
                shift = (new_date - old_date).days
            except ValueError:
                shift = 0
        else:
            shift = 0

        ms["due"] = str(new_date)

        # Offer cascade
        if shift != 0:
            milestones = proj.get("milestones", [])
            downstream = [m for m in milestones[item.index + 1:]
                          if not m.get("done") and m.get("due")]
            if downstream:
                cascade = self._modal_confirm("Cascade",
                    f"Shift {len(downstream)} downstream by {shift:+d}d?")
                if cascade:
                    for m in downstream:
                        try:
                            d = parse_date(m["due"])
                            m["due"] = str(d + datetime.timedelta(days=shift))
                        except ValueError:
                            pass

        self._save_and_rebuild()

    def action_add_item(self):
        """Add a milestone or task to the current project (right panel context)."""
        proj = self._current_project()
        if not proj:
            return

        choice = self._cmd_params.pop("item_type", None) or self._modal_input("Add Item", "Type (m/t): ",
            ["(m) milestone", "(t) task"])
        if not choice:
            return

        if choice.lower().startswith("m"):
            name = self._cmd_params.pop("name", None) or self._modal_input("Add Milestone", "Name: ")
            if not name:
                return
            due_str = self._cmd_params.pop("due", None) or self._modal_input("Add Milestone", "Due date: ",
                [f"Milestone: {name}", "", "Format: YYYY-MM-DD"])
            if not due_str:
                return
            try:
                due = parse_date(due_str)
            except ValueError:
                return
            if "milestones" not in proj:
                proj["milestones"] = []
            proj["milestones"].append({"name": name, "due": str(due), "done": False})
            self._save_and_rebuild()

        elif choice.lower().startswith("t"):
            # If cursor is on a milestone or ms_task, add under that milestone
            item = self._current_detail_item()
            ms_target = None
            if item and item.kind == "milestone":
                ms_target = proj.get("milestones", [])[item.index]
            elif item and item.kind == "ms_task":
                ms_target = proj.get("milestones", [])[item.index[0]]

            desc = self._cmd_params.pop("desc", None)
            if not desc:
                if ms_target:
                    desc = self._modal_input("Add Task", "Description: ",
                        [f"Milestone: {ms_target['name']}"])
                else:
                    desc = self._modal_input("Add Task", "Description: ")
            if not desc:
                return
            due_str = self._cmd_params.pop("due", None) or self._modal_input_date("Task Due Date",
                "Due date (blank for none): ", body_lines=[f"Task: {desc}"])
            if due_str:
                task_obj = {"desc": desc, "due": due_str}
            else:
                task_obj = desc
            if ms_target:
                if "tasks" not in ms_target:
                    ms_target["tasks"] = []
                ms_target["tasks"].append(task_obj)
            else:
                if "tasks" not in proj:
                    proj["tasks"] = []
                proj["tasks"].append(task_obj)
            self._save_and_rebuild()

    def action_inbox_add(self):
        """Quick-capture an item into the Inbox project."""
        text = self._cmd_params.pop("text", None) or self._modal_input("Inbox", "Add: ")
        if not text:
            return
        inbox = self._get_or_create_inbox()
        if "tasks" not in inbox:
            inbox["tasks"] = []
        inbox["tasks"].append(text)
        self._save_and_rebuild()

    def action_inbox_move(self):
        """Move an inbox task to another project as task or milestone."""
        proj = self._current_project()
        if not proj or proj.get("name", "").lower() != "inbox":
            return
        item = self._current_detail_item()
        if not item or item.kind != "task":
            return
        task_obj = proj["tasks"][item.index]
        task_display = _task_text(task_obj)

        # Build list of active target projects (excluding Inbox)
        targets = [p for p in self.projects
                   if p.get("status") == "active"
                   and p.get("name", "").lower() != "inbox"]
        if not targets:
            return

        body = [f"{i+1}. {p['name']}" for i, p in enumerate(targets)]
        pick = self._modal_input("Move to Project", "Number or name: ", body)
        if not pick:
            return

        target = None
        try:
            idx = int(pick) - 1
            if 0 <= idx < len(targets):
                target = targets[idx]
        except ValueError:
            pick_l = pick.lower()
            for p in targets:
                if pick_l in p["name"].lower():
                    target = p
                    break
        if not target:
            return

        choice = self._modal_choice("Move as", f"→ {target['name']}",
                                    [("t", "task"), ("m", "milestone")])
        if not choice:
            return

        if choice == "t":
            if "tasks" not in target:
                target["tasks"] = []
            target["tasks"].append(task_obj)
        elif choice == "m":
            due_str = self._modal_input("Milestone Due Date", "Due: ",
                [f"Milestone: {task_display}", "", "Format: YYYY-MM-DD"])
            if not due_str:
                return
            try:
                due = parse_date(due_str)
            except ValueError:
                return
            if "milestones" not in target:
                target["milestones"] = []
            target["milestones"].append({"name": task_display, "due": str(due), "done": False})

        proj["tasks"].pop(item.index)
        self._save_and_rebuild()

    def action_add_project(self):
        """Guided Q&A to add a new project."""
        name = self._cmd_params.pop("name", None) or self._modal_input("Add Project", "Name: ")
        if not name:
            return

        category = self._cmd_params.pop("category", None) or self._modal_input("Add Project", "Category: ",
            [f"Project: {name}", "",
             "e.g., research, software, admin"])
        deadline_str = self._cmd_params.pop("deadline", None) or self._modal_input("Add Project", "Deadline: ",
            [f"Project: {name}", "",
             "Format: YYYY-MM-DD (blank to skip)"])
        deadline = None
        if deadline_str:
            try:
                deadline = str(parse_date(deadline_str))
            except ValueError:
                pass

        proj = {"name": name, "category": category or "general",
                "status": "active"}
        if deadline:
            proj["deadline"] = deadline
        proj["milestones"] = []
        proj["tasks"] = []

        # Milestones
        while True:
            ms_name = self._modal_input("Add Milestone",
                "Name (blank to stop): ", [f"Project: {name}"])
            if not ms_name:
                break
            ms_due = self._modal_input("Add Milestone", "Due date: ",
                [f"Milestone: {ms_name}"])
            try:
                due = str(parse_date(ms_due))
            except ValueError:
                due = ms_due
            proj["milestones"].append({"name": ms_name, "due": due, "done": False})

        # Tasks
        while True:
            task = self._modal_input("Add Task",
                "Task (blank to stop): ", [f"Project: {name}"])
            if not task:
                break
            proj["tasks"].append(task)

        # Notes
        notes = self._modal_input("Add Project",
            "Notes (blank to skip): ", [f"Project: {name}"])
        if notes:
            proj["notes"] = notes

        self.projects.append(proj)
        self._save_and_rebuild()
        # Move cursor to new project
        for i, p in enumerate(self.filtered):
            if p is proj:
                self.left_cursor = i
                break
        self._rebuild_detail()

        # Offer to launch Claude Code for planning
        ch = self._modal_choice("Plan", "Launch Claude Code to plan this project?",
                                [("y", "Yes"), ("n", "No")])
        if ch == "y":
            self.action_claude_session(proj)

    # ─── Chat description ─────────────────────────────────────────────

    def _draw_chat_overlay(self, chat_lines, chat_scroll, input_buf, is_thinking):
        """Near-fullscreen chat overlay for project description building."""
        h, w = self.stdscr.getmaxyx()
        box_w = max(60, w - 4)
        box_h = max(16, h - 4)
        sy = max(0, (h - box_h) // 2)
        sx = max(0, (w - box_w) // 2)
        inner_w = box_w - 2
        chat_h = box_h - 6  # title + chat area + separator + input + separator + footer

        # Clear area
        blank = " " * box_w
        for cy in range(sy, min(sy + box_h, h)):
            self._safe_addstr(cy, sx, blank)

        # Top border
        title = " Chat: Project Description "
        top_bar = "─" * (box_w - 2)
        top_bar = top_bar[:1] + title + top_bar[1 + len(title):]
        self._safe_addstr(sy, sx, "┌" + top_bar[:box_w - 2] + "┐")

        # Chat content
        visible = chat_lines[chat_scroll:chat_scroll + chat_h]
        for row_i in range(chat_h):
            y = sy + 1 + row_i
            if row_i < len(visible):
                ctype, ctext = visible[row_i]
                line = ctext[:inner_w].ljust(inner_w)
                if ctype == "user":
                    self._safe_addstr(y, sx + 1, line, curses.color_pair(C_CYAN))
                elif ctype == "assistant":
                    self._safe_addstr(y, sx + 1, line, curses.color_pair(C_GREEN))
                else:
                    self._safe_addstr(y, sx + 1, line)
            else:
                self._safe_addstr(y, sx + 1, " " * inner_w)
            self._safe_addstr(y, sx, "│")
            self._safe_addstr(y, sx + box_w - 1, "│")

        # Input separator
        sep_y = sy + 1 + chat_h
        self._safe_addstr(sep_y, sx, "├" + "─" * (box_w - 2) + "┤")

        # Input line
        inp_y = sep_y + 1
        if is_thinking:
            inp_text = " [Thinking...]"
            self._safe_addstr(inp_y, sx, "│")
            self._safe_addstr(inp_y, sx + 1, inp_text[:inner_w].ljust(inner_w), curses.A_DIM)
            self._safe_addstr(inp_y, sx + box_w - 1, "│")
        else:
            prompt_str = " > "
            buf_display = input_buf[-(inner_w - len(prompt_str) - 1):]
            inp_text = prompt_str + buf_display
            self._safe_addstr(inp_y, sx, "│")
            self._safe_addstr(inp_y, sx + 1, inp_text[:inner_w].ljust(inner_w))
            self._safe_addstr(inp_y, sx + box_w - 1, "│")

        # Footer separator
        foot_sep_y = inp_y + 1
        self._safe_addstr(foot_sep_y, sx, "├" + "─" * (box_w - 2) + "┤")

        # Footer
        foot_y = foot_sep_y + 1
        keys = " Enter:send  Ctrl-D:done (save)  PgUp/PgDn:scroll  Esc:cancel "
        self._safe_addstr(foot_y, sx, "│")
        self._safe_addstr(foot_y, sx + 1, keys[:inner_w].center(inner_w), curses.A_DIM)
        self._safe_addstr(foot_y, sx + box_w - 1, "│")

        # Bottom border
        bot_y = foot_y + 1
        self._safe_addstr(bot_y, sx, "└" + "─" * (box_w - 2) + "┘")

        self.stdscr.refresh()

    def _chat_build_display(self, history, wrap_w):
        """Convert conversation history to flat display lines."""
        lines = []
        for msg in history:
            role = msg["role"]
            content = msg["content"]
            if role == "user":
                prefix = "You: "
                ctype = "user"
            else:
                prefix = "Claude: "
                ctype = "assistant"
            wrapped = textwrap.wrap(content, width=wrap_w - len(prefix) - 2,
                                   subsequent_indent=" " * len(prefix))
            if not wrapped:
                wrapped = [""]
            for i, wline in enumerate(wrapped):
                if i == 0:
                    lines.append((ctype, f"  {prefix}{wline}"))
                else:
                    lines.append((ctype, f"  {wline}"))
            lines.append(("blank", ""))
        return lines

    def _chat_build_prompt(self, project_name, category, history):
        """Build prompt for Claude with conversation context."""
        preamble = (
            f"You are helping describe the project \"{project_name}\" "
            f"(category: {category or 'general'}). "
            f"Ask clarifying questions about goals, scope, methods, deliverables, "
            f"and key milestones to understand the project. Keep responses concise "
            f"(2-3 sentences). Ask one question at a time."
        )
        parts = [f"System: {preamble}\n"]
        for msg in history:
            role = "User" if msg["role"] == "user" else "Assistant"
            parts.append(f"{role}: {msg['content']}")
        parts.append("Assistant:")
        return "\n".join(parts)

    def _chat_synthesize_prompt(self, project_name, category, history):
        """Build final synthesis prompt to distill conversation into description."""
        transcript = "\n".join(
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
            for m in history
        )
        return (
            f"Based on this conversation about the project \"{project_name}\" "
            f"(category: {category or 'general'}), write a concise 2-4 sentence "
            f"project description that captures the key goals, scope, and methods. "
            f"Output ONLY the description text, nothing else.\n\n"
            f"Conversation:\n{transcript}"
        )

    _MODEL_IDS = {
        "haiku": "claude-haiku-4-5-20251001",
        "sonnet": "claude-sonnet-4-6",
    }

    def _get_claude_model(self):
        """Return the Claude model ID from config, or prompt user to choose."""
        default = self.config.get("claude_model", "")
        if default in self._MODEL_IDS:
            return self._MODEL_IDS[default]
        # No default configured — ask
        choice = self._modal_choice("Model", "Choose model:",
                                    [("h", "Haiku (fast)"), ("s", "Sonnet")])
        if choice is None:
            return None
        return self._MODEL_IDS["haiku"] if choice == "h" else self._MODEL_IDS["sonnet"]

    def _chat_send_to_claude(self, prompt, model):
        """Send prompt to Claude CLI and return response text."""
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        try:
            result = subprocess.run(
                ["claude", "-p", "--model", model, "--dangerously-skip-permissions"],
                input=prompt, capture_output=True, text=True, timeout=120,
                env=env,
            )
            return result.stdout.strip()
        except Exception:
            return "[Error: Claude did not respond]"

    def action_chat_description(self, project=None):
        """Interactive chat to build/refine a project description."""
        if project is None:
            project = self._current_project()
        if not project:
            return

        # Model selection
        model = self._get_claude_model()
        if model is None:
            return

        proj_name = project.get("name", "")
        category = project.get("category", "")
        existing_desc = project.get("description", "")

        history = []  # list of {"role", "content"}

        # Initial assistant message
        if existing_desc:
            init_msg = (f"The current description for \"{proj_name}\" is:\n"
                        f"\"{existing_desc}\"\n\n"
                        f"What would you like to change or add?")
        else:
            init_msg = (f"Let's build a description for \"{proj_name}\". "
                        f"What is this project about?")
        history.append({"role": "assistant", "content": init_msg})

        input_buf = ""
        chat_scroll = 0
        is_thinking = False

        curses.curs_set(1)
        try:
            while True:
                h, w = self.stdscr.getmaxyx()
                box_w = max(60, w - 4)
                inner_w = box_w - 2
                box_h = max(16, h - 4)
                chat_h = box_h - 6

                chat_lines = self._chat_build_display(history, inner_w)
                # Auto-scroll to bottom
                max_scroll = max(0, len(chat_lines) - chat_h)
                if chat_scroll > max_scroll:
                    chat_scroll = max_scroll

                self._draw_chat_overlay(chat_lines, chat_scroll, input_buf, is_thinking)

                try:
                    ch = self.stdscr.getch()
                except curses.error:
                    continue

                if ch == 27:  # Esc — cancel
                    break
                elif ch == 4:  # Ctrl-D — done, synthesize
                    if len(history) < 2:
                        # Need at least one user message
                        break
                    is_thinking = True
                    self._draw_chat_overlay(chat_lines, chat_scroll, input_buf, is_thinking)

                    synth_prompt = self._chat_synthesize_prompt(proj_name, category, history)
                    desc = self._chat_send_to_claude(synth_prompt, model)
                    is_thinking = False

                    if desc and not desc.startswith("[Error"):
                        # Confirm
                        confirm = self._modal_choice(
                            "Save Description", desc[:200],
                            [("y", "Save"), ("n", "Discard")])
                        if confirm == "y":
                            project["description"] = desc
                            self._save_and_rebuild()
                            self._rebuild_detail()
                    break
                elif ch in (curses.KEY_PPAGE, 339):  # PgUp
                    chat_scroll = max(0, chat_scroll - chat_h)
                elif ch in (curses.KEY_NPAGE, 338):  # PgDn
                    max_scroll = max(0, len(chat_lines) - chat_h)
                    chat_scroll = min(max_scroll, chat_scroll + chat_h)
                elif ch in (curses.KEY_ENTER, ord("\n"), 10, 13):  # Enter — send
                    msg = input_buf.strip()
                    if not msg:
                        continue
                    history.append({"role": "user", "content": msg})
                    input_buf = ""
                    is_thinking = True

                    # Redraw with thinking indicator and auto-scroll
                    chat_lines = self._chat_build_display(history, inner_w)
                    chat_scroll = max(0, len(chat_lines) - chat_h)
                    self._draw_chat_overlay(chat_lines, chat_scroll, input_buf, is_thinking)

                    prompt = self._chat_build_prompt(proj_name, category, history)
                    reply = self._chat_send_to_claude(prompt, model)
                    is_thinking = False
                    history.append({"role": "assistant", "content": reply})

                    # Auto-scroll to bottom
                    chat_lines = self._chat_build_display(history, inner_w)
                    chat_scroll = max(0, len(chat_lines) - chat_h)
                elif ch in (curses.KEY_BACKSPACE, 127, 263):
                    input_buf = input_buf[:-1]
                elif ch == curses.KEY_RESIZE:
                    self._calc_dimensions()
                elif 32 <= ch <= 126:
                    input_buf += chr(ch)
        finally:
            curses.curs_set(0)
            self._rebuild_detail()
            self.draw()

    # ─── Claude Code session ─────────────────────────────────────────

    def _build_claude_context(self, project):
        """Generate CLAUDE.md content for a Claude Code session."""
        name = project.get("name", "Untitled")
        category = project.get("category", "")
        status = project.get("status", "")
        deadline = project.get("deadline", "")
        description = project.get("description", "")
        notes = project.get("notes", "")

        lines = [
            f"# Project: {name}",
            "",
            f"- Category: {category}" if category else None,
            f"- Status: {status}" if status else None,
            f"- Deadline: {deadline}" if deadline else None,
            f"- Today: {today()}",
            "",
        ]
        lines = [l for l in lines if l is not None]

        if description:
            lines += ["## Description", description, ""]
        if notes:
            lines += ["## Notes", notes, ""]

        milestones = project.get("milestones", [])
        if milestones:
            lines.append("## Current Milestones")
            for ms in milestones:
                done = "DONE" if ms.get("done") else "TODO"
                due = f" (due {ms.get('due', '?')})" if ms.get("due") else ""
                lines.append(f"- [{done}] {ms.get('name', '')}{due}")
                for t in ms.get("tasks", []):
                    td = "DONE" if _task_done(t) else "TODO"
                    lines.append(f"  - [{td}] {_task_text(t)}")
            lines.append("")

        tasks = project.get("tasks", [])
        if tasks:
            lines.append("## Current Tasks")
            for t in tasks:
                td = "DONE" if _task_done(t) else "TODO"
                lines.append(f"- [{td}] {_task_text(t)}")
            lines.append("")

        lines += [
            "---",
            "",
            "# Instructions",
            "",
            "You are helping plan this project. Discuss the project with the user,",
            "ask clarifying questions, and help them think through milestones and tasks.",
            "",
            "When the user is satisfied with the plan, write a file called `output.yaml`",
            "in this directory with the following schema:",
            "",
            "```yaml",
            'description: "2-4 sentence project description"',
            "milestones:",
            '  - name: "Milestone Name"',
            '    due: "YYYY-MM-DD"',
            "    tasks:",
            '      - desc: "Task description"',
            '        due: "YYYY-MM-DD"  # optional',
            "tasks:",
            '  - desc: "Standalone task"',
            '    due: "YYYY-MM-DD"  # optional',
            "```",
            "",
            "Rules:",
            "- Only include NEW items (not already listed above)",
            "- Use YYYY-MM-DD format for all dates",
            "- Omit empty sections (e.g. if no milestones, leave out the milestones key)",
            "- description is optional if the project already has a good one",
        ]
        return "\n".join(lines)

    def action_claude_session(self, project=None):
        """Launch an interactive Claude Code session for project planning."""
        if project is None:
            project = self._current_project()
        if not project:
            return

        if not self._modal_confirm("Claude Code",
                                   f"Launch Claude Code for '{project.get('name', '')}'?"):
            return

        tmpdir = tempfile.mkdtemp(prefix="lori_claude_")
        try:
            # Write CLAUDE.md context
            claude_md = os.path.join(tmpdir, "CLAUDE.md")
            with open(claude_md, "w") as f:
                f.write(self._build_claude_context(project))

            # Prepare env without CLAUDECODE to avoid nesting error
            env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

            # Release terminal to Claude Code
            curses.endwin()
            subprocess.call(
                ["claude", "--dangerously-skip-permissions"],
                cwd=tmpdir, env=env)

            # Restore curses
            self.stdscr.refresh()
            curses.curs_set(0)

            # Check for output
            output_path = os.path.join(tmpdir, "output.yaml")
            if os.path.exists(output_path):
                self._process_claude_output(project, output_path)
        finally:
            # Cleanup tmpdir
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
            self._rebuild_detail()
            self.draw()

    def _process_claude_output(self, project, output_path):
        """Parse output.yaml and present review overlay."""
        try:
            with open(output_path) as f:
                data = yaml.safe_load(f)
        except Exception:
            return
        if not data or not isinstance(data, dict):
            return

        items = []  # list of (type_label, description, data_dict, accepted)

        # Description
        desc = data.get("description")
        if desc and isinstance(desc, str):
            items.append(("DESC", desc[:200], {"description": desc}, True))

        # Milestones
        existing_ms_names = {ms.get("name", "").lower()
                             for ms in project.get("milestones", [])}
        for ms in data.get("milestones", []):
            if not isinstance(ms, dict):
                continue
            name = ms.get("name", "")
            if name.lower() in existing_ms_names:
                continue  # skip duplicates
            due = ms.get("due", "")
            tasks = ms.get("tasks", [])
            label = name
            if due:
                label += f" (due {due})"
            if tasks:
                label += f" [{len(tasks)} tasks]"
            items.append(("MILESTONE", label, ms, True))

        # Standalone tasks
        for t in data.get("tasks", []):
            if not isinstance(t, dict):
                continue
            desc_t = t.get("desc", "")
            due = t.get("due", "")
            label = desc_t
            if due:
                label += f" (due {due})"
            items.append(("TASK", label, t, True))

        if not items:
            return

        result = self._claude_review_items(items, project)
        if result is None:
            return

        # Apply accepted items
        self._push_undo()
        for type_label, description, data_dict, accepted in result:
            if not accepted:
                continue
            if type_label == "DESC":
                project["description"] = data_dict["description"]
            elif type_label == "MILESTONE":
                ms_entry = {
                    "name": data_dict.get("name", ""),
                    "done": False,
                }
                if data_dict.get("due"):
                    ms_entry["due"] = data_dict["due"]
                ms_tasks = []
                for t in data_dict.get("tasks", []):
                    if isinstance(t, dict):
                        task_entry = {"desc": t.get("desc", ""), "done": False}
                        if t.get("due"):
                            task_entry["due"] = t["due"]
                        ms_tasks.append(task_entry)
                if ms_tasks:
                    ms_entry["tasks"] = ms_tasks
                project.setdefault("milestones", []).append(ms_entry)
            elif type_label == "TASK":
                task_entry = {"desc": data_dict.get("desc", ""), "done": False}
                if data_dict.get("due"):
                    task_entry["due"] = data_dict["due"]
                project.setdefault("tasks", []).append(task_entry)

        save_projects(self.projects)
        self._rebuild_filtered()
        self._rebuild_detail()

    def _claude_review_items(self, items, project):
        """Interactive review overlay. Returns items with accept/reject, or None."""
        cursor = 0
        scroll = 0
        curses.flushinp()

        while True:
            self.draw()
            self._draw_claude_review(items, cursor, scroll, project)
            self.stdscr.refresh()

            try:
                ch = self.stdscr.getch()
            except curses.error:
                continue

            if ch in (ord("q"), 27):  # q or Esc — cancel
                return None
            elif ch in (ord("j"), curses.KEY_DOWN):
                if cursor < len(items) - 1:
                    cursor += 1
            elif ch in (ord("k"), curses.KEY_UP):
                if cursor > 0:
                    cursor -= 1
            elif ch == ord(" "):  # Space — toggle
                t, d, data, acc = items[cursor]
                items[cursor] = (t, d, data, not acc)
            elif ch in (ord("S"), ord("s")):  # Save/confirm
                return items

            # Scroll management
            h, _ = self.stdscr.getmaxyx()
            visible_h = max(1, h - 10)
            if cursor < scroll:
                scroll = cursor
            if cursor >= scroll + visible_h:
                scroll = cursor - visible_h + 1

    def _draw_claude_review(self, items, cursor, scroll, project):
        """Draw centered review overlay for Claude output items."""
        h, w = self.stdscr.getmaxyx()
        box_w = min(80, w - 4)
        if box_w < 30:
            box_w = w - 2
        inner_w = box_w - 4
        visible_h = max(1, h - 10)
        box_h = visible_h + 5  # title + items + footer + borders

        sy = max(0, (h - box_h) // 2)
        sx = max(0, (w - box_w) // 2)

        # Clear area
        blank = " " * box_w
        for cy in range(sy, min(sy + box_h, h)):
            self._safe_addstr(cy, sx, blank)

        # Title
        proj_name = project.get("name", "")
        title = f" Review: {proj_name} "
        top_bar = "─" * (box_w - 2)
        tl = min(len(title), len(top_bar) - 1)
        top_bar = top_bar[:1] + title[:tl] + top_bar[1 + tl:]
        self._safe_addstr(sy, sx, "┌" + top_bar[:box_w - 2] + "┐")

        # Items
        visible = items[scroll:scroll + visible_h]
        for row_i in range(visible_h):
            y = sy + 1 + row_i
            if y >= h - 1:
                break
            if row_i < len(visible):
                t, desc, _, accepted = visible[row_i]
                idx = scroll + row_i
                is_cur = idx == cursor

                mark = "✓" if accepted else "✗"
                attr = curses.color_pair(C_GREEN) if accepted else curses.color_pair(C_RED)
                if is_cur:
                    attr |= curses.A_REVERSE

                tag = f"[{t:9s}]"
                line = f" {mark} {tag} {desc}"
                line = line[:inner_w].ljust(inner_w)
                self._safe_addstr(y, sx, "│ ", curses.A_REVERSE if is_cur else 0)
                self._safe_addstr(y, sx + 2, line, attr)
                self._safe_addstr(y, sx + box_w - 1, "│",
                                  curses.A_REVERSE if is_cur else 0)
            else:
                self._safe_addstr(y, sx,
                                  "│" + " " * (box_w - 2) + "│")

        # Separator
        sep_y = sy + 1 + visible_h
        if sep_y < h:
            self._safe_addstr(sep_y, sx, "├" + "─" * (box_w - 2) + "┤")

        # Footer
        footer_y = sep_y + 1
        if footer_y < h:
            accepted_count = sum(1 for _, _, _, a in items if a)
            footer = f" Space toggle  S save ({accepted_count}/{len(items)})  q cancel"
            self._safe_addstr(footer_y, sx,
                              "│ " + footer[:inner_w].ljust(inner_w) + "│")

        # Bottom border
        bottom_y = footer_y + 1
        if bottom_y < h:
            self._safe_addstr(bottom_y, sx, "└" + "─" * (box_w - 2) + "┘")

    def action_archive_project(self):
        """Archive a project by changing its status to paused or completed."""
        if self.view_mode != VIEW_PROJECTS:
            return
        proj = self._current_project()
        if not proj:
            return
        choice = self._modal_choice(
            "Archive", proj["name"],
            [("p", "paused"), ("c", "completed")])
        if choice is None:
            return
        status_map = {"p": "paused", "c": "completed"}
        proj["status"] = status_map[choice]
        self._save_and_rebuild()

    def action_delete_project(self):
        """Permanently delete a project."""
        if self.view_mode != VIEW_PROJECTS:
            return
        proj = self._current_project()
        if not proj:
            return
        if not self._modal_confirm("Delete Project",
                                   f"Permanently delete '{proj['name']}'?"):
            return
        self.projects.remove(proj)
        self._save_and_rebuild()

    def action_edit_notes(self):
        proj = self._current_project()
        if not proj:
            return

        current = proj.get("notes", "")
        body = [f"Current: {current}"] if current else None
        new_notes = self._modal_input("Edit Notes", "Notes: ", body)
        if new_notes:
            proj["notes"] = new_notes
            self._save_and_rebuild()

    def _edit_project_field(self, field_name):
        proj = self._current_project()
        if not proj:
            return
        if field_name == "name":
            cur = proj.get("name", "")
            val = self._modal_input("Edit Title", "Title: ", default=cur)
            if val and val != cur:
                proj["name"] = val
                self._save_and_rebuild()
        elif field_name == "category":
            cur = proj.get("category", "")
            val = self._modal_input("Edit Category", "Category: ", default=cur)
            if val and val != cur:
                proj["category"] = val
                self._save_and_rebuild()
        elif field_name == "status":
            choices = [("a", "active"), ("p", "paused"), ("c", "completed")]
            key = self._modal_choice("Edit Status", "Select status:", choices)
            if key:
                status_map = {"a": "active", "p": "paused", "c": "completed"}
                val = status_map[key]
                if val != proj.get("status", "active"):
                    proj["status"] = val
                    self._save_and_rebuild()
        elif field_name == "deadline":
            cur = proj.get("deadline", "")
            val = self._modal_input_date("Edit Deadline", "Deadline (YYYY-MM-DD): ", default=cur)
            if val and val != cur:
                proj["deadline"] = val
                self._save_and_rebuild()
        elif field_name == "description":
            cur = proj.get("description", "")
            body = [f"Current: {cur}"] if cur else None
            val = self._modal_input("Edit Description", "Description: ", body, default=cur)
            if val and val != cur:
                proj["description"] = val
                self._save_and_rebuild()

    # ─── Availability (when2meet) ────────────────────────────────────────

    def action_show_avail(self):
        """Interactive availability grid for when2meet."""
        default_start = self.sched_date.strftime("%Y-%m-%d") if hasattr(self, "sched_date") else ""
        start_str = self._cmd_params.pop("start_date", None) or self._modal_input_date("Availability", "Start date: ",
                                           default=default_start,
                                           body_lines=["Generate availability grid for when2meet."])
        if not start_str:
            return
        start_date = parse_date(start_str)

        end_str = self._cmd_params.pop("end_date", None) or self._modal_input_date("Availability", "End date: ",
                                         default=(start_date + datetime.timedelta(days=4)).strftime("%Y-%m-%d"))
        if not end_str:
            return
        end_date = parse_date(end_str)
        if end_date < start_date:
            self._modal_scroll_text("Error", ["End date is before start date."])
            return

        # Hour range
        config = load_config()
        default_slots = get_work_hours(config)
        default_h_start = min(s for s, e in default_slots)
        default_h_end = max(e for s, e in default_slots)

        h_start_str = self._modal_input("Availability", "Start hour: ",
                                        body_lines=[f"Default: {default_h_start}"],
                                        default=str(default_h_start))
        if not h_start_str:
            return
        h_end_str = self._modal_input("Availability", "End hour: ",
                                      body_lines=[f"Default: {default_h_end}"],
                                      default=str(default_h_end))
        if not h_end_str:
            return
        try:
            hour_start = int(h_start_str)
            hour_end = int(h_end_str)
        except ValueError:
            self._modal_scroll_text("Error", ["Invalid hour value."])
            return

        # Tier selection
        tier_choice = self._modal_choice("Availability Tier",
            "How strict should availability be?",
            [("1", "Ignore blocked time (most available)"),
             ("2", "Include blocked time (default)"),
             ("3", "Add ±30min buffer around events")])
        if tier_choice is None:
            return
        tier = int(tier_choice)

        # Slot size
        slot_min = 30

        # Collect dates
        dates = []
        d = start_date
        while d <= end_date:
            dates.append(d)
            d += datetime.timedelta(days=1)

        events = load_schedule()

        # Build busy filter
        if tier == 1:
            is_busy = lambda ev: ev.get("type") != "blocked"
        else:
            is_busy = lambda ev: True
        buffer_min = 30 if tier == 3 else 0

        # Build per-slot event info and availability
        grid = {}     # grid[date][(h,m)] = list of overlapping events
        avail = {}    # avail[date][(h,m)] = True/False

        for d in dates:
            day_events = expand_events_for_date(events, d)

            # Build busy intervals with buffer
            busy_intervals = []
            for ev in day_events:
                if not is_busy(ev):
                    continue
                ev_start_str = ev.get("start") or ev.get("depart")
                ev_end_str = ev.get("end")
                if not ev_start_str:
                    continue
                es = parse_time(ev_start_str)
                if ev_end_str:
                    ee = parse_time(ev_end_str)
                elif ev.get("type") == "travel":
                    ee = (datetime.datetime.combine(d, es) + datetime.timedelta(minutes=30)).time()
                else:
                    ee = (datetime.datetime.combine(d, es) + datetime.timedelta(hours=1)).time()
                es_dt = datetime.datetime.combine(d, es) - datetime.timedelta(minutes=buffer_min)
                ee_dt = datetime.datetime.combine(d, ee) + datetime.timedelta(minutes=buffer_min)
                busy_intervals.append((es_dt.time(), ee_dt.time()))

            slot_map = {}
            slot_avail = {}
            h, m = hour_start, 0
            while h < hour_end:
                slot_time = datetime.time(h, m)
                slot_end = (datetime.datetime.combine(d, slot_time) + datetime.timedelta(minutes=slot_min)).time()

                # Find overlapping events (for display)
                overlapping = []
                for ev in day_events:
                    ev_s = ev.get("start") or ev.get("depart")
                    ev_e = ev.get("end")
                    if not ev_s:
                        continue
                    es = parse_time(ev_s)
                    if ev_e:
                        ee = parse_time(ev_e)
                    elif ev.get("type") == "travel":
                        ee = (datetime.datetime.combine(d, es) + datetime.timedelta(minutes=30)).time()
                    else:
                        ee = (datetime.datetime.combine(d, es) + datetime.timedelta(hours=1)).time()
                    if es < slot_end and ee > slot_time:
                        overlapping.append(ev)
                slot_map[(h, m)] = overlapping

                # Check busy
                busy = False
                for bs, be in busy_intervals:
                    if bs < slot_end and be > slot_time:
                        busy = True
                        break
                slot_avail[(h, m)] = not busy

                m += slot_min
                if m >= 60:
                    h += m // 60
                    m = m % 60
            grid[d] = slot_map
            avail[d] = slot_avail

        # Build output lines
        tier_names = {1: "ignore blocked", 2: "include blocked", 3: "+30min buffer"}
        lines = []
        lines.append(f"Tier {tier}: {tier_names[tier]}")
        lines.append(f"{fmt_date(start_date)} to {fmt_date(end_date)}, {hour_start}:00-{hour_end}:00, {slot_min}min slots")
        lines.append("")

        # Determine column width based on number of dates
        col_w = max(10, min(14, 60 // max(1, len(dates))))

        header = "Time    " + "".join(d.strftime(" %a %-m/%-d").ljust(col_w) for d in dates)
        lines.append(header)
        lines.append("─" * len(header))

        h, m = hour_start, 0
        while h < hour_end:
            time_label = f"{h:02d}:{m:02d}   "
            cells = []
            for d in dates:
                is_free = avail[d].get((h, m), True)
                if is_free:
                    cells.append(" ✓ FREE".ljust(col_w))
                else:
                    blocking = grid[d].get((h, m), [])
                    blocking = [ev for ev in blocking if is_busy(ev)]
                    if blocking:
                        name = blocking[0].get("title", "busy")
                        if len(name) > col_w - 2:
                            name = name[:col_w - 4] + ".."
                        cells.append(f" {name}".ljust(col_w))
                    else:
                        cells.append(" ~buffer".ljust(col_w))
            lines.append(time_label + "".join(cells))
            m += slot_min
            if m >= 60:
                h += m // 60
                m = m % 60

        lines.append("")
        for d in dates:
            free_count = sum(1 for v in avail[d].values() if v)
            total = len(avail[d])
            free_hrs = free_count * slot_min / 60
            lines.append(f"{d.strftime('%a %-m/%-d')}: {free_count}/{total} slots free ({free_hrs:.1f}h)")

        self._modal_scroll_text("Availability", lines)

    # ─── Command palette ──────────────────────────────────────────────────

    def action_command_palette(self):
        """Open a natural-language command palette (vim-style : prompt)."""
        command = self._modal_input("Command", ": ",
            ['Examples: "add project Research Paper"',
             '"inbox buy groceries"',
             '"switch to calendar"',
             '"mark done"',
             '"add meeting tomorrow 2pm-3pm"'])
        if not command:
            return
        self._show_loading("Parsing command...")
        parsed = self._parse_command(command)
        if not parsed:
            return
        action = parsed.get("action", "")
        params = parsed.get("params", {})
        # Normalize time params to HH:MM
        for key in ("start", "end"):
            if key in params:
                try:
                    params[key] = parse_time(params[key]).strftime("%H:%M")
                except (ValueError, TypeError):
                    pass
        try:
            self._cmd_params = params
            self._dispatch_command(action)
        finally:
            self._cmd_params = {}

    def _parse_command(self, command_text):
        """Use Claude Haiku to parse a natural-language command into action + params."""
        # Gather context
        cur_mode = {0: "tasks", 1: "calendar", 2: "mail"}.get(self.mode, "tasks")
        cur_project = ""
        proj = self._current_project()
        if proj:
            cur_project = proj.get("name", "")
        project_names = [p.get("name", "") for p in self.projects if p.get("status") == "active"]

        prompt = f"""You are a command parser for a project management TUI.
Parse the user's natural language command into a JSON action.

USER COMMAND: {command_text}

CONTEXT:
- Today's date: {today()}
- Current mode: {cur_mode}
- Current project: {cur_project}
- Active projects: {', '.join(project_names)}

AVAILABLE ACTIONS AND EXTRACTABLE PARAMS:
| Action | Params |
|--------|--------|
| add_project | name, category, deadline |
| add_task | desc, due, project |
| add_milestone | name, due, project |
| add_event | title, date, start, end, location |
| mark_done | (uses current selection) |
| delete | (uses current selection) |
| reschedule | date |
| archive_project | (uses current selection) |
| delete_project | (uses current selection) |
| edit_notes | (uses current selection) |
| inbox_add | text |
| switch_calendar | |
| switch_tasks | |
| open_mail | |
| show_avail | start_date, end_date |
| cycle_view | |
| undo | |

RULES:
- Dates should be YYYY-MM-DD format. Resolve relative dates (tomorrow, next monday, etc.) relative to today.
- "inbox <text>" is shorthand for inbox_add with text param.
- Only include params the user actually specified; omit unknown ones.
- For add_task, if the user mentions a project name, include it as "project".
- Return ONLY valid JSON, no markdown fences, no explanation.

OUTPUT FORMAT:
{{"action": "<action_name>", "params": {{...}}}}
"""
        model = self._MODEL_IDS["haiku"]
        raw = self._chat_send_to_claude(prompt, model)
        if not raw or raw.startswith("[Error"):
            self._modal_scroll_text("Error", ["Failed to parse command.", "", raw or ""])
            return None
        # Strip markdown fences if present
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r'^```\w*\n?', '', text)
            text = re.sub(r'\n?```$', '', text)
            text = text.strip()
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if not m:
            self._modal_scroll_text("Error", ["Could not parse response:", "", text])
            return None
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            self._modal_scroll_text("Error", ["Invalid JSON from Claude:", "", text])
            return None

    def _dispatch_command(self, action):
        """Route a parsed command action to the appropriate handler."""
        dispatch = {
            "add_project":      lambda: self.action_add_project(),
            "add_task":         self._cmd_add_task,
            "add_milestone":    self._cmd_add_milestone,
            "add_event":        lambda: self.action_add_event(),
            "mark_done":        lambda: self.action_done(),
            "delete":           lambda: self.action_delete(),
            "reschedule":       lambda: self.action_reschedule(),
            "archive_project":  lambda: self.action_archive_project(),
            "delete_project":   lambda: self.action_delete_project(),
            "edit_notes":       lambda: self.action_edit_notes(),
            "inbox_add":        lambda: self.action_inbox_add(),
            "switch_calendar":  lambda: self._set_mode(MODE_CALENDAR),
            "switch_tasks":     lambda: self._set_mode(MODE_TASKS),
            "open_mail":        lambda: self._enter_mail_mode(),
            "show_avail":       lambda: self.action_show_avail(),
            "cycle_view":       lambda: self._cycle_view(),
            "undo":             lambda: self._pop_undo(),
        }
        handler = dispatch.get(action)
        if handler:
            handler()
        else:
            self._modal_scroll_text("Unknown Action",
                [f"Action '{action}' is not recognized.", "",
                 "Available: " + ", ".join(sorted(dispatch.keys()))])

    def _cmd_add_task(self):
        """Handle add_task from command palette — navigate to project first if specified."""
        project_name = self._cmd_params.pop("project", None)
        if project_name:
            # Try to navigate to the named project
            for i, p in enumerate(self.filtered):
                if p.get("name", "").lower() == project_name.lower():
                    self._set_mode(MODE_TASKS)
                    if self.view_mode != VIEW_PROJECTS:
                        self.view_mode = VIEW_PROJECTS
                        self._rebuild_filtered()
                    self.left_cursor = i
                    self.left_scroll = max(0, i - 5)
                    self._rebuild_detail()
                    break
        # Remap desc → desc for _cmd_params (already correct name)
        self._cmd_params["item_type"] = "t"
        self.action_add_item()

    def _cmd_add_milestone(self):
        """Handle add_milestone from command palette — navigate to project first if specified."""
        project_name = self._cmd_params.pop("project", None)
        if project_name:
            for i, p in enumerate(self.filtered):
                if p.get("name", "").lower() == project_name.lower():
                    self._set_mode(MODE_TASKS)
                    if self.view_mode != VIEW_PROJECTS:
                        self.view_mode = VIEW_PROJECTS
                        self._rebuild_filtered()
                    self.left_cursor = i
                    self.left_scroll = max(0, i - 5)
                    self._rebuild_detail()
                    break
        self._cmd_params["item_type"] = "m"
        self.action_add_item()

    def _set_mode(self, target_mode):
        """Switch to a specific mode without toggling."""
        if target_mode == MODE_MAIL:
            self._enter_mail_mode()
        elif self.mode != target_mode:
            self._toggle_mode()

    # ─── Schedule actions ─────────────────────────────────────────────────

    def action_add_event(self):
        title = self._cmd_params.pop("title", None) or self._modal_input("Add New Event", "Title: ",
            ["Blank at any prompt to cancel."])
        if not title:
            return

        choice = self._modal_input("Add New Event", "Type [1]: ", [
            "Event type:",
            "  1 = one-time    (single date)",
            "  2 = recurring   (weekly/daily)",
            "  3 = travel      (from/to)",
            "  4 = blocked     (unavailable)",
        ]) or "1"

        ev = {"title": title}

        if choice == "2":
            rec = self._modal_input("Recurring Event", "Pattern [1]: ", [
                "Recurrence pattern:",
                "  1 = weekly  (every tuesday, etc.)",
                "  2 = daily   (every day/weekdays)",
                "  3 = monthly (same day or Nth weekday)",
            ]) or "1"
            if rec == "1":
                ev["recurring"] = "weekly"
                days = self._modal_input_days("Recurring Event", "Days: ", [
                    "M T W R F S s  (R=Thu, S=Sat, s=Sun)",
                    "e.g.: MWF  or  monday,wednesday,friday",
                ])
                if not days:
                    return
                day_list = [d.strip() for d in days.split(",") if d.strip()]
                if len(day_list) == 1:
                    ev["day"] = day_list[0]
                else:
                    ev["days"] = day_list
                interval = self._modal_input_int("Recurring Event",
                    "Interval [1]: ", "1", [
                    "Repeat every N weeks",
                    "  1 = every, 2 = every other, etc.",
                ])
                if interval != "1":
                    ev["interval"] = int(interval)
                    ev["start_date"] = self._modal_input_date(
                        "Recurring Event",
                        f"Anchor [{self.sched_date}]: ",
                        str(self.sched_date),
                        ["First occurrence week (YYYY-MM-DD)"],
                    )
            elif rec == "3":
                ev["recurring"] = "monthly"
                self._prompt_monthly_pattern(ev, "Recurring Event")
            else:
                ev["recurring"] = "daily"
                days = self._modal_input_days("Recurring Event",
                    "Days [all]: ", [
                    "M T W R F S s  or 'all'",
                    "e.g.: MWF  or  monday,wednesday,friday",
                ]) or "all"
                if days != "all":
                    ev["days"] = [d.strip() for d in days.split(",")]
            ev["start"] = self._modal_input_time("Recurring Event",
                "Start time (HH:MM): ")
            ev["end"] = self._modal_input_time("Recurring Event",
                "End time (HH:MM): ")
            if not ev["start"] or not ev["end"]:
                return
            loc = self._modal_input("Recurring Event", "Location: ")
            if loc:
                ev["location"] = loc
            tz = self._modal_input("Recurring Event", "Timezone: ", [
                "e.g. America/New_York, Europe/Zurich",
                "Blank for local time.",
            ])
            if tz:
                ev["timezone"] = tz
        elif choice == "3":
            ev["type"] = "travel"
            rec = self._modal_input("Travel Event", "Type [1]: ", [
                "(1) one-time  (2) recurring",
            ]) or "1"
            if rec == "2":
                rec_pat = self._modal_input("Recurring Travel", "Pattern [1]: ", [
                    "Recurrence pattern:",
                    "  1 = weekly  (every tuesday, etc.)",
                    "  2 = daily   (every day/weekdays)",
                    "  3 = monthly (same day or Nth weekday)",
                ]) or "1"
                if rec_pat == "1":
                    ev["recurring"] = "weekly"
                    days = self._modal_input_days("Recurring Travel", "Days: ", [
                        "M T W R F S s  (R=Thu, S=Sat, s=Sun)",
                        "e.g.: MWF  or  monday,wednesday,friday",
                    ])
                    if not days:
                        return
                    day_list = [d.strip() for d in days.split(",") if d.strip()]
                    if len(day_list) == 1:
                        ev["day"] = day_list[0]
                    else:
                        ev["days"] = day_list
                    interval = self._modal_input_int("Recurring Travel",
                        "Interval [1]: ", "1", [
                        "Repeat every N weeks",
                        "  1 = every, 2 = every other, etc.",
                    ])
                    if interval != "1":
                        ev["interval"] = int(interval)
                        ev["start_date"] = self._modal_input_date(
                            "Recurring Travel",
                            f"Anchor [{self.sched_date}]: ",
                            str(self.sched_date),
                            ["First occurrence week (YYYY-MM-DD)"],
                        )
                elif rec_pat == "3":
                    ev["recurring"] = "monthly"
                    self._prompt_monthly_pattern(ev, "Recurring Travel")
                else:
                    ev["recurring"] = "daily"
                    days = self._modal_input_days("Recurring Travel",
                        "Days [all]: ", [
                        "M T W R F S s  or 'all'",
                    ]) or "all"
                    if days != "all":
                        ev["days"] = [d.strip() for d in days.split(",")]
            else:
                ev["date"] = self._modal_input_date("Travel Event",
                    f"Date [{self.sched_date}]: ",
                    str(self.sched_date))
            ev["depart"] = self._modal_input_time("Travel Event",
                "Depart time (HH:MM): ")
            if not ev["depart"]:
                return
            ev["end"] = self._modal_input_time("Travel Event",
                "Arrive time (HH:MM): ")
            ev["from"] = self._modal_input("Travel Event", "From: ")
            ev["to"] = self._modal_input("Travel Event", "To: ")
        elif choice == "4":
            ev["type"] = "blocked"
            rec = self._modal_input("Blocked Time", "Type [1]: ", [
                "(1) one-time  (2) recurring",
            ]) or "1"
            if rec == "2":
                rec_pat = self._modal_input("Blocked Time", "Pattern [1]: ", [
                    "Recurrence pattern:",
                    "  1 = weekly  (every tuesday, etc.)",
                    "  2 = daily   (every day/weekdays)",
                    "  3 = monthly (same day or Nth weekday)",
                ]) or "1"
                if rec_pat == "1":
                    ev["recurring"] = "weekly"
                    days = self._modal_input_days("Blocked Time", "Days: ", [
                        "M T W R F S s  (R=Thu, S=Sat, s=Sun)",
                        "e.g.: MWF  or  monday,wednesday,friday",
                    ])
                    if not days:
                        return
                    day_list = [d.strip() for d in days.split(",") if d.strip()]
                    if len(day_list) == 1:
                        ev["day"] = day_list[0]
                    else:
                        ev["days"] = day_list
                elif rec_pat == "3":
                    ev["recurring"] = "monthly"
                    self._prompt_monthly_pattern(ev, "Blocked Time")
                else:
                    ev["recurring"] = "daily"
                    days = self._modal_input_days("Blocked Time",
                        "Days [all]: ", [
                        "M T W R F S s  or 'all'",
                    ]) or "all"
                    if days != "all":
                        ev["days"] = [d.strip() for d in days.split(",")]
            else:
                ev["date"] = self._modal_input_date("Blocked Time",
                    f"Date [{self.sched_date}]: ",
                    str(self.sched_date))
            ev["start"] = self._modal_input_time("Blocked Time",
                "Start time (HH:MM): ")
            ev["end"] = self._modal_input_time("Blocked Time",
                "End time (HH:MM): ")
            if not ev["start"] or not ev["end"]:
                return
        else:
            ev["date"] = self._cmd_params.pop("date", None) or self._modal_input_date("One-time Event",
                f"Date [{self.sched_date}]: ",
                str(self.sched_date))
            ev["start"] = self._cmd_params.pop("start", None) or self._modal_input_time("One-time Event",
                "Start time (HH:MM): ")
            ev["end"] = self._cmd_params.pop("end", None) or self._modal_input_time("One-time Event",
                "End time (HH:MM): ")
            if not ev["start"] or not ev["end"]:
                return
            loc = self._cmd_params.pop("location", None) or self._modal_input("One-time Event", "Location: ")
            if loc:
                ev["location"] = loc
            tz = self._modal_input("One-time Event", "Timezone: ", [
                "e.g. America/New_York, Europe/Zurich",
                "Blank for local time.",
            ])
            if tz:
                ev["timezone"] = tz

        # Private flag — applies to any event type
        priv = self._modal_input("Add New Event", "Private? [n]: ", [
            "(y) yes  (n) no",
        ]) or "n"
        if priv.lower() in ("y", "yes"):
            ev["private"] = True

        self.schedule.append(ev)
        self._save_schedule_and_rebuild()

    def _prompt_edit_fields(self, target, dlg="Edit Event"):
        """Prompt user to edit fields on target dict. Modifies target in place."""
        # Title
        new_title = self._modal_input(dlg, "Title: ",
            ["Blank to keep current.", f"Current: {target.get('title', '')}"],
            default=target.get("title", ""))
        if new_title:
            target["title"] = new_title

        # Time fields
        if target.get("type") == "travel":
            cur_depart = target.get("depart", "")
            new_depart = self._modal_input_time(dlg, f"Depart [{cur_depart}]: ",
                ["Blank to keep current."])
            if new_depart:
                target["depart"] = new_depart

            cur_end = target.get("end", "")
            new_end = self._modal_input_time(dlg, f"Arrive [{cur_end}]: ",
                ["Blank to keep current."])
            if new_end:
                target["end"] = new_end
        else:
            cur_start = target.get("start", "")
            new_start = self._modal_input_time(dlg, f"Start [{cur_start}]: ",
                ["Blank to keep current."])
            if new_start:
                target["start"] = new_start

            cur_end = target.get("end", "")
            new_end = self._modal_input_time(dlg, f"End [{cur_end}]: ",
                ["Blank to keep current."])
            if new_end:
                target["end"] = new_end

        # Location / travel from-to
        if target.get("type") != "travel":
            cur_loc = target.get("location", "")
            new_loc = self._modal_input(dlg, f"Location [{cur_loc}]: ",
                ["Blank to keep current."], default=cur_loc)
            if new_loc != cur_loc:
                if new_loc:
                    target["location"] = new_loc
                else:
                    target.pop("location", None)
        else:
            cur_from = target.get("from", "")
            new_from = self._modal_input(dlg, f"From [{cur_from}]: ",
                ["Blank to keep current."], default=cur_from)
            if new_from != cur_from and new_from:
                target["from"] = new_from

            cur_to = target.get("to", "")
            new_to = self._modal_input(dlg, f"To [{cur_to}]: ",
                ["Blank to keep current."], default=cur_to)
            if new_to != cur_to and new_to:
                target["to"] = new_to

        # Timezone
        cur_tz = target.get("timezone", "")
        new_tz = self._modal_input(dlg, f"Timezone [{cur_tz}]: ", [
            "e.g. America/New_York, Europe/Zurich",
            "Blank to keep. Type 'none' to remove.",
        ], default=cur_tz)
        if new_tz and new_tz.lower() == "none":
            target.pop("timezone", None)
        elif new_tz and new_tz != cur_tz:
            target["timezone"] = new_tz

        # Private flag
        cur_priv = "y" if target.get("private") else "n"
        new_priv = self._modal_input(dlg, f"Private? [{cur_priv}]: ", [
            "(y) yes  (n) no  (blank to keep)",
        ])
        if new_priv.lower() in ("y", "yes"):
            target["private"] = True
        elif new_priv.lower() in ("n", "no"):
            target.pop("private", None)

    def action_edit_event(self):
        if not self.sched_day_items:
            return
        idx = min(self.left_cursor, len(self.sched_day_items) - 1)
        item = self.sched_day_items[idx]
        if item["kind"] != "event" or not item["event"]:
            return

        ev = item["event"]
        si = self._find_sched_event(ev)
        if si is None:
            return
        sched_ev = self.schedule[si]

        has_dates_list = bool(sched_ev.get("dates"))
        is_multi = bool(sched_ev.get("recurring")) or has_dates_list

        if not is_multi:
            self._prompt_edit_fields(sched_ev)
            self._save_schedule_and_rebuild()
            return

        choice = self._modal_choice(
            "Edit Recurring Event",
            f"Edit '{sched_ev.get('title', '')}'?",
            [("o", "Only this occurrence"),
             ("f", "This and all future"),
             ("a", "All occurrences")])
        if choice is None:
            return

        ev_date = ev.get("date")
        date_str = str(ev_date) if ev_date else None

        if choice == "a":
            # Edit the source entry directly
            self._prompt_edit_fields(sched_ev)

        elif choice == "o":
            # Create a one-time copy, exclude this date from the original
            import copy
            new_ev = copy.deepcopy(sched_ev)
            # Strip recurring fields, make it a one-time event
            for key in ("recurring", "day", "days", "interval", "start_date",
                        "end_date", "except_dates", "dates", "day_of_month",
                        "day_of_week", "week_of_month"):
                new_ev.pop(key, None)
            new_ev["date"] = date_str

            self._prompt_edit_fields(new_ev, "Edit This Occurrence")

            # Exclude this date from original
            if has_dates_list:
                dates = sched_ev.get("dates", [])
                sched_ev["dates"] = [d for d in dates if str(d) != date_str]
                if not sched_ev["dates"]:
                    self.schedule.pop(si)
            else:
                exc = sched_ev.get("except_dates", [])
                if date_str and date_str not in [str(d) for d in exc]:
                    exc.append(date_str)
                    sched_ev["except_dates"] = exc

            self.schedule.append(new_ev)

        elif choice == "f":
            # Split: end original before this date, create new recurring from this date
            import copy
            new_ev = copy.deepcopy(sched_ev)

            if has_dates_list:
                # Split dates list
                future_dates = [d for d in sched_ev.get("dates", [])
                                if str(d) >= date_str]
                past_dates = [d for d in sched_ev.get("dates", [])
                              if str(d) < date_str]
                if past_dates:
                    sched_ev["dates"] = past_dates
                else:
                    self.schedule.pop(si)
                new_ev["dates"] = future_dates
            else:
                # Set end_date on original
                if ev_date:
                    sched_ev["end_date"] = str(ev_date - datetime.timedelta(days=1))
                # New recurring starts from this date
                new_ev.pop("except_dates", None)
                new_ev.pop("end_date", None)
                new_ev["start_date"] = date_str

            self._prompt_edit_fields(new_ev, "Edit Future Events")
            self.schedule.append(new_ev)

        self._save_schedule_and_rebuild()

    def _find_sched_event(self, ev):
        """Find the index of the source schedule entry matching an expanded event."""
        # Use tagged index from expand_events_for_date when available
        idx = ev.get("_sched_idx")
        if idx is not None and 0 <= idx < len(self.schedule):
            sched_ev = self.schedule[idx]
            if sched_ev.get("title") == ev.get("title"):
                return idx
        # Fallback to title/time matching
        ev_date_str = str(ev.get("date")) if ev.get("date") else None
        for i, sched_ev in enumerate(self.schedule):
            if sched_ev.get("title") != ev.get("title"):
                continue
            time_match = (sched_ev.get("start") == ev.get("start") or
                          sched_ev.get("depart") == ev.get("depart"))
            if not time_match:
                continue
            if ev.get("recurring"):
                if sched_ev.get("recurring") == ev.get("recurring"):
                    return i
            elif sched_ev.get("dates"):
                # Custom dates list — match by title + time (already checked)
                return i
            else:
                sched_date_str = str(sched_ev.get("date")) if sched_ev.get("date") else None
                if sched_date_str == ev_date_str:
                    return i
        return None

    def _get_current_sched_event(self):
        """Return the event dict for the currently selected schedule item, or None."""
        if self.view_mode == VIEW_SCHED_DAY:
            if not self.sched_day_items:
                return None
            idx = min(self.left_cursor, len(self.sched_day_items) - 1)
            item = self.sched_day_items[idx]
            if item["kind"] != "event" or not item["event"]:
                return None
            return item["event"]
        elif self.view_mode == VIEW_SCHED_WEEK:
            if not self.sched_week_data:
                return None
            idx = min(self.left_cursor, len(self.sched_week_data) - 1)
            events = self.sched_week_data[idx]["events"]
            if not events:
                return None
            ei = min(self.week_event_cursor, len(events) - 1)
            return events[ei]
        elif self.view_mode == VIEW_SCHED_NDAY:
            if not self.sched_nday_data:
                return None
            idx = min(self.left_cursor, len(self.sched_nday_data) - 1)
            events = self.sched_nday_data[idx]["events"]
            if not events:
                return None
            ei = min(self.nday_event_cursor, len(events) - 1)
            return events[ei]
        return None

    def action_open_location(self):
        """Show location URL as a full-width overlay line, then try to open in browser."""
        import re
        ev = self._get_current_sched_event()
        if not ev:
            return
        loc = ev.get("location") or ""
        match = re.search(r'https?://\S+', loc)
        if not match:
            return
        url = match.group(0)

        # Show overlay: full-width URL on a centered line (terminal-clickable)
        curses.flushinp()
        self.draw()
        h, w = self.stdscr.getmaxyx()
        cy = h // 2
        blank = " " * (w - 1)
        for dy in (-1, 0, 1, 2):
            if 0 <= cy + dy < h:
                self._safe_addstr(cy + dy, 0, blank)
        self._safe_addstr(cy - 1, 1, "Location URL (press any key):", curses.A_DIM)
        # Write URL — let terminal detect it as clickable
        try:
            self.stdscr.addstr(cy, 1, url, curses.A_BOLD | curses.color_pair(C_CYAN))
        except curses.error:
            pass
        self._safe_addstr(cy + 1, 1, "(opening in browser...)", curses.A_DIM)
        self.stdscr.refresh()

        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass

        self.stdscr.getch()

    def action_delete_event(self):
        if not self.sched_day_items:
            return
        idx = min(self.left_cursor, len(self.sched_day_items) - 1)
        item = self.sched_day_items[idx]
        if item["kind"] != "event" or not item["event"]:
            return

        ev = item["event"]
        title = ev.get("title", "???")

        # Determine if this is a multi-occurrence event
        si = self._find_sched_event(ev)
        has_dates_list = si is not None and bool(self.schedule[si].get("dates"))
        is_multi = bool(ev.get("recurring")) or has_dates_list

        if is_multi:
            choice = self._modal_choice(
                "Delete Recurring Event",
                f"Delete '{title}'?",
                [("o", "Only this occurrence"),
                 ("f", "This and all future"),
                 ("a", "All occurrences")])
            if choice is None:
                return

            if si is None:
                return
            sched_ev = self.schedule[si]
            ev_date = ev.get("date")
            date_str = str(ev_date) if ev_date else None

            if choice == "o":
                if has_dates_list:
                    # Remove this date from the dates list
                    dates = sched_ev.get("dates", [])
                    dates = [d for d in dates if str(d) != date_str]
                    if dates:
                        sched_ev["dates"] = dates
                    else:
                        self.schedule.pop(si)
                else:
                    # Add this date to except_dates
                    exc = sched_ev.get("except_dates", [])
                    if date_str and date_str not in [str(d) for d in exc]:
                        exc.append(date_str)
                        sched_ev["except_dates"] = exc
            elif choice == "f":
                if has_dates_list:
                    # Remove this date and all future from the dates list
                    dates = sched_ev.get("dates", [])
                    dates = [d for d in dates
                             if str(d) < date_str]
                    if dates:
                        sched_ev["dates"] = dates
                    else:
                        self.schedule.pop(si)
                else:
                    # Set an end_date on the recurring event (day before this one)
                    if ev_date:
                        end = ev_date - datetime.timedelta(days=1)
                        sched_ev["end_date"] = str(end)
            elif choice == "a":
                self.schedule.pop(si)
        else:
            if not self._modal_confirm("Delete Event", f"Delete '{title}'?"):
                return
            if si is not None:
                self.schedule.pop(si)

        self._save_schedule_and_rebuild()

    def action_copy_event(self):
        """Copy the currently selected event to the clipboard."""
        ev = self._get_current_sched_event()
        if not ev:
            return
        si = self._find_sched_event(ev)
        if si is None:
            return
        sched_ev = self.schedule[si]

        has_dates_list = bool(sched_ev.get("dates"))
        is_multi = bool(sched_ev.get("recurring")) or has_dates_list

        if is_multi:
            choice = self._modal_choice(
                "Copy Event",
                f"Copy '{sched_ev.get('title', '')}'?",
                [("o", "Only this occurrence"),
                 ("a", "All occurrences")])
            if choice is None:
                return
            if choice == "o":
                new_ev = copy.deepcopy(sched_ev)
                for key in ("recurring", "day", "days", "interval", "start_date",
                            "end_date", "except_dates", "dates", "day_of_month",
                            "day_of_week", "week_of_month"):
                    new_ev.pop(key, None)
                new_ev["date"] = str(ev.get("date")) if ev.get("date") else None
                self.clipboard_event = new_ev
                self.clipboard_mode = "one"
            else:
                self.clipboard_event = copy.deepcopy(sched_ev)
                self.clipboard_mode = "all"
        else:
            self.clipboard_event = copy.deepcopy(sched_ev)
            self.clipboard_mode = "one"

    def action_paste_event(self, target_date=None):
        """Paste the clipboard event onto the target date."""
        if self.clipboard_event is None:
            return
        new_ev = copy.deepcopy(self.clipboard_event)
        if target_date is None:
            target_date = self.sched_date

        day_names = ["monday", "tuesday", "wednesday", "thursday",
                     "friday", "saturday", "sunday"]
        target_day = day_names[target_date.weekday()]

        if self.clipboard_mode == "one":
            new_ev["date"] = str(target_date)
        elif self.clipboard_mode == "all":
            rec = new_ev.get("recurring")
            if rec == "weekly":
                if "days" in new_ev:
                    new_ev["days"] = [target_day]
                elif "day" in new_ev:
                    new_ev["day"] = target_day
                else:
                    new_ev["day"] = target_day
            elif rec == "monthly":
                if new_ev.get("day_of_week"):
                    new_ev["day_of_week"] = target_day
                    # Compute week_of_month from target date
                    new_ev["week_of_month"] = (target_date.day - 1) // 7 + 1
                elif "day_of_month" in new_ev:
                    new_ev["day_of_month"] = target_date.day
            # daily: no day change needed

            new_ev.pop("except_dates", None)
            new_ev.pop("end_date", None)
            new_ev["start_date"] = str(target_date)
            new_ev.pop("date", None)

        self.schedule.append(new_ev)
        self._save_schedule_and_rebuild()

    # ─── Timeline actions ──────────────────────────────────────────────────

    def _current_timeline_entry(self):
        if not self.timeline_items or self.left_cursor >= len(self.timeline_items):
            return None
        return self.timeline_items[self.left_cursor]

    def _timeline_action_done(self):
        entry = self._current_timeline_entry()
        if not entry:
            return
        kind = entry.get("kind", "milestone")
        if kind == "milestone":
            ms = entry["milestone"]
            if ms.get("done"):
                ms.pop("done", None)
                ms.pop("completed_date", None)
            else:
                ms["done"] = True
                ms["completed_date"] = str(today())
        else:
            t = entry["task"]
            t_dict = _task_to_dict(t)
            if _task_done(t_dict):
                t_dict.pop("done", None)
                t_dict.pop("completed_date", None)
            else:
                t_dict["done"] = True
                t_dict["completed_date"] = str(today())
            # Replace in-place if it was promoted from string
            if kind == "ms_task":
                ms = entry["milestone"]
                ms["tasks"][entry["task_index"]] = t_dict
            else:
                proj = entry["project"]
                proj["tasks"][entry["task_index"]] = t_dict
        self._save_and_rebuild()

    def _timeline_action_undone(self):
        entry = self._current_timeline_entry()
        if not entry:
            return
        ms = entry["milestone"]
        if not ms.get("done"):
            return
        ms.pop("done", None)
        ms.pop("completed_date", None)
        self._save_and_rebuild()

    def _timeline_action_delete(self):
        entry = self._current_timeline_entry()
        if not entry:
            return
        kind = entry.get("kind", "milestone")
        if kind == "milestone":
            name = entry["milestone"].get("name", "")
            if not self._modal_confirm("Delete", f"Delete milestone '{name}'?"):
                return
            entry["project"]["milestones"].pop(entry["ms_index"])
        elif kind == "ms_task":
            desc = _task_text(entry["task"])
            if not self._modal_confirm("Delete", f"Delete task '{desc}'?"):
                return
            entry["milestone"]["tasks"].pop(entry["task_index"])
        else:
            desc = _task_text(entry["task"])
            if not self._modal_confirm("Delete", f"Delete task '{desc}'?"):
                return
            entry["project"]["tasks"].pop(entry["task_index"])
        self._save_and_rebuild()

    def _timeline_action_reschedule(self):
        entry = self._current_timeline_entry()
        if not entry:
            return
        kind = entry.get("kind", "milestone")
        if kind == "milestone":
            ms = entry["milestone"]
            if ms.get("done"):
                return
            label = f"Milestone: {ms['name']}"
            current_due = ms.get("due", "none")
            new_date_str = self._modal_input("Reschedule",
                f"New date ({current_due}): ", [label])
            if not new_date_str:
                return
            try:
                new_date = parse_date(new_date_str)
            except ValueError:
                return
            ms["due"] = str(new_date)
        else:
            t = entry["task"]
            t_dict = _task_to_dict(t)
            if _task_done(t_dict):
                return
            label = f"Task: {_task_text(t_dict)}"
            current_due = t_dict.get("due", "none")
            new_date_str = self._modal_input("Reschedule",
                f"New date ({current_due}): ", [label])
            if not new_date_str:
                return
            try:
                new_date = parse_date(new_date_str)
            except ValueError:
                return
            t_dict["due"] = str(new_date)
            if kind == "ms_task":
                entry["milestone"]["tasks"][entry["task_index"]] = t_dict
            else:
                entry["project"]["tasks"][entry["task_index"]] = t_dict
        self._save_and_rebuild()

    # ─── Mail integration ──────────────────────────────────────────────────

    _MAIL_CACHE_DIR = os.path.join(os.path.expanduser("~/.lori"), "mail_cache")

    def _mail_load_disk_cache(self):
        """Load cached email list and body cache from disk."""
        list_path = os.path.join(self._MAIL_CACHE_DIR, "list.json")
        if os.path.exists(list_path):
            try:
                with open(list_path) as f:
                    self._mail_disk_cache = {e["uid"]: e for e in json.load(f)}
            except (json.JSONDecodeError, KeyError):
                self._mail_disk_cache = {}
        else:
            self._mail_disk_cache = {}
        # Load cached bodies
        body_dir = os.path.join(self._MAIL_CACHE_DIR, "bodies")
        if os.path.isdir(body_dir):
            for fname in os.listdir(body_dir):
                if fname.endswith(".txt"):
                    uid = fname[:-4]
                    if uid not in self._mail_body_cache:
                        try:
                            with open(os.path.join(body_dir, fname)) as f:
                                self._mail_body_cache[uid] = f.read()
                        except OSError:
                            pass

    def _mail_save_disk_cache(self):
        """Persist email list and new bodies to disk."""
        os.makedirs(self._MAIL_CACHE_DIR, exist_ok=True)
        with open(os.path.join(self._MAIL_CACHE_DIR, "list.json"), "w") as f:
            json.dump(self.mail_emails, f)
        body_dir = os.path.join(self._MAIL_CACHE_DIR, "bodies")
        os.makedirs(body_dir, exist_ok=True)
        for uid, body in self._mail_body_cache.items():
            path = os.path.join(body_dir, f"{uid}.txt")
            if not os.path.exists(path):
                with open(path, "w") as f:
                    f.write(body)

    def _mail_rebuild_threads(self):
        """Rebuild mail_threads from mail_emails based on current mode."""
        if self.mail_threaded:
            self.mail_threads = _build_mail_threads(self.mail_emails)
        else:
            # Flat mode: each email is its own "thread"
            self.mail_threads = []
            for em in self.mail_emails:
                frm = em.get("from", "")
                if "<" in frm:
                    frm = frm.split("<")[0].strip().strip('"')
                self.mail_threads.append({
                    "subject": em.get("subject", "") or "(no subject)",
                    "norm_subject": _normalize_subject(em.get("subject", "")),
                    "emails": [em],
                    "uids": {em["uid"]},
                    "latest_date": em.get("date", ""),
                    "unread_count": 0 if em.get("isRead", True) else 1,
                    "from_summary": frm or em.get("from", ""),
                })
        self._mail_build_display_rows()

    def _mail_build_display_rows(self):
        """Build flat display rows list from mail_threads (thread + email rows)."""
        if not self.mail_threaded:
            self._mail_display_rows = []
            return
        rows = []
        for i, thread in enumerate(self.mail_threads):
            rows.append({"type": "thread", "thread_idx": i, "thread": thread})
            if i in self._mail_expanded and len(thread["emails"]) > 1:
                emails_rev = list(reversed(thread["emails"]))
                for j, em in enumerate(emails_rev):
                    rows.append({"type": "email", "thread_idx": i, "email": em,
                                 "pos": j, "total": len(emails_rev)})
        self._mail_display_rows = rows

    def _mail_connect(self):
        """Lazy IMAP connect / reconnect."""
        if self.mail_imap:
            try:
                self.mail_imap.socket().settimeout(10)
                self.mail_imap.noop()
                return
            except Exception:
                self.mail_imap = None
        self._show_loading("Connecting to mail server...")
        try:
            cache = get_token_cache()
            token, username = authenticate(cache)
            save_token_cache(cache)
            self.mail_imap = connect_imap(token, username)
        except Exception as e:
            self.mail_imap = None
            self._modal_input("Connection Error",
                              "Could not connect to mail server.",
                              [str(e)[:60], "", "Press Enter to dismiss."])
            raise

    def _mail_fetch_body_with_retry(self, uid, auto=False):
        """Fetch an email body, retrying once on connection failure.
        Returns body text or None on failure. Caches to disk on success."""
        for attempt in range(2):
            try:
                self._mail_connect()
                body = fetch_email_body(self.mail_imap, uid)
                self._mail_body_cache[uid] = body
                body_dir = os.path.join(self._MAIL_CACHE_DIR, "bodies")
                os.makedirs(body_dir, exist_ok=True)
                try:
                    with open(os.path.join(body_dir, f"{uid}.txt"), "w") as f:
                        f.write(body)
                except OSError:
                    pass
                return body
            except Exception:
                self.mail_imap = None
                if attempt == 0:
                    continue
                if not auto:
                    self._modal_input("Error",
                                      "Could not load email body.",
                                      ["Connection lost. Retry failed.",
                                       "Press Enter."])
                return None

    def _mail_fetch_list(self):
        try:
            self._mail_connect()
        except Exception:
            return
        # Load disk cache if first time
        if not hasattr(self, "_mail_disk_cache"):
            self._mail_load_disk_cache()

        try:
            self._show_loading("Checking for new emails...")
            current_uids = search_uids(self.mail_imap,
                                       unread=self.mail_unread_filter, top=100)
        except Exception:
            self.mail_imap = None
            self._modal_input("Error", "Lost connection while fetching.",
                              ["Will use cached emails.", "Press Enter."])
            # Fall back to disk cache
            cached = self._mail_disk_cache
            if cached:
                uids = sorted(cached.keys(), key=lambda u: int(u), reverse=True)
                self.mail_emails = [cached[u] for u in uids]
                self._mail_loaded_count = len(self.mail_emails)
                self._mail_rebuild_threads()
            return

        cached = self._mail_disk_cache
        new_uids = [u for u in current_uids if u not in cached]

        if new_uids:
            try:
                n = len(new_uids)
                new_emails = fetch_email_list(
                    self.mail_imap, only_uids=new_uids,
                    on_progress=lambda cur, tot: self._show_loading(
                        f"Fetching {n} new emails...", progress=(cur, tot)))
                for e in new_emails:
                    cached[e["uid"]] = e
            except Exception:
                self.mail_imap = None

        # Build ordered list from current UIDs
        self.mail_emails = [cached[u] for u in current_uids if u in cached]
        self._mail_loaded_count = len(self.mail_emails)
        # Only prune stale cache entries when showing all mail (not filtered)
        if not self.mail_unread_filter:
            current_set = set(current_uids)
            self._mail_disk_cache = {u: e for u, e in cached.items()
                                     if u in current_set}
        self._mail_save_disk_cache()
        self._mail_rebuild_threads()

    def _mail_load_more(self):
        """Fetch 10 older emails and append to the list."""
        if not self.mail_emails:
            return
        self._mail_connect()
        self._show_loading("Loading more emails...")
        older = fetch_email_list(
            self.mail_imap, unread=self.mail_unread_filter, top=10,
            skip=self._mail_loaded_count,
            on_progress=lambda cur, tot: self._show_loading(
                "Loading more...", progress=(cur, tot)))
        if older:
            self.mail_emails.extend(older)
            self._mail_loaded_count += len(older)
            if hasattr(self, "_mail_disk_cache"):
                for e in older:
                    self._mail_disk_cache[e["uid"]] = e
                self._mail_save_disk_cache()
            self._mail_rebuild_threads()

    def _mail_build_body_lines(self, em, body):
        """Build mail_body_lines with a compact header block + wrapped body."""
        wrap_w = max(10, self.right_w - 1)
        lines = []

        # Header block
        subj = _sanitize_text(em.get("subject", "(no subject)"))
        frm = _sanitize_text(em.get("from", ""))
        to = _sanitize_text(em.get("to", ""))
        cc = _sanitize_text(em.get("cc", ""))
        date = self._mail_format_date(em.get("date", ""))

        lines.append(f"Subject: {subj}")
        lines.append(f"From: {frm}")
        if to:
            lines.append(f"To: {to}")
        if cc:
            lines.append(f"Cc: {cc}")
        lines.append(f"Date: {date}")
        lines.append("─" * wrap_w)
        lines.append("")

        # Wrap body; in processed mode collapse runs of blank lines to at most 1
        blank_run = 0
        for raw_line in _sanitize_text(body).splitlines():
            stripped = raw_line.strip()
            if not stripped:
                blank_run += 1
                if self._mail_raw_mode or blank_run <= 1:
                    lines.append("")
                continue
            blank_run = 0
            while _str_width(raw_line) > wrap_w:
                chunk = _wc_truncate(raw_line, wrap_w)
                lines.append(chunk)
                raw_line = raw_line[len(chunk):]
            lines.append(raw_line)

        self.mail_body_lines = lines
        self.mail_body_uid = em["uid"]
        self.mail_body_scroll = 0

    def _mail_open(self, auto=False):
        if not self.mail_emails:
            return
        em = self.mail_emails[self.left_cursor]
        uid = em["uid"]

        # If already showing this email's conversation view, just refocus
        conv_uids = {e["uid"] for e in self._conv_emails} if self._conv_emails else set()
        if conv_uids == {uid} and self.mail_body_uid == "__conv__":
            if not auto:
                self.focus = RIGHT
            return

        # Set up single-email conversation view
        self._conv_emails = [em]
        self._conv_collapsed = set()
        self._conv_quotes_shown = set()
        self._conv_pos = 0

        # Fetch body
        if uid not in self._mail_body_cache:
            if not auto:
                self._show_loading("Loading email...")
            body = self._mail_fetch_body_with_retry(uid, auto)
            if body is None:
                return
            self._mail_body_cache[uid] = body
            body_dir = os.path.join(self._MAIL_CACHE_DIR, "bodies")
            os.makedirs(body_dir, exist_ok=True)
            try:
                with open(os.path.join(body_dir, f"{uid}.txt"), "w") as f:
                    f.write(body)
            except OSError:
                pass

        self._mail_build_conversation_lines()
        self.mail_body_scroll = 0
        self.mail_body_uid = "__conv__"

        # Mark email as read
        if not em.get("isRead", True):
            try:
                self._mail_connect()
                self.mail_imap.select("INBOX", readonly=False)
                set_flag(self.mail_imap, em["uid"], "\\Seen", enable=True)
                self.mail_imap.select("INBOX", readonly=True)
                em["isRead"] = True
            except Exception:
                pass

        if not auto:
            self.focus = RIGHT

    def _mail_open_thread(self, auto=False):
        """Open the current thread: fetch all bodies, build conversation view."""
        if not self.mail_threads:
            return
        idx = self.left_cursor
        if idx >= len(self.mail_threads):
            return
        if idx == self.mail_thread_body_idx:
            if not auto:
                self.focus = RIGHT
            return

        thread = self.mail_threads[idx]
        if not auto:
            self._show_loading("Loading conversation...")

        # Fetch bodies for all emails in thread
        bodies = []
        for em in thread["emails"]:
            uid = em["uid"]
            if uid in self._mail_body_cache:
                bodies.append((em, self._mail_body_cache[uid]))
            else:
                body = self._mail_fetch_body_with_retry(uid, auto)
                if body is None:
                    return
                bodies.append((em, body))

        # Build conversation lines
        lines = []
        wrap_w = max(10, self.right_w - 1)
        for i, (em, body) in enumerate(bodies):
            # Separator
            frm = em.get("from", "")
            if "<" in frm:
                frm = frm.split("<")[0].strip().strip('"') or frm
            date = em.get("date", "")
            for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%d %b %Y %H:%M:%S %z",
                        "%a, %d %b %Y %H:%M:%S %Z"):
                try:
                    from datetime import datetime as _dt
                    dt = _dt.strptime(date.strip(), fmt)
                    date = dt.strftime("%b %d %H:%M")
                    break
                except (ValueError, TypeError):
                    continue
            else:
                date = date[:16]
            sep = f"─── {frm} | {date} "
            # Pad with ─ to fill width
            sep += "─" * max(0, wrap_w - len(sep))
            lines.append(sep)
            lines.append("")
            for raw_line in body.splitlines():
                while len(raw_line) > wrap_w:
                    lines.append(raw_line[:wrap_w])
                    raw_line = raw_line[wrap_w:]
                lines.append(raw_line)
            if i < len(bodies) - 1:
                lines.append("")

        self.mail_thread_body_lines = lines
        self.mail_thread_body_scroll = 0
        self.mail_thread_body_idx = idx

        # Mark all emails in thread as read
        for em in thread["emails"]:
            if not em.get("isRead", True):
                try:
                    self._mail_connect()
                    self.mail_imap.select("INBOX", readonly=False)
                    set_flag(self.mail_imap, em["uid"], "\\Seen", enable=True)
                    self.mail_imap.select("INBOX", readonly=True)
                    em["isRead"] = True
                except Exception:
                    pass
        thread["unread_count"] = 0

        if not auto:
            self.focus = RIGHT

    @staticmethod
    def _mail_strip_quotes(body):
        """Split email body into (main_text, quoted_text)."""
        lines = body.splitlines()
        cut = len(lines)
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Lines starting with '>'
            if stripped.startswith(">"):
                cut = i
                break
            # "On ... wrote:" pattern
            if stripped.startswith("On ") and stripped.endswith("wrote:"):
                cut = i
                break
            # "From: ... Sent:" or similar forwarding headers
            if stripped.startswith("From:") and i > 0:
                cut = i
                break
            if stripped.startswith("-----Original Message-----"):
                cut = i
                break
            if stripped.startswith("_" * 10):
                cut = i
                break
        main = "\n".join(lines[:cut]).rstrip()
        quoted = "\n".join(lines[cut:]).rstrip()
        return main, quoted

    def _mail_open_conversation(self, thread_idx, auto=False, focus_email_uid=None):
        """Open a thread as a conversation view in the right panel."""
        if thread_idx >= len(self.mail_threads):
            return
        thread = self.mail_threads[thread_idx]
        if not thread["emails"]:
            return

        # If already showing this thread's conversation, just refocus
        thread_uids = {e["uid"] for e in thread["emails"]}
        conv_uids = {e["uid"] for e in self._conv_emails} if self._conv_emails else set()
        if thread_uids == conv_uids and self.mail_body_uid == "__conv__":
            if focus_email_uid:
                for i, em in enumerate(self._conv_emails):
                    if em["uid"] == focus_email_uid:
                        self._conv_pos = i
                        self._conv_collapsed.discard(i)
                        self._mail_build_conversation_lines()
                        self._mail_scroll_to_conv_pos()
                        break
            if not auto:
                self.focus = RIGHT
            return

        # Build conversation email list (newest first)
        self._conv_emails = list(reversed(thread["emails"]))

        # Auto-collapse if >5 emails
        self._conv_collapsed = set()
        if len(self._conv_emails) > 5:
            self._conv_collapsed = set(range(1, len(self._conv_emails)))

        self._conv_quotes_shown = set()

        # Determine focused position
        self._conv_pos = 0
        if focus_email_uid:
            for i, em in enumerate(self._conv_emails):
                if em["uid"] == focus_email_uid:
                    self._conv_pos = i
                    self._conv_collapsed.discard(i)
                    break

        # Fetch bodies for all emails
        if not auto:
            self._show_loading("Loading conversation...",
                               progress=(0, len(self._conv_emails)))
        for idx, em in enumerate(self._conv_emails):
            uid = em["uid"]
            if uid not in self._mail_body_cache:
                body = self._mail_fetch_body_with_retry(uid, auto)
                if body is None:
                    return
            if not auto:
                self._show_loading("Loading conversation...",
                                   progress=(idx + 1, len(self._conv_emails)))

        # Build the conversation lines
        self._mail_build_conversation_lines()
        self.mail_body_scroll = 0
        self._mail_scroll_to_conv_pos()

        # Mark all emails as read
        for em in thread["emails"]:
            if not em.get("isRead", True):
                try:
                    self._mail_connect()
                    self.mail_imap.select("INBOX", readonly=False)
                    set_flag(self.mail_imap, em["uid"], "\\Seen", enable=True)
                    self.mail_imap.select("INBOX", readonly=True)
                    em["isRead"] = True
                except Exception:
                    pass
        thread["unread_count"] = 0

        # Set body UID to a sentinel so single-email logic doesn't interfere
        self.mail_body_uid = "__conv__"

        if not auto:
            self.focus = RIGHT

    def _mail_build_conversation_lines(self):
        """Build mail_body_lines and _conv_line_map from _conv_emails."""
        lines = []
        line_map = []
        box_w = max(14, self.right_w - 2)  # leave room for panel border
        wrap_w = max(6, box_w - 4)          # 2 for "│ " left + 2 for " │" right

        def _box_line(content, lpad="│ ", rpad=" │"):
            """Build a box content line: lpad + content padded to wrap_w + rpad, truncated to box_w."""
            cw = _str_width(content)
            if cw > wrap_w:
                content = _wc_truncate(content, wrap_w)
                cw = _str_width(content)
            s = lpad + content + " " * max(0, wrap_w - cw) + rpad
            return _wc_truncate(s, box_w)

        def _wrap_text(text, ww):
            """Wrap text to ww display columns, returning list of strings."""
            result = []
            for raw_line in _sanitize_text(text).splitlines():
                stripped = raw_line.strip()
                if not stripped:
                    result.append("")
                    continue
                while _str_width(raw_line) > ww:
                    chunk = _wc_truncate(raw_line, ww)
                    result.append(chunk)
                    raw_line = raw_line[len(chunk):]
                result.append(raw_line)
            return result

        for i, em in enumerate(self._conv_emails):
            # Parse from/date for box header
            frm = _sanitize_text(em.get("from", "")).replace("\n", " ")
            if "<" in frm:
                display_name = frm.split("<")[0].strip().strip('"')
                email_addr = frm.split("<")[-1].rstrip(">").strip()
                if display_name:
                    header_from = f"{display_name} ({email_addr})"
                else:
                    header_from = email_addr
            else:
                header_from = frm
            date = self._mail_format_date(em.get("date", ""))

            # Build top border with from/date label — truncate name to keep date visible
            date_part = f" · {date} "
            date_part_w = _str_width(date_part)
            max_label_w = box_w - 4  # reserve "╭─" + "─" + "╮"
            name_part = f" {header_from}"
            name_budget = max_label_w - date_part_w
            if name_budget >= 4:
                # Enough room for truncated name + date
                if _str_width(name_part) > name_budget:
                    name_part = _wc_truncate(name_part, name_budget - 1) + "…"
                label = name_part + date_part
            else:
                # Too narrow — just show what fits
                label = f" {header_from} · {date} "
            if _str_width(label) > max_label_w:
                label = _wc_truncate(label, max_label_w - 1) + "…"
            label_w = _str_width(label)
            fill = max(0, box_w - 3 - label_w)
            top = "╭─" + label + "─" * fill + "╮"
            top = _wc_truncate(top, box_w)
            bot = _wc_truncate("╰" + "─" * max(0, box_w - 2) + "╯", box_w)

            if i in self._conv_collapsed:
                # Collapsed: two-line box
                lines.append(top)
                line_map.append((i, "collapsed_top"))
                lines.append(bot)
                line_map.append((i, "collapsed_bot"))
            else:
                # Expanded box — top
                lines.append(top)
                line_map.append((i, "box_top"))

                # Header lines inside box (collapse newlines from RFC header folding)
                to = _sanitize_text(em.get("to", "")).replace("\n", " ")
                cc = _sanitize_text(em.get("cc", "")).replace("\n", " ")
                email_subj = _sanitize_text(em.get("subject", "(no subject)")).replace("\n", " ")
                hdr_lines = [f"Subject: {email_subj}", f"From: {frm}"]
                if to:
                    hdr_lines.append(f"To: {to}")
                if cc:
                    hdr_lines.append(f"Cc: {cc}")
                hdr_lines.append(f"Date: {date}")
                for hl in hdr_lines:
                    lines.append(_box_line(_wc_truncate(hl, wrap_w)))
                    line_map.append((i, "header"))

                # Separator + blank padding line
                sep = _wc_truncate("│" + "─" * max(0, box_w - 2) + "│", box_w)
                lines.append(sep)
                line_map.append((i, "separator"))
                lines.append(_box_line(""))
                line_map.append((i, "body"))

                # Body text
                uid = em["uid"]
                body = self._mail_body_cache.get(uid, "")
                main_text, quoted_text = self._mail_strip_quotes(body)
                main_text, main_links = _shorten_urls(main_text)

                # Wrap and add main body lines
                blank_run = 0
                for wline in _wrap_text(main_text, wrap_w):
                    if not wline.strip():
                        blank_run += 1
                        if self._mail_raw_mode or blank_run <= 1:
                            lines.append(_box_line(""))
                            line_map.append((i, "body"))
                        continue
                    blank_run = 0
                    lines.append(_box_line(wline))
                    line_map.append((i, "body"))

                # Links footnote section
                if main_links:
                    lines.append(_box_line(""))
                    line_map.append((i, "body"))
                    lines.append(_box_line("─" * min(20, wrap_w)))
                    line_map.append((i, "separator"))
                    for li, url in enumerate(main_links, 1):
                        for chunk in _wrap_text(f"[{li}] {url}", wrap_w):
                            lines.append(_box_line(chunk))
                            line_map.append((i, "body"))

                # Quoted text handling
                if quoted_text.strip():
                    if i in self._conv_quotes_shown:
                        blank_run = 0
                        for wline in _wrap_text(quoted_text, wrap_w):
                            if not wline.strip():
                                blank_run += 1
                                if self._mail_raw_mode or blank_run <= 1:
                                    lines.append(_box_line(""))
                                    line_map.append((i, "quote"))
                                continue
                            blank_run = 0
                            lines.append(_box_line(wline))
                            line_map.append((i, "quote"))
                    else:
                        hint = "··· quoted text hidden (o to show) ···"
                        lines.append(_box_line(_wc_truncate(hint, wrap_w)))
                        line_map.append((i, "quote_hidden"))

                # Blank padding + bottom border
                lines.append(_box_line(""))
                line_map.append((i, "body"))
                bot = "╰" + "─" * max(0, box_w - 2) + "╯"
                lines.append(bot[:box_w])
                line_map.append((i, "box_bot"))

            # Spacer between emails
            if i < len(self._conv_emails) - 1:
                lines.append("")
                line_map.append((i, "spacer"))

        self.mail_body_lines = lines
        self._conv_line_map = line_map

    def _mail_scroll_to_conv_pos(self):
        """Scroll to make the focused email visible."""
        for li, (idx, ltype) in enumerate(self._conv_line_map):
            if idx == self._conv_pos:
                self.mail_body_scroll = li
                return

    def _mail_sync_left_to_conv(self):
        """Move the left panel cursor to match the current conversation email."""
        if not self._conv_emails or not self._mail_display_rows:
            return
        if self._conv_pos >= len(self._conv_emails):
            return
        target_uid = self._conv_emails[self._conv_pos]["uid"]
        for i, row in enumerate(self._mail_display_rows):
            if row["type"] == "email" and row["email"]["uid"] == target_uid:
                self.left_cursor = i
                # Adjust scroll to keep cursor visible
                if self.left_cursor < self.left_scroll:
                    self.left_scroll = self.left_cursor
                elif self.left_cursor >= self.left_scroll + self.content_h:
                    self.left_scroll = self.left_cursor - self.content_h + 1
                return

    def _mail_open_current_row(self, auto=False):
        """Open the email for the current display row (threaded mode)."""
        if not self._mail_display_rows:
            return
        if self.left_cursor >= len(self._mail_display_rows):
            return
        row = self._mail_display_rows[self.left_cursor]

        # Delegate all threads (single or multi-email) to conversation view
        tidx = row["thread_idx"]
        if tidx < len(self.mail_threads):
            focus_uid = row["email"]["uid"] if row["type"] == "email" else None
            self._mail_open_conversation(tidx, auto=auto, focus_email_uid=focus_uid)
            return

        if not auto:
            self.focus = RIGHT

    def _mail_current_thread_idx(self):
        """Get the thread index for the current cursor in threaded mode."""
        if not self._mail_display_rows:
            return None
        if self.left_cursor >= len(self._mail_display_rows):
            return None
        return self._mail_display_rows[self.left_cursor]["thread_idx"]

    def _mail_target_uids(self):
        """Return set of UIDs from selected threads or current thread."""
        if not self.mail_threads:
            return set()
        if self.mail_selected:
            uids = set()
            for tidx in self.mail_selected:
                if 0 <= tidx < len(self.mail_threads):
                    uids |= self.mail_threads[tidx]["uids"]
            return uids
        if self.mail_threaded:
            tidx = self._mail_current_thread_idx()
            if tidx is not None and 0 <= tidx < len(self.mail_threads):
                return set(self.mail_threads[tidx]["uids"])
            return set()
        if self.left_cursor < len(self.mail_threads):
            return set(self.mail_threads[self.left_cursor]["uids"])
        return set()

    def _mail_mark_pending_body(self):
        """Mark that the body pane needs loading after the user stops scrolling."""
        if self.mail_threaded and self._mail_display_rows:
            if self.left_cursor < len(self._mail_display_rows):
                row = self._mail_display_rows[self.left_cursor]
                tidx = row["thread_idx"]
                # Check if we're already showing the right thread
                if tidx < len(self.mail_threads):
                    thread_uids = set(self.mail_threads[tidx]["uids"])
                    conv_uids = {e["uid"] for e in self._conv_emails} if self._conv_emails else set()
                    if thread_uids != conv_uids or self.mail_body_uid != "__conv__":
                        self.mail_body_lines = []
                        self.mail_body_uid = None
                        self._conv_emails = []
                        self._conv_line_map = []
                        self._mail_body_pending = True
        elif self.mail_emails:
            uid = self.mail_emails[self.left_cursor]["uid"]
            conv_uids = {e["uid"] for e in self._conv_emails} if self._conv_emails else set()
            if conv_uids != {uid}:
                self.mail_body_lines = []
                self.mail_body_uid = None
                self._conv_emails = []
                self._conv_line_map = []
                self._mail_body_pending = True

    def _mail_idle_load(self):
        """Called when getch times out — load the body for the current email."""
        self._mail_body_pending = False
        if self.mail_threaded and self._mail_display_rows:
            self._mail_open_current_row(auto=True)
        elif self.mail_emails:
            self._mail_open(auto=True)

    def _mail_resize_left(self, delta):
        """Adjust mail left pane width by delta columns."""
        self._mail_left_w_offset += delta
        self._calc_dimensions()
        # Re-wrap body lines for new right_w
        if self._conv_emails:
            self._mail_build_conversation_lines()
        elif self.mail_body_uid:
            self.mail_body_uid = None  # force re-wrap on next open
        if self.mail_thread_body_idx is not None:
            self.mail_thread_body_idx = None  # force re-wrap on next open

    def _mail_toggle_seen(self):
        if self.mail_threaded:
            tidx = self._mail_current_thread_idx()
            if tidx is None or tidx >= len(self.mail_threads):
                return
            thread = self.mail_threads[tidx]
            # Toggle: if any unread, mark all read; else mark all unread
            mark_read = thread["unread_count"] > 0
            self._show_loading("Updating flags...")
            self._mail_connect()
            self.mail_imap.select("INBOX", readonly=False)
            for em in thread["emails"]:
                set_flag(self.mail_imap, em["uid"], "\\Seen", enable=mark_read)
                em["isRead"] = mark_read
            self.mail_imap.select("INBOX", readonly=True)
            thread["unread_count"] = 0 if mark_read else len(thread["emails"])
        else:
            if not self.mail_emails:
                return
            em = self.mail_emails[self.left_cursor]
            self._show_loading("Updating flag...")
            self._mail_connect()
            self.mail_imap.select("INBOX", readonly=False)
            set_flag(self.mail_imap, em["uid"], "\\Seen", enable=not em["isRead"])
            self.mail_imap.select("INBOX", readonly=True)
            em["isRead"] = not em["isRead"]

    def _mail_toggle_flag(self):
        """Toggle \\Flagged (star) on current email or thread."""
        if self.mail_threaded:
            tidx = self._mail_current_thread_idx()
            if tidx is None or tidx >= len(self.mail_threads):
                return
            thread = self.mail_threads[tidx]
            # Toggle: if any flagged, unflag all; else flag all
            any_flagged = any(e.get("isFlagged") for e in thread["emails"])
            new_flag = not any_flagged
            self._show_loading("Updating flag...")
            self._mail_connect()
            self.mail_imap.select("INBOX", readonly=False)
            for em in thread["emails"]:
                set_flag(self.mail_imap, em["uid"], "\\Flagged", enable=new_flag)
                em["isFlagged"] = new_flag
            self.mail_imap.select("INBOX", readonly=True)
        else:
            if not self.mail_emails:
                return
            em = self.mail_emails[self.left_cursor]
            new_flag = not em.get("isFlagged", False)
            self._show_loading("Updating flag...")
            self._mail_connect()
            self.mail_imap.select("INBOX", readonly=False)
            set_flag(self.mail_imap, em["uid"], "\\Flagged", enable=new_flag)
            self.mail_imap.select("INBOX", readonly=True)
            em["isFlagged"] = new_flag

    def _mail_delete(self):
        """Delete selected emails/threads (or current if none selected)."""
        if self.mail_threaded:
            target_uids = self._mail_target_uids()
        else:
            target_uids = {em["uid"] for em in self.mail_emails if em["uid"] in self.mail_selected}
            if not target_uids:
                if self.mail_emails and self.left_cursor < len(self.mail_emails):
                    target_uids = {self.mail_emails[self.left_cursor]["uid"]}
        if not target_uids:
            return
        n = len(target_uids)
        choice = self._modal_choice("Delete", f"Delete {n} email(s)?",
                                    [("y", "Yes"), ("n", "No")])
        if choice != "y":
            return
        self._show_loading(f"Deleting {n} email(s)...")
        self._mail_connect()
        self.mail_imap.select("INBOX", readonly=False)
        for uid in target_uids:
            set_flag(self.mail_imap, uid, "\\Deleted")
        self.mail_imap.expunge()
        self.mail_imap.select("INBOX", readonly=True)
        self.mail_emails = [em for em in self.mail_emails if em["uid"] not in target_uids]
        self.mail_selected.clear()
        if self.mail_body_uid in target_uids:
            self.mail_body_uid = None
            self.mail_body_lines = []
            self._conv_emails = []
            self._conv_line_map = []
        self.mail_thread_body_lines = []
        self.mail_thread_body_idx = None
        self._mail_expanded.clear()
        self._mail_rebuild_threads()
        n_items = len(self._mail_display_rows) if self.mail_threaded else len(self.mail_emails)
        self.left_cursor = min(self.left_cursor, max(0, n_items - 1))
        # Auto-load the now-selected email/thread into the right panel
        if n_items > 0:
            self._mail_body_pending = True

    def _mail_archive(self):
        """Archive selected emails/threads (or current if none selected)."""
        if self.mail_threaded:
            target_uids = self._mail_target_uids()
        else:
            target_uids = {em["uid"] for em in self.mail_emails if em["uid"] in self.mail_selected}
            if not target_uids:
                if self.mail_emails and self.left_cursor < len(self.mail_emails):
                    target_uids = {self.mail_emails[self.left_cursor]["uid"]}
        if not target_uids:
            return
        n = len(target_uids)
        choice = self._modal_choice("Archive", f"Archive {n} email(s)?",
                                    [("y", "Yes"), ("n", "No")])
        if choice != "y":
            return
        self._show_loading(f"Archiving {n} email(s)...")
        self._mail_connect()
        self.mail_imap.select("INBOX", readonly=False)
        for uid in target_uids:
            uid_bytes = uid.encode() if isinstance(uid, str) else uid
            self.mail_imap.uid("copy", uid_bytes, "Archive")
            set_flag(self.mail_imap, uid, "\\Deleted")
        self.mail_imap.expunge()
        self.mail_imap.select("INBOX", readonly=True)
        self.mail_emails = [em for em in self.mail_emails if em["uid"] not in target_uids]
        self.mail_selected.clear()
        if self.mail_body_uid in target_uids:
            self.mail_body_uid = None
            self.mail_body_lines = []
            self._conv_emails = []
            self._conv_line_map = []
        self.mail_thread_body_lines = []
        self.mail_thread_body_idx = None
        self._mail_expanded.clear()
        self._mail_rebuild_threads()
        n_items = len(self._mail_display_rows) if self.mail_threaded else len(self.mail_emails)
        self.left_cursor = min(self.left_cursor, max(0, n_items - 1))
        # Auto-load the now-selected email/thread into the right panel
        if n_items > 0:
            self._mail_body_pending = True

    def _mail_scroll_list(self, delta):
        items = self._mail_display_rows if self.mail_threaded else self.mail_emails
        if not items:
            return
        self.left_cursor = max(0, min(len(items) - 1, self.left_cursor + delta))
        if self.left_cursor < self.left_scroll:
            self.left_scroll = self.left_cursor
        elif self.left_cursor >= self.left_scroll + self.content_h:
            self.left_scroll = self.left_cursor - self.content_h + 1

    def _mail_search(self):
        """Prompt for search query and jump to first match."""
        query = self._modal_input("Search Mail", "Search: ")
        if not query:
            return
        self._mail_search_query = query.lower()
        self._mail_search_next(0)

    def _mail_search_next(self, start, direction=1):
        """Jump to next item matching the search query from start index."""
        q = self._mail_search_query
        if self.mail_threaded:
            items = self._mail_display_rows
        else:
            items = self.mail_emails
        if not q or not items:
            return
        n = len(items)
        for i in range(n):
            idx = (start + i * direction) % n
            if self.mail_threaded:
                row = items[idx]
                if row["type"] == "thread":
                    subj = row["thread"].get("subject", "").lower()
                    frm = row["thread"].get("from_summary", "").lower()
                else:
                    subj = row["email"].get("subject", "").lower()
                    frm = row["email"].get("from", "").lower()
            else:
                em = items[idx]
                subj = em.get("subject", "").lower()
                frm = em.get("from", "").lower()
            if q in subj or q in frm:
                self.left_cursor = idx
                if self.left_cursor < self.left_scroll:
                    self.left_scroll = self.left_cursor
                elif self.left_cursor >= self.left_scroll + self.content_h:
                    self.left_scroll = self.left_cursor - self.content_h + 1
                self._mail_mark_pending_body()
                return

    def _draw_left_panel_mail(self):
        if self.mail_threaded:
            self._draw_left_panel_mail_threaded()
        else:
            self._draw_left_panel_mail_flat()

    def _mail_format_date(self, raw_date):
        """Parse a raw email date string into a short display form."""
        for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%d %b %Y %H:%M:%S %z",
                    "%a, %d %b %Y %H:%M:%S %Z"):
            try:
                from datetime import datetime as _dt
                dt = _dt.strptime(raw_date.strip(), fmt)
                return dt.strftime("%m/%d %H:%M")
            except (ValueError, TypeError):
                continue
        return raw_date[:11]

    def _draw_left_panel_mail_threaded(self):
        if not self._mail_display_rows:
            self._safe_addstr(1, 1, "No emails.".ljust(self.left_w), curses.A_DIM)
            self._safe_addstr(2, 1, "Press 'r' to refresh.".ljust(self.left_w), curses.A_DIM)
            return

        display_w = min(self.left_w, self.max_x - 3)

        for i in range(self.content_h):
            idx = self.left_scroll + i
            if idx >= len(self._mail_display_rows):
                break
            y = i + 1
            row = self._mail_display_rows[idx]
            is_cursor = (idx == self.left_cursor)
            tidx = row["thread_idx"]
            is_sel_marked = tidx in self.mail_selected

            if row["type"] == "thread":
                thread = row["thread"]
                count = len(thread["emails"])

                # Status indicators
                if is_sel_marked:
                    dot = "[*]"
                elif thread["unread_count"] > 0:
                    dot = "● "
                else:
                    dot = "  "

                # Star indicator
                has_flag = any(e.get("isFlagged") for e in thread["emails"])
                star = "★ " if has_flag else "  "

                # Expand indicator
                if count > 1:
                    arrow = "▼ " if tidx in self._mail_expanded else "▶ "
                else:
                    arrow = "  "

                frm = _sanitize_text(thread["from_summary"]).replace("\n", " ")
                date = self._mail_format_date(thread["latest_date"])
                subj = _sanitize_text(thread["subject"] or "(no subject)").replace("\n", " ")
                if count > 1:
                    subj = f"{subj} ({count})"

                avail = self.left_w - 2
                prefix = dot + star + arrow
                prefix_w = _str_width(prefix)
                date_w = _str_width(date)
                from_w = min(15, max(8, avail // 4))
                subj_w = avail - prefix_w - from_w - 1 - date_w - 1
                if subj_w < 5:
                    subj_w = avail - prefix_w - date_w - 1
                    from_w = 0
                subj_w = max(0, subj_w)

                line = prefix + _wc_ljust(_wc_truncate(subj, subj_w), subj_w)
                if from_w > 0:
                    line += " " + _wc_ljust(_wc_truncate(frm, from_w), from_w)
                line += " " + date

                attr = 0
                if self.focus == LEFT:
                    if is_cursor:
                        attr = curses.A_REVERSE | curses.color_pair(C_BLUE)
                    if is_sel_marked and not is_cursor:
                        attr |= curses.color_pair(C_CYAN)
                    elif is_sel_marked and is_cursor:
                        attr = curses.color_pair(C_CYAN) | curses.A_REVERSE
                    if thread["unread_count"] > 0:
                        attr |= curses.A_BOLD
                else:
                    # Right panel focused — dim non-cursor items
                    if is_cursor:
                        attr = curses.A_BOLD
                    elif is_sel_marked:
                        attr = curses.color_pair(C_CYAN)
                    else:
                        attr = curses.A_DIM
                    if thread["unread_count"] > 0 and not is_cursor:
                        attr |= curses.A_BOLD

                self._safe_addstr(y, 1, _wc_ljust(_wc_truncate(line, display_w), display_w), attr, max_n=display_w)

            else:  # email row
                em = row["email"]
                pos, total = row["pos"], row["total"]
                connector = "└ " if pos == total - 1 else "├ "

                if is_sel_marked:
                    dot = "[*]"
                elif not em.get("isRead", True):
                    dot = "● "
                else:
                    dot = "  "

                star = "★ " if em.get("isFlagged") else "  "

                frm = _sanitize_text(em.get("from", "")).replace("\n", " ")
                if "<" in frm:
                    frm = frm.split("<")[0].strip().strip('"') or frm
                date = self._mail_format_date(em.get("date", ""))

                avail = self.left_w - 2
                prefix = "   " + connector + dot + star
                prefix_w = _str_width(prefix)
                date_w = _str_width(date)
                name_w = max(0, avail - prefix_w - date_w - 1)

                line = prefix
                line += _wc_ljust(_wc_truncate(frm, name_w), name_w)
                line += " " + date

                if self.focus == LEFT:
                    attr = curses.A_DIM
                    if is_cursor:
                        attr = curses.A_REVERSE | curses.color_pair(C_BLUE)
                    if is_sel_marked and not is_cursor:
                        attr = curses.color_pair(C_CYAN) | curses.A_DIM
                    elif is_sel_marked and is_cursor:
                        attr = curses.color_pair(C_CYAN) | curses.A_REVERSE
                    if not em.get("isRead", True):
                        attr |= curses.A_BOLD
                else:
                    # Right panel focused — dim non-cursor items
                    if is_cursor:
                        attr = curses.A_BOLD
                    elif is_sel_marked:
                        attr = curses.color_pair(C_CYAN)
                    else:
                        attr = curses.A_DIM

                self._safe_addstr(y, 1, _wc_ljust(_wc_truncate(line, display_w), display_w), attr, max_n=display_w)

    def _draw_left_panel_mail_flat(self):
        if not self.mail_emails:
            self._safe_addstr(1, 1, "No emails.".ljust(self.left_w), curses.A_DIM)
            self._safe_addstr(2, 1, "Press 'r' to refresh.".ljust(self.left_w), curses.A_DIM)
            return

        for i in range(self.content_h):
            idx = self.left_scroll + i
            if idx >= len(self.mail_emails):
                break
            y = i + 1
            em = self.mail_emails[idx]

            is_sel = em["uid"] in self.mail_selected
            if is_sel:
                dot = "[*]"
            elif not em["isRead"]:
                dot = "● "
            else:
                dot = "  "

            star = "★ " if em.get("isFlagged") else "  "

            frm = _sanitize_text(em["from"]).replace("\n", " ")
            if "<" in frm:
                frm = frm.split("<")[0].strip().strip('"')
            if not frm:
                frm = _sanitize_text(em["from"]).replace("\n", " ")

            date = em["date"]
            for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%d %b %Y %H:%M:%S %z",
                        "%a, %d %b %Y %H:%M:%S %Z"):
                try:
                    from datetime import datetime as _dt
                    dt = _dt.strptime(date.strip(), fmt)
                    date = dt.strftime("%m/%d %H:%M")
                    break
                except (ValueError, ImportError):
                    continue
            else:
                date = date[:11]

            subj = _sanitize_text(em["subject"] or "(no subject)").replace("\n", " ")

            display_w = min(self.left_w, self.max_x - 3)
            avail = self.left_w - 2
            prefix = dot + star
            prefix_w = _str_width(prefix)
            date_w = _str_width(date)
            from_w = min(15, max(8, avail // 4))
            subj_w = avail - prefix_w - from_w - 1 - date_w - 1
            if subj_w < 5:
                subj_w = avail - prefix_w - date_w - 1
                from_w = 0
            subj_w = max(0, subj_w)

            line = prefix
            line += _wc_ljust(_wc_truncate(subj, subj_w), subj_w)
            if from_w > 0:
                line += " " + _wc_ljust(_wc_truncate(frm, from_w), from_w)
            line += " " + date

            is_selected = (idx == self.left_cursor)
            is_sel_marked = em["uid"] in self.mail_selected
            if self.focus == LEFT:
                attr = 0
                if is_selected:
                    attr = curses.A_REVERSE | curses.color_pair(C_BLUE)
                if is_sel_marked and not is_selected:
                    attr |= curses.color_pair(C_CYAN)
                elif is_sel_marked and is_selected:
                    attr = curses.color_pair(C_CYAN) | curses.A_REVERSE
                if not em["isRead"]:
                    attr |= curses.A_BOLD
            else:
                # Right panel focused — dim non-cursor items
                if is_selected:
                    attr = curses.A_BOLD
                elif is_sel_marked:
                    attr = curses.color_pair(C_CYAN)
                else:
                    attr = curses.A_DIM
                if not em["isRead"] and not is_selected:
                    attr |= curses.A_BOLD

            self._safe_addstr(y, 1, _wc_ljust(_wc_truncate(line, display_w), display_w), attr, max_n=display_w)

    def _mail_extract_items(self):
        """Use Claude CLI to extract tasks and events from selected emails."""
        import os
        import re

        if not self.mail_selected:
            return
        model = self._get_claude_model()
        if model is None:
            return

        self._show_loading("Extracting tasks & events with Claude...")

        today_str = str(today())
        all_tasks = []
        all_events = []
        # Strip CLAUDECODE env var to avoid nesting error
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

        # Build project context for LLM
        proj_ctx_lines = []
        for p in self.projects:
            if p.get("status") != "active":
                continue
            pname = p.get("name", "")
            pdesc = p.get("description", "")
            ms_list = [m["name"] for m in p.get("milestones", []) if not m.get("done")]
            parts = []
            if pdesc:
                parts.append(f"desc: {pdesc[:150]}")
            if ms_list:
                parts.append(f"milestones: {', '.join(ms_list)}")
            if parts:
                proj_ctx_lines.append(f"  - {pname} ({'; '.join(parts)})")
            else:
                proj_ctx_lines.append(f"  - {pname}")
        proj_ctx = "\n".join(proj_ctx_lines) if proj_ctx_lines else "  (none)"

        # Derive UIDs from thread selections when threaded
        if self.mail_threaded:
            target_uids = self._mail_target_uids()
        else:
            target_uids = set(self.mail_selected)

        # Collect all email content into a single prompt for one Claude call
        email_sections = []
        n_emails = 0
        for em in self.mail_emails:
            if em["uid"] not in target_uids:
                continue
            n_emails += 1
            self._show_loading(f"Loading email bodies ({n_emails})...")
            self._mail_connect()
            body = self._mail_body_cache.get(em["uid"])
            if not body:
                try:
                    body = fetch_email_body(self.mail_imap, em["uid"])
                    self._mail_body_cache[em["uid"]] = body
                except Exception:
                    body = ""
            preview = body[:2000] if body else ""
            email_sections.append(
                f"--- Email {n_emails} ---\n"
                f"Subject: {em['subject']}\n"
                f"From: {em['from']}\n"
                f"Date: {em.get('date', '')}\n\n"
                f"{preview}"
            )

        if not email_sections:
            return

        combined = "\n\n".join(email_sections)
        # Cap total input to avoid excessive token usage
        combined = combined[:12000]

        prompt = (
            f"{combined}\n\n"
            f"Extract action items and calendar events from the above email(s).\n"
            f"Today's date is {today_str}.\n\n"
            f"Active projects:\n{proj_ctx}\n\n"
            f"Output format (one item per line):\n"
            f"TASK|description|YYYY-MM-DD|project_name|milestone_name\n"
            f"TASK|description|YYYY-MM-DD|project_name|\n"
            f"TASK|description||project_name|\n"
            f"TASK|description|||\n"
            f"EVENT|title|YYYY-MM-DD|HH:MM|HH:MM|location\n"
            f"EVENT|title|YYYY-MM-DD|HH:MM|HH:MM|\n\n"
            f"Rules:\n"
            f"- TASK = something someone needs to do\n"
            f"- EVENT = something happening at a specific date/time (meeting, call, deadline)\n"
            f"- Resolve relative dates (\"next Tuesday\") relative to today\n"
            f"- If event has no clear time, use 09:00-10:00\n"
            f"- Assign each TASK to the most relevant project from the list above\n"
            f"- Use project descriptions to determine the best match\n"
            f"- If a project has milestones, assign the task to the best-fitting milestone\n"
            f"- If no project fits, leave project_name and milestone_name empty\n"
            f"- Deduplicate: if the same action is mentioned across emails, emit it once\n"
            f"- If no actionable items, return NONE"
        )

        self._show_loading(f"Extracting from {n_emails} email(s) with Claude...")

        try:
            result = subprocess.run(
                ["claude", "-p", "--model", model],
                input=prompt, capture_output=True, text=True, timeout=180,
                env=env,
            )
            text = result.stdout.strip()
            if text and text.upper() != "NONE":
                for line in text.splitlines():
                    line = line.strip()
                    if not line or line.upper() == "NONE":
                        continue
                    if line.startswith("```"):
                        continue
                    parts = line.split("|")
                    if len(parts) >= 2 and parts[0].strip().upper() == "TASK":
                        desc = parts[1].strip()
                        due = parts[2].strip() if len(parts) > 2 else ""
                        proj = parts[3].strip() if len(parts) > 3 else ""
                        ms = parts[4].strip() if len(parts) > 4 else ""
                        if desc:
                            all_tasks.append({"desc": desc, "due": due,
                                              "project": proj, "milestone": ms})
                    elif len(parts) >= 4 and parts[0].strip().upper() == "EVENT":
                        title = parts[1].strip()
                        date_s = parts[2].strip()
                        start_s = parts[3].strip() if len(parts) > 3 else "09:00"
                        end_s = parts[4].strip() if len(parts) > 4 else "10:00"
                        loc = parts[5].strip() if len(parts) > 5 else ""
                        if title and date_s:
                            ev = {
                                "title": title,
                                "date": date_s,
                                "start": start_s or "09:00",
                                "end": end_s or "10:00",
                            }
                            if loc:
                                ev["location"] = loc
                            all_events.append(ev)
                    else:
                        # Fallback: old line-by-line task parsing
                        line = re.sub(r"^[\d]+[.)]\s*", "", line)
                        line = line.lstrip("-•* ")
                        if line and line.upper() != "NONE":
                            all_tasks.append(line)
        except Exception:
            pass

        if not all_tasks and not all_events:
            self._modal_input("Info", "No items found", ["No actionable items extracted."])
            self.mail_selected.clear()
            return

        # Build review items
        review_items = []
        for t in all_tasks:
            if isinstance(t, dict):
                proj_name = t.get("project", "") or "Inbox"
                review_items.append({"type": "task", "desc": t.get("desc", str(t)),
                                     "due": t.get("due", ""), "project": proj_name,
                                     "milestone": t.get("milestone", ""),
                                     "accepted": True})
            else:
                review_items.append({"type": "task", "desc": str(t),
                                     "due": "", "project": "Inbox",
                                     "milestone": "",
                                     "accepted": True})
        for ev in all_events:
            review_items.append({"type": "event", "title": ev.get("title", ""),
                                 "date": ev.get("date", ""),
                                 "start": ev.get("start", "09:00"),
                                 "end": ev.get("end", "10:00"),
                                 "location": ev.get("location", ""),
                                 "recurring": ev.get("days", ""),
                                 "accepted": True})

        accepted = self._mail_review_items(review_items)
        if accepted is None:
            return

        acc_tasks = [it for it in accepted if it["type"] == "task"]
        acc_events = [it for it in accepted if it["type"] == "event"]

        # Store tasks grouped by project
        if acc_tasks:
            for it in acc_tasks:
                proj_name = it.get("project", "Inbox")
                ms_name = it.get("milestone", "")
                if proj_name.lower() == "inbox":
                    target = self._get_or_create_inbox()
                else:
                    target = None
                    for p in self.projects:
                        if p.get("name", "").lower() == proj_name.lower():
                            target = p
                            break
                    if not target:
                        target = self._get_or_create_inbox()
                task_obj = {"desc": it["desc"]} if it["due"] else it["desc"]
                if it["due"]:
                    task_obj["due"] = it["due"]
                # Place under milestone if specified
                placed = False
                if ms_name:
                    for ms in target.get("milestones", []):
                        if ms.get("name", "").lower() == ms_name.lower():
                            ms.setdefault("tasks", []).append(task_obj)
                            placed = True
                            break
                if not placed:
                    target.setdefault("tasks", []).append(task_obj)

        # Store events in schedule
        if acc_events:
            for it in acc_events:
                ev = {"title": it["title"], "date": it["date"],
                      "start": it["start"], "end": it["end"]}
                if it["location"]:
                    ev["location"] = it["location"]
                if it["recurring"]:
                    ev["days"] = it["recurring"]
                self.schedule.append(ev)
            save_schedule(self.schedule)

        self._save_and_rebuild()
        self.mail_selected.clear()

    def _mail_review_items(self, items):
        """Interactive review overlay. Returns list of accepted items, or None on cancel."""
        if not items:
            return None
        cursor = 0
        self._review_scroll = 0
        curses.flushinp()

        while True:
            self._draw_review_overlay(items, cursor)
            try:
                ch = self.stdscr.getch()
            except curses.error:
                continue

            if ch == curses.KEY_RESIZE:
                self._calc_dimensions()
                continue
            elif ch == 27:  # Esc — cancel
                return None
            elif ch in (ord("j"), curses.KEY_DOWN):
                cursor = min(cursor + 1, len(items) - 1)
            elif ch in (ord("k"), curses.KEY_UP):
                cursor = max(cursor - 1, 0)
            elif ch == ord("a"):
                items[cursor]["accepted"] = True
                if cursor < len(items) - 1:
                    cursor += 1
            elif ch == ord("x"):
                items[cursor]["accepted"] = False
                if cursor < len(items) - 1:
                    cursor += 1
            elif ch == ord("q"):
                return None
            elif ch == ord("S"):
                return [it for it in items if it["accepted"]]
            else:
                self._review_handle_field_edit(ch, items[cursor])

    def _draw_review_overlay(self, items, cursor):
        """Render a two-pane review overlay: left=item list, right=detail."""
        h, w = self.stdscr.getmaxyx()

        it = items[cursor]
        is_task = it["type"] == "task"

        # ── Geometry ──
        box_w = max(60, w - 4)
        box_h = max(12, h - 4)
        sy = max(0, (h - box_h) // 2)
        sx = max(0, (w - box_w) // 2)
        inner_w = box_w - 2          # inside the outer │…│
        left_w = max(20, inner_w * 35 // 100)
        right_w = inner_w - left_w - 1  # -1 for divider │
        content_h = box_h - 4        # top border, content rows, footer sep, footer, bottom border

        # ── Clear overlay area ──
        blank_line = " " * box_w
        for cy in range(sy, min(sy + box_h, h)):
            self._safe_addstr(cy, sx, blank_line)

        # ── Top border with divider tee ──
        title = f" Review Extracted Items ({len(items)} items) "
        top = "┌─" + title
        remaining = box_w - 2 - 1 - len(title)  # -2 for ┌└, -1 for ┐
        div_pos = left_w + 1  # position of ┬ relative to inside (after ┌)
        # Build top border character by character
        top_bar = list("─" * (box_w - 2))
        # Place title
        for i, ch in enumerate(title):
            if 1 + i < len(top_bar):
                top_bar[1 + i] = ch
        # Place ┬ at divider
        if div_pos < len(top_bar):
            top_bar[div_pos] = "┬"
        self._safe_addstr(sy, sx, "┌" + "".join(top_bar) + "┐")

        # ── Build left-pane display entries (with optional divider) ──
        left_entries = []  # ("item", idx) or ("divider", None)
        num_tasks = sum(1 for it in items if it["type"] == "task")
        has_divider = 0 < num_tasks < len(items)
        for i in range(len(items)):
            if has_divider and i == num_tasks:
                left_entries.append(("divider", None))
            left_entries.append(("item", i))
        total_display = len(left_entries)

        # Find cursor's display row
        cursor_display = 0
        for di, (et, ei) in enumerate(left_entries):
            if et == "item" and ei == cursor:
                cursor_display = di
                break

        # ── Scroll tracking for left pane ──
        scroll = getattr(self, "_review_scroll", 0)
        if cursor_display < scroll:
            scroll = cursor_display
        elif cursor_display >= scroll + content_h:
            scroll = cursor_display - content_h + 1
        scroll = max(0, min(scroll, max(0, total_display - content_h)))
        self._review_scroll = scroll

        # ── Build right-pane detail lines ──
        rlines = []
        mark = "✓" if it["accepted"] else "✗"
        kind = "TASK" if is_task else "EVENT"
        title_text = it.get("desc", "") if is_task else it.get("title", "")
        max_title = right_w - 12
        rlines.append(("header", f" {mark} {kind}  \"{title_text[:max_title]}\""))
        rlines.append(("normal", ""))

        if is_task:
            due_str = it.get("due", "") or "(none)"
            ms_str = it.get("milestone", "") or "(none)"
            rlines.append(("normal", f"     Due: {due_str}"))
            rlines.append(("normal", f"     Project: [{it.get('project', 'Inbox')}]"))
            rlines.append(("normal", f"     Milestone: {ms_str}"))
            rlines.append(("normal", ""))
            rlines.append(("normal", " " + "─" * (right_w - 2)))
            rlines.append(("normal", " Fields:"))
            rlines.append(("normal", f"   [d] Description: {it.get('desc', '')[:right_w - 22]}"))
            rlines.append(("normal", f"   [u] Due date:    {due_str}"))
            rlines.append(("normal", f"   [p] Project:     {it.get('project', 'Inbox')}"))
            rlines.append(("normal", f"   [m] Milestone:   {ms_str}"))
        else:
            rlines.append(("normal", f"     Date: {it.get('date', '')}  {it.get('start', '')}-{it.get('end', '')}"))
            if it.get("location"):
                rlines.append(("normal", f"     Location: {it['location'][:right_w - 16]}"))
            rlines.append(("normal", ""))
            rlines.append(("normal", " " + "─" * (right_w - 2)))
            rlines.append(("normal", " Fields:"))
            rlines.append(("normal", f"   [t] Title:     {it.get('title', '')[:right_w - 20]}"))
            rlines.append(("normal", f"   [d] Date:      {it.get('date', '')}"))
            rlines.append(("normal", f"   [s] Start:     {it.get('start', '')}"))
            rlines.append(("normal", f"   [e] End:       {it.get('end', '')}"))
            rlines.append(("normal", f"   [l] Location:  {it.get('location', '') or '(none)'}"))
            rlines.append(("normal", f"   [r] Recurring: {it.get('recurring', '') or '(none)'}"))

        # ── Draw content rows ──
        for row_i in range(content_h):
            y = sy + 1 + row_i

            # Left pane: item list with divider
            display_idx = scroll + row_i
            if display_idx < total_display:
                etype, eidx = left_entries[display_idx]
                if etype == "divider":
                    div_label = " Events "
                    dashes_l = (left_w - len(div_label)) // 2
                    dashes_r = left_w - len(div_label) - dashes_l
                    div_text = ("─" * dashes_l + div_label + "─" * dashes_r)[:left_w]
                    self._safe_addstr(y, sx, "│")
                    self._safe_addstr(y, sx + 1, div_text, curses.A_DIM)
                else:
                    itm = items[eidx]
                    m = "✓" if itm["accepted"] else "✗"
                    k = "TASK" if itm["type"] == "task" else "EVNT"
                    ttl = itm.get("desc", "") if itm["type"] == "task" else itm.get("title", "")
                    left_text = f" {m} {k}  {ttl}"
                    left_text = left_text[:left_w]
                    left_cell = left_text.ljust(left_w)

                    attr = 0
                    if eidx == cursor:
                        attr = curses.A_REVERSE | curses.A_BOLD
                    elif itm["accepted"]:
                        attr = curses.color_pair(C_GREEN)
                    else:
                        attr = curses.color_pair(C_RED)

                    self._safe_addstr(y, sx, "│")
                    self._safe_addstr(y, sx + 1, left_cell, attr)
            else:
                self._safe_addstr(y, sx, "│" + " " * left_w)

            # Vertical divider
            self._safe_addstr(y, sx + 1 + left_w, "│")

            # Right pane: detail
            if row_i < len(rlines):
                rtype, rtext = rlines[row_i]
                right_cell = rtext[:right_w].ljust(right_w)
                if rtype == "header":
                    if it["accepted"]:
                        self._safe_addstr(y, sx + 2 + left_w, right_cell,
                                          curses.color_pair(C_GREEN) | curses.A_BOLD)
                    else:
                        self._safe_addstr(y, sx + 2 + left_w, right_cell,
                                          curses.color_pair(C_RED) | curses.A_BOLD)
                else:
                    self._safe_addstr(y, sx + 2 + left_w, right_cell)
            else:
                self._safe_addstr(y, sx + 2 + left_w, " " * right_w)

            # Right outer border
            self._safe_addstr(y, sx + box_w - 1, "│")

        # ── Footer separator with ┴ at divider ──
        foot_y = sy + 1 + content_h
        foot_bar = list("─" * (box_w - 2))
        if div_pos < len(foot_bar):
            foot_bar[div_pos] = "┴"
        self._safe_addstr(foot_y, sx, "├" + "".join(foot_bar) + "┤")

        # ── Footer with keybinding hints ──
        if is_task:
            keys_help = "a:accept  x:reject  d/u/p/m:edit fields  j/k:nav  S:done  q:cancel"
        else:
            keys_help = "a:accept  x:reject  t/d/s/e/l/r:edit  j/k:nav  S:done  q:cancel"
        footer_text = keys_help[:inner_w].center(inner_w)
        self._safe_addstr(foot_y + 1, sx, "│" + footer_text + "│", curses.A_DIM)

        # ── Bottom border ──
        self._safe_addstr(foot_y + 2, sx, "└" + "─" * (box_w - 2) + "┘")

        self.stdscr.refresh()

    def _review_handle_field_edit(self, ch, item):
        """Dispatch field edits for a review item."""
        if item["type"] == "task":
            if ch == ord("d"):
                val = self._modal_input("Edit Description", "Desc: ",
                                        default=item.get("desc", ""))
                if val:
                    item["desc"] = val
            elif ch == ord("u"):
                val = self._modal_input_date("Edit Due Date", "Due (YYYY-MM-DD): ",
                                             default=item.get("due", ""))
                if val:
                    item["due"] = val
            elif ch == ord("p"):
                val = self._review_pick_project(item.get("project", "Inbox"))
                if val:
                    item["project"] = val
                    # Reset milestone when project changes
                    item["milestone"] = ""
            elif ch == ord("m"):
                val = self._review_pick_milestone(item.get("project", "Inbox"),
                                                   item.get("milestone", ""))
                if val is not None:
                    item["milestone"] = val
        else:  # event
            if ch == ord("t"):
                val = self._modal_input("Edit Title", "Title: ",
                                        default=item.get("title", ""))
                if val:
                    item["title"] = val
            elif ch == ord("d"):
                val = self._modal_input_date("Edit Date", "Date (YYYY-MM-DD): ",
                                             default=item.get("date", ""))
                if val:
                    item["date"] = val
            elif ch == ord("s"):
                val = self._modal_input_time("Edit Start", "Start (HH:MM): ")
                if val:
                    item["start"] = val
            elif ch == ord("e"):
                val = self._modal_input_time("Edit End", "End (HH:MM): ")
                if val:
                    item["end"] = val
            elif ch == ord("l"):
                val = self._modal_input("Edit Location", "Location: ",
                                        default=item.get("location", ""))
                if val is not None:
                    item["location"] = val
            elif ch == ord("r"):
                val = self._modal_input("Edit Recurring", "Days (e.g. MWF): ",
                                        default=item.get("recurring", ""))
                if val is not None:
                    item["recurring"] = val

    def _review_pick_project(self, current):
        """Let user pick a project from active projects list."""
        targets = [p for p in self.projects if p.get("status") == "active"]
        if not targets:
            return current
        body = [f"{i+1}. {p['name']}" for i, p in enumerate(targets)]
        pick = self._modal_input("Pick Project", "Number or name: ", body)
        if not pick:
            return current
        try:
            idx = int(pick) - 1
            if 0 <= idx < len(targets):
                return targets[idx]["name"]
        except ValueError:
            pick_l = pick.lower()
            for p in targets:
                if pick_l in p["name"].lower():
                    return p["name"]
        return current

    def _review_pick_milestone(self, proj_name, current):
        """Let user pick a milestone from the given project."""
        proj = None
        for p in self.projects:
            if p.get("name", "").lower() == proj_name.lower():
                proj = p
                break
        if not proj:
            self._modal_input("Info", "No milestones", ["Project not found."])
            return current
        milestones = [m for m in proj.get("milestones", []) if not m.get("done")]
        if not milestones:
            self._modal_input("Info", "No milestones",
                              [f"No open milestones in {proj_name}."])
            return current
        body = [f"{i+1}. {m['name']}" + (f" (due {m['due']})" if m.get('due') else "")
                for i, m in enumerate(milestones)]
        body.append(f"{len(milestones)+1}. (none)")
        pick = self._modal_input("Pick Milestone", "Number or name: ", body)
        if not pick:
            return current
        try:
            idx = int(pick) - 1
            if idx == len(milestones):
                return ""
            if 0 <= idx < len(milestones):
                return milestones[idx]["name"]
        except ValueError:
            pick_l = pick.lower()
            for m in milestones:
                if pick_l in m["name"].lower():
                    return m["name"]
        return current

    def _handle_mail_keys(self, key):
        """Handle keys when focused on mail list (left panel)."""
        if key in (ord("j"), curses.KEY_DOWN):
            self._mail_scroll_list(1)
            self._mail_mark_pending_body()
        elif key in (ord("k"), curses.KEY_UP):
            self._mail_scroll_list(-1)
            self._mail_mark_pending_body()
        elif key == ord("J"):
            self._mail_scroll_list(self.content_h // 2)
            self._mail_mark_pending_body()
        elif key == ord("K"):
            self._mail_scroll_list(-self.content_h // 2)
            self._mail_mark_pending_body()
        elif key in (10, 13, ord("l"), curses.KEY_RIGHT):
            if self.mail_threaded:
                if self._mail_display_rows and self.left_cursor < len(self._mail_display_rows):
                    row = self._mail_display_rows[self.left_cursor]
                    tidx = row["thread_idx"]
                    if row["type"] == "thread" and len(row["thread"]["emails"]) > 1:
                        # Expand thread in left panel and open conversation
                        if tidx not in self._mail_expanded:
                            self._mail_expanded.add(tidx)
                            self._mail_build_display_rows()
                        self._mail_open_conversation(tidx)
                        self._mail_sync_left_to_conv()
                    elif row["type"] == "email":
                        # Email row inside expanded thread: open conversation, focus that email
                        self._mail_open_conversation(tidx, focus_email_uid=row["email"]["uid"])
                        self._mail_sync_left_to_conv()
                    else:
                        # Single-email thread: open in conversation view
                        self._mail_open_current_row()
            else:
                self._mail_open()
        elif key == ord("x"):
            if self.mail_threaded:
                tidx = self._mail_current_thread_idx()
                if tidx is not None:
                    if tidx in self.mail_selected:
                        self.mail_selected.discard(tidx)
                    else:
                        self.mail_selected.add(tidx)
            else:
                if self.mail_emails:
                    uid = self.mail_emails[self.left_cursor]["uid"]
                    if uid in self.mail_selected:
                        self.mail_selected.discard(uid)
                    else:
                        self.mail_selected.add(uid)
        elif key == ord("X"):
            if self.mail_threaded:
                if self.mail_threads:
                    all_idxs = set(range(len(self.mail_threads)))
                    if self.mail_selected >= all_idxs:
                        self.mail_selected.clear()
                    else:
                        self.mail_selected = all_idxs
            else:
                if self.mail_emails:
                    all_uids = {em["uid"] for em in self.mail_emails}
                    if self.mail_selected >= all_uids:
                        self.mail_selected.clear()
                    else:
                        self.mail_selected = all_uids
        elif key == ord("T"):
            self._mail_extract_items()
        elif key == ord("+"):
            self._mail_load_more()
        elif key == ord("t"):
            # Toggle threaded/flat view
            self.mail_threaded = not self.mail_threaded
            self._mail_expanded.clear()
            self._mail_rebuild_threads()
            self.left_cursor = 0
            self.left_scroll = 0
            self.mail_selected.clear()
            self.mail_thread_body_lines = []
            self.mail_thread_body_idx = None
            self.mail_thread_body_scroll = 0
            self.mail_body_lines = []
            self.mail_body_uid = None
            self._conv_emails = []
            self._conv_line_map = []
            self._conv_collapsed = set()
            self._conv_quotes_shown = set()
            self.mail_body_scroll = 0
        elif key == ord("u"):
            self.mail_unread_filter = not self.mail_unread_filter
            self._mail_expanded.clear()
            self._mail_fetch_list()
            n_items = len(self._mail_display_rows) if self.mail_threaded else len(self.mail_emails)
            self.left_cursor = min(self.left_cursor, max(0, n_items - 1))
            self.left_scroll = 0
            self.mail_body_lines = []
            self.mail_body_uid = None
            self.mail_body_scroll = 0
            self.mail_thread_body_lines = []
            self.mail_thread_body_idx = None
            self.mail_thread_body_scroll = 0
            self.mail_selected.clear()
        elif key == ord("r"):
            self._mail_expanded.clear()
            self._mail_fetch_list()
            n_items = len(self._mail_display_rows) if self.mail_threaded else len(self.mail_emails)
            self.left_cursor = min(self.left_cursor, max(0, n_items - 1))
            self.left_scroll = 0
            self.mail_body_lines = []
            self.mail_body_uid = None
            self.mail_body_scroll = 0
            self.mail_thread_body_lines = []
            self.mail_thread_body_idx = None
            self.mail_thread_body_scroll = 0
            self.mail_selected.clear()
        elif key == ord("m"):
            self._mail_toggle_seen()
        elif key == ord("s"):
            self._mail_toggle_flag()
        elif key == ord("#"):
            self._mail_delete()
        elif key == ord("e"):
            self._mail_archive()
        elif key == ord("g"):
            self.left_cursor = 0
            self.left_scroll = 0
        elif key == ord("G"):
            items = self._mail_display_rows if self.mail_threaded else self.mail_emails
            if items:
                self.left_cursor = len(items) - 1
                self.left_scroll = max(0, len(items) - self.content_h)
        elif key == ord("/"):
            self._mail_search()
        elif key == ord("n"):
            if self._mail_search_query:
                self._mail_search_next(self.left_cursor + 1, 1)
        elif key == ord("N"):
            if self._mail_search_query:
                self._mail_search_next(self.left_cursor - 1, -1)
        elif key == ord("\\"):
            self._right_panel_hidden = not self._right_panel_hidden
            self._calc_dimensions()
        elif key == ord(">"):
            self._mail_resize_left(5)
        elif key == ord("<"):
            self._mail_resize_left(-5)
        elif key == ord("S"):
            self._mail_summarize()
        elif key == ord(","):
            self._show_settings()
        elif key == ord("?"):
            self._show_help()
        elif key == ord("c"):
            self._toggle_mode()
        elif key == ord("v"):
            self._cycle_view()

    def _handle_mail_right_keys(self, key):
        """Handle keys when focused on mail body (right panel)."""
        if key in (ord("j"), curses.KEY_DOWN):
            max_scroll = max(0, len(self.mail_body_lines) - self.content_h)
            self.mail_body_scroll = min(max_scroll, self.mail_body_scroll + 1)
        elif key in (ord("k"), curses.KEY_UP):
            self.mail_body_scroll = max(0, self.mail_body_scroll - 1)
        elif key == ord("J"):
            max_scroll = max(0, len(self.mail_body_lines) - self.content_h)
            self.mail_body_scroll = min(max_scroll, self.mail_body_scroll + self.content_h // 2)
        elif key == ord("K"):
            self.mail_body_scroll = max(0, self.mail_body_scroll - self.content_h // 2)
        elif key == ord("n"):
            # Next email in conversation
            if self._conv_emails and self._conv_pos < len(self._conv_emails) - 1:
                self._conv_pos += 1
                self._conv_collapsed.discard(self._conv_pos)
                self._mail_build_conversation_lines()
                self._mail_scroll_to_conv_pos()
                self._mail_sync_left_to_conv()
        elif key == ord("p"):
            # Previous email in conversation
            if self._conv_emails and self._conv_pos > 0:
                self._conv_pos -= 1
                self._conv_collapsed.discard(self._conv_pos)
                self._mail_build_conversation_lines()
                self._mail_scroll_to_conv_pos()
                self._mail_sync_left_to_conv()
        elif key == ord("o"):
            # Toggle quoted text on focused email
            if self._conv_emails:
                if self._conv_pos in self._conv_quotes_shown:
                    self._conv_quotes_shown.discard(self._conv_pos)
                else:
                    self._conv_quotes_shown.add(self._conv_pos)
                self._mail_build_conversation_lines()
        elif key == ord("\\"):
            # Toggle collapse/expand all
            if self._conv_emails and len(self._conv_emails) > 1:
                if self._conv_collapsed:
                    self._conv_collapsed.clear()
                else:
                    self._conv_collapsed = set(range(len(self._conv_emails))) - {self._conv_pos}
                self._mail_build_conversation_lines()
        elif key in (10, 13):
            # Enter on collapsed email -> expand it
            if self._conv_line_map and self._conv_emails:
                # Find which email is at the current scroll position
                vis_line = self.mail_body_scroll
                if vis_line < len(self._conv_line_map):
                    eidx, ltype = self._conv_line_map[vis_line]
                    if ltype in ("collapsed_top", "collapsed_bot") and eidx in self._conv_collapsed:
                        self._conv_collapsed.discard(eidx)
                        self._conv_pos = eidx
                        self._mail_build_conversation_lines()
                        self._mail_scroll_to_conv_pos()
        elif key == ord("w"):
            # Toggle raw/processed view
            self._mail_raw_mode = not self._mail_raw_mode
            if self._conv_emails:
                self._mail_build_conversation_lines()
        elif key == ord("S"):
            self._mail_summarize()
        elif key == ord(","):
            self._show_settings()
        elif key == ord("?"):
            self._show_help()
        elif key in (ord("h"), 27, curses.KEY_LEFT):
            # Collapse the current thread and move cursor to its header row
            if self.mail_threaded and self._mail_display_rows:
                tidx = None
                if self.left_cursor < len(self._mail_display_rows):
                    tidx = self._mail_display_rows[self.left_cursor]["thread_idx"]
                if tidx is not None and tidx in self._mail_expanded:
                    self._mail_expanded.discard(tidx)
                    self._mail_build_display_rows()
                    # Find the thread header row
                    for i, row in enumerate(self._mail_display_rows):
                        if row["type"] == "thread" and row["thread_idx"] == tidx:
                            self.left_cursor = i
                            if self.left_cursor < self.left_scroll:
                                self.left_scroll = self.left_cursor
                            elif self.left_cursor >= self.left_scroll + self.content_h:
                                self.left_scroll = self.left_cursor - self.content_h + 1
                            break
            self.focus = LEFT

    # ─── Help ─────────────────────────────────────────────────────────────

    def _show_help(self):
        """Show keybinding help popup for the current mode."""
        sections = []

        sections.append(("Global", [
            (":",  "Command palette"),
            ("M",  "Open mail"),
            ("q",  "Quit"),
            (",",  "Settings"),
            ("?",  "This help"),
        ]))

        if self.mode == MODE_MAIL:
            sections.append(("Mail ─ List", [
                ("j/k",     "Navigate up/down"),
                ("g/G",     "Jump to top/bottom"),
                ("Enter",   "Open / expand thread"),
                ("/",       "Search"),
                ("n/N",     "Next/prev search match"),
                ("x",       "Select email"),
                ("X",       "Select all"),
                ("t",       "Toggle threaded/flat"),
                ("T",       "Extract tasks (Claude)"),
                ("S",       "Summarize email (Claude)"),
                ("s",       "Toggle star"),
                ("m",       "Toggle read/unread"),
                ("e",       "Archive"),
                ("#",       "Delete"),
                ("r",       "Refresh inbox"),
                ("+",       "Load more emails"),
                (">/<",     "Resize left pane"),
                ("c",       "Switch to tasks"),
                ("v",       "Cycle view"),
            ]))
            sections.append(("Mail ─ Body", [
                ("j/k",     "Scroll up/down"),
                ("J/K",     "Page up/down"),
                ("n/p",     "Next/prev email in thread"),
                ("o",       "Toggle quoted text"),
                ("\\",      "Expand/collapse all"),
                ("S",       "Summarize email (Claude)"),
                ("w",       "Toggle raw/compact"),
                ("h/Esc",   "Back to list"),
            ]))
        elif self.mode == MODE_TASKS:
            sections.append(("Projects", [
                ("j/k",     "Navigate up/down"),
                ("Enter",   "View details"),
                ("a",       "Add project"),
                ("x",       "Delete project"),
                ("A",       "Archive project"),
                ("D",       "Claude Code session"),
                ("s",       "Sort projects"),
                ("v",       "Cycle view"),
                ("f",       "Toggle filter"),
                ("i",       "Inbox quick-capture"),
                ("u",       "Undo"),
                ("c",       "Switch to calendar"),
            ]))
            sections.append(("Details (right)", [
                ("j/k",     "Navigate fields"),
                ("Enter",   "Edit field"),
                ("a",       "Add item"),
                ("d",       "Toggle done"),
                ("x",       "Delete item"),
                ("r",       "Reschedule"),
                ("n",       "Edit notes"),
                ("h/Esc",   "Back to list"),
            ]))
        elif self.mode == MODE_CALENDAR:
            sections.append(("Calendar", [
                ("j/k",     "Navigate events"),
                ("h/l",     "Prev/next day"),
                ("t",       "Jump to today"),
                ("a",       "Add event"),
                ("e",       "Edit event"),
                ("x",       "Delete event"),
                ("y",       "Copy event"),
                ("p",       "Paste event"),
                ("o",       "Open event details"),
                ("v",       "Cycle view"),
                ("u",       "Undo"),
                ("c",       "Switch to tasks"),
            ]))

        # Flatten into display lines
        lines = []
        for title, keys in sections:
            if lines:
                lines.append("")
            lines.append(f"── {title} ──")
            for key, desc in keys:
                lines.append(f"  {key:<10} {desc}")

        self._modal_scroll_text("Help", lines)

    # ─── Settings ──────────────────────────────────────────────────────────

    def _show_settings(self):
        """Show settings dialog to configure defaults."""
        curses.flushinp()
        items = [
            ("claude_model", "Claude model", [("h", "Haiku (fast)", "haiku"), ("s", "Sonnet", "sonnet"), ("a", "Always ask", "ask")]),
        ]
        cursor = 0
        while True:
            self.draw()
            h, w = self.stdscr.getmaxyx()
            box_w = min(max(55, w // 2), w - 4)
            inner = box_w - 4
            blank = "│" + " " * (box_w - 2) + "│"
            box_h = len(items) * 2 + 5
            sy = max(0, (h - box_h) // 2)
            sx = max(0, (w - box_w) // 2)

            t = "Settings"
            dashes = max(1, box_w - 5 - len(t))
            self._safe_addstr(sy, sx, "┌─ " + t + " " + "─" * dashes + "┐")
            self._safe_addstr(sy + 1, sx, blank)

            row = sy + 2
            for idx, (key, label, options) in enumerate(items):
                current = self.config.get(key, "")
                display_val = current if current else "ask"
                for _shortcut, olabel, cfg_val in options:
                    if current == cfg_val:
                        display_val = olabel
                        break
                line = f"  {label}: {display_val}"
                attr = curses.A_REVERSE if idx == cursor else 0
                self._safe_addstr(row, sx,
                                  "│" + line[:box_w - 2].ljust(box_w - 2) + "│", attr)
                row += 1
                self._safe_addstr(row, sx, blank)
                row += 1

            hint = "Enter: change  q/Esc: close"
            self._safe_addstr(row, sx,
                              "└─ " + hint[:box_w - 5] + " " + "─" * max(1, box_w - 5 - len(hint) - 1) + "┘")
            self.stdscr.refresh()

            try:
                ch = self.stdscr.getch()
            except curses.error:
                continue
            if ch in (27, ord("q")):
                return
            elif ch in (ord("j"), curses.KEY_DOWN):
                cursor = min(len(items) - 1, cursor + 1)
            elif ch in (ord("k"), curses.KEY_UP):
                cursor = max(0, cursor - 1)
            elif ch in (10, curses.KEY_ENTER, ord("\n")):
                key, label, options = items[cursor]
                shortcut_to_cfg = {sc: cv for sc, _ol, cv in options}
                choice = self._modal_choice(label, f"Choose {label.lower()}:",
                                            [(sc, ol) for sc, ol, _cv in options])
                if choice is not None:
                    cfg_val = shortcut_to_cfg[choice]
                    if cfg_val == "ask":
                        self.config.pop(key, None)
                    else:
                        self.config[key] = cfg_val
                    save_config(self.config)
            elif ch == curses.KEY_RESIZE:
                self._calc_dimensions()

    # ─── Mail summarize ──────────────────────────────────────────────────

    def _mail_summarize(self):
        """Summarize the current email using Claude and display in a popup."""
        import os
        # Get current email body
        if self._conv_emails:
            bodies = []
            for em in self._conv_emails:
                uid = em["uid"]
                body = self._mail_body_cache.get(uid, "")
                if body.strip():
                    frm = em.get("from", "")
                    subj = em.get("subject", "")
                    bodies.append(f"From: {frm}\nSubject: {subj}\n\n{body}")
            full_text = "\n---\n".join(bodies)
        else:
            return
        if not full_text.strip():
            return

        model = self._get_claude_model()
        if model is None:
            return
        self._show_loading("Summarizing with Claude...")

        prompt = (
            "Summarize the following email thread in TL;DR style. "
            "Be concise — use bullet points for key points, action items, "
            "and deadlines. Keep it short (5-10 lines max).\n\n"
            f"{full_text[:8000]}"
        )

        response = self._chat_send_to_claude(prompt, model)
        if not response or response.startswith("[Error"):
            self._modal_input("Error", "Press Enter.",
                              ["Claude summarization failed.", response or ""])
            return

        self._modal_scroll_text("TL;DR", response.splitlines())

    # ─── Main loop ────────────────────────────────────────────────────────

    def run(self):
        while True:
            self._calc_dimensions()
            self.draw()

            # Use short timeout when a mail body load is pending
            if self._mail_body_pending:
                self.stdscr.timeout(150)
            else:
                self.stdscr.timeout(-1)

            try:
                key = self.stdscr.getch()
            except curses.error:
                continue

            if key == -1:  # timeout expired — load pending body
                self._mail_idle_load()
                continue

            if key == curses.KEY_RESIZE:
                self._calc_dimensions()
                continue

            if key == ord("q"):
                self._show_loading("Quitting...")
                if self.mail_imap:
                    try:
                        self.mail_imap.socket().settimeout(2)
                        self.mail_imap.logout()
                    except Exception:
                        pass
                break

            # Global: M → mail mode
            if key == ord("M"):
                self._enter_mail_mode()
                continue

            # Global: , → settings
            if key == ord(","):
                self._show_settings()
                continue

            # Global: ? → help
            if key == ord("?"):
                self._show_help()
                continue

            # Global: : → command palette
            if key == ord(":"):
                self.action_command_palette()
                continue

            # Mail mode handles its own keys
            if self.mode == MODE_MAIL:
                if self.focus == LEFT:
                    self._handle_mail_keys(key)
                else:
                    self._handle_mail_right_keys(key)
                continue

            # Filter toggle
            if key == ord("f"):
                self.show_all = not self.show_all
                self._rebuild_filtered()
                self.left_cursor = min(self.left_cursor, max(0, len(self.filtered) - 1))
                self.left_scroll = 0
                self._rebuild_detail()
                continue

            # Global undo
            if key == ord("u"):
                self._pop_undo()
                continue

            # Inbox quick-capture
            if key == ord("i"):
                self.action_inbox_add()
                continue

            if self.focus == LEFT:
                self._handle_left_keys(key)
            else:
                self._handle_right_keys(key)

    def _left_item_count(self):
        if self.view_mode == VIEW_MAIL_INBOX:
            return len(self._mail_display_rows) if self.mail_threaded else len(self.mail_emails)
        if self.view_mode == VIEW_SCHED_DAY:
            return len(self.sched_day_items)
        if self.view_mode == VIEW_SCHED_NDAY:
            return len(self.sched_nday_data)
        if self.view_mode == VIEW_SCHED_WEEK:
            return len(self.sched_week_data)
        if self.view_mode == VIEW_SCHED_MONTH:
            return len(self.sched_month_data)
        if self.view_mode in (VIEW_TODAY, VIEW_WEEK, VIEW_MONTH):
            return len(self.timeline_items)
        return len(self.filtered)

    def _cycle_view(self):
        """Cycle v within the current mode's view list."""
        if self.mode == MODE_MAIL:
            views = _MAIL_VIEWS
        elif self.mode == MODE_CALENDAR:
            views = _CAL_VIEWS
        else:
            views = _TASK_VIEWS
        idx = views.index(self.view_mode) if self.view_mode in views else 0
        self.view_mode = views[(idx + 1) % len(views)]
        self.left_cursor = 0
        self.left_scroll = 0
        if self.mode == MODE_CALENDAR:
            label = self._CAL_VIEW_LABELS.get(self.view_mode, "day")
            self.config["calendar_view"] = label
            save_config(self.config)
        self._rebuild_filtered()
        self._rebuild_detail()

    _CAL_VIEW_NAMES = {
        "day": VIEW_SCHED_DAY, "nday": VIEW_SCHED_NDAY,
        "week": VIEW_SCHED_WEEK, "month": VIEW_SCHED_MONTH,
    }
    _CAL_VIEW_LABELS = {v: k for k, v in _CAL_VIEW_NAMES.items()}

    def _toggle_mode(self):
        """Toggle: Tasks ↔ Calendar. Use M for mail."""
        if self.mode == MODE_TASKS:
            self.mode = MODE_CALENDAR
            default_view = self.config.get("calendar_view", "day")
            self.view_mode = self._CAL_VIEW_NAMES.get(default_view, VIEW_SCHED_DAY)
        else:
            self.mode = MODE_TASKS
            self.view_mode = VIEW_PROJECTS
        self.left_cursor = 0
        self.left_scroll = 0
        self.right_cursor = 0
        self.right_scroll = 0
        self.focus = LEFT
        self._rebuild_filtered()
        self._rebuild_detail()

    def _enter_mail_mode(self):
        """Switch to mail mode."""
        if self.mode == MODE_MAIL:
            return
        self.mode = MODE_MAIL
        self.view_mode = VIEW_MAIL_INBOX
        if not self.mail_emails:
            # Load disk cache first for instant display
            if not hasattr(self, "_mail_disk_cache"):
                self._mail_load_disk_cache()
            if self._mail_disk_cache:
                uids = sorted(self._mail_disk_cache.keys(),
                              key=lambda u: int(u), reverse=True)
                self.mail_emails = [self._mail_disk_cache[u] for u in uids]
                self._mail_loaded_count = len(self.mail_emails)
                self._mail_rebuild_threads()
            # Then do incremental fetch for new emails
            self._mail_connect()
            self._mail_fetch_list()
        self.left_cursor = 0
        self.left_scroll = 0
        self.right_cursor = 0
        self.right_scroll = 0
        self.focus = LEFT
        self.mail_thread_body_lines = []
        self._mail_body_pending = True
        self.mail_thread_body_idx = None
        self.mail_thread_body_scroll = 0
        self._rebuild_filtered()
        self._rebuild_detail()

    def _toggle_week_start(self):
        """Toggle between Monday-first and Sunday-first week layout and save."""
        self.week_start_sunday = not self.week_start_sunday
        self.config["week_start"] = "sunday" if self.week_start_sunday else "monday"
        save_config(self.config)

    def _handle_left_keys(self, key):
        if self.view_mode == VIEW_SCHED_DAY:
            self._handle_sched_day_keys(key)
            return
        if self.view_mode == VIEW_SCHED_NDAY:
            self._handle_sched_nday_keys(key)
            return
        if self.view_mode == VIEW_SCHED_WEEK:
            self._handle_sched_week_keys(key)
            return
        if self.view_mode == VIEW_SCHED_MONTH:
            self._handle_sched_month_keys(key)
            return

        if key in (curses.KEY_UP, ord("k")):
            self._move_left(-1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self._move_left(1)
        elif key in (curses.KEY_RIGHT, ord("\n"), curses.KEY_ENTER, 10, 13, ord("\t")):
            if self._left_item_count() > 0 and self.detail_items:
                self.focus = RIGHT
                self._snap_right_cursor()
        elif key == ord("v"):
            self._cycle_view()
        elif key == ord("c"):
            self._toggle_mode()
        elif key == ord("s"):
            if self.view_mode == VIEW_PROJECTS:
                self.sort_by_due = not self.sort_by_due
                self._rebuild_filtered()
                self.left_cursor = 0
                self.left_scroll = 0
                self._rebuild_detail()
        elif key == ord("a"):
            if self.view_mode in (VIEW_TODAY, VIEW_WEEK, VIEW_MONTH):
                self.action_add_item()
            else:
                self.action_add_project()
        elif key == ord("d"):
            if self.view_mode in (VIEW_TODAY, VIEW_WEEK, VIEW_MONTH):
                self._timeline_action_done()
        elif key == ord("r"):
            if self.view_mode in (VIEW_TODAY, VIEW_WEEK, VIEW_MONTH):
                self._timeline_action_reschedule()
        elif key == ord("x"):
            if self.view_mode in (VIEW_TODAY, VIEW_WEEK, VIEW_MONTH):
                self._timeline_action_delete()
            elif self.view_mode == VIEW_PROJECTS:
                self.action_delete_project()
        elif key == ord("A"):
            if self.view_mode == VIEW_PROJECTS:
                self.action_archive_project()
        elif key == ord("g"):
            # Go to top
            self.left_cursor = 0
            self.left_scroll = 0
            self._rebuild_detail()
        elif key == ord("G"):
            # Go to bottom
            count = self._left_item_count()
            if count > 0:
                self.left_cursor = count - 1
                self._rebuild_detail()
        elif key == ord("D"):
            if self.view_mode == VIEW_PROJECTS:
                self.action_claude_session()
        elif key == ord("\\"):
            self._right_panel_hidden = not self._right_panel_hidden
            self._calc_dimensions()
        elif key == ord(">"):
            self._left_w_offset += 5
            self._calc_dimensions()
        elif key == ord("<"):
            self._left_w_offset -= 5
            self._calc_dimensions()

    def _handle_sched_day_keys(self, key):
        if key in (curses.KEY_UP, ord("k")):
            self._move_left(-1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self._move_left(1)
        elif key in (curses.KEY_RIGHT, ord("\n"), curses.KEY_ENTER, 10, 13):
            if self._left_item_count() > 0 and self.detail_items:
                self.focus = RIGHT
                self._snap_right_cursor()
        elif key == ord("v"):
            self._cycle_view()
        elif key == ord("c"):
            self._toggle_mode()
        elif key == ord("h"):
            self.sched_date -= datetime.timedelta(days=1)
            self.left_cursor = 0
            self.left_scroll = 0
            self._rebuild_schedule_day()
            self._rebuild_detail()
        elif key == ord("l"):
            self.sched_date += datetime.timedelta(days=1)
            self.left_cursor = 0
            self.left_scroll = 0
            self._rebuild_schedule_day()
            self._rebuild_detail()
        elif key == ord("t"):
            self.sched_date = today()
            self.left_cursor = 0
            self.left_scroll = 0
            self._rebuild_schedule_day()
            self._rebuild_detail()
        elif key == ord("a"):
            self.action_add_event()
        elif key == ord("e"):
            self.action_edit_event()
        elif key == ord("x"):
            self.action_delete_event()
        elif key == ord("y"):
            self.action_copy_event()
        elif key == ord("p"):
            self.action_paste_event()
        elif key == ord("o"):
            self.action_open_location()
        elif key == ord("g"):
            self.left_cursor = 0
            self.left_scroll = 0
            self._rebuild_detail()
        elif key == ord("G"):
            count = self._left_item_count()
            if count > 0:
                self.left_cursor = count - 1
                self._rebuild_detail()
        elif key == ord("W"):
            self.action_show_avail()
        elif key == ord("S"):
            self._toggle_week_start()

    def _handle_sched_week_keys(self, key):
        if key in (curses.KEY_UP, ord("k")):
            # Move event cursor up within selected day
            if self.sched_week_data:
                idx = min(self.left_cursor, len(self.sched_week_data) - 1)
                events = self.sched_week_data[idx]["events"]
                if events and self.week_event_cursor > 0:
                    self.week_event_cursor -= 1
                    self._rebuild_detail()
        elif key in (curses.KEY_DOWN, ord("j")):
            # Move event cursor down within selected day
            if self.sched_week_data:
                idx = min(self.left_cursor, len(self.sched_week_data) - 1)
                events = self.sched_week_data[idx]["events"]
                if events and self.week_event_cursor < len(events) - 1:
                    self.week_event_cursor += 1
                    self._rebuild_detail()
        elif key == ord("h"):
            # Move to previous day column; shift window at left edge
            if self.left_cursor > 0:
                self.left_cursor -= 1
                self.week_event_cursor = 0
                self._rebuild_detail()
            else:
                self.sched_date -= datetime.timedelta(days=7)
                self.week_event_cursor = 0
                self._rebuild_schedule_week()
                self._rebuild_detail()
        elif key == ord("l"):
            # Move to next day column; shift window at right edge
            if self.left_cursor < len(self.sched_week_data) - 1:
                self.left_cursor += 1
                self.week_event_cursor = 0
                self._rebuild_detail()
            else:
                self.sched_date += datetime.timedelta(days=7)
                self.left_cursor = len(self.sched_week_data) - 1
                self.week_event_cursor = 0
                self._rebuild_schedule_week()
                self._rebuild_detail()
        elif key in (curses.KEY_RIGHT, ord("\n"), curses.KEY_ENTER, 10, 13):
            # Drill into day view
            if self.sched_week_data:
                idx = min(self.left_cursor, len(self.sched_week_data) - 1)
                self.sched_date = self.sched_week_data[idx]["date"]
                self.view_mode = VIEW_SCHED_DAY
                self.left_cursor = 0
                self.left_scroll = 0
                self._rebuild_schedule_day()
                self._rebuild_detail()
        elif key == ord("v"):
            self._cycle_view()
        elif key == ord("c"):
            self._toggle_mode()
        elif key == ord("t"):
            self.sched_date = today()
            self.left_cursor = 0
            self.week_event_cursor = 0
            self.left_scroll = 0
            self._rebuild_schedule_week()
            self._rebuild_detail()
        elif key == ord("a"):
            if self.sched_week_data:
                idx = min(self.left_cursor, len(self.sched_week_data) - 1)
                old_date = self.sched_date
                self.sched_date = self.sched_week_data[idx]["date"]
                self.action_add_event()
                self.sched_date = old_date
                self._rebuild_schedule_week()
                self._rebuild_detail()
        elif key in (ord("e"), ord("x")):
            self._week_action_on_event(key)
        elif key == ord("y"):
            self.action_copy_event()
        elif key == ord("p"):
            if self.sched_week_data:
                idx = min(self.left_cursor, len(self.sched_week_data) - 1)
                target_date = self.sched_week_data[idx]["date"]
                self.action_paste_event(target_date)
                self._rebuild_schedule_week()
                self._rebuild_detail()
        elif key == ord("o"):
            self.action_open_location()
        elif key == ord("g"):
            self.left_cursor = 0
            self.week_event_cursor = 0
            self.left_scroll = 0
            self._rebuild_detail()
        elif key == ord("G"):
            if self.sched_week_data:
                self.left_cursor = len(self.sched_week_data) - 1
                events = self.sched_week_data[self.left_cursor]["events"]
                self.week_event_cursor = max(0, len(events) - 1)
                self._rebuild_detail()
        elif key == ord("W"):
            self.action_show_avail()
        elif key == ord("S"):
            self._toggle_week_start()
            self._rebuild_schedule_week()
            self._rebuild_detail()

    def _week_action_on_event(self, key):
        """Run edit/delete on the selected week event by temporarily setting up day context."""
        if not self.sched_week_data:
            return
        idx = min(self.left_cursor, len(self.sched_week_data) - 1)
        events = self.sched_week_data[idx]["events"]
        if not events:
            return
        ei = min(self.week_event_cursor, len(events) - 1)
        target = events[ei]
        t_title = target.get("title", "")
        t_start = target.get("start") or target.get("depart") or ""

        old_date = self.sched_date
        old_cursor = self.left_cursor
        old_view = self.view_mode

        self.sched_date = self.sched_week_data[idx]["date"]
        self.view_mode = VIEW_SCHED_DAY
        self._rebuild_schedule_day()

        for i, item in enumerate(self.sched_day_items):
            if item["kind"] == "event" and item["event"]:
                ev = item["event"]
                if (ev.get("title") == t_title and
                    (ev.get("start") or ev.get("depart") or "") == t_start):
                    self.left_cursor = i
                    break

        if key == ord("e"):
            self.action_edit_event()
        else:
            self.action_delete_event()

        self.sched_date = old_date
        self.view_mode = old_view
        self.left_cursor = old_cursor
        self._rebuild_schedule_week()
        if self.sched_week_data and idx < len(self.sched_week_data):
            events = self.sched_week_data[idx]["events"]
            self.week_event_cursor = min(self.week_event_cursor, max(0, len(events) - 1))
        self._rebuild_detail()

    def _nday_action_on_event(self, key):
        """Run edit/delete on the selected nday event by temporarily setting up day context."""
        if not self.sched_nday_data:
            return
        idx = min(self.left_cursor, len(self.sched_nday_data) - 1)
        events = self.sched_nday_data[idx]["events"]
        if not events:
            return
        ei = min(self.nday_event_cursor, len(events) - 1)
        target = events[ei]
        t_title = target.get("title", "")
        t_start = target.get("start") or target.get("depart") or ""

        # Save nday state
        old_date = self.sched_date
        old_cursor = self.left_cursor
        old_view = self.view_mode

        # Switch to day context
        self.sched_date = self.sched_nday_data[idx]["date"]
        self.view_mode = VIEW_SCHED_DAY
        self._rebuild_schedule_day()

        # Find matching event in sched_day_items
        for i, item in enumerate(self.sched_day_items):
            if item["kind"] == "event" and item["event"]:
                ev = item["event"]
                if (ev.get("title") == t_title and
                    (ev.get("start") or ev.get("depart") or "") == t_start):
                    self.left_cursor = i
                    break

        if key == ord("e"):
            self.action_edit_event()
        else:
            self.action_delete_event()

        # Restore nday state
        self.sched_date = old_date
        self.view_mode = old_view
        self.left_cursor = old_cursor
        self._rebuild_schedule_nday()
        if self.sched_nday_data and idx < len(self.sched_nday_data):
            events = self.sched_nday_data[idx]["events"]
            self.nday_event_cursor = min(self.nday_event_cursor, max(0, len(events) - 1))
        self._rebuild_detail()

    def _handle_sched_nday_keys(self, key):
        if key in (curses.KEY_UP, ord("k")):
            # Move event cursor up within selected day
            if self.sched_nday_data:
                idx = min(self.left_cursor, len(self.sched_nday_data) - 1)
                events = self.sched_nday_data[idx]["events"]
                if events and self.nday_event_cursor > 0:
                    self.nday_event_cursor -= 1
                    self._rebuild_detail()
        elif key in (curses.KEY_DOWN, ord("j")):
            # Move event cursor down within selected day
            if self.sched_nday_data:
                idx = min(self.left_cursor, len(self.sched_nday_data) - 1)
                events = self.sched_nday_data[idx]["events"]
                if events and self.nday_event_cursor < len(events) - 1:
                    self.nday_event_cursor += 1
                    self._rebuild_detail()
        elif key == ord("h"):
            # Move to previous day column; shift window at left edge
            if self.left_cursor > 0:
                self.left_cursor -= 1
                self.nday_event_cursor = 0
                self._rebuild_detail()
            else:
                self.sched_date -= datetime.timedelta(days=1)
                self.nday_event_cursor = 0
                self._rebuild_schedule_nday()
                self._rebuild_detail()
        elif key == ord("l"):
            # Move to next day column; shift window at right edge
            if self.left_cursor < len(self.sched_nday_data) - 1:
                self.left_cursor += 1
                self.nday_event_cursor = 0
                self._rebuild_detail()
            else:
                self.sched_date += datetime.timedelta(days=1)
                self.left_cursor = len(self.sched_nday_data) - 1
                self.nday_event_cursor = 0
                self._rebuild_schedule_nday()
                self._rebuild_detail()
        elif key in (curses.KEY_RIGHT, ord("\n"), curses.KEY_ENTER, 10, 13):
            # Drill into day view
            if self.sched_nday_data:
                idx = min(self.left_cursor, len(self.sched_nday_data) - 1)
                self.sched_date = self.sched_nday_data[idx]["date"]
                self.view_mode = VIEW_SCHED_DAY
                self.left_cursor = 0
                self.left_scroll = 0
                self._rebuild_schedule_day()
                self._rebuild_detail()
        elif key == ord("v"):
            self._cycle_view()
        elif key == ord("c"):
            self._toggle_mode()
        elif key == ord("t"):
            self.sched_date = today()
            self.left_cursor = 0
            self.nday_event_cursor = 0
            self.left_scroll = 0
            self._rebuild_schedule_nday()
            self._rebuild_detail()
        elif key == ord("+") or key == ord("="):
            self.sched_nday_count = min(14, self.sched_nday_count + 1)
            self.left_cursor = min(self.left_cursor, self.sched_nday_count - 1)
            self.nday_event_cursor = 0
            self._rebuild_schedule_nday()
            self._rebuild_detail()
        elif key == ord("-"):
            self.sched_nday_count = max(2, self.sched_nday_count - 1)
            self.left_cursor = min(self.left_cursor, self.sched_nday_count - 1)
            self.nday_event_cursor = 0
            self._rebuild_schedule_nday()
            self._rebuild_detail()
        elif key == ord("a"):
            if self.sched_nday_data:
                idx = min(self.left_cursor, len(self.sched_nday_data) - 1)
                old_date = self.sched_date
                self.sched_date = self.sched_nday_data[idx]["date"]
                self.action_add_event()
                self.sched_date = old_date
                self._rebuild_schedule_nday()
                self._rebuild_detail()
        elif key in (ord("e"), ord("x")):
            self._nday_action_on_event(key)
        elif key == ord("y"):
            self.action_copy_event()
        elif key == ord("p"):
            if self.sched_nday_data:
                idx = min(self.left_cursor, len(self.sched_nday_data) - 1)
                target_date = self.sched_nday_data[idx]["date"]
                self.action_paste_event(target_date)
                self._rebuild_schedule_nday()
                self._rebuild_detail()
        elif key == ord("o"):
            self.action_open_location()
        elif key == ord("g"):
            self.left_cursor = 0
            self.nday_event_cursor = 0
            self.left_scroll = 0
            self._rebuild_detail()
        elif key == ord("G"):
            if self.sched_nday_data:
                self.left_cursor = len(self.sched_nday_data) - 1
                events = self.sched_nday_data[self.left_cursor]["events"]
                self.nday_event_cursor = max(0, len(events) - 1)
                self._rebuild_detail()
        elif key == ord("W"):
            self.action_show_avail()
        elif key == ord("S"):
            self._toggle_week_start()

    def _handle_sched_month_keys(self, key):
        if key in (curses.KEY_UP, ord("k")):
            self._move_left(-1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self._move_left(1)
        elif key in (curses.KEY_RIGHT, ord("\n"), curses.KEY_ENTER, 10, 13):
            # Drill into day view
            if self.sched_month_data:
                idx = min(self.left_cursor, len(self.sched_month_data) - 1)
                entry = self.sched_month_data[idx]
                if entry.get("kind") != "week_header":
                    self.sched_date = entry["date"]
                    self.view_mode = VIEW_SCHED_DAY
                    self.left_cursor = 0
                    self.left_scroll = 0
                    self._rebuild_schedule_day()
                    self._rebuild_detail()
        elif key == ord("v"):
            self._cycle_view()
        elif key == ord("c"):
            self._toggle_mode()
        elif key == ord("h"):
            # Previous month
            d = self.sched_date.replace(day=1) - datetime.timedelta(days=1)
            self.sched_date = d.replace(day=1)
            self.left_cursor = 0
            self.left_scroll = 0
            self._rebuild_schedule_month()
            self._rebuild_detail()
        elif key == ord("l"):
            # Next month
            import calendar
            d = self.sched_date
            num_days = calendar.monthrange(d.year, d.month)[1]
            self.sched_date = d.replace(day=1) + datetime.timedelta(days=num_days)
            self.left_cursor = 0
            self.left_scroll = 0
            self._rebuild_schedule_month()
            self._rebuild_detail()
        elif key == ord("t"):
            self.sched_date = today()
            self.left_cursor = 0
            self.left_scroll = 0
            self._rebuild_schedule_month()
            self._rebuild_detail()
        elif key == ord("g"):
            self.left_cursor = 0
            self.left_scroll = 0
            self._rebuild_detail()
        elif key == ord("G"):
            count = self._left_item_count()
            if count > 0:
                self.left_cursor = count - 1
                self._rebuild_detail()
        elif key == ord("W"):
            self.action_show_avail()
        elif key == ord("S"):
            self._toggle_week_start()
            self._rebuild_schedule_month()
            self._rebuild_detail()

    def _handle_right_keys(self, key):
        if key in (curses.KEY_UP, ord("k")):
            self._move_right(-1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self._move_right(1)
        elif key == ord("l"):
            # Drill into milestone → jump to first sub-task
            if self.detail_items and 0 <= self.right_cursor < len(self.detail_items):
                item = self.detail_items[self.right_cursor]
                if item.kind == "milestone":
                    ms_idx = item.index
                    # Find first ms_task belonging to this milestone
                    for di_idx in range(self.right_cursor + 1, len(self.detail_items)):
                        di = self.detail_items[di_idx]
                        if di.kind == "ms_task" and di.index[0] == ms_idx:
                            self.right_cursor = di_idx
                            break
        elif key == ord("h"):
            # If on ms_task, jump back to parent milestone; otherwise go to left panel
            if self.detail_items and 0 <= self.right_cursor < len(self.detail_items):
                item = self.detail_items[self.right_cursor]
                if item.kind == "ms_task":
                    ms_idx = item.index[0]
                    for di_idx in range(self.right_cursor - 1, -1, -1):
                        di = self.detail_items[di_idx]
                        if di.kind == "milestone" and di.index == ms_idx:
                            self.right_cursor = di_idx
                            break
                else:
                    self.focus = LEFT
            else:
                self.focus = LEFT
        elif key in (curses.KEY_LEFT, 27):  # 27 = Escape
            self.focus = LEFT
        elif key == ord("d"):
            self.action_done()
        elif key == ord("x"):
            self.action_delete()
        elif key == ord("r"):
            self.action_reschedule()
        elif key == ord("a"):
            self.action_add_item()
        elif key == ord("n"):
            self.action_edit_notes()
        elif key == ord("m"):
            self.action_inbox_move()
        elif key == ord("g"):
            self._move_right(-999)
        elif key == ord("G"):
            self._move_right(999)
        elif key == ord("K"):
            self.action_move_task(-1)
        elif key == ord("J"):
            self.action_move_task(1)
        elif key == ord("D"):
            self.action_claude_session()
        elif key == ord(">"):
            self._left_w_offset += 5
            self._calc_dimensions()
        elif key == ord("<"):
            self._left_w_offset -= 5
            self._calc_dimensions()
        elif key in (curses.KEY_ENTER, 10, 13):
            if self.detail_items and 0 <= self.right_cursor < len(self.detail_items):
                item = self.detail_items[self.right_cursor]
                if item.kind == "field":
                    self._edit_project_field(item.index)


# ─── Entry point ──────────────────────────────────────────────────────────────

def run_tui():
    curses.set_escdelay(25)
    curses.wrapper(lambda stdscr: ProjectBrowser(stdscr).run())


if __name__ == "__main__":
    run_tui()
