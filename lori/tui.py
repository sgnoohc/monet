#!/usr/bin/env python3
"""Curses TUI project browser for lori."""

import copy
import curses
import datetime
import sys
from collections import namedtuple

from lori import (load_projects, save_projects, parse_date, today, fmt_date,
                  load_schedule, load_config, save_config,
                  expand_events_for_date,
                  calc_free_time, parse_time, fmt_time, save_schedule,
                  day_name_to_int, get_work_hours, convert_event_time)

# ─── Data structures ─────────────────────────────────────────────────────────

DetailItem = namedtuple("DetailItem", ["kind", "index", "text", "selectable"])
# kind: "header" | "info" | "milestone" | "task" | "notes" | "blank"
# index: position in project["milestones"] or project["tasks"], or None
# selectable: whether cursor can land on this row

LEFT, RIGHT = 0, 1
VIEW_PROJECTS, VIEW_TODAY, VIEW_WEEK, VIEW_MONTH = 0, 1, 2, 3
VIEW_SCHED_DAY, VIEW_SCHED_WEEK, VIEW_SCHED_MONTH, VIEW_SCHED_NDAY = 4, 5, 6, 7

MODE_TASKS, MODE_CALENDAR = 0, 1
_TASK_VIEWS = [VIEW_PROJECTS, VIEW_TODAY, VIEW_WEEK, VIEW_MONTH]
_CAL_VIEWS = [VIEW_SCHED_DAY, VIEW_SCHED_NDAY, VIEW_SCHED_WEEK, VIEW_SCHED_MONTH]

# ─── Color pairs ──────────────────────────────────────────────────────────────

C_GREEN = 1
C_RED = 2
C_YELLOW = 3
C_CYAN = 4
C_STATUS_BAR = 5
C_BLUE = 6
C_MAGENTA = 7
C_NONWORK = 8


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
                if not due:
                    continue
                try:
                    due_date = parse_date(due)
                except ValueError:
                    continue
                # Include if overdue or within cutoff
                if due_date <= cutoff:
                    items.append({"milestone": ms, "project": proj,
                                  "due_date": due_date, "ms_index": i})

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

        # Category & status
        cat = proj.get("category", "")
        status = proj.get("status", "active")
        if cat:
            self.detail_items.append(DetailItem("info", None, f"Category: {cat}", False))
        self.detail_items.append(DetailItem("info", None, f"Status: {status}", False))

        # Deadline
        dl = proj.get("deadline")
        if dl:
            try:
                dl_date = parse_date(dl)
                delta = (dl_date - today()).days
                self.detail_items.append(DetailItem("info", None,
                    f"Deadline: {fmt_date(dl_date)} ({delta}d)", False))
            except ValueError:
                self.detail_items.append(DetailItem("info", None, f"Deadline: {dl}", False))

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
                    t_text = t if isinstance(t, str) else t.get("desc", str(t))
                    self.detail_items.append(DetailItem("ms_task", (i, j), f"      · {t_text}", True))

        # Tasks
        tasks = proj.get("tasks", [])
        if tasks:
            self.detail_items.append(DetailItem("blank", None, "", False))
            self.detail_items.append(DetailItem("header", None, "Tasks", False))
            for i, t in enumerate(tasks):
                text = f"  · {t}"
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
        # Left panel width: 70% for schedule grid views, 35% otherwise
        if self.view_mode in (VIEW_SCHED_DAY, VIEW_SCHED_WEEK, VIEW_SCHED_NDAY):
            self.left_w = max(40, min(self.max_x * 70 // 100, self.max_x - 25))
        else:
            self.left_w = max(20, min(40, self.max_x * 35 // 100))
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

        self._draw_borders()
        self._draw_left_panel()
        self._draw_right_panel()
        self._draw_status_bar()
        self.stdscr.refresh()

    def _draw_borders(self):
        h, w = self.max_y, self.max_x
        lw = self.left_w

        # Top border
        top = "┌" + "─" * lw + "┬" + "─" * (w - lw - 3) + "┐"
        self._safe_addstr(0, 0, top[:w])

        # Left panel title
        if self.view_mode == VIEW_SCHED_DAY:
            filter_label = self.sched_date.strftime("%a %b %d")
        elif self.view_mode == VIEW_SCHED_NDAY:
            filter_label = f"{self.sched_nday_count}-Day View"
        elif self.view_mode == VIEW_SCHED_WEEK:
            filter_label = "Schedule"
        elif self.view_mode == VIEW_SCHED_MONTH:
            filter_label = self.sched_date.strftime("%B %Y")
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
        self._safe_addstr(0, 2, title, curses.A_BOLD)

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
        self._safe_addstr(0, lw + 3, rtitle[:self.right_w - 2], curses.A_BOLD)

        # Vertical borders for content rows
        for y in range(1, min(h - 2, 1 + self.content_h)):
            self._safe_addstr(y, 0, "│")
            self._safe_addstr(y, lw + 1, "│")
            self._safe_addstr(y, w - 2, "│")

        # Bottom border of content
        bot_y = min(h - 2, 1 + self.content_h)
        bot = "├" + "─" * lw + "┴" + "─" * (w - lw - 3) + "┤"
        self._safe_addstr(bot_y, 0, bot[:w])

        # Status bar border
        if bot_y + 2 < h:
            final = "└" + "─" * (w - 3) + "┘"
            self._safe_addstr(bot_y + 2, 0, final[:w])

    def _draw_left_panel(self):
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
            ms_name = entry["milestone"].get("name", "???")
            proj_name = entry["project"].get("name", "???")
            date_str = due_date.strftime("%b %d")
            text = f" {date_str}  {ms_name} [{proj_name}]"
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
        max_w = self.right_w

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

            # Highlight selectable row if cursor is on it
            if idx == self.right_cursor and item.selectable and self.focus == RIGHT:
                attr = curses.A_REVERSE | curses.A_BOLD

            self._safe_addstr(y, x_offset + 1, text.ljust(max_w - 1), attr | color)

    def _draw_status_bar(self):
        bar_y = min(self.max_y - 2, 2 + self.content_h)
        w = self.max_x - 3

        _undo_hint = "  u undo" if self._undo_stack else ""
        if self.focus == LEFT:
            if self.view_mode == VIEW_SCHED_DAY:
                hints = " ↑↓ navigate  h/l day  t today  a add  e edit  x delete  y copy  p paste  o open" + _undo_hint + "  v view  c tasks  q quit"
            elif self.view_mode == VIEW_SCHED_NDAY:
                hints = f" j/k events  h/l day  Enter drill  a add  e edit  x del  y copy  p paste  o open  +/- days ({self.sched_nday_count})  t today" + _undo_hint + "  v view  q quit"
            elif self.view_mode == VIEW_SCHED_WEEK:
                hints = " j/k events  h/l day  Enter drill  a add  e edit  x del  y copy  p paste  o open  t today" + _undo_hint + "  v view  c tasks  q quit"
            elif self.view_mode == VIEW_SCHED_MONTH:
                hints = " ↑↓ navigate  Enter day  h/l month  t today" + _undo_hint + "  v view  c tasks  q quit"
            elif self.view_mode in (VIEW_TODAY, VIEW_WEEK, VIEW_MONTH):
                hints = " ↑↓ navigate  Enter/→ details  d done  r reschedule  x delete" + _undo_hint + "  i inbox  v view  c cal  q quit"
            else:
                hints = " ↑↓ navigate  Enter/→ details  v view  s sort  a add  x delete  A archive" + _undo_hint + "  f filter  i inbox  c cal  q quit"
        else:
            # Context-sensitive hints for right panel
            parts = [" ↑↓ navigate  ←/Esc back"]
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
                    parts.append("d done  x delete  J/K reorder")
                    proj = self._current_project()
                    if proj and proj.get("name", "").lower() == "inbox":
                        parts.append("m move")
            if self._undo_stack:
                parts.append("u undo")
            parts.append("a add  n notes  q quit")
            hints = "  ".join(parts)

        hints = hints[:w]
        self._safe_addstr(bar_y, 1, hints.ljust(w), curses.color_pair(C_STATUS_BAR))

    def _safe_addstr(self, y, x, text, attr=0):
        try:
            self.stdscr.addnstr(y, x, text, self.max_x - x - 1, attr)
        except curses.error:
            pass

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
            box_w = min(50, w - 4)
            if box_w < 20:
                box_w = w - 2
            inner = box_w - 4

            lines = body_lines or []
            max_body = max(0, h - 7)
            displayed = lines[:max_body]
            n = len(displayed)
            box_h = 5 + n + (1 if n else 0)
            box_h = min(box_h, h - 2)

            sy = max(0, (h - box_h) // 2)
            sx = max(0, (w - box_w) // 2)

            # Top border
            t = title[:inner]
            dashes = max(1, box_w - 5 - len(t))
            self._safe_addstr(sy, sx, "┌─ " + t + " " + "─" * dashes + "┐")

            row = 1
            blank = "│" + " " * (box_w - 2) + "│"
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
            box_w = min(50, w - 4)
            if box_w < 20:
                box_w = w - 2
            inner = box_w - 4

            sy = max(0, (h - 6) // 2)
            sx = max(0, (w - box_w) // 2)

            t = title[:inner]
            dashes = max(1, box_w - 5 - len(t))
            self._safe_addstr(sy, sx, "┌─ " + t + " " + "─" * dashes + "┐")

            blank = "│" + " " * (box_w - 2) + "│"
            self._safe_addstr(sy + 1, sx, blank)
            self._safe_addstr(sy + 2, sx,
                              "│  " + message[:inner].ljust(inner) + "│")
            self._safe_addstr(sy + 3, sx, blank)

            yn = "(y) yes  (n) no"
            pad = max(0, inner - len(yn))
            self._safe_addstr(sy + 4, sx,
                              "│  " + (" " * pad + yn)[:inner] + "│")
            self._safe_addstr(sy + 5, sx, "└" + "─" * (box_w - 2) + "┘")

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
        n_lines = 2 + len(choices)  # message + blank + choices
        while True:
            h, w = self.stdscr.getmaxyx()
            box_w = min(55, w - 4)
            if box_w < 20:
                box_w = w - 2
            inner = box_w - 4

            box_h = n_lines + 3  # top border + inner + bottom border
            sy = max(0, (h - box_h) // 2)
            sx = max(0, (w - box_w) // 2)

            t = title[:inner]
            dashes = max(1, box_w - 5 - len(t))
            self._safe_addstr(sy, sx, "┌─ " + t + " " + "─" * dashes + "┐")

            blank = "│" + " " * (box_w - 2) + "│"
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
            self._safe_addstr(row, sx, blank)
            row += 1
            esc_line = "(Esc) cancel"
            self._safe_addstr(row, sx,
                              "│  " + esc_line[:inner].ljust(inner) + "│")
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
        extra = body_lines or []
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
                tasks.pop(item.index)
                self._save_and_rebuild()
                # Adjust cursor
                self._snap_right_cursor()

        elif item.kind == "ms_task":
            ms_idx, t_idx = item.index
            ms = proj["milestones"][ms_idx]
            tasks = ms.get("tasks", [])
            if 0 <= t_idx < len(tasks):
                tasks.pop(t_idx)
                self._save_and_rebuild()
                self._snap_right_cursor()

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
                desc = tasks[item.index]
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
                desc = tasks[t_idx] if isinstance(tasks[t_idx], str) else tasks[t_idx].get("desc", "")
                if not self._modal_confirm("Delete", f"Delete task '{desc}'?"):
                    return
                tasks.pop(t_idx)
                self._save_and_rebuild()
                self._snap_right_cursor()

    def action_reschedule(self):
        item = self._current_detail_item()
        proj = self._current_project()
        if not item or not proj or item.kind != "milestone":
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

        choice = self._modal_input("Add Item", "Type (m/t): ",
            ["(m) milestone", "(t) task"])
        if not choice:
            return

        if choice.lower().startswith("m"):
            name = self._modal_input("Add Milestone", "Name: ")
            if not name:
                return
            due_str = self._modal_input("Add Milestone", "Due date: ",
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

            if ms_target:
                desc = self._modal_input("Add Task", "Description: ",
                    [f"Milestone: {ms_target['name']}"])
            else:
                desc = self._modal_input("Add Task", "Description: ")
            if not desc:
                return
            if ms_target:
                if "tasks" not in ms_target:
                    ms_target["tasks"] = []
                ms_target["tasks"].append(desc)
            else:
                if "tasks" not in proj:
                    proj["tasks"] = []
                proj["tasks"].append(desc)
            self._save_and_rebuild()

    def action_inbox_add(self):
        """Quick-capture an item into the Inbox project."""
        text = self._modal_input("Inbox", "Add: ")
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
        task_text = proj["tasks"][item.index]

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
            target["tasks"].append(task_text)
        elif choice == "m":
            due_str = self._modal_input("Milestone Due Date", "Due: ",
                [f"Milestone: {task_text}", "", "Format: YYYY-MM-DD"])
            if not due_str:
                return
            try:
                due = parse_date(due_str)
            except ValueError:
                return
            if "milestones" not in target:
                target["milestones"] = []
            target["milestones"].append({"name": task_text, "due": str(due), "done": False})

        proj["tasks"].pop(item.index)
        self._save_and_rebuild()

    def action_add_project(self):
        """Guided Q&A to add a new project."""
        name = self._modal_input("Add Project", "Name: ")
        if not name:
            return

        category = self._modal_input("Add Project", "Category: ",
            [f"Project: {name}", "",
             "e.g., research, software, admin"])
        deadline_str = self._modal_input("Add Project", "Deadline: ",
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

    # ─── Schedule actions ─────────────────────────────────────────────────

    def action_add_event(self):
        title = self._modal_input("Add New Event", "Title: ",
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
            ev["date"] = self._modal_input_date("One-time Event",
                f"Date [{self.sched_date}]: ",
                str(self.sched_date))
            ev["start"] = self._modal_input_time("One-time Event",
                "Start time (HH:MM): ")
            ev["end"] = self._modal_input_time("One-time Event",
                "End time (HH:MM): ")
            if not ev["start"] or not ev["end"]:
                return
            loc = self._modal_input("One-time Event", "Location: ")
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
        ms = entry["milestone"]
        if ms.get("done"):
            ms.pop("done", None)
            ms.pop("completed_date", None)
            self._save_and_rebuild()
            return
        ms["done"] = True
        ms["completed_date"] = str(today())
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
        ms = entry["milestone"]
        name = ms.get("name", "")
        if not self._modal_confirm("Delete", f"Delete milestone '{name}'?"):
            return
        proj = entry["project"]
        proj["milestones"].pop(entry["ms_index"])
        self._save_and_rebuild()

    def _timeline_action_reschedule(self):
        entry = self._current_timeline_entry()
        if not entry:
            return
        ms = entry["milestone"]
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
        ms["due"] = str(new_date)
        self._save_and_rebuild()

    # ─── Main loop ────────────────────────────────────────────────────────

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
        views = _CAL_VIEWS if self.mode == MODE_CALENDAR else _TASK_VIEWS
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
        """Switch between task mode and calendar mode."""
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
        elif key == ord("S"):
            self._toggle_week_start()
            self._rebuild_schedule_month()
            self._rebuild_detail()

    def _handle_right_keys(self, key):
        if key in (curses.KEY_UP, ord("k")):
            self._move_right(-1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self._move_right(1)
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


# ─── Entry point ──────────────────────────────────────────────────────────────

def run_tui():
    curses.set_escdelay(25)
    curses.wrapper(lambda stdscr: ProjectBrowser(stdscr).run())


if __name__ == "__main__":
    run_tui()
