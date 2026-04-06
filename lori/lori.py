#!/usr/bin/env python3
"""lori — Life Orchestration & Routine Intelligence"""

import argparse
import datetime
import json
import os
import pathlib
import smtplib
import subprocess
import sys
import textwrap
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
import yaml

# ─── Paths ────────────────────────────────────────────────────────────────────

LORI_DIR = pathlib.Path.home() / ".lori"
CONFIG_FILE = LORI_DIR / "config.yaml"
PROJECTS_FILE = LORI_DIR / "projects.yaml"
SCHEDULE_FILE = LORI_DIR / "schedule.yaml"
LOCATIONS_FILE = LORI_DIR / "locations.yaml"
ALERTS_FILE = LORI_DIR / ".alerts_sent"
DASHBOARD_FILE = LORI_DIR / "dashboard.html"

# ─── Data helpers ─────────────────────────────────────────────────────────────

def load_yaml(path):
    if not path.exists():
        return {} if "config" in path.name or "locations" in path.name else []
    with open(path) as f:
        data = yaml.safe_load(f)
    if data is None:
        return {} if "config" in path.name or "locations" in path.name else []
    return data


def save_yaml(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def load_config():
    return load_yaml(CONFIG_FILE)


def save_config(config):
    save_yaml(CONFIG_FILE, config)


def load_projects():
    return load_yaml(PROJECTS_FILE)


def save_projects(projects):
    save_yaml(PROJECTS_FILE, projects)


def load_schedule():
    data = load_yaml(SCHEDULE_FILE)
    if isinstance(data, dict):
        return data.get("events", [])
    return data


def save_schedule(events):
    save_yaml(SCHEDULE_FILE, {"events": events})


def load_locations():
    return load_yaml(LOCATIONS_FILE)


def save_locations(locs):
    save_yaml(LOCATIONS_FILE, locs)


# ─── Task helpers ─────────────────────────────────────────────────────────────

def _task_text(t):
    """Extract display text from a task (string or dict)."""
    return t if isinstance(t, str) else t.get("desc", str(t))


def _task_due(t):
    """Extract due date string from a task, or None."""
    if isinstance(t, dict):
        return t.get("due")
    return None


# ─── Date/time utilities ─────────────────────────────────────────────────────

def today():
    return datetime.date.today()


def now():
    return datetime.datetime.now()


def parse_date(s):
    if isinstance(s, datetime.date):
        return s
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d"):
        try:
            d = datetime.datetime.strptime(s, fmt).date()
            if fmt == "%m/%d":
                d = d.replace(year=today().year)
            return d
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {s}")


def parse_time(s):
    if isinstance(s, datetime.time):
        return s
    for fmt in ("%H:%M", "%H", "%I:%M%p", "%I:%M %p"):
        try:
            return datetime.datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse time: {s}")


def fmt_date(d):
    return d.strftime("%a %b %-d")


def fmt_time(t):
    return t.strftime("%H:%M")


def convert_event_time(time_str, event_tz_str, local_tz_str):
    """Convert a time string from event_tz to local_tz for today's date.
    Returns the converted datetime.time, or original parsed time if no conversion needed."""
    if not event_tz_str or not local_tz_str or event_tz_str == local_tz_str:
        return parse_time(time_str)
    from zoneinfo import ZoneInfo
    t = parse_time(time_str)
    dt = datetime.datetime.combine(datetime.date.today(), t, tzinfo=ZoneInfo(event_tz_str))
    local_dt = dt.astimezone(ZoneInfo(local_tz_str))
    return local_dt.time()


def day_name_to_int(name):
    names = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
             "friday": 4, "saturday": 5, "sunday": 6}
    return names.get(name.lower())


# ─── Schedule expansion ──────────────────────────────────────────────────────

def expand_events_for_date(events, target_date):
    """Expand recurring events and filter for a specific date."""
    result = []
    dow = target_date.weekday()
    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    target_day = day_names[dow]

    for _sched_idx, ev in enumerate(events):
        ev = dict(ev)  # copy
        ev["_sched_idx"] = _sched_idx
        rec = ev.get("recurring")

        if rec:
            # Skip excluded dates
            except_dates = ev.get("except_dates", [])
            if except_dates:
                if target_date in [parse_date(d) if isinstance(d, str) else d for d in except_dates]:
                    continue
            # Skip past end_date
            end_date = ev.get("end_date")
            if end_date:
                if target_date > (parse_date(end_date) if isinstance(end_date, str) else end_date):
                    continue
            # Recurring event
            if rec == "daily":
                days = ev.get("days", day_names)
                if target_day not in [d.lower() for d in days]:
                    continue
            elif rec == "weekly":
                # Support single day or list of days
                ev_days = ev.get("days")
                if ev_days:
                    if target_day not in [d.lower() for d in ev_days]:
                        continue
                elif ev.get("day", "").lower() != target_day:
                    continue
                # Support interval (e.g. every 2 weeks) with start_date anchor
                interval = ev.get("interval", 1)
                if interval > 1:
                    anchor = ev.get("start_date")
                    if anchor:
                        anchor_date = parse_date(anchor)
                        # Compare Monday of each week
                        anchor_monday = anchor_date - datetime.timedelta(days=anchor_date.weekday())
                        target_monday = target_date - datetime.timedelta(days=target_date.weekday())
                        weeks_diff = (target_monday - anchor_monday).days // 7
                        if weeks_diff % interval != 0:
                            continue
            elif rec == "monthly":
                day_of_week = ev.get("day_of_week")
                if day_of_week:
                    # Nth weekday pattern (e.g. 3rd Wednesday)
                    if target_day != day_of_week.lower():
                        continue
                    wom = ev.get("week_of_month", 1)
                    if wom == -1:
                        # Last occurrence: next week would be different month
                        next_week = target_date + datetime.timedelta(days=7)
                        if next_week.month == target_date.month:
                            continue
                    else:
                        occurrence = (target_date.day - 1) // 7 + 1
                        if occurrence != wom:
                            continue
                else:
                    # Fixed day of month
                    if target_date.day != ev.get("day_of_month", 1):
                        continue
                # Optional interval (every N months) with start_date anchor
                interval = ev.get("interval", 1)
                if interval > 1:
                    anchor = ev.get("start_date")
                    if anchor:
                        anchor_date = parse_date(anchor)
                        months_diff = (target_date.year - anchor_date.year) * 12 + (target_date.month - anchor_date.month)
                        if months_diff % interval != 0:
                            continue
            ev["date"] = target_date
            result.append(ev)
        else:
            # Check dates list (custom recurring dates)
            dates_list = ev.get("dates")
            if dates_list:
                if target_date in [parse_date(d) for d in dates_list]:
                    ev["date"] = target_date
                    result.append(ev)
                continue
            # One-time event
            ev_date = ev.get("date")
            if ev_date and parse_date(ev_date) == target_date:
                ev["date"] = target_date
                result.append(ev)

    # Sort by start time
    def sort_key(e):
        t = e.get("start") or e.get("depart") or "23:59"
        return parse_time(t)

    result.sort(key=sort_key)
    return result


# ─── Free time calculation ────────────────────────────────────────────────────

DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

def _normalize_slots(value):
    """Normalize work hours value to list of [start, end] slots.
    Accepts: [9,18], [[9,12],[13,17]], or nested variants."""
    if not value:
        return [[9, 18]]
    if isinstance(value[0], list):
        return value  # already [[9,12],[13,17]]
    return [value]    # single [9,18] → [[9,18]]


def get_work_hours(config, day=None):
    """Return list of [start, end] work-hour slots for a given day (0=Mon).
    Supports: [9,18], [[9,12],[13,17]], and per-day dict formats."""
    default = config.get("work_hours", [9, 18])
    if isinstance(default, dict):
        base = default.get("default", [9, 18])
        if day is not None:
            day_key = DAY_NAMES[day] if isinstance(day, int) else day
            return _normalize_slots(default.get(day_key, base))
        return _normalize_slots(base)
    return _normalize_slots(default)


def calc_free_time(events_today, config, date=None):
    """Calculate free time slots within work hours (supports multiple slots per day)."""
    day = (date or today()).weekday()
    ref = date or today()
    slots = get_work_hours(config, day)

    # Build busy list from events
    busy = []
    for ev in events_today:
        start = ev.get("start") or ev.get("depart")
        end = ev.get("end")
        if not start:
            continue
        s = parse_time(start)
        if end:
            e = parse_time(end)
        elif ev.get("type") == "travel":
            dt = datetime.datetime.combine(ref, s) + datetime.timedelta(minutes=30)
            e = dt.time()
        else:
            dt = datetime.datetime.combine(ref, s) + datetime.timedelta(hours=1)
            e = dt.time()
        if s < e:
            busy.append((s, e))

    busy.sort()

    # Merge overlapping busy periods
    merged = []
    for s, e in busy:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    # Find free gaps within each work slot
    free = []
    for ws_h, we_h in slots:
        ws = datetime.time(ws_h, 0)
        we = datetime.time(23, 59) if we_h >= 24 else datetime.time(we_h, 0)
        cursor = ws
        for s, e in merged:
            # Clamp busy period to this work slot
            s_clamped = max(s, ws)
            e_clamped = min(e, we)
            if s_clamped >= we:
                break
            if s_clamped < e_clamped:
                if cursor < s_clamped:
                    free.append((cursor, s_clamped))
                cursor = max(cursor, e_clamped)
        if cursor < we:
            free.append((cursor, we))

    total_mins = sum(
        (datetime.datetime.combine(ref, e) - datetime.datetime.combine(ref, s)).seconds // 60
        for s, e in free
    )
    return free, total_mins


# ─── OSRM / Nominatim ────────────────────────────────────────────────────────

OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


def geocode(address):
    """Geocode address to (lat, lon) using Nominatim."""
    resp = requests.get(NOMINATIM_URL, params={
        "q": address, "format": "json", "limit": 1
    }, headers={"User-Agent": "lori-personal-assistant/1.0"}, timeout=10)
    resp.raise_for_status()
    results = resp.json()
    if not results:
        return None
    return (float(results[0]["lat"]), float(results[0]["lon"]))


def get_driving_time(from_coords, to_coords):
    """Get driving time between two (lat, lon) pairs using OSRM."""
    # OSRM uses lon,lat order
    coords_str = f"{from_coords[1]},{from_coords[0]};{to_coords[1]},{to_coords[0]}"
    url = f"{OSRM_URL}/{coords_str}"
    resp = requests.get(url, params={"overview": "false"}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        return None
    route = data["routes"][0]
    return {
        "duration_seconds": route["duration"],
        "duration_minutes": round(route["duration"] / 60, 1),
        "distance_km": round(route["distance"] / 1000, 1),
        "distance_miles": round(route["distance"] / 1609.34, 1),
    }


def resolve_location(name_or_addr, locations):
    """Resolve a location name or address to coords, geocoding if needed."""
    if name_or_addr in locations:
        loc = locations[name_or_addr]
        if "coords" in loc:
            return tuple(loc["coords"]), locations
    # Try geocoding
    addr = name_or_addr
    if name_or_addr in locations and "address" in locations[name_or_addr]:
        addr = locations[name_or_addr]["address"]
    coords = geocode(addr)
    if coords and name_or_addr in locations:
        locations[name_or_addr]["coords"] = list(coords)
        save_locations(locations)
    return coords, locations


# ─── Email ────────────────────────────────────────────────────────────────────

def send_email(to_addr, subject, body_html, config):
    """Send an email using system mail or SMTP."""
    method = config.get("email", {}).get("method", "mail")

    if method == "smtp":
        smtp_conf = config.get("email", {})
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = smtp_conf.get("from", to_addr)
        msg["To"] = to_addr
        msg.attach(MIMEText(body_html, "html"))
        with smtplib.SMTP(smtp_conf.get("host", "localhost"), smtp_conf.get("port", 25)) as s:
            if smtp_conf.get("tls"):
                s.starttls()
            if smtp_conf.get("user"):
                s.login(smtp_conf["user"], smtp_conf["password"])
            s.sendmail(msg["From"], [to_addr], msg.as_string())
    else:
        # Build proper MIME message and send via sendmail
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["To"] = to_addr
        msg["From"] = to_addr
        msg.attach(MIMEText(body_html, "html"))
        proc = subprocess.run(
            ["/usr/sbin/sendmail", "-t"],
            input=msg.as_string(), capture_output=True, text=True
        )
        if proc.returncode != 0:
            print(f"mail error: {proc.stderr}", file=sys.stderr)


# ─── Fuzzy matching ──────────────────────────────────────────────────────────

def fuzzy_match(query, items, key=None):
    """Simple fuzzy matching — case-insensitive substring match, scored by position."""
    query_lower = query.lower()
    scored = []
    for item in items:
        text = key(item) if key else item
        text_lower = text.lower()
        if query_lower in text_lower:
            score = text_lower.index(query_lower)
            scored.append((score, item))
        elif all(c in text_lower for c in query_lower):
            scored.append((100, item))
    scored.sort(key=lambda x: x[0])
    return [item for _, item in scored]


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI: init
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_init(args):
    """Create ~/.lori/ with template YAML files."""
    if LORI_DIR.exists() and not args.force:
        print(f"~/.lori/ already exists. Use --force to overwrite templates.")
        return

    LORI_DIR.mkdir(parents=True, exist_ok=True)

    if not CONFIG_FILE.exists() or args.force:
        save_yaml(CONFIG_FILE, {
            "work_hours": [9, 18],
            "timezone": "America/New_York",
            "briefing_days_ahead": 7,
            "location": "Gainesville,FL",
            "weather": {"api_key": "YOUR_OPENWEATHERMAP_KEY"},
            "email": {"to": "your@email.com", "method": "mail"},
            "alert_minutes_before": 15,
        })

    if not PROJECTS_FILE.exists() or args.force:
        save_yaml(PROJECTS_FILE, [])

    if not SCHEDULE_FILE.exists() or args.force:
        save_yaml(SCHEDULE_FILE, {"events": []})

    if not LOCATIONS_FILE.exists() or args.force:
        save_yaml(LOCATIONS_FILE, {
            "home": {"address": "", "coords": []},
            "office": {"address": "", "coords": []},
        })

    print(f"Initialized ~/.lori/ with template files.")
    print(f"  Edit {CONFIG_FILE} to configure preferences.")
    print(f"  Edit {LOCATIONS_FILE} to add your locations.")


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI: setup
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_setup(args):
    """Interactive configuration wizard."""
    # Auto-init if ~/.lori/ doesn't exist
    if not LORI_DIR.exists():
        print("No ~/.lori/ found — running init first...\n")
        cmd_init(args)
        print()

    config = load_config()

    print("lori setup — interactive configuration")
    print("Press Enter to keep current value shown in [brackets].\n")

    # 1. Work hours
    # Parsing/formatting helpers for slot input
    def _parse_slots(text):
        """Parse '9,17' or '9,12 13,17' into [[9,17]] or [[9,12],[13,17]]."""
        parts = text.strip().split()
        slots = []
        for part in parts:
            nums = part.split(",")
            if len(nums) == 2:
                slots.append([int(nums[0]), int(nums[1])])
        return slots

    def _fmt_slots(slots):
        """Format [[9,12],[13,17]] as '9,12 13,17'."""
        slots = _normalize_slots(slots)
        return " ".join(f"{s},{e}" for s, e in slots)

    def _fmt_slots_display(slots):
        """Format [[9,12],[13,17]] as '9:00–12:00, 13:00–17:00'."""
        slots = _normalize_slots(slots)
        return ", ".join(f"{s}:00–{e}:00" for s, e in slots)

    cur_hours = config.get("work_hours", [9, 18])
    if isinstance(cur_hours, dict):
        cur_default = cur_hours.get("default", [9, 18])
    else:
        cur_default = cur_hours
    cur_default_str = _fmt_slots(cur_default)
    print(f"  Format: start,end — or multiple slots: 9,12 13,17")
    val = input(f"  Default work hours [{cur_default_str}]: ").strip()
    default_hours = _parse_slots(val) if val else _normalize_slots(cur_default)
    # Simplify single slot for cleaner YAML
    if len(default_hours) == 1:
        default_hours = default_hours[0]

    # Per-day overrides
    per_day = input(f"  Set different hours for specific days? [y/N]: ").strip().lower()
    if per_day in ("y", "yes"):
        work = {"default": default_hours}
        # Carry over existing per-day settings
        if isinstance(cur_hours, dict):
            for d in DAY_NAMES:
                if d in cur_hours:
                    work[d] = cur_hours[d]
        day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for i, day in enumerate(DAY_NAMES):
            cur_day = work.get(day)
            if cur_day:
                cur_day_str = _fmt_slots(cur_day)
            else:
                cur_day_str = "default"
            val = input(f"    {day_labels[i]} [{cur_day_str}]: ").strip()
            if val and val.lower() != "default":
                parsed = _parse_slots(val)
                if parsed:
                    work[day] = parsed[0] if len(parsed) == 1 else parsed
            elif val.lower() == "default" and day in work:
                del work[day]
        # If no per-day overrides, simplify to plain value
        if all(d not in work for d in DAY_NAMES):
            config["work_hours"] = default_hours
        else:
            config["work_hours"] = work
    else:
        config["work_hours"] = default_hours

    # 2. Timezone
    cur_tz = config.get("timezone", "America/New_York")
    print(f"  Common timezones: America/New_York, America/Chicago, America/Denver, America/Los_Angeles, UTC")
    val = input(f"  Timezone [{cur_tz}]: ").strip() or cur_tz
    config["timezone"] = val

    # 3. Location
    cur_loc = config.get("location", "Gainesville,FL")
    val = input(f"  Location (city for weather) [{cur_loc}]: ").strip() or cur_loc
    config["location"] = val

    # 4. Weather API key
    weather = config.get("weather", {})
    if not isinstance(weather, dict):
        weather = {}
    cur_key = weather.get("api_key", "")
    display_key = cur_key if cur_key and cur_key != "YOUR_OPENWEATHERMAP_KEY" else ""
    print(f"  Free API key from https://openweathermap.org/api")
    val = input(f"  Weather API key [{display_key or 'none'}]: ").strip() or display_key
    weather["api_key"] = val or "YOUR_OPENWEATHERMAP_KEY"
    config["weather"] = weather

    # 5. Briefing days ahead
    cur_days = config.get("briefing_days_ahead", 7)
    val = input(f"  Briefing days ahead [{cur_days}]: ").strip()
    config["briefing_days_ahead"] = int(val) if val else cur_days

    # 6. Alert minutes before
    cur_alert = config.get("alert_minutes_before", 15)
    val = input(f"  Alert minutes before events [{cur_alert}]: ").strip()
    config["alert_minutes_before"] = int(val) if val else cur_alert

    # 7. Email address
    email = config.get("email", {})
    if not isinstance(email, dict):
        email = {}
    cur_email = email.get("to", "")
    display_email = cur_email if cur_email and cur_email != "your@email.com" else ""
    val = input(f"  Email address [{display_email or 'none'}]: ").strip() or display_email
    email["to"] = val or "your@email.com"

    # 8. Email method
    cur_method = email.get("method", "mail")
    print(f"  Email method:  (1) mail (system)  (2) smtp")
    method_input = input(f"  Choice [{1 if cur_method == 'mail' else 2}]: ").strip()
    if method_input == "2":
        email["method"] = "smtp"
    elif method_input == "1":
        email["method"] = "mail"
    # else keep current

    # 9. SMTP details (only if smtp)
    if email.get("method") == "smtp":
        smtp = email.get("smtp", {})
        if not isinstance(smtp, dict):
            smtp = {}
        print()
        val = input(f"  SMTP host [{smtp.get('host', '')}]: ").strip()
        if val:
            smtp["host"] = val
        val = input(f"  SMTP port [{smtp.get('port', 587)}]: ").strip()
        smtp["port"] = int(val) if val else smtp.get("port", 587)
        val = input(f"  SMTP user [{smtp.get('user', '')}]: ").strip()
        if val:
            smtp["user"] = val
        val = input(f"  SMTP password [{smtp.get('password', '')}]: ").strip()
        if val:
            smtp["password"] = val
        cur_tls = smtp.get("tls", True)
        val = input(f"  SMTP TLS [{'yes' if cur_tls else 'no'}]: ").strip().lower()
        if val in ("yes", "y", "true", "1"):
            smtp["tls"] = True
        elif val in ("no", "n", "false", "0"):
            smtp["tls"] = False
        val = input(f"  SMTP from address [{smtp.get('from', '')}]: ").strip()
        if val:
            smtp["from"] = val
        email["smtp"] = smtp

    config["email"] = email

    # Save
    save_yaml(CONFIG_FILE, config)

    # Summary
    print(f"\n✓ Setup complete. Config saved to {CONFIG_FILE}")
    wh = config["work_hours"]
    if isinstance(wh, dict):
        print(f"  Work hours:    {_fmt_slots_display(wh['default'])} (default)")
        day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for i, day in enumerate(DAY_NAMES):
            if day in wh:
                print(f"                 {day_labels[i]}: {_fmt_slots_display(wh[day])}")
    else:
        print(f"  Work hours:    {_fmt_slots_display(wh)}")
    print(f"  Timezone:      {config['timezone']}")
    print(f"  Location:      {config['location']}")
    print(f"  Email:         {email['to']} via {email.get('method', 'mail')}")


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI: briefing
# ═══════════════════════════════════════════════════════════════════════════════

def greeting():
    h = now().hour
    if h < 12:
        return "Good morning!"
    elif h < 17:
        return "Good afternoon!"
    else:
        return "Good evening!"


def cmd_briefing(args):
    config = load_config()
    projects = load_projects()
    events = load_schedule()
    td = today()
    days_ahead = config.get("briefing_days_ahead", 7)

    if args.short:
        print_short_briefing(config, projects, events, td, days_ahead)
    else:
        print_full_briefing(config, projects, events, td, days_ahead)


def print_full_briefing(config, projects, events, td, days_ahead):
    date_str = td.strftime("%A, %B %-d, %Y")
    w = 54

    print("═" * w)
    print(f"  {greeting()} — {date_str}".center(w))
    print("═" * w)
    print()

    # Today's events
    today_events = expand_events_for_date(events, td)
    locations = load_locations()

    if today_events:
        print(f"TODAY ({len(today_events)} items)")
        for ev in today_events:
            start = ev.get("start") or ev.get("depart") or ""
            end = ev.get("end") or ""
            title = ev.get("title", "")
            tag = ""
            if ev.get("type") == "travel":
                fr = ev.get("from", "")
                to = ev.get("to", "")
                # Try to get driving time
                dur = ""
                try:
                    fc, locations = resolve_location(fr, locations)
                    tc, locations = resolve_location(to, locations)
                    if fc and tc:
                        info = get_driving_time(fc, tc)
                        if info:
                            dur = f", {int(info['duration_minutes'])} min"
                except Exception:
                    pass
                tag = f"[travel{dur}]"
            elif ev.get("type") == "blocked":
                tag = "[blocked]"
            elif ev.get("location"):
                tag = f"[{ev['location']}]"

            time_str = fmt_time(parse_time(start)) if start else ""
            if end:
                time_str += f"-{fmt_time(parse_time(end))}"
            print(f"  {time_str:13s} {title:30s} {tag}")
    else:
        print("TODAY — no events scheduled")

    print()

    # Free time
    free, total_mins = calc_free_time(today_events, config)
    if free:
        slots = ", ".join(f"{fmt_time(s)}-{fmt_time(e)}" for s, e in free)
        hours = total_mins / 60
        print(f"FREE TIME TODAY: ~{hours:.1f}h ({slots})")
    else:
        print("FREE TIME TODAY: none within work hours")
    print()

    # Overdue
    overdue = []
    for p in projects:
        if p.get("status") != "active":
            continue
        for m in p.get("milestones", []):
            if m.get("done"):
                continue
            due = parse_date(m["due"]) if m.get("due") else None
            if due and due < td:
                days_late = (td - due).days
                overdue.append((p["name"], m["name"], days_late))
            for t in m.get("tasks", []):
                if isinstance(t, dict) and not t.get("done") and t.get("due"):
                    try:
                        t_due = parse_date(t["due"])
                    except ValueError:
                        continue
                    if t_due < td:
                        overdue.append((p["name"], t.get("desc", ""), (td - t_due).days))
        for t in p.get("tasks", []):
            if isinstance(t, dict) and not t.get("done") and t.get("due"):
                try:
                    t_due = parse_date(t["due"])
                except ValueError:
                    continue
                if t_due < td:
                    overdue.append((p["name"], t.get("desc", ""), (td - t_due).days))

    if overdue:
        print("OVERDUE")
        for pname, mname, days in sorted(overdue, key=lambda x: -x[2]):
            print(f'  * {pname} -> "{mname}" ({days} day{"s" if days != 1 else ""} overdue)')
        print()

    # Due this week
    week_end = td + datetime.timedelta(days=days_ahead)
    due_soon = []
    for p in projects:
        if p.get("status") != "active":
            continue
        for m in p.get("milestones", []):
            if m.get("done"):
                continue
            due = parse_date(m["due"]) if m.get("due") else None
            if due and td <= due <= week_end:
                due_soon.append((p["name"], m["name"], due))
            for t in m.get("tasks", []):
                if isinstance(t, dict) and not t.get("done") and t.get("due"):
                    try:
                        t_due = parse_date(t["due"])
                    except ValueError:
                        continue
                    if td <= t_due <= week_end:
                        due_soon.append((p["name"], t.get("desc", ""), t_due))
        for t in p.get("tasks", []):
            if isinstance(t, dict) and not t.get("done") and t.get("due"):
                try:
                    t_due = parse_date(t["due"])
                except ValueError:
                    continue
                if td <= t_due <= week_end:
                    due_soon.append((p["name"], t.get("desc", ""), t_due))

    if due_soon:
        print("DUE THIS WEEK")
        for pname, mname, due in sorted(due_soon, key=lambda x: x[2]):
            print(f"  * {pname} -> \"{mname}\" ({fmt_date(due)})")
        print()

    # Active projects summary
    active = [p for p in projects if p.get("status") == "active"]
    if active:
        cats = {}
        for p in active:
            c = p.get("category", "other")
            cats[c] = cats.get(c, 0) + 1
        cat_str = "  ".join(f"{c.title()} ({n})" for c, n in sorted(cats.items()))
        print(f"ACTIVE PROJECTS ({len(active)})")
        print(f"  {cat_str}")
        print()

    # Next actions (first task from each active project)
    actions = []
    for p in active:
        tasks = p.get("tasks", [])
        if tasks:
            t = tasks[0]
            task = _task_text(t)
            due_s = _task_due(t)
            due_info = ""
            if due_s:
                due_d = parse_date(due_s)
                days = (due_d - td).days
                if days < 0:
                    due_info = f" ({-days}d overdue)"
                else:
                    due_info = f" (due {fmt_date(due_d)})"
            actions.append((task, pname := p["name"], due_info))
    if actions:
        print("NEXT ACTIONS")
        for task, pname, due_info in actions[:6]:
            print(f"  * {task}{due_info} [{pname}]")
        print()

    print("═" * w)


def print_short_briefing(config, projects, events, td, days_ahead):
    date_str = td.strftime("%a %b %-d")
    today_events = expand_events_for_date(events, td)
    free, total_mins = calc_free_time(today_events, config)
    hours = total_mins / 60

    # Count overdue
    overdue_count = 0
    for p in projects:
        if p.get("status") != "active":
            continue
        for m in p.get("milestones", []):
            if not m.get("done") and m.get("due"):
                if parse_date(m["due"]) < td:
                    overdue_count += 1

    active_count = sum(1 for p in projects if p.get("status") == "active")

    print(f"── lori | {date_str} ──  {len(today_events)} events, ~{hours:.1f}h free, "
          f"{active_count} projects"
          + (f", {overdue_count} overdue!" if overdue_count else ""))

    if today_events:
        for ev in today_events[:4]:
            start = ev.get("start") or ev.get("depart") or ""
            title = ev.get("title", "")
            t = fmt_time(parse_time(start)) if start else "     "
            print(f"  {t}  {title}")
        if len(today_events) > 4:
            print(f"  ... and {len(today_events) - 4} more")


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI: week
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_week(args):
    config = load_config()
    events = load_schedule()
    projects = load_projects()
    td = today()

    print(f"\n  Weekly Overview — {fmt_date(td)} to {fmt_date(td + datetime.timedelta(days=6))}\n")

    for i in range(7):
        d = td + datetime.timedelta(days=i)
        day_events = expand_events_for_date(events, d)
        free, total_mins = calc_free_time(day_events, config, date=d)
        hours = total_mins / 60
        bar = "█" * int(hours) + "░" * (9 - int(hours))
        marker = " ◄ today" if i == 0 else ""
        print(f"  {d.strftime('%a %b %d')}  {bar} {hours:4.1f}h free  ({len(day_events)} events){marker}")

    # Deadlines this week
    week_end = td + datetime.timedelta(days=7)
    deadlines = []
    for p in projects:
        if p.get("status") != "active":
            continue
        for m in p.get("milestones", []):
            if m.get("done"):
                continue
            due = parse_date(m["due"]) if m.get("due") else None
            if due and td <= due < week_end:
                deadlines.append((due, p["name"], m["name"]))
            for t in m.get("tasks", []):
                if isinstance(t, dict) and not t.get("done") and t.get("due"):
                    try:
                        t_due = parse_date(t["due"])
                    except ValueError:
                        continue
                    if td <= t_due < week_end:
                        deadlines.append((t_due, p["name"], t.get("desc", "")))
        for t in p.get("tasks", []):
            if isinstance(t, dict) and not t.get("done") and t.get("due"):
                try:
                    t_due = parse_date(t["due"])
                except ValueError:
                    continue
                if td <= t_due < week_end:
                    deadlines.append((t_due, p["name"], t.get("desc", "")))
    if deadlines:
        print(f"\n  Deadlines this week:")
        for due, pname, mname in sorted(deadlines):
            print(f"    {fmt_date(due)}: {mname} [{pname}]")
    print()


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI: projects
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_projects(args):
    projects = load_projects()
    if not projects:
        print("No projects. Use `lori add project` to add one.")
        return

    td = today()
    by_cat = {}
    for p in projects:
        if args.all or p.get("status") == "active":
            cat = p.get("category", "other")
            by_cat.setdefault(cat, []).append(p)

    for cat, projs in sorted(by_cat.items()):
        print(f"\n  {cat.upper()} ({len(projs)})")
        for p in projs:
            status_icon = {"active": "●", "paused": "◌", "completed": "✓"}.get(p.get("status", "active"), "?")
            deadline = ""
            if p.get("deadline"):
                dl = parse_date(p["deadline"])
                days = (dl - td).days
                if days < 0:
                    deadline = f" (OVERDUE {-days}d)"
                elif days <= 7:
                    deadline = f" (due in {days}d)"
                else:
                    deadline = f" (due {fmt_date(dl)})"

            ms = p.get("milestones", [])
            done_ms = sum(1 for m in ms if m.get("done"))
            ms_str = f" [{done_ms}/{len(ms)} milestones]" if ms else ""

            print(f"    {status_icon} {p['name']}{deadline}{ms_str}")
    print()


def cmd_show(args):
    projects = load_projects()
    matches = fuzzy_match(args.name, projects, key=lambda p: p["name"])
    if not matches:
        print(f"No project matching '{args.name}'")
        return

    p = matches[0]
    td = today()
    print(f"\n  {p['name']}")
    print(f"  {'─' * len(p['name'])}")
    print(f"  Category: {p.get('category', 'other')}")
    print(f"  Status:   {p.get('status', 'active')}")
    if p.get("deadline"):
        dl = parse_date(p["deadline"])
        days = (dl - td).days
        overdue = " (OVERDUE)" if days < 0 else ""
        print(f"  Deadline: {p['deadline']} ({days}d){overdue}")

    if p.get("milestones"):
        print(f"\n  Milestones:")
        for m in p["milestones"]:
            check = "✓" if m.get("done") else " "
            due_str = ""
            if m.get("due"):
                due = parse_date(m["due"])
                days = (due - td).days
                if m.get("done"):
                    due_str = f" (done)"
                elif days < 0:
                    due_str = f" ({-days}d overdue)"
                else:
                    due_str = f" (due {fmt_date(due)})"
            rescheduled = ""
            if m.get("rescheduled"):
                rescheduled = f" [rescheduled {m['rescheduled']}]"
            print(f"    [{check}] {m['name']}{due_str}{rescheduled}")
            for t in m.get("tasks", []):
                task_str = _task_text(t)
                t_due_s = _task_due(t)
                t_due_info = ""
                if t_due_s:
                    t_due_d = parse_date(t_due_s)
                    t_days = (t_due_d - td).days
                    if t_days < 0:
                        t_due_info = f" ({-t_days}d overdue)"
                    else:
                        t_due_info = f" (due {fmt_date(t_due_d)})"
                print(f"          · {task_str}{t_due_info}")

    if p.get("tasks"):
        print(f"\n  Tasks:")
        for i, t in enumerate(p["tasks"], 1):
            task_str = _task_text(t)
            due_s = _task_due(t)
            due_info = ""
            if due_s:
                due_d = parse_date(due_s)
                days = (due_d - td).days
                if days < 0:
                    due_info = f" ({-days}d overdue)"
                else:
                    due_info = f" (due {fmt_date(due_d)})"
            print(f"    {i}. {task_str}{due_info}")

    if p.get("notes"):
        print(f"\n  Notes: {p['notes']}")
    print()


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI: add project (guided Q&A)
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_add_project(args):
    print("\n  Add New Project\n")
    name = input("  Project name: ").strip()
    if not name:
        print("  Cancelled.")
        return

    print("  Categories: research, software, admin, coursework")
    category = input("  Category [research]: ").strip().lower() or "research"

    deadline = input("  Deadline (YYYY-MM-DD, or blank): ").strip()

    milestones = []
    print("  Add milestones (blank to finish):")
    while True:
        mname = input("    Milestone name: ").strip()
        if not mname:
            break
        mdue = input(f"    Due date for '{mname}': ").strip()
        milestones.append({"name": mname, "due": mdue, "done": False})

    tasks = []
    print("  Add tasks (blank to finish):")
    while True:
        task = input("    Task: ").strip()
        if not task:
            break
        tasks.append(task)

    notes = input("  Notes (optional): ").strip()

    project = {
        "name": name,
        "category": category,
        "status": "active",
    }
    if deadline:
        project["deadline"] = deadline
    if milestones:
        project["milestones"] = milestones
    if tasks:
        project["tasks"] = tasks
    if notes:
        project["notes"] = notes

    projects = load_projects()
    projects.append(project)
    save_projects(projects)
    print(f"\n  Added project: {name}")


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI: add event (guided Q&A)
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_add_event(args):
    print("\n  Add New Event\n")
    title = input("  Event title: ").strip()
    if not title:
        print("  Cancelled.")
        return

    print("  Type: (1) one-time  (2) recurring  (3) travel  (4) blocked")
    etype = input("  Type [1]: ").strip() or "1"

    events = load_schedule()

    if etype == "2":
        # Recurring
        print("  Recurrence: (1) weekly  (2) daily")
        rec = input("  [1]: ").strip() or "1"
        ev = {"title": title}
        if rec == "1":
            ev["recurring"] = "weekly"
            day = input("  Day of week: ").strip().lower()
            ev["day"] = day
        else:
            ev["recurring"] = "daily"
            days_input = input("  Days (comma-separated, or 'all'): ").strip().lower()
            if days_input != "all":
                ev["days"] = [d.strip() for d in days_input.split(",")]
        ev["start"] = input("  Start time (HH:MM): ").strip()
        ev["end"] = input("  End time (HH:MM): ").strip()
        loc = input("  Location (optional): ").strip()
        if loc:
            ev["location"] = loc
    elif etype == "3":
        # Travel
        date = input("  Date (YYYY-MM-DD): ").strip()
        depart = input("  Depart time (HH:MM): ").strip()
        fr = input("  From location: ").strip()
        to = input("  To location: ").strip()
        ev = {
            "title": title,
            "type": "travel",
            "date": date,
            "depart": depart,
            "from": fr,
            "to": to,
        }
    elif etype == "4":
        # Blocked
        print("  Recurrence: (1) one-time  (2) recurring")
        rec = input("  [1]: ").strip() or "1"
        ev = {"title": title, "type": "blocked"}
        if rec == "2":
            ev["recurring"] = "daily"
            days_input = input("  Days (comma-separated, or 'all'): ").strip().lower()
            if days_input != "all":
                ev["days"] = [d.strip() for d in days_input.split(",")]
        else:
            ev["date"] = input("  Date (YYYY-MM-DD): ").strip()
        ev["start"] = input("  Start time (HH:MM): ").strip()
        ev["end"] = input("  End time (HH:MM): ").strip()
    else:
        # One-time
        date = input("  Date (YYYY-MM-DD): ").strip()
        start = input("  Start time (HH:MM): ").strip()
        end = input("  End time (HH:MM): ").strip()
        loc = input("  Location (optional): ").strip()
        ev = {"title": title, "date": date, "start": start, "end": end}
        if loc:
            ev["location"] = loc

    events.append(ev)
    save_schedule(events)
    print(f"\n  Added event: {title}")


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI: add task / milestone
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_add_task(args):
    projects = load_projects()
    matches = fuzzy_match(args.project, projects, key=lambda p: p["name"])
    if not matches:
        print(f"No project matching '{args.project}'")
        return
    p = matches[0]
    if "tasks" not in p:
        p["tasks"] = []
    if getattr(args, "due", None):
        p["tasks"].append({"desc": args.desc, "due": args.due})
    else:
        p["tasks"].append(args.desc)
    save_projects(projects)
    due_str = f" (due {args.due})" if getattr(args, "due", None) else ""
    print(f"  Added task to {p['name']}: {args.desc}{due_str}")


def cmd_add_milestone(args):
    projects = load_projects()
    matches = fuzzy_match(args.project, projects, key=lambda p: p["name"])
    if not matches:
        print(f"No project matching '{args.project}'")
        return
    p = matches[0]
    if "milestones" not in p:
        p["milestones"] = []
    p["milestones"].append({"name": args.name, "due": args.due, "done": False})
    save_projects(projects)
    print(f"  Added milestone to {p['name']}: {args.name} (due {args.due})")


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI: done (fuzzy match)
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_done(args):
    projects = load_projects()
    query = args.item
    found = False

    # Search milestones first
    for p in projects:
        for m in p.get("milestones", []):
            if not m.get("done") and query.lower() in m["name"].lower():
                m["done"] = True
                m["completed_date"] = str(today())
                save_projects(projects)
                print(f"  ✓ Marked done: {m['name']} [{p['name']}]")
                found = True
                break
        if found:
            break

    # Search tasks
    if not found:
        for p in projects:
            tasks = p.get("tasks", [])
            for i, t in enumerate(tasks):
                text = t if isinstance(t, str) else t.get("desc", str(t))
                if query.lower() in text.lower():
                    removed = tasks.pop(i)
                    save_projects(projects)
                    print(f"  ✓ Completed task: {text} [{p['name']}]")
                    found = True
                    break
            if found:
                break

    if not found:
        print(f"  No matching item for '{query}'")


def cmd_undone(args):
    projects = load_projects()
    completed = []
    for p in projects:
        for m in p.get("milestones", []):
            if m.get("done"):
                completed.append((p, m))

    if not completed:
        print("  No completed milestones to undo.")
        return

    print("\n  Completed milestones:\n")
    for i, (p, m) in enumerate(completed, 1):
        date = m.get("completed_date", "?")
        print(f"    {i}) {m['name']} [{p['name']}] (completed {date})")
    print()

    try:
        choice = input("  Undo which? (number): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if not choice.isdigit() or not (1 <= int(choice) <= len(completed)):
        print("  Invalid selection.")
        return

    _, m = completed[int(choice) - 1]
    m.pop("done", None)
    m.pop("completed_date", None)
    save_projects(projects)
    print(f"  ↩ Unmarked: {m['name']}")


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI: checkin (interactive project follow-up)
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_checkin(args):
    projects = load_projects()
    active = [p for p in projects if p.get("status") == "active"]
    if not active:
        print("No active projects.")
        return

    print("\n  Project Check-in\n")
    for i, p in enumerate(active, 1):
        print(f"  {i}. {p['name']}")
    print()

    choice = input("  Select project (number or name): ").strip()
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(active):
            p = active[idx]
        else:
            print("  Invalid selection.")
            return
    else:
        matches = fuzzy_match(choice, active, key=lambda p: p["name"])
        if not matches:
            print(f"  No match for '{choice}'")
            return
        p = matches[0]

    cmd_show_inline(p)

    while True:
        print("\n  Actions: (d)one milestone, (t)ask add, (n)otes, (r)eschedule, (q)uit")
        action = input("  > ").strip().lower()
        if action == "q" or not action:
            break
        elif action == "d":
            # Mark milestone done
            undone = [m for m in p.get("milestones", []) if not m.get("done")]
            if not undone:
                print("  All milestones done!")
                continue
            for i, m in enumerate(undone, 1):
                print(f"    {i}. {m['name']} (due {m.get('due', '?')})")
            sel = input("  Mark done (number): ").strip()
            if sel.isdigit() and 1 <= int(sel) <= len(undone):
                m = undone[int(sel) - 1]
                m["done"] = True
                m["completed_date"] = str(today())
                save_projects(projects)
                print(f"  ✓ {m['name']}")
        elif action == "t":
            task = input("  New task: ").strip()
            if task:
                p.setdefault("tasks", []).append(task)
                save_projects(projects)
                print(f"  Added: {task}")
        elif action == "n":
            notes = input("  Notes: ").strip()
            if notes:
                p["notes"] = notes
                save_projects(projects)
                print("  Notes updated.")
        elif action == "r":
            cmd_reschedule_project(p, projects)


def cmd_show_inline(p):
    td = today()
    print(f"\n  ── {p['name']} ──")
    if p.get("milestones"):
        for m in p["milestones"]:
            check = "✓" if m.get("done") else " "
            due_str = ""
            if m.get("due"):
                due = parse_date(m["due"])
                days = (due - td).days
                if m.get("done"):
                    due_str = " (done)"
                elif days < 0:
                    due_str = f" ({-days}d overdue)"
                else:
                    due_str = f" (due {fmt_date(due)})"
            print(f"    [{check}] {m['name']}{due_str}")
            for t in m.get("tasks", []):
                text = t if isinstance(t, str) else t.get("desc", str(t))
                print(f"          · {text}")
    if p.get("tasks"):
        print(f"  Tasks:")
        for t in p["tasks"]:
            text = t if isinstance(t, str) else t.get("desc", str(t))
            print(f"    - {text}")


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI: reschedule
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_reschedule(args):
    projects = load_projects()
    matches = fuzzy_match(args.project, projects, key=lambda p: p["name"])
    if not matches:
        print(f"No project matching '{args.project}'")
        return
    cmd_reschedule_project(matches[0], projects)


def cmd_reschedule_project(p, projects):
    milestones = [m for m in p.get("milestones", []) if not m.get("done")]
    if not milestones:
        print("  No pending milestones to reschedule.")
        return

    print(f"\n  Reschedule — {p['name']}")
    for i, m in enumerate(milestones, 1):
        print(f"    {i}. {m['name']} (due {m.get('due', '?')})")

    sel = input("  Select milestone (number): ").strip()
    if not sel.isdigit() or not (1 <= int(sel) <= len(milestones)):
        print("  Cancelled.")
        return

    m = milestones[int(sel) - 1]
    old_due = parse_date(m["due"])
    new_due_str = input(f"  New date for '{m['name']}' (was {m['due']}): ").strip()
    if not new_due_str:
        print("  Cancelled.")
        return

    new_due = parse_date(new_due_str)
    delta = (new_due - old_due).days
    m["due"] = str(new_due)
    m["rescheduled"] = str(today())

    # Cascade prompt
    idx = milestones.index(m)
    downstream = milestones[idx + 1:]
    if downstream and delta > 0:
        cascade = input(f"  Shift {len(downstream)} downstream milestone(s) by {delta} days? [y/N]: ").strip().lower()
        if cascade == "y":
            for dm in downstream:
                if dm.get("due"):
                    dm["due"] = str(parse_date(dm["due"]) + datetime.timedelta(days=delta))
                    dm["rescheduled"] = str(today())

    # Deadline warning
    if p.get("deadline"):
        dl = parse_date(p["deadline"])
        latest = max(parse_date(m["due"]) for m in p.get("milestones", []) if m.get("due") and not m.get("done"))
        if latest > dl:
            print(f"  ⚠ Latest milestone ({latest}) exceeds deadline ({p['deadline']})!")
            update_dl = input(f"  Update deadline to {latest}? [y/N]: ").strip().lower()
            if update_dl == "y":
                p["deadline"] = str(latest)

    save_projects(projects)
    print(f"  ✓ Rescheduled.")


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI: timeline
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_timeline(args):
    projects = load_projects()
    matches = fuzzy_match(args.project, projects, key=lambda p: p["name"])
    if not matches:
        print(f"No project matching '{args.project}'")
        return

    p = matches[0]
    milestones = p.get("milestones", [])
    if not milestones:
        print("  No milestones.")
        return

    td = today()
    print(f"\n  Timeline — {p['name']}\n")

    dated = [(parse_date(m["due"]), m) for m in milestones if m.get("due")]
    dated.sort(key=lambda x: x[0])

    if not dated:
        print("  No dated milestones.")
        return

    min_date = min(td, dated[0][0])
    max_date = max(td, dated[-1][0])
    if p.get("deadline"):
        max_date = max(max_date, parse_date(p["deadline"]))
    span = (max_date - min_date).days or 1
    width = 50

    for due, m in dated:
        pos = int((due - min_date).days / span * width)
        check = "✓" if m.get("done") else "○"
        marker = "│"
        delay = ""
        if m.get("rescheduled"):
            delay = " (rescheduled)"
        overdue = ""
        if not m.get("done") and due < td:
            overdue = " OVERDUE"
        line = " " * pos + marker
        print(f"  {line}")
        print(f"  {' ' * pos}{check} {m['name']} — {fmt_date(due)}{delay}{overdue}")

    # Show today marker
    today_pos = int((td - min_date).days / span * width)
    print(f"\n  {' ' * today_pos}▼ today ({fmt_date(td)})")

    if p.get("deadline"):
        dl_pos = int((parse_date(p["deadline"]) - min_date).days / span * width)
        print(f"  {' ' * dl_pos}◆ deadline ({p['deadline']})")
    print()


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI: drive
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_drive(args):
    locations = load_locations()
    fr = args.src  # renamed from 'from' which is reserved
    to = args.to

    from_coords, locations = resolve_location(fr, locations)
    to_coords, locations = resolve_location(to, locations)

    if not from_coords:
        print(f"  Could not resolve location: {fr}")
        return
    if not to_coords:
        print(f"  Could not resolve location: {to}")
        return

    info = get_driving_time(from_coords, to_coords)
    if not info:
        print("  Could not get driving directions.")
        return

    print(f"\n  {fr} → {to}")
    print(f"  Duration: {int(info['duration_minutes'])} min ({info['duration_seconds']:.0f}s)")
    print(f"  Distance: {info['distance_miles']:.1f} mi ({info['distance_km']:.1f} km)")
    print()


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI: alert setup / check-alerts
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_cron_setup(args):
    lori_path = pathlib.Path.home() / "bin" / "lori"
    dashboard = LORI_DIR / "dashboard.html"
    entry = f"0 6 * * * {lori_path} html && scp {dashboard} uaf-2:~/public_html/hpg/"

    # Read current scrontab
    result = subprocess.run(["scrontab", "-l"], capture_output=True, text=True)
    current = result.stdout if result.returncode == 0 else ""

    if entry in current:
        print("  Dashboard cron entry already installed.")
        return

    new_crontab = current.rstrip() + "\n" + entry + "\n"
    proc = subprocess.run(["scrontab", "-"], input=new_crontab, capture_output=True, text=True)
    if proc.returncode == 0:
        print("  Installed scrontab entry for daily dashboard (6 AM).")
        print(f"  Entry: {entry}")
    else:
        print(f"  Error installing scrontab: {proc.stderr}")


def cmd_alert_setup(args):
    lori_path = pathlib.Path.home() / "bin" / "lori"
    entry = f"*/15 * * * * {lori_path} --check-alerts"

    # Read current scrontab
    result = subprocess.run(["scrontab", "-l"], capture_output=True, text=True)
    current = result.stdout if result.returncode == 0 else ""

    if entry in current:
        print("  Alert scrontab entry already installed.")
        return

    new_crontab = current.rstrip() + "\n" + entry + "\n"
    proc = subprocess.run(["scrontab", "-"], input=new_crontab, capture_output=True, text=True)
    if proc.returncode == 0:
        print("  Installed scrontab entry for alerts (every 15 min).")
        print(f"  Entry: {entry}")
    else:
        print(f"  Error installing scrontab: {proc.stderr}")


def cmd_check_alerts(args):
    config = load_config()
    events = load_schedule()
    td = today()
    n = now()
    alert_mins = config.get("alert_minutes_before", 15)
    to_addr = config.get("email", {}).get("to")
    if not to_addr:
        return

    today_events = expand_events_for_date(events, td)

    # Load sent alerts
    sent = set()
    if ALERTS_FILE.exists():
        with open(ALERTS_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith(str(td)):
                    sent.add(line)

    for ev in today_events:
        start_str = ev.get("start") or ev.get("depart")
        if not start_str:
            continue
        start = parse_time(start_str)
        event_dt = datetime.datetime.combine(td, start)
        delta = (event_dt - n).total_seconds() / 60

        if 0 <= delta <= alert_mins:
            alert_key = f"{td}|{ev.get('title')}|{start_str}"
            if alert_key in sent:
                continue

            # Build alert email
            title = ev.get("title", "Event")
            body = f"<h2>Upcoming: {title}</h2>"
            body += f"<p>Starts at {start_str}"
            if ev.get("location"):
                body += f" — {ev['location']}"
            body += "</p>"

            # Remaining schedule
            body += "<h3>Rest of today:</h3><ul>"
            for e2 in today_events:
                s2 = e2.get("start") or e2.get("depart") or ""
                if s2 and parse_time(s2) >= start:
                    body += f"<li>{s2} — {e2.get('title', '')}</li>"
            body += "</ul>"

            send_email(to_addr, f"[lori] {title} in {int(delta)} min", body, config)

            # Record sent
            with open(ALERTS_FILE, "a") as f:
                f.write(alert_key + "\n")

    # Clean old alerts (keep only today)
    if ALERTS_FILE.exists():
        with open(ALERTS_FILE) as f:
            lines = [l for l in f if l.strip().startswith(str(td))]
        with open(ALERTS_FILE, "w") as f:
            f.writelines(lines)


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI: html / email — ambient TV dashboard
# ═══════════════════════════════════════════════════════════════════════════════

_QUOTES = [
    ("The best way to predict the future is to create it.", "Peter Drucker"),
    ("Stay hungry. Stay foolish.", "Steve Jobs"),
    ("In the middle of difficulty lies opportunity.", "Albert Einstein"),
    ("The only way to do great work is to love what you do.", "Steve Jobs"),
    ("It does not matter how slowly you go as long as you do not stop.", "Confucius"),
    ("What we think, we become.", "Buddha"),
    ("Simplicity is the ultimate sophistication.", "Leonardo da Vinci"),
    ("The purpose of life is not to be happy. It is to be useful.", "Ralph Waldo Emerson"),
    ("Well done is better than well said.", "Benjamin Franklin"),
    ("Strive not to be a success, but rather to be of value.", "Albert Einstein"),
    ("The mind is everything. What you think you become.", "Buddha"),
    ("An unexamined life is not worth living.", "Socrates"),
    ("Imagination is more important than knowledge.", "Albert Einstein"),
    ("Life is what happens when you're busy making other plans.", "John Lennon"),
    ("You must be the change you wish to see in the world.", "Mahatma Gandhi"),
    ("The only true wisdom is in knowing you know nothing.", "Socrates"),
    ("Not all those who wander are lost.", "J.R.R. Tolkien"),
    ("Do what you can, with what you have, where you are.", "Theodore Roosevelt"),
    ("Everything you can imagine is real.", "Pablo Picasso"),
    ("The journey of a thousand miles begins with one step.", "Lao Tzu"),
    ("We are what we repeatedly do. Excellence is not an act, but a habit.", "Aristotle"),
    ("Turn your wounds into wisdom.", "Oprah Winfrey"),
    ("The secret of getting ahead is getting started.", "Mark Twain"),
    ("It always seems impossible until it's done.", "Nelson Mandela"),
    ("Be yourself; everyone else is already taken.", "Oscar Wilde"),
    ("To live is the rarest thing in the world.", "Oscar Wilde"),
    ("Act as if what you do makes a difference. It does.", "William James"),
    ("What lies behind us and what lies before us are tiny matters compared to what lies within us.", "Ralph Waldo Emerson"),
    ("The best time to plant a tree was 20 years ago. The second best time is now.", "Chinese Proverb"),
    ("Your time is limited. Don't waste it living someone else's life.", "Steve Jobs"),
]


def _fetch_news(max_per_source=2):
    """Fetch headlines from HN + major news RSS feeds. Order: HN, NYT, WSJ, Reuters, CNN, BBC, NBC, Fox."""
    import xml.etree.ElementTree as ET
    headlines = []
    # Hacker News first
    try:
        r = requests.get("https://hacker-news.firebaseio.com/v0/topstories.json", timeout=3)
        if r.status_code == 200:
            ids = r.json()[:5]
            for item_id in ids:
                try:
                    ir = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json", timeout=3)
                    if ir.status_code == 200:
                        item = ir.json()
                        title = item.get("title", "")
                        url = item.get("url", f"https://news.ycombinator.com/item?id={item_id}")
                        if title:
                            headlines.append(("HN", title, url))
                except Exception:
                    pass
    except Exception:
        pass
    # RSS feeds in display order
    feeds = [
        ("NYT", "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml"),
        ("WSJ", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
        ("Reuters", "https://news.google.com/rss/search?q=site:reuters.com&hl=en-US&gl=US&ceid=US:en"),
        ("CNN", "http://rss.cnn.com/rss/cnn_topstories.rss"),
        ("BBC", "https://feeds.bbci.co.uk/news/rss.xml"),
        ("NBC", "https://feeds.nbcnews.com/nbcnews/public/news"),
        ("Fox", "https://moxie.foxnews.com/google-publisher/latest.xml"),
    ]
    for name, url in feeds:
        try:
            resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item")[:max_per_source]:
                title = item.find("title")
                link = item.find("link")
                if title is not None and title.text:
                    href = link.text.strip() if link is not None and link.text else ""
                    headlines.append((name, title.text.strip(), href))
        except Exception:
            pass
    return headlines


def _fetch_stocks():
    """Fetch major index/commodity performance from Yahoo Finance with hourly closes for sparklines."""
    symbols = [
        ("^GSPC", "S&P 500"), ("^DJI", "Dow"), ("^IXIC", "Nasdaq"),
        ("CL=F", "WTI Oil"), ("BZ=F", "Brent"), ("GC=F", "Gold"),
        ("BTC-USD", "Bitcoin"), ("^TNX", "10Y Yield"),
    ]
    results = []
    for sym, name in symbols:
        try:
            r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                params={"interval": "1h", "range": "5d"},
                headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
            if r.status_code == 200:
                data = r.json()["chart"]["result"][0]
                meta = data["meta"]
                price = meta["regularMarketPrice"]
                prev = meta["chartPreviousClose"]
                chg = price - prev
                pct = (chg / prev) * 100 if prev else 0
                closes = []
                try:
                    closes = [v for v in data["indicators"]["quote"][0]["close"] if v is not None]
                except Exception:
                    pass
                results.append((name, price, chg, pct, closes))
        except Exception:
            pass
    return results


def _build_sparkline_svg(closes, width=100, height=24):
    """Build an inline SVG sparkline polyline from a list of close prices."""
    if not closes or len(closes) < 2:
        return ""
    mn, mx = min(closes), max(closes)
    rng = mx - mn if mx != mn else 1
    n = len(closes)
    points = []
    for i, v in enumerate(closes):
        x = round(i / (n - 1) * width, 1)
        y = round(height - (v - mn) / rng * (height - 2) - 1, 1)
        points.append(f"{x},{y}")
    color = "#55efc4" if closes[-1] >= closes[0] else "#ff6b6b"
    return (f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            f'style="vertical-align:middle;" xmlns="http://www.w3.org/2000/svg">'
            f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="1.5"/></svg>')


def _build_overlapped_sparklines_svg(series, width=280, height=40):
    """Build overlapped multi-series sparkline SVG.

    series: list of (closes_list, color_string)
    Y-axis auto-scales to the data range with padding.
    """
    if not series:
        return ""
    # Find global min/max across all series for auto-scaling
    all_vals = []
    for closes, _ in series:
        if closes and len(closes) >= 2:
            all_vals.extend(closes)
    if not all_vals:
        return ""
    data_min = min(all_vals)
    data_max = max(all_vals)
    # Add 10% padding on each side, clamp to 0-100
    padding = max((data_max - data_min) * 0.1, 2)
    y_min = max(data_min - padding, 0)
    y_max = min(data_max + padding, 100)
    y_range = y_max - y_min if y_max != y_min else 1
    svg_lines = ""
    for closes, color in series:
        if not closes or len(closes) < 2:
            continue
        n = len(closes)
        points = []
        for i, v in enumerate(closes):
            x = round(i / (n - 1) * width, 1)
            y = round(height - (v - y_min) / y_range * (height - 2) - 1, 1)
            points.append(f"{x},{y}")
        svg_lines += f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="1.2" opacity="0.8"/>'
    if not svg_lines:
        return ""
    # Y-axis labels (min/max)
    lbl_min = f"{y_min:.0f}%"
    lbl_max = f"{y_max:.0f}%"
    labels = (f'<text x="{width - 1}" y="9" text-anchor="end" font-size="7" fill="rgba(255,255,255,0.25)" font-family="JetBrains Mono,monospace">{lbl_max}</text>'
              f'<text x="{width - 1}" y="{height - 2}" text-anchor="end" font-size="7" fill="rgba(255,255,255,0.25)" font-family="JetBrains Mono,monospace">{lbl_min}</text>')
    return (f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            f'style="vertical-align:middle; display:block;" xmlns="http://www.w3.org/2000/svg">'
            f'{labels}{svg_lines}</svg>')


def _fetch_predictions():
    """Fetch Polymarket markets: politics + trending/immediate with trend data.

    Returns list of event dicts:
      {"title", "link", "section", "choices": [{"label", "prob", "history": [floats]}]}
    section is "politics" or "trending"
    """
    events = []

    def _parse_event(ev, section):
        """Parse a single Polymarket event into our dict format."""
        title = ev.get("title", "")
        slug = ev.get("slug", "")
        link = f"https://polymarket.com/event/{slug}" if slug else ""
        markets = ev.get("markets", [])
        choices = []
        for mkt in markets:
            label = mkt.get("groupItemTitle", "") or mkt.get("question", "")
            prob = 0
            try:
                bid = float(mkt.get("bestBid", 0) or 0)
                ask = float(mkt.get("bestAsk", 0) or 0)
                if bid == 0 and ask >= 0.99:
                    continue
                prob = round(((bid + ask) / 2) * 100) if (bid or ask) else 0
                if prob == 0:
                    prices = json.loads(mkt.get("outcomePrices", "[]"))
                    prob = round(float(prices[0]) * 100) if prices else 0
            except Exception:
                pass
            token_id = ""
            try:
                tids = json.loads(mkt.get("clobTokenIds", "[]") or "[]")
                token_id = tids[0] if tids else ""
            except Exception:
                token_id = mkt.get("clobTokenIds", [""])[0] if isinstance(mkt.get("clobTokenIds"), list) else ""
            choices.append({"label": label, "prob": prob, "token_id": token_id, "history": []})
        choices.sort(key=lambda c: c["prob"], reverse=True)
        choices = choices[:4]
        # Fetch 7-day price history for top choices
        for ch in choices:
            if ch["token_id"]:
                try:
                    hr = requests.get("https://clob.polymarket.com/prices-history",
                        params={"market": ch["token_id"], "interval": "max", "fidelity": "500"},
                        timeout=5)
                    if hr.status_code == 200:
                        hist = hr.json().get("history", [])
                        ch["history"] = [pt["p"] for pt in hist if "p" in pt]
                except Exception:
                    pass
        return {"title": title, "link": link, "section": section, "choices": choices}

    # ── 1. Politics: Trump, Congress, US politics ──
    _pol_keywords = {"trump", "presidential", "congress", "senate", "house rep",
                     "gop", "republican", "democrat", "nominee", "cabinet",
                     "impeach", "veto", "speaker", "approval rating", "fed ",
                     "us ", "u.s.", "america", "white house", "scotus", "supreme court",
                     "tariff", "election", "governor", "geopoliti", "china", "russia",
                     "ukraine", "iran", "war", "nato", "eu ", "trade deal"}
    try:
        r = requests.get("https://gamma-api.polymarket.com/events",
            params={"limit": 25, "active": "true", "order": "volume24hr",
                    "ascending": "false", "tag_slug": "politics"},
            timeout=8)
        if r.status_code == 200:
            seen_slugs = set()
            for ev in r.json():
                title_lower = ev.get("title", "").lower()
                if not any(kw in title_lower for kw in _pol_keywords):
                    continue
                slug = ev.get("slug", "")
                if slug in seen_slugs:
                    continue
                seen_slugs.add(slug)
                events.append(_parse_event(ev, "politics"))
                if len([e for e in events if e["section"] == "politics"]) >= 8:
                    break
    except Exception:
        pass

    # ── 2. Trending / immediate (any topic, highest volume) ──
    seen_titles = {e["title"].lower() for e in events}
    try:
        r = requests.get("https://gamma-api.polymarket.com/events",
            params={"limit": 25, "active": "true", "order": "volume24hr",
                    "ascending": "false"},
            timeout=8)
        if r.status_code == 200:
            for ev in r.json():
                title = ev.get("title", "")
                if title.lower() in seen_titles:
                    continue
                seen_titles.add(title.lower())
                events.append(_parse_event(ev, "trending"))
                if len([e for e in events if e["section"] == "trending"]) >= 7:
                    break
    except Exception:
        pass

    return events


def _fetch_science():
    """Fetch launches, NASA headlines, CERN/LHC, solar/space weather, LIGO events."""
    import xml.etree.ElementTree as ET
    import re as _re
    launches = []
    nasa = []
    cern = []
    solar = {}      # solar wind speed, Bz, Kp, sun image URL
    ligo = []       # recent gravitational wave events

    # Space launches
    try:
        r = requests.get("https://ll.thespacedevs.com/2.2.0/launch/upcoming/",
            params={"limit": 3, "mode": "list"}, timeout=10)
        if r.status_code == 200:
            for lch in r.json().get("results", []):
                launches.append((lch.get("name", ""), lch.get("net", "")))
    except Exception:
        pass

    # NASA headlines
    try:
        r = requests.get("https://www.nasa.gov/news-release/feed/",
            timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        root = ET.fromstring(r.content)
        for item in root.findall(".//item")[:3]:
            title = item.find("title")
            link = item.find("link")
            if title is not None and title.text:
                href = link.text.strip() if link is not None and link.text else ""
                nasa.append((title.text.strip(), href))
    except Exception:
        pass

    # CERN Courier (LHC/particle physics) — malformed XML, use regex
    try:
        r = requests.get("https://cerncourier.com/feed/",
            timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            items = _re.findall(r'<item>.*?</item>', r.text, _re.DOTALL)
            for item_str in items[:3]:
                tm = _re.search(r'<title>(.*?)</title>', item_str)
                lm = _re.search(r'<link>(.*?)</link>', item_str)
                if tm:
                    href = lm.group(1).strip() if lm else ""
                    cern.append((tm.group(1).strip(), href))
    except Exception:
        pass

    # CERN LHC luminosity
    try:
        r = requests.get("https://lpc.web.cern.ch/cgi-bin/getTotalLumi.py", timeout=6)
        if r.status_code == 200:
            solar["lhc_lumi"] = r.json().get("lumi_str", "")
    except Exception:
        pass

    # Solar wind speed + magnetic field (NOAA SWPC)
    try:
        r = requests.get("https://services.swpc.noaa.gov/products/summary/solar-wind-speed.json", timeout=5)
        if r.status_code == 200:
            solar["wind_speed"] = r.json().get("WindSpeed", "")
    except Exception:
        pass
    try:
        r = requests.get("https://services.swpc.noaa.gov/products/summary/solar-wind-mag-field.json", timeout=5)
        if r.status_code == 200:
            d = r.json()
            solar["bz"] = d.get("Bz", "")
            solar["bt"] = d.get("Bt", "")
    except Exception:
        pass

    # Kp index (latest value)
    try:
        r = requests.get("https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json", timeout=5)
        if r.status_code == 200:
            data = r.json()
            if len(data) > 1:
                solar["kp"] = data[-1][1]  # latest Kp value
    except Exception:
        pass

    # Solar wind plasma 2-hour for sparkline
    try:
        r = requests.get("https://services.swpc.noaa.gov/products/solar-wind/plasma-2-hour.json", timeout=5)
        if r.status_code == 200:
            data = r.json()[1:]  # skip header
            solar["wind_history"] = [float(row[1]) for row in data if row[1] is not None and row[1] != ""]
    except Exception:
        pass

    # LIGO GraceDB recent superevents
    try:
        r = requests.get("https://gracedb.ligo.org/api/superevents/?format=json&count=3", timeout=8)
        if r.status_code == 200:
            for se in r.json().get("superevents", [])[:3]:
                sid = se.get("superevent_id", "")
                created = se.get("created", "")[:16]
                labels = se.get("labels", [])
                group = se.get("preferred_event_data", {}).get("group", "")
                ligo.append((sid, created, group, labels))
    except Exception:
        pass

    return launches, nasa, cern, solar, ligo


def _fetch_hpc():
    """Fetch HiPerGator CPU/GPU usage for avery and avery-b.

    Returns list of tuples: (qos, ncpus_current, ngpus_current, ncpus_24h, ngpus_24h, ncpus_thresh, ngpus_thresh, has_gpu)
    avery-b has no GPUs, so has_gpu=False for it.
    """
    results = []
    last_updated = ""
    for qos in ["avery", "avery-b"]:
        try:
            r = requests.get(f"https://sgnoohc.github.io/hpg_librarian/data_{qos}.json", timeout=10)
            if r.status_code == 200:
                data = r.json()
                # Track most recent last_updated across QOS fetches
                lu = data.get("metadata", {}).get("last_updated", "")
                if lu > last_updated:
                    last_updated = lu
                obs = data.get("observables_snapshot", {})
                thresholds = data.get("thresholds", {})
                ncpus_thresh = thresholds.get("NCPUS", 0)
                ngpus_thresh = thresholds.get("NGPUS", 0)
                has_gpu = qos != "avery-b" and ngpus_thresh > 0
                # Sum all users' values per time step for NCPUS
                ncpus_users = obs.get("NCPUS", {})
                n = 0
                for vals in ncpus_users.values():
                    n = len(vals)
                    break
                ncpus_total = [0] * n
                for vals in ncpus_users.values():
                    for i, v in enumerate(vals):
                        if v is not None:
                            ncpus_total[i] += v
                ngpus_total = []
                if has_gpu:
                    ngpus_users = obs.get("NGPUS", {})
                    ngpus_total = [0] * n
                    for vals in ngpus_users.values():
                        for i, v in enumerate(vals):
                            if v is not None:
                                ngpus_total[i] += v
                # Last snapshot entry can be 0 (partial); walk back to find last real value
                ncpus_current = 0
                for _i in range(len(ncpus_total)-1, max(len(ncpus_total)-5, -1), -1):
                    if ncpus_total[_i] > 0:
                        ncpus_current = ncpus_total[_i]; break
                ngpus_current = 0
                if ngpus_total:
                    for _i in range(len(ngpus_total)-1, max(len(ngpus_total)-5, -1), -1):
                        if ngpus_total[_i] > 0:
                            ngpus_current = ngpus_total[_i]; break
                # Snapshot has ~1 point/min; grab last ~24h (1440 pts) and downsample to ~48 points
                tail = min(1440, len(ncpus_total))
                step = max(1, tail // 48)
                ncpus_24h = ncpus_total[-tail::step]
                ngpus_24h = ngpus_total[-tail::step] if ngpus_total else []
                results.append((qos, ncpus_current, ngpus_current, ncpus_24h, ngpus_24h, ncpus_thresh, ngpus_thresh, has_gpu))
        except Exception:
            pass
    return results, last_updated


def _fetch_entertainment():
    """Fetch top movies and TV shows from Rotten Tomatoes via JSON-LD scraping."""
    import re as _re
    movies = []
    shows = []
    for kind, dest in [("movies_in_theaters", movies), ("tv_series_browse", shows)]:
        try:
            r = requests.get(f"https://www.rottentomatoes.com/browse/{kind}/sort:popular",
                timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                # Extract JSON-LD
                m = _re.search(r'<script type="application/ld\+json">(.*?)</script>', r.text, _re.DOTALL)
                if m:
                    data = json.loads(m.group(1))
                    items = data.get("itemListElement", {})
                    if isinstance(items, dict):
                        items = items.get("itemListElement", [])
                    for item in items[:15]:
                        name = item.get("name", "")
                        url = item.get("url", "")
                        rating = item.get("aggregateRating", {})
                        score = rating.get("ratingValue", "")
                        if name:
                            dest.append((name, str(score), url))
        except Exception:
            pass
    return movies, shows


def _fetch_pg_essay(seed_date):
    """Fetch a random Paul Graham essay (deterministic per day).

    Returns (title, url, text, essay_list) where essay_list is [(slug, title), ...].
    """
    import re as _re
    import random as _rng
    try:
        r = requests.get("http://www.paulgraham.com/articles.html",
            timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return "", "", "", []
        # Parse essay links
        links = _re.findall(r'<a href="([^"]+\.html)">([^<]+)</a>', r.text)
        # Filter out non-essay pages
        skip = {"hierarchies.html", "index.html", "hierarchies.html", "bio.html",
                "nsearch.html", "ind.html", "rss.html", "antispam.html", "hierarchies.html"}
        essays = [(slug, title) for slug, title in links if slug not in skip and len(title) > 5]
        if not essays:
            return "", "", "", []
        _rng.seed(seed_date.toordinal())
        slug, title = _rng.choice(essays)
        url = f"http://www.paulgraham.com/{slug}"
        # Fetch essay text
        er = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        if er.status_code != 200:
            return title, url, "", essays
        # Strip HTML tags to get plain text
        text = _re.sub(r'<script[^>]*>.*?</script>', '', er.text, flags=_re.DOTALL)
        text = _re.sub(r'<style[^>]*>.*?</style>', '', text, flags=_re.DOTALL)
        text = _re.sub(r'<[^>]+>', ' ', text)
        text = _re.sub(r'&[a-z]+;', ' ', text)
        text = _re.sub(r'\s+', ' ', text).strip()
        # Skip header cruft — find the essay body (usually after the title)
        idx = text.find(title)
        if idx > 0:
            text = text[idx + len(title):]
        return title, url, text.strip()[:4000], essays
    except Exception:
        return "", "", "", []


def generate_dashboard_html(target_date=None):
    config = load_config()
    projects = load_projects()
    events = load_schedule()
    locations = load_locations()
    td = target_date or today()
    days_ahead = config.get("briefing_days_ahead", 7)
    date_str = td.strftime("%A, %B %-d, %Y")

    _rb = '<button class="reorder-btn" onclick="movePanel(this,-1)">&#9650;</button><button class="reorder-btn" onclick="movePanel(this,1)">&#9660;</button>'
    _rb_first = '<button class="reorder-btn" onclick="movePanel(this,-1)" style="margin-left:auto">&#9650;</button><button class="reorder-btn" onclick="movePanel(this,1)">&#9660;</button>'

    # Weather — try OpenWeatherMap, fallback to Open-Meteo (free, no key)
    weather_html = ""
    w_temp = w_desc = w_emoji = w_hi = w_lo = ""
    api_key = config.get("weather", {}).get("api_key", "")
    location = config.get("location", "Gainesville,FL")

    wmo_weather = {
        0: ("Clear Sky", "☀️"), 1: ("Mainly Clear", "🌤️"), 2: ("Partly Cloudy", "⛅"), 3: ("Overcast", "☁️"),
        45: ("Fog", "🌫️"), 48: ("Rime Fog", "🌫️"),
        51: ("Light Drizzle", "🌦️"), 53: ("Drizzle", "🌦️"), 55: ("Heavy Drizzle", "🌦️"),
        61: ("Light Rain", "🌧️"), 63: ("Rain", "🌧️"), 65: ("Heavy Rain", "🌧️"),
        71: ("Light Snow", "❄️"), 73: ("Snow", "❄️"), 75: ("Heavy Snow", "❄️"),
        80: ("Light Showers", "🌧️"), 81: ("Showers", "🌧️"), 82: ("Heavy Showers", "🌧️"),
        95: ("Thunderstorm", "⛈️"), 96: ("Hail Storm", "⛈️"), 99: ("Hail Storm", "⛈️"),
    }

    if api_key and api_key != "YOUR_OPENWEATHERMAP_KEY":
        try:
            resp = requests.get("https://api.openweathermap.org/data/2.5/forecast", params={
                "q": location, "appid": api_key, "units": "imperial", "cnt": 32
            }, timeout=10)
            if resp.status_code == 200:
                wdata = resp.json()
                current = wdata["list"][0]
                temp = round(current["main"]["temp"])
                desc = current["weather"][0]["description"].title()
                hi = round(current["main"]["temp_max"])
                lo = round(current["main"]["temp_min"])
                main_weather = current["weather"][0]["main"].lower()
                weather_emoji = {"clear": "☀️", "clouds": "☁️", "rain": "🌧️", "drizzle": "🌦️",
                                 "thunderstorm": "⛈️", "snow": "❄️", "mist": "🌫️", "fog": "🌫️"}
                emoji = weather_emoji.get(main_weather, "🌤️")
                w_temp, w_desc, w_emoji, w_hi, w_lo = temp, desc, emoji, hi, lo

                weather_html = f"""<div class="glass drag" data-wid="forecast">
                  <div class="stitle drag-handle" style="color:#00cec9; cursor:grab;">&#127780; FORECAST{_rb_first}</div>
                  <div style="display:flex; align-items:center; gap:12px; margin-bottom:12px;">
                    <span style="font-size:42px; line-height:1;">{emoji}</span>
                    <div>
                      <div style="font-size:28px; font-weight:700; color:#fff;">{temp}°F</div>
                      <div style="font-size:13px; color:rgba(255,255,255,0.5);">{desc} · H:{hi}° L:{lo}°</div>
                    </div>
                  </div>
                  <div style="display:flex; gap:8px; flex-wrap:wrap;">"""
                seen_dates = set()
                for entry in wdata["list"]:
                    d = entry["dt_txt"][:10]
                    if d == str(td) or d in seen_dates:
                        continue
                    seen_dates.add(d)
                    if len(seen_dates) > 3:
                        break
                    fdate = datetime.datetime.strptime(d, "%Y-%m-%d").strftime("%a")
                    ftemp = round(entry["main"]["temp"])
                    fmain = entry["weather"][0]["main"].lower()
                    femoji = weather_emoji.get(fmain, "🌤️")
                    weather_html += f"""<div style="flex:1; min-width:70px; padding:8px; background:rgba(255,255,255,0.06); border-radius:10px; text-align:center;">
                      <div style="font-size:18px;">{femoji}</div>
                      <div style="font-size:11px; font-weight:600; color:rgba(255,255,255,0.7);">{fdate}</div>
                      <div style="font-size:13px; color:#a29bfe; font-weight:600;">{ftemp}°F</div>
                    </div>"""
                weather_html += "</div></div>"
        except Exception:
            pass

    # Fallback: Open-Meteo (free, no API key needed)
    hourly_html = ""
    if not weather_html:
        try:
            city = location.split(",")[0].strip()
            geo = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1}, timeout=10).json()
            if geo.get("results"):
                lat, lon = geo["results"][0]["latitude"], geo["results"][0]["longitude"]
                wr = requests.get("https://api.open-meteo.com/v1/forecast", params={
                    "latitude": lat, "longitude": lon,
                    "current": "temperature_2m,weather_code",
                    "daily": "temperature_2m_max,temperature_2m_min,weather_code",
                    "hourly": "temperature_2m,weather_code,precipitation_probability,wind_speed_10m",
                    "temperature_unit": "fahrenheit", "forecast_days": 4, "timezone": "auto",
                }, timeout=10).json()

                w_temp = round(wr["current"]["temperature_2m"])
                cur_code = wr["current"]["weather_code"]
                w_desc, w_emoji = wmo_weather.get(cur_code, ("Unknown", "🌤️"))
                w_hi = round(wr["daily"]["temperature_2m_max"][0])
                w_lo = round(wr["daily"]["temperature_2m_min"][0])

                weather_html = f"""<div class="glass drag" data-wid="forecast">
                  <div class="stitle drag-handle" style="color:#00cec9; cursor:grab;">&#127780; FORECAST{_rb_first}</div>
                  <div style="display:flex; align-items:center; gap:12px; margin-bottom:12px;">
                    <span style="font-size:42px; line-height:1;">{w_emoji}</span>
                    <div>
                      <div style="font-size:28px; font-weight:700; color:#fff;">{w_temp}°F</div>
                      <div style="font-size:13px; color:rgba(255,255,255,0.5);">{w_desc} · H:{w_hi}° L:{w_lo}°</div>
                    </div>
                  </div>
                  <div style="display:flex; gap:8px; flex-wrap:wrap;">"""
                for fi in range(1, len(wr["daily"]["time"])):
                    fdate = datetime.datetime.strptime(wr["daily"]["time"][fi], "%Y-%m-%d").strftime("%a")
                    fhi = round(wr["daily"]["temperature_2m_max"][fi])
                    flo = round(wr["daily"]["temperature_2m_min"][fi])
                    fc = wr["daily"]["weather_code"][fi]
                    _, femoji = wmo_weather.get(fc, ("", "🌤️"))
                    weather_html += f"""<div style="flex:1; min-width:70px; padding:10px; background:rgba(255,255,255,0.06); border-radius:10px; text-align:center;">
                      <div style="font-size:26px;">{femoji}</div>
                      <div style="font-size:13px; font-weight:600; color:rgba(255,255,255,0.7);">{fdate}</div>
                      <div style="font-size:17px; color:#a29bfe; font-weight:600;">{fhi}°/{flo}°</div>
                    </div>"""
                weather_html += "</div></div>"

                # ── Hourly forecast panel ──
                h_times = wr.get("hourly", {}).get("time", [])
                h_temps = wr.get("hourly", {}).get("temperature_2m", [])
                h_codes = wr.get("hourly", {}).get("weather_code", [])
                h_precip = wr.get("hourly", {}).get("precipitation_probability", [])
                h_wind = wr.get("hourly", {}).get("wind_speed_10m", [])
                if h_times and h_temps:
                    # Find current hour index
                    now_str = now().strftime("%Y-%m-%dT%H:00")
                    start_idx = 0
                    for hi, t in enumerate(h_times):
                        if t >= now_str:
                            start_idx = hi
                            break
                    # Next 24 hours
                    hourly_items = ""
                    for hi in range(start_idx, min(start_idx + 24, len(h_times))):
                        ht = datetime.datetime.strptime(h_times[hi], "%Y-%m-%dT%H:%M")
                        hr_label = ht.strftime("%-I%p").lower()
                        if hi == start_idx:
                            hr_label = "Now"
                        htemp = round(h_temps[hi])
                        hcode = h_codes[hi] if hi < len(h_codes) else 0
                        _, hemoji = wmo_weather.get(hcode, ("", "🌤️"))
                        hprec = h_precip[hi] if hi < len(h_precip) else 0
                        hws = round(h_wind[hi]) if hi < len(h_wind) else 0
                        prec_tag = f'<div style="font-size:8px; color:#74b9ff;">{round(hprec)}%</div>' if hprec and hprec > 0 else ''
                        hourly_items += f'''<div style="min-width:52px; padding:6px 4px; text-align:center; flex-shrink:0;">
                          <div style="font-size:10px; color:rgba(255,255,255,0.45); font-weight:600;">{hr_label}</div>
                          <div style="font-size:22px; margin:2px 0;">{hemoji}</div>
                          {prec_tag}
                          <div style="font-size:13px; font-weight:600; color:rgba(255,255,255,0.85);">{htemp}°</div>
                          <div style="font-size:9px; color:rgba(255,255,255,0.3);">{hws}mph</div>
                        </div>'''
                    # Temp sparkline for 24h
                    h_temp_slice = [h_temps[i] for i in range(start_idx, min(start_idx + 24, len(h_temps)))]
                    temp_spark = _build_sparkline_svg(h_temp_slice, width=380, height=30) if len(h_temp_slice) >= 2 else ""
                    hourly_html = f'''<div class="glass drag" data-wid="hourly-weather" style="padding:12px 16px;">
                      <div class="stitle drag-handle" style="color:#00cec9; cursor:grab;">&#9201; HOURLY · {location}{_rb_first}</div>
                      <div style="display:flex; overflow-x:auto; gap:2px; padding-bottom:4px; scrollbar-width:thin; scrollbar-color:rgba(255,255,255,0.1) transparent;">{hourly_items}</div>
                      <div style="margin-top:4px;"><div style="font-size:8px; color:rgba(255,255,255,0.3); margin-bottom:2px;">24H TEMP</div>{temp_spark}</div>
                    </div>'''
        except Exception:
            pass

    # Quote of the day (consistent per date)
    import random as _rng
    _rng.seed(td.toordinal())
    quote_text, quote_author = _rng.choice(_QUOTES)

    # News headlines
    news_items = _fetch_news(max_per_source=5)

    # Stock indices
    stock_data = _fetch_stocks()

    # Prediction markets
    predictions = _fetch_predictions()

    # Science (launches + NASA + CERN + solar + LIGO)
    launches, nasa_headlines, cern_headlines, solar_data, ligo_events = _fetch_science()

    # Entertainment (Rotten Tomatoes)
    rt_movies, rt_shows = _fetch_entertainment()

    # Paul Graham essay of the day
    pg_title, pg_url, pg_text, pg_essays = _fetch_pg_essay(td)

    # HiPerGator usage
    hpc_data, hpc_updated_raw = _fetch_hpc()
    hpc_updated_fmt = ""
    if hpc_updated_raw:
        try:
            from datetime import datetime as _dt
            import re as _re2
            # Fix timezone offset: -0400 → -04:00 for fromisoformat
            _fixed = _re2.sub(r'([+-]\d{2})(\d{2})$', r'\1:\2', hpc_updated_raw)
            _hpc_ts = _dt.fromisoformat(_fixed)
            hpc_updated_fmt = _hpc_ts.strftime("%-I:%M %p")
        except Exception:
            hpc_updated_fmt = hpc_updated_raw[:16]

    # Background — YouTube aerial video IDs (muted, looped, no controls)
    aerial_videos = [
        # --- Nature & Landscapes ---
        ("lM02vNMRRB0", "Earth From Above — 7hr 4K"),
        ("n6YZs__0Pt0", "Flying Over Iceland 4K"),
        ("ftlvreFtA2A", "Flying Over Norway 4K"),
        ("ChOhcHD8fBA", "Patagonia 8K"),
        ("1PTs1mqrToM", "Brazil 4K Scenic"),
        ("OfO6zxvhtBg", "Antarctica 4K Scenic"),
        ("LXb3EKWsInQ", "Costa Rica 4K HDR"),
        ("vtxVK3sbZ0o", "New Zealand 4K Scenic"),
        ("Ee0Qh_nIoHw", "Africa 4K Scenic"),
        ("RNKWoqDlbxc", "Ireland 4K Drone Fly By"),
        ("0vsHnXjnWmI", "Alaska 4K Relaxation"),
        ("3lK8IdwJUqY", "Alaska 4K Ultra HD"),
        ("-53mGJ4h5sQ", "Amazon Rainforest 4K"),
        ("FXpMp3-ZClw", "Finland — Bird's Eye View 4K"),
        ("RAbig3RxWTs", "Estonia, Latvia & Lithuania 4K"),
        ("ZvBjy6a4-yM", "Portugal Coastlines 4K"),
        ("kFjFvfu9Ldg", "Vietnam North to South 4K"),
        ("hAzpEQ189Uw", "Northern Argentina 4K"),
        ("bi3VuibR9Is", "Colorado Autumn Flyover 4K"),
        ("4bafVt7V06Y", "Fiji Islands — 11hr 4K"),
        ("VVjmFIhJ7Ks", "Peru Untouched Jungle 4K"),
        # --- Mountains & Alps ---
        ("linlz7-Pnvw", "Switzerland 8K Ultra HD"),
        ("vU5s41EuM8s", "Swiss Alps — Matterhorn 4K"),
        ("3PZ65s2qLTE", "The Alps — 60min 4K"),
        ("-00PZ3FaHV4", "Dolomites 4K Scenic"),
        ("WBIOP01Bb_U", "Winter Golden Light 4K"),
        # --- Islands & Beaches ---
        ("3FZZ8BU8K8o", "Greek Islands & Beaches 4K"),
        ("54xXb7R33rQ", "Santorini, Corfu & Athens 3hr 4K"),
        ("4zAEDLwl9HI", "Santorini 4K Ultra HD"),
        ("62bWUYRxi8g", "Maui 4K Scenic"),
        ("1nf61dNdzPc", "Flying Over Kauai 4K"),
        ("4AtJV7U3DlU", "Flying Over Oahu 4K"),
        ("2iNdNqHRtCg", "Maldives 4K Crystal Waters"),
        ("1E5eTuYv_xg", "Maldives — Aerial Drone 4K"),
        ("2b2gJu-g3qE", "Italy 4K Scenic"),
        ("rFYYY9Axdkc", "Tropical Island Journey 8hr 4K"),
        # --- Cities ---
        ("4U2doN7RViU", "New York by Drone 4K HDR"),
        ("9yT2slMJZZ4", "New York City at Night 4K"),
        ("NDHuHu6QYeY", "Boston Aerial 8K HDR"),
        ("99ZU9piXq14", "Dubai by Drone 4K"),
        ("1m0xYx8sdyY", "Flying Over London 4K"),
        ("3EEnPfyfIJA", "Paris Aerial 4K"),
        ("6k7a8bw451M", "Japan Night Aerials 8K"),
        ("_3QuHXpikFk", "Flying Over Japan 4K"),
        ("7EJ3BcbB1M4", "Tokyo by Drone 4K"),
        ("KStBLFhyTcY", "Saint-Tropez 4K HDR"),
        ("keEN1N9OQJw", "Kyiv City Life 4K HDR"),
        # --- Space & Night Sky ---
        ("1wuyI5LSo-s", "Earth from ISS — ESA 4K"),
        ("YGZIaatAZ2U", "Pilot's View Over Greenland 4K"),
        ("U7twKn7IopE", "Northern Lights — 12hr 4K"),
        ("ejzmUmT9qrU", "Nightscapes — 8hr 4K Astrolapse"),
        ("4Q_-W0DAx6U", "Milky Way & Northern Lights 4K"),
        # --- Scotland & UK ---
        ("5U7HVaWAQRE", "Scotland 4K Ultra HD"),
        ("6QtP-BccWWU", "Scotland Isle of Skye 4K"),
        ("Scxs7L0vhZ4", "Norway — Timelapse Adventure 4K"),
        # --- Oceans & Underwater ---
        ("ewX-BNUwi3c", "Rainbow Reef — 8hr Underwater 8K"),
        ("1GIG2SFlAPM", "Great Barrier Reef 4K Drone"),
        # --- Grand Canyon ---
        ("4Y8eHOp9ah4", "Grand Canyon by Drone 4K"),
        # --- Apple TV / macOS Sonoma Screensavers ---
        ("2DDfL6uOUOw", "Apple TV · Flying Over Shaikh Zaid Road Dubai"),
        ("33LrIL2jsO8", "Apple TV · Far Out 4hr 4K"),
        ("_7vUD0QzLs8", "Apple TV · Over Northern China toward Korea"),
        ("8IGpCHVQu4I", "Apple TV · Over Yosemite National Park"),
        ("4lyrOQpviZY", "Apple TV · Central Park New York"),
        ("fOZAK-0ZFuA", "Apple TV · Iceland Landscape 4K"),
        ("y0dYqbYkqAw", "Apple TV · Yosemite National Park 4K"),
        ("kRrnR5bsqh8", "Apple TV · Iceland Landscape to Sky Snow 4K"),
        ("xXeNCjACEPY", "Apple TV · WWDC23 Apple Logo"),
        ("m2RWBs7KtlE", "Apple TV · Palau Jellyfish Ballet"),
        ("_wzOzMB_7cw", "Apple TV · California Kelp Forest Underwater"),
        ("i_ykeAE-aTo", "Apple TV · Barracuda Battery Underwater"),
        ("jOcyh0BrQOY", "Apple TV · Los Angeles Airport Cityscape 4K"),
        ("k5F3FdpPFgE", "Apple TV · London Evening Flyover"),
        ("1nJ35CXmOC8", "Apple TV · Los Angeles Sunset Cityscape"),
        ("VQHlFpWqh5Y", "Apple TV · Dubai Skyline Drone 4K"),
        ("0dMP-WIiaEs", "Apple TV · Sonoma Horizon"),
        ("SCgPjb3-W4I", "Apple TV · Sonoma Clouds"),
        ("brxH36Se9mg", "Apple TV · Sonoma Evening"),
        ("Qw4zFYlgeXU", "Apple TV · Sonoma River"),
        ("tDoZJ3aKp28", "Apple TV · California Wildflowers"),
        ("M0o5xB0QqTs", "Apple TV · Oregon Sunset Landscape"),
        ("rGbbhEi9a2A", "Apple TV · Captivating Oregon Coastline"),
        ("EyrS2hN3dGY", "Apple TV · Utah Evening"),
        ("0KZpNO3TqcQ", "Apple TV · Utah Monument Valley"),
        ("qTl2KWHg7E8", "Apple TV · Utah Cathedral Canyon"),
        ("pIh_teWB6qI", "Apple TV · Utah Factory Butte"),
        ("QEJ38Uxtwks", "Apple TV · Utah Lake Powell"),
        ("mnzRlq0E6gE", "Apple TV · Utah Olympia Bar"),
        ("_bg2rmR3bBE", "Apple TV · Grand Canyon Evening"),
        ("DB0QQFFqJ2s", "Apple TV · Grand Canyon Sediment"),
        ("Xvlvh-nEJ7U", "Apple TV · Grand Canyon Sunset Splendor"),
        ("Ga2d6iG6w8Y", "Apple TV · Arizona Coal Mine Canyon"),
        ("_fLz5a3yCK8", "Apple TV · California Temblor Range"),
        ("iemO_vyViQA", "Apple TV · California Carrizo Plain"),
        ("QabXLfEHKIw", "Apple TV · Redwoods From Above"),
        ("odTsAdzWbdc", "Apple TV · Redwoods River Serene"),
        ("BRN5_p1Sp2s", "Apple TV · Hawaiian Valley Serenity"),
        ("HDR8O3PVHTE", "Apple TV · Hawaii Coastline"),
        ("QNHiFR-XNkQ", "Apple TV · Hawaii Dark Clouds"),
        ("Ocig-YX1erc", "Apple TV · Tahiti Waves Mist"),
        ("iEGqyHTObIQ", "Apple TV · Patagonia Lake Tranquility"),
        ("b9S3vIGVmpQ", "Apple TV · Patagonia River Landscapes"),
        ("rzlNJ2B9rCk", "Apple TV · Icelandic Coastline Serenity"),
        ("EZu4qcxSjzc", "Apple TV · Icelandic Lake Reflections"),
        ("gay1MXagJPQ", "Apple TV · Icelandic Riverbed Serenity"),
        ("CZyGGGcPzWw", "Apple TV · Icelandic Fjord Exploration"),
        ("7KeJXMB3rWQ", "Apple TV · Greenland Glacier Snow"),
        ("S28gXu3AAZw", "Apple TV · Greenland Tranquil Evening"),
        ("3DUHlmZc8vU", "Apple TV · Fjord From Above"),
        ("lNVbulZdNDI", "Apple TV · China Mountain Cliffs"),
        ("tRhERyMsb6Q", "Apple TV · China Silhouette Elegance"),
        ("nDDBDl2o_7Y", "Apple TV · China Paddy Field Beauty"),
        ("BNOv4e7JsGQ", "Apple TV · Great Wall of China"),
        ("TeRPBNdKH5w", "Apple TV · Great Wall of China Daylight"),
        ("OTa_i_IIGRw", "Apple TV · Flying Over Hong Kong Skyline"),
        ("vlwQNLVTOqE", "Apple TV · Hong Kong at Night"),
        ("W88q50t1-mA", "Apple TV · Hong Kong Horizon Cityscape"),
        ("lSpYLG87c_Q", "Apple TV · Flying Over New York at Night"),
        ("SZiXmtlJ5B4", "Apple TV · New York Midtown Cityscape"),
        ("Mvpy5-pal3U", "Apple TV · Flying by Hollywood Sign LA"),
        ("qEk1SdjvhXI", "Apple TV · San Francisco at Night"),
        ("M_azCfuFeAE", "Apple TV · San Francisco Fog"),
        ("sDQgk9xlFxU", "Apple TV · San Francisco Ferry Building"),
        ("4FemBZfe4uY", "Apple TV · San Francisco Ferry Building New"),
        ("Qe_ITuAhikQ", "Apple TV · Fly-by Golden Gate Bridge"),
        ("-kvR5DHjf2g", "Apple TV · Night in Burj Khalifa Dubai"),
        ("H6x9Vo-j-g8", "Apple TV · Dubai Creek Harbour"),
        ("XwgKXJwJ4og", "Apple TV · Dubai Creek Old Dubai"),
        ("ng0SF4oaGfE", "Apple TV · London Skyline"),
        ("i0_OIFAoiBo", "Apple TV · Los Angeles at Night"),
        ("kVOjy6qKXS0", "Apple TV · Africa from Above"),
        ("8eEBzCuuqhM", "Apple TV · South Africa / Red Sea Coral"),
        ("WNA8jDc2Ewg", "Apple TV · West Africa Earth"),
        ("iOKf8dSnJA8", "Apple TV · North Africa Earth"),
        ("m7YkeOYtrKg", "Apple TV · East Asia Earth"),
        ("LBhZdTRj-g4", "Apple TV · North Atlantic"),
        ("o7AKfPoMcV0", "Apple TV · Middle Eastern Tapestry Earth"),
        ("PFWpuFhZNDI", "Apple TV · Caribbean Dreamscape Earth"),
        ("cSsB_7qIB6U", "Apple TV · Caribbean Sea Earth"),
        ("Qf6s2vr_oh4", "Apple TV · Southern Europe Midnight"),
        ("UTCeMwFPZLQ", "Apple TV · Space View China at Night"),
        ("-pU8niIVazo", "Apple TV · Earth Caribbean Islands"),
        ("vzdWCEs7b1Q", "Apple TV · Earth Australia"),
        ("UzLaaSEhEdw", "Apple TV · Earth California"),
        ("ZIux5d_AodI", "Apple TV · Earth Southern California"),
        ("fLXhx_dWNhk", "Apple TV · Earth Europe Night"),
        ("TOOuAEahgq8", "Apple TV · Palau Jellyfish Blue Underwater"),
        ("Zde6DJpRUkI", "Apple TV · Alaskan Jellyfish Dark Underwater"),
        ("YKbVobKw_SY", "Apple TV · Alaskan Jellyfish Light Underwater"),
        ("bLQJ0kUJmOI", "Apple TV · Jack School Underwater Ballet"),
        ("HGXqb0I_4DU", "Apple TV · Kelp Dark Mystique Underwater"),
        ("OCN63pIirAg", "Apple TV · Bumpheads Underwater"),
        ("TsQIMbmudJA", "Apple TV · California Dolphin Pod Underwater"),
        ("G5ZKcG7AJdU", "Apple TV · Cownose Rays Underwater"),
        ("2-Gw44GymkE", "Apple TV · Grey Reef Sharks Underwater"),
        ("7xQYpisKF6o", "Apple TV · Sea Stars Underwater"),
        ("183PAc9ibWc", "Apple TV · Seal Pod Underwater Odyssey"),
    ]
    video_idx = td.timetuple().tm_yday % len(aerial_videos)
    video_id = aerial_videos[video_idx][0]
    videos_js = ", ".join(f'{{id:"{v[0]}",label:"{v[1]}"}}' for v in aerial_videos)
    # Fallback static image
    fallback_img = "https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=1920&q=80"

    # Today's events
    today_events = expand_events_for_date(events, td)
    events_html = ""
    for ev in today_events:
        start = ev.get("start") or ev.get("depart") or ""
        end = ev.get("end") or ""
        title = ev.get("title", "")
        tag = ""
        tag_color = "rgba(255,255,255,0.5)"
        if ev.get("type") == "travel":
            tag = "travel"
            tag_color = "#f0c040"
        elif ev.get("type") == "blocked":
            tag = "blocked"
            tag_color = "#ff6b6b"
        elif ev.get("location"):
            loc = ev["location"]
            tag_color = "#a29bfe"
            if "zoom.us" in loc or "meet.google" in loc or "teams.microsoft" in loc or loc.startswith("http"):
                if "zoom.us" in loc:
                    label = "Zoom"
                elif "meet.google" in loc:
                    label = "Meet"
                elif "teams.microsoft" in loc:
                    label = "Teams"
                else:
                    label = "Link"
                tag = f'<a href="{loc}" target="_blank" style="color:#a29bfe; text-decoration:underline;">{label}</a>'
            else:
                tag = loc

        parsed_start = parse_time(start) if start else None
        time_str = fmt_time(parsed_start) if parsed_start else ""
        if end:
            time_str += f"–{fmt_time(parse_time(end))}"
        # ISO datetime for JS countdown (e.g. "2026-03-31T14:00")
        start_iso = f"{td.isoformat()}T{parsed_start.strftime('%H:%M')}" if parsed_start else ""
        parsed_end = parse_time(end) if end else None
        end_iso = f"{td.isoformat()}T{parsed_end.strftime('%H:%M')}" if parsed_end else ""

        loc_raw = ev.get("location", "").replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
        events_html += f"""
          <div class="ev-row" data-start="{start_iso}" data-end="{end_iso}" data-location="{loc_raw}" style="display:flex; align-items:center; padding:7px 0; border-bottom:1px solid rgba(255,255,255,0.06);">
            <div style="min-width:100px; color:#a29bfe; font-weight:600; font-size:13px; font-variant-numeric:tabular-nums;">{time_str}</div>
            <div class="ev-title" style="flex:1; color:rgba(255,255,255,0.92); font-size:14px;">{title}</div>
            <div class="ev-countdown" style="display:none; color:#ff6b6b; font-size:11px; font-weight:700; font-variant-numeric:tabular-nums; min-width:50px; text-align:right; animation:blink 1s step-end infinite;"></div>
            <div style="color:{tag_color}; font-size:11px; font-weight:600; text-transform:uppercase;">{tag}</div>
          </div>"""

    # Free time
    free, total_mins = calc_free_time(today_events, config)
    free_str = ", ".join(f"{fmt_time(s)}–{fmt_time(e)}" for s, e in free)
    hours = total_mins / 60

    # Collect all tasks/milestones with due dates for the dashboard
    week_end = td + datetime.timedelta(days=days_ahead)
    all_due_items = []  # (due_date, name, project_name, is_milestone)
    for p in projects:
        if p.get("status") != "active":
            continue
        pname = p.get("name", "")
        for m in p.get("milestones", []):
            if m.get("done"):
                continue
            if m.get("due"):
                try:
                    due = parse_date(m["due"])
                except ValueError:
                    due = None
                if due and due <= week_end:
                    all_due_items.append((due, m["name"], pname, True))
            for t in m.get("tasks", []):
                if isinstance(t, dict) and not t.get("done") and t.get("due"):
                    try:
                        t_due = parse_date(t["due"])
                    except ValueError:
                        continue
                    if t_due <= week_end:
                        all_due_items.append((t_due, t.get("desc", ""), pname, False))
        for t in p.get("tasks", []):
            if isinstance(t, dict) and not t.get("done") and t.get("due"):
                try:
                    t_due = parse_date(t["due"])
                except ValueError:
                    continue
                if t_due <= week_end:
                    all_due_items.append((t_due, t.get("desc", ""), pname, False))

    all_due_items.sort(key=lambda x: x[0])
    tasks_list_html = ""
    current_heading = None
    for due, name, pname, is_ms in all_due_items:
        delta = (due - td).days
        if delta < 0:
            heading = "OVERDUE"
            heading_color = "#ff6b6b"
            color = "#ff6b6b"
            sub = f"{-delta}d late"
        elif delta == 0:
            heading = "TODAY"
            heading_color = "#f0c040"
            color = "#f0c040"
            sub = ""
        elif delta == 1:
            heading = "TOMORROW"
            heading_color = "#a29bfe"
            color = "rgba(255,255,255,0.55)"
            sub = ""
        else:
            heading = due.strftime("%a, %b %-d").upper()
            heading_color = "rgba(255,255,255,0.35)"
            color = "rgba(255,255,255,0.55)"
            sub = ""
        if heading != current_heading:
            mt = "12px" if current_heading is not None else "0"
            tasks_list_html += f'<div style="margin-top:{mt}; padding-bottom:3px; border-bottom:1px solid rgba(255,255,255,0.06); margin-bottom:4px;"><span style="font-family:JetBrains Mono,monospace; font-size:10px; color:{heading_color}; letter-spacing:0.08em;">{heading}</span></div>'
            current_heading = heading
        marker = "●" if is_ms else "·"
        sub_span = f' <span style="color:{color}; font-size:11px;">({sub})</span>' if sub else ""
        tasks_list_html += f'<div style="padding:3px 0 3px 8px; color:rgba(255,255,255,0.9); font-size:13px;"><span style="color:{color};">{marker}</span> {name} <span style="color:rgba(255,255,255,0.3); font-size:11px;">[{pname}]</span>{sub_span}</div>'

    # ── iCal-style week calendar (4-day view with navigation) ──
    cal_start_hour = 7
    cal_end_hour = 21
    cal_hours = cal_end_hour - cal_start_hour
    hour_px = 44
    cal_num_days = 14  # generate 14 days, show 4 at a time (adjustable)

    # Time gutter labels
    time_gutter = ""
    for h in range(cal_start_hour, cal_end_hour):
        lbl = f"{h % 12 or 12}{'a' if h < 12 else 'p'}"
        time_gutter += f'<div style="height:{hour_px}px; font-size:10px; color:rgba(255,255,255,0.35); text-align:right; padding-right:6px; line-height:1;">{lbl}</div>'

    # Day columns with overlap detection
    day_headers = ""
    day_columns = ""
    week_total_free = 0
    cal_day_labels_js = []
    for i in range(cal_num_days):
        d = td + datetime.timedelta(days=i)
        day_evts = expand_events_for_date(events, d)
        _, day_mins = calc_free_time(day_evts, config, date=d)
        week_total_free += day_mins
        is_td = (d == td)
        vis = "flex:1; min-width:0;" if i < 2 else "flex:1; min-width:0; display:none;"

        # JS label data
        cal_day_labels_js.append(f'"{d.strftime("%b %-d")}"')

        # Header
        day_name = d.strftime("%a")
        day_num = d.strftime("%-d")
        hdr_bg = "background:rgba(162,155,254,0.2); border-radius:8px;" if is_td else ""
        hdr_color = "#a29bfe" if is_td else "rgba(255,255,255,0.5)"
        num_weight = "700" if is_td else "500"
        day_headers += f'''<div class="cal-hdr" data-day="{i}" style="{vis} text-align:center; padding:6px 2px; {hdr_bg}">
            <div style="font-size:10px; color:{hdr_color}; text-transform:uppercase; letter-spacing:0.05em;">{day_name}</div>
            <div style="font-size:16px; font-weight:{num_weight}; color:{'#fff' if is_td else 'rgba(255,255,255,0.7)'};">{day_num}</div>
        </div>'''

        # Grid lines
        grid_lines = ""
        for h in range(cal_hours):
            grid_lines += f'<div style="height:{hour_px}px; border-top:1px solid rgba(255,255,255,0.05);"></div>'

        # ── Overlap detection: collect timed events, assign columns ──
        timed = []
        for ev in day_evts:
            st_raw = ev.get("start") or ev.get("depart")
            if not st_raw:
                continue
            st = parse_time(st_raw)
            et_raw = ev.get("end")
            if et_raw:
                et = parse_time(et_raw)
            else:
                et = (datetime.datetime.combine(d, st) + datetime.timedelta(hours=1)).time()
            sm = max(st.hour * 60 + st.minute - cal_start_hour * 60, 0)
            em = min(et.hour * 60 + et.minute - cal_start_hour * 60, cal_hours * 60)
            if em > sm:
                timed.append((sm, em, ev, st, et))
        timed.sort(key=lambda x: (x[0], -(x[1] - x[0])))

        # Greedy column assignment
        columns_end = []  # end-minute of last event in each column
        assignments = []
        for sm, em, ev, st, et in timed:
            placed = False
            for ci in range(len(columns_end)):
                if columns_end[ci] <= sm:
                    columns_end[ci] = em
                    assignments.append((ev, ci, st, et, sm, em))
                    placed = True
                    break
            if not placed:
                assignments.append((ev, len(columns_end), st, et, sm, em))
                columns_end.append(em)
        total_cols = max(len(columns_end), 1)

        # Generate event blocks with column-aware positioning
        event_blocks = ""
        for ev, col_idx, st, et, sm, em in assignments:
            top_pct = sm / (cal_hours * 60) * 100
            height_pct = max((em - sm) / (cal_hours * 60) * 100, 1.5)
            left_pct = col_idx / total_cols * 100
            width_pct = 100 / total_cols

            ev_title = ev.get("title", "")
            if ev.get("type") == "travel":
                ev_bg, ev_border = "rgba(240,192,64,0.75)", "#f0c040"
            elif ev.get("type") == "blocked":
                ev_bg, ev_border = "rgba(255,107,107,0.7)", "#ff6b6b"
            else:
                ev_bg, ev_border = "rgba(162,155,254,0.65)", "#a29bfe"

            event_blocks += f'''<div style="position:absolute; top:{top_pct:.1f}%; height:{height_pct:.1f}%;
                left:{left_pct:.1f}%; width:{width_pct:.1f}%;
                padding:0 1px; box-sizing:border-box;">
                <div style="height:100%; background:{ev_bg}; border-left:2px solid {ev_border}; border-radius:3px;
                padding:1px 3px; overflow:hidden; font-size:9px; color:#fff; line-height:1.3; cursor:default;"
                title="{fmt_time(st)}–{fmt_time(et)} {ev_title}">
                <div style="font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">{ev_title}</div>
                </div></div>'''

        col_bg = "background:rgba(162,155,254,0.04);" if is_td else ""
        col_vis = "" if i < 2 else "display:none;"
        day_columns += f'<div class="cal-col" data-day="{i}" style="flex:1; min-width:0; position:relative; {col_bg} border-left:1px solid rgba(255,255,255,0.04); {col_vis}">{grid_lines}{event_blocks}</div>'

    week_free_hours = week_total_free / 60
    cal_labels_js = ",".join(cal_day_labels_js)

    # Active projects
    active = [p for p in projects if p.get("status") == "active"]
    projects_html = ""
    for p in active:
        ms = p.get("milestones", [])
        done = sum(1 for m in ms if m.get("done"))
        total = len(ms)
        pct = int(done / total * 100) if total else 0
        cat_color = {"research": "#74b9ff", "software": "#a29bfe", "admin": "#f0c040", "coursework": "#ff6b6b"}.get(
            p.get("category", ""), "rgba(255,255,255,0.5)")
        deadline_str = ""
        if p.get("deadline"):
            dl = parse_date(p["deadline"])
            days = (dl - td).days
            if days < 0:
                deadline_str = f'<span style="color:#ff6b6b; font-size:12px; font-weight:600;">OVERDUE {-days}d</span>'
            elif days <= 7:
                deadline_str = f'<span style="color:#f0c040; font-size:12px; font-weight:600;">{days}d left</span>'
            else:
                deadline_str = f'<span style="color:rgba(255,255,255,0.4); font-size:12px;">{fmt_date(dl)}</span>'

        projects_html += f"""
          <div style="padding:8px 0; border-bottom:1px solid rgba(255,255,255,0.06);">
            <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:4px;">
              <div><span style="color:{cat_color}; font-size:14px;">●</span> <span style="color:rgba(255,255,255,0.9); font-weight:500;">{p['name']}</span></div>
              <div>{deadline_str}</div>
            </div>
            <div style="display:flex; align-items:center; gap:8px;">
              <div style="flex:1; background:rgba(255,255,255,0.08); border-radius:99px; height:6px; overflow:hidden;">
                <div style="background:{cat_color}; width:{max(pct, 0)}%; height:100%; border-radius:99px;"></div>
              </div>
              <span style="font-size:11px; color:rgba(255,255,255,0.4); font-weight:600;">{done}/{total}</span>
            </div>
          </div>"""

    # News HTML — collapsed (1 per source) + expanded (all 5 per source)
    news_html = ""
    news_expanded_html = ""
    source_colors = {"HN": "#ff6600", "NYT": "#a29bfe", "WSJ": "#55efc4", "Reuters": "#fd79a8", "CNN": "#ff6b6b", "BBC": "#bb1919", "NBC": "#74b9ff", "Fox": "#f0c040"}
    # Group by source
    from collections import OrderedDict
    news_by_src = OrderedDict()
    for src, title, href in news_items:
        news_by_src.setdefault(src, []).append((title, href))

    def _news_row(src, title, href):
        c = source_colors.get(src, "rgba(255,255,255,0.5)")
        t_esc = title.replace('"', '&quot;').replace('<', '&lt;')
        link = f'<a href="{href}" target="_blank" style="color:rgba(255,255,255,0.8); font-size:12px; text-decoration:none;" title="{t_esc}">{title[:85]}</a>' if href else f'<span style="color:rgba(255,255,255,0.8); font-size:12px;">{title[:85]}</span>'
        return f'<div style="padding:3px 0; border-bottom:1px solid rgba(255,255,255,0.04);"><span style="color:{c}; font-size:9px; font-weight:600; text-transform:uppercase; letter-spacing:0.05em; min-width:48px; display:inline-block;">{src}</span> {link}</div>'

    for src, items in news_by_src.items():
        if items:
            news_html += _news_row(src, items[0][0], items[0][1])
            for title, href in items[:5]:
                news_expanded_html += _news_row(src, title, href)

    # Stocks HTML — compact + expanded with sparklines
    stocks_compact_html = ""
    stocks_expanded_html = ""
    for item in stock_data:
        name, price, chg, pct = item[0], item[1], item[2], item[3]
        closes = item[4] if len(item) > 4 else []
        arrow = "▲" if chg >= 0 else "▼"
        c = "#55efc4" if chg >= 0 else "#ff6b6b"
        # Format price based on ticker type
        if name == "10Y Yield":
            price_str = f"{price:.2f}%"
        elif name == "Bitcoin":
            price_str = f"{price:,.0f}"
        elif name in ("WTI Oil", "Brent", "Gold"):
            price_str = f"${price:,.2f}"
        else:
            price_str = f"{price:,.0f}"
        row = f'<div class="stock-row" data-sym="{name}" style="display:flex; justify-content:space-between; align-items:center; padding:4px 0;"><span style="color:rgba(255,255,255,0.6); font-size:12px;">{name}</span><span class="stock-val" style="font-size:12px;"><span style="color:rgba(255,255,255,0.8);">{price_str}</span> <span style="color:{c};">{arrow} {abs(pct):.1f}%</span></span></div>'
        stocks_compact_html += row
        spark = _build_sparkline_svg(closes)
        stocks_expanded_html += row
        if spark:
            stocks_expanded_html += f'<div style="padding:0 0 4px 0;">{spark}</div>'

    # Predictions HTML — split into politics + trending, each with compact/expanded
    _choice_colors = ["#a29bfe", "#55efc4", "#f0c040", "#fd79a8", "#74b9ff", "#ff6b6b"]
    pol_compact_html = ""
    pol_expanded_html = ""
    trend_compact_html = ""
    trend_expanded_html = ""
    pol_count = 0
    trend_count = 0
    for ev in predictions:
        title = ev["title"]
        link = ev["link"]
        choices = ev["choices"]
        section = ev.get("section", "")
        t_esc = title.replace('"', '&quot;').replace('<', '&lt;')
        link_html = f'<a href="{link}" target="_blank" style="color:rgba(255,255,255,0.9); font-size:13px; font-weight:500; text-decoration:none;" title="{t_esc}">{title[:65]}</a>' if link else f'<span style="color:rgba(255,255,255,0.9); font-size:13px; font-weight:500;">{title[:65]}</span>'
        event_block = f'<div style="padding:6px 0; border-bottom:1px solid rgba(255,255,255,0.06);">{link_html}'
        event_block_exp = event_block
        spark_series = []
        for ci, ch in enumerate(choices):
            c = _choice_colors[ci % len(_choice_colors)]
            label = ch["label"][:30] if ch["label"] else "Yes"
            prob = ch["prob"]
            bar_w = max(prob, 2)
            row = f'<div style="display:flex; align-items:center; gap:6px; padding:2px 0;"><span style="color:{c}; font-size:10px; min-width:80px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{label}</span><div style="flex:1; background:rgba(255,255,255,0.06); border-radius:99px; height:5px; overflow:hidden;"><div style="background:{c}; width:{bar_w}%; height:100%; border-radius:99px;"></div></div><span style="color:{c}; font-size:11px; font-weight:600; min-width:32px; text-align:right;">{prob}%</span></div>'
            event_block += row
            event_block_exp += row
            hist = ch.get("history", [])
            if hist and len(hist) >= 2:
                spark_series.append(([p * 100 for p in hist], c))
        if spark_series:
            overlap_svg = _build_overlapped_sparklines_svg(spark_series, width=280, height=36)
            if overlap_svg:
                event_block_exp += f'<div style="padding:2px 0 2px 0; margin-top:2px; background:rgba(255,255,255,0.03); border-radius:6px; padding:3px 4px;">{overlap_svg}</div>'
        event_block += '</div>'
        event_block_exp += '</div>'
        if section == "politics":
            pol_compact_html += event_block
            pol_expanded_html += event_block_exp
            pol_count += 1
        else:
            trend_compact_html += event_block
            trend_expanded_html += event_block_exp
            trend_count += 1

    # Science HTML — redesigned with live data visualizations
    science_html = ""
    _sci_any = launches or nasa_headlines or cern_headlines or solar_data or ligo_events
    if _sci_any:
        # ── Space Weather gauges row ──
        sw_wind = solar_data.get("wind_speed", "")
        sw_bz = solar_data.get("bz", "")
        sw_bt = solar_data.get("bt", "")
        sw_kp = solar_data.get("kp", "")
        lhc_lumi = solar_data.get("lhc_lumi", "")
        if sw_wind or sw_kp or lhc_lumi:
            science_html += '<div style="display:flex; gap:6px; flex-wrap:wrap; margin-bottom:10px;">'
            if sw_wind:
                science_html += f'<div style="flex:1; min-width:60px; padding:6px 8px; background:rgba(255,255,255,0.06); border-radius:8px; text-align:center;"><div style="font-size:8px; color:rgba(255,255,255,0.4); text-transform:uppercase; letter-spacing:0.05em;">Wind</div><div style="font-size:16px; font-weight:600; color:#74b9ff;">{sw_wind}<span style="font-size:9px; color:rgba(255,255,255,0.35);"> km/s</span></div></div>'
            if sw_bz:
                bz_val = float(sw_bz) if sw_bz else 0
                bz_color = "#ff6b6b" if bz_val < -5 else "#f0c040" if bz_val < 0 else "#55efc4"
                science_html += f'<div style="flex:1; min-width:60px; padding:6px 8px; background:rgba(255,255,255,0.06); border-radius:8px; text-align:center;"><div style="font-size:8px; color:rgba(255,255,255,0.4); text-transform:uppercase; letter-spacing:0.05em;">Bz</div><div style="font-size:16px; font-weight:600; color:{bz_color};">{sw_bz}<span style="font-size:9px; color:rgba(255,255,255,0.35);"> nT</span></div></div>'
            if sw_kp:
                kp_val = float(sw_kp) if sw_kp else 0
                kp_color = "#ff6b6b" if kp_val >= 5 else "#f0c040" if kp_val >= 4 else "#55efc4"
                science_html += f'<div style="flex:1; min-width:60px; padding:6px 8px; background:rgba(255,255,255,0.06); border-radius:8px; text-align:center;"><div style="font-size:8px; color:rgba(255,255,255,0.4); text-transform:uppercase; letter-spacing:0.05em;">Kp</div><div style="font-size:16px; font-weight:600; color:{kp_color};">{sw_kp}</div></div>'
            if lhc_lumi:
                science_html += f'<div style="flex:1; min-width:60px; padding:6px 8px; background:rgba(255,255,255,0.06); border-radius:8px; text-align:center;"><div style="font-size:8px; color:rgba(255,255,255,0.4); text-transform:uppercase; letter-spacing:0.05em;">LHC</div><div style="font-size:14px; font-weight:600; color:#f0c040;">{lhc_lumi}</div></div>'
            science_html += '</div>'
        # Solar wind sparkline
        wind_history = solar_data.get("wind_history", [])
        if wind_history:
            sw_spark = _build_sparkline_svg(wind_history[-48:], width=380, height=28)
            if sw_spark:
                science_html += f'<div style="margin-bottom:8px;"><div style="font-size:8px; color:rgba(255,255,255,0.3); margin-bottom:2px;">SOLAR WIND 2H</div>{sw_spark}</div>'
        # ── Live images row: Sun (SUVI 304 Å) + Aurora ──
        science_html += '<div style="display:flex; gap:6px; margin-bottom:10px;">'
        science_html += '<div style="flex:1; text-align:center;"><img src="https://services.swpc.noaa.gov/images/animations/suvi/primary/304/latest.png" style="width:100%; border-radius:8px; opacity:0.9;" alt="Sun SUVI 304" onerror="this.style.display=\'none\'"><div style="font-size:8px; color:rgba(255,255,255,0.3); margin-top:2px;">SUN 304\u00c5 LIVE</div></div>'
        science_html += '<div style="flex:1; text-align:center;"><img src="https://services.swpc.noaa.gov/images/aurora-forecast-northern-hemisphere.jpg" style="width:100%; border-radius:8px; opacity:0.9;" alt="Aurora Forecast" onerror="this.style.display=\'none\'"><div style="font-size:8px; color:rgba(255,255,255,0.3); margin-top:2px;">AURORA FORECAST</div></div>'
        science_html += '</div>'
        # ── LIGO Gravitational Wave Events ──
        if ligo_events:
            science_html += '<div style="font-family:JetBrains Mono,monospace; font-size:9px; color:#a29bfe; letter-spacing:0.1em; text-transform:uppercase; margin-bottom:4px;">LIGO EVENTS</div>'
            for sid, created, group, labels in ligo_events:
                label_tags = ""
                for lb in labels[:3]:
                    label_tags += f'<span style="background:rgba(162,155,254,0.2); color:#a29bfe; font-size:7px; padding:1px 4px; border-radius:3px; margin-left:3px;">{lb}</span>'
                science_html += f'<div style="padding:2px 0; border-bottom:1px solid rgba(255,255,255,0.04); display:flex; align-items:center; gap:4px;"><span style="color:rgba(255,255,255,0.7); font-size:11px; font-weight:500;">{sid}</span><span style="color:rgba(255,255,255,0.3); font-size:10px;">{group}</span><span style="flex:1;"></span>{label_tags}</div>'
        # ── Launches ──
        if launches:
            science_html += '<div style="font-family:JetBrains Mono,monospace; font-size:9px; color:#fd79a8; letter-spacing:0.1em; text-transform:uppercase; margin:8px 0 4px 0;">&#128640; LAUNCHES</div>'
            for name, net in launches:
                countdown = ""
                if net:
                    try:
                        launch_dt = datetime.datetime.fromisoformat(net.replace("Z", "+00:00"))
                        delta = launch_dt - datetime.datetime.now(datetime.timezone.utc)
                        if delta.total_seconds() > 0:
                            countdown = f"T-{delta.days}d {delta.seconds // 3600}h"
                        else:
                            countdown = "Launched"
                    except Exception:
                        pass
                science_html += f'<div style="padding:3px 0; border-bottom:1px solid rgba(255,255,255,0.04); display:flex; justify-content:space-between;"><span style="color:rgba(255,255,255,0.8); font-size:12px; flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{name[:55]}</span><span style="color:#55efc4; font-size:11px; font-weight:600; flex-shrink:0; margin-left:8px;">{countdown}</span></div>'
        # ── CMS Vistar (LHC operational status) ──
        science_html += '<div style="font-family:JetBrains Mono,monospace; font-size:9px; color:#f0c040; letter-spacing:0.1em; text-transform:uppercase; margin:8px 0 4px 0;">&#9883; LHC / CMS</div>'
        science_html += '<div style="margin-bottom:8px;"><a href="https://op-webtools.web.cern.ch/vistar/?usr=LHCCMS" target="_blank"><img src="https://vistar-capture.s3.cern.ch/cms.png" style="width:100%; border-radius:6px; opacity:0.9;" alt="LHC CMS Vistar" onerror="this.parentElement.style.display=\'none\'"></a><div style="font-size:8px; color:rgba(255,255,255,0.3); margin-top:2px;">CMS VISTAR LIVE</div></div>'
        # ── CERN Courier headlines ──
        if cern_headlines:
            science_html += '<div style="font-family:JetBrains Mono,monospace; font-size:9px; color:#f0c040; letter-spacing:0.1em; text-transform:uppercase; margin:4px 0 4px 0;">CERN COURIER</div>'
            for title, href in cern_headlines:
                t_esc = title.replace('"', '&quot;').replace('<', '&lt;')
                link_tag = f'<a href="{href}" target="_blank" style="color:rgba(255,255,255,0.8); font-size:12px; text-decoration:none;" title="{t_esc}">{title[:75]}</a>' if href else f'<span style="color:rgba(255,255,255,0.8); font-size:12px;">{title[:75]}</span>'
                science_html += f'<div style="padding:3px 0; border-bottom:1px solid rgba(255,255,255,0.04);">{link_tag}</div>'
        # ── NASA headlines ──
        if nasa_headlines:
            science_html += '<div style="font-family:JetBrains Mono,monospace; font-size:9px; color:#74b9ff; letter-spacing:0.1em; text-transform:uppercase; margin:8px 0 4px 0;">&#128225; NASA</div>'
            for title, href in nasa_headlines:
                t_esc = title.replace('"', '&quot;').replace('<', '&lt;')
                link_tag = f'<a href="{href}" target="_blank" style="color:rgba(255,255,255,0.8); font-size:12px; text-decoration:none;" title="{t_esc}">{title[:75]}</a>' if href else f'<span style="color:rgba(255,255,255,0.8); font-size:12px;">{title[:75]}</span>'
                science_html += f'<div style="padding:3px 0; border-bottom:1px solid rgba(255,255,255,0.04);">{link_tag}</div>'

    # HPC HTML — default shows sparklines (expanded), toggle hides them (compact)
    hpc_compact_html = ""
    hpc_expanded_html = ""
    def _hpc_color(val, thresh):
        if thresh == 0:
            return "rgba(255,255,255,0.6)"
        ratio = val / thresh
        if ratio > 0.8:
            return "#ff6b6b"
        elif ratio > 0.5:
            return "#f0c040"
        return "#55efc4"
    for item in hpc_data:
        qos, ncpus, ngpus, ncpus_24h, ngpus_24h, ncpus_thresh, ngpus_thresh = item[:7]
        has_gpu = item[7] if len(item) > 7 else True
        cpu_color = _hpc_color(ncpus, ncpus_thresh)
        cpu_row = f'<div style="display:flex; justify-content:space-between; align-items:center; padding:3px 0;"><span style="color:rgba(255,255,255,0.6); font-size:12px;">{qos} CPU</span><span style="font-size:12px;"><span style="color:{cpu_color}; font-weight:600;">{int(ncpus)}</span><span style="color:rgba(255,255,255,0.35);"> / {int(ncpus_thresh)}</span></span></div>'
        hpc_compact_html += cpu_row
        cpu_spark = _build_sparkline_svg(ncpus_24h)
        hpc_expanded_html += cpu_row
        if cpu_spark:
            hpc_expanded_html += f'<div style="padding:0 0 4px 0;">{cpu_spark}</div>'
        if has_gpu:
            gpu_color = _hpc_color(ngpus, ngpus_thresh)
            gpu_row = f'<div style="display:flex; justify-content:space-between; align-items:center; padding:3px 0;"><span style="color:rgba(255,255,255,0.6); font-size:12px;">{qos} GPU</span><span style="font-size:12px;"><span style="color:{gpu_color}; font-weight:600;">{int(ngpus)}</span><span style="color:rgba(255,255,255,0.35);"> / {int(ngpus_thresh)}</span></span></div>'
            hpc_compact_html += gpu_row
            gpu_spark = _build_sparkline_svg(ngpus_24h)
            hpc_expanded_html += gpu_row
            if gpu_spark:
                hpc_expanded_html += f'<div style="padding:0 0 4px 0;">{gpu_spark}</div>'

    # Entertainment HTML (Rotten Tomatoes)
    ent_compact_html = ""
    ent_expanded_html = ""
    _compact_n = 5
    def _ent_row(name, score, url):
        s_color = "#55efc4" if score.isdigit() and int(score) >= 60 else "#f0c040" if score.isdigit() and int(score) >= 40 else "#ff6b6b"
        n_esc = name.replace('"', '&quot;').replace('<', '&lt;')
        link_tag = f'<a href="{url}" target="_blank" style="color:rgba(255,255,255,0.8); font-size:12px; text-decoration:none;" title="{n_esc}">{name[:50]}</a>' if url else f'<span style="color:rgba(255,255,255,0.8); font-size:12px;">{name[:50]}</span>'
        score_tag = f'<span style="color:{s_color}; font-size:11px; font-weight:600;">{score}%</span>' if score else ''
        return f'<div style="padding:3px 0; border-bottom:1px solid rgba(255,255,255,0.04); display:flex; justify-content:space-between; align-items:center;">{link_tag}{score_tag}</div>'
    if rt_movies or rt_shows:
        if rt_movies:
            mov_hdr = '<div style="font-family:JetBrains Mono,monospace; font-size:9px; color:#ff6b6b; letter-spacing:0.1em; text-transform:uppercase; margin-bottom:4px;">&#127909; MOVIES</div>'
            ent_compact_html += mov_hdr
            ent_expanded_html += mov_hdr
            for idx, (name, score, url) in enumerate(rt_movies):
                row = _ent_row(name, score, url)
                if idx < _compact_n:
                    ent_compact_html += row
                ent_expanded_html += row
        if rt_shows:
            show_hdr = '<div style="font-family:JetBrains Mono,monospace; font-size:9px; color:#a29bfe; letter-spacing:0.1em; text-transform:uppercase; margin:8px 0 4px 0;">&#128250; TV SHOWS</div>'
            ent_compact_html += show_hdr
            ent_expanded_html += show_hdr
            for idx, (name, score, url) in enumerate(rt_shows):
                row = _ent_row(name, score, url)
                if idx < _compact_n:
                    ent_compact_html += row
                ent_expanded_html += row

    # Paul Graham essay HTML
    pg_html = ""
    if pg_title and pg_text:
        pg_t_esc = pg_title.replace('"', '&quot;').replace('<', '&lt;')
        pg_text_esc = pg_text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
        pg_html = f'''<a id="pg-title" href="{pg_url}" target="_blank" style="color:#f0c040; font-size:14px; font-weight:600; text-decoration:none; display:block; margin-bottom:6px;" title="{pg_t_esc}">{pg_title}</a>
        <div id="pg-body" style="max-height:300px; overflow-y:auto; scrollbar-width:thin; scrollbar-color:rgba(255,255,255,0.1) transparent; font-size:12px; color:rgba(255,255,255,0.7); line-height:1.6;">{pg_text_esc}</div>'''

    # Greetings
    hr = now().hour
    if hr < 12:
        greet = "Good morning"
    elif hr < 17:
        greet = "Good afternoon"
    else:
        greet = "Good evening"

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="300">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    font-family: 'Space Grotesk', -apple-system, sans-serif;
    height: 100vh; overflow: hidden;
    background: #0a0a1a;
    color: #fff;
  }}
  .video-bg {{
    position: fixed; top:0; left:0; width:100%; height:100%;
    z-index:0; overflow:hidden; pointer-events:none;
  }}
  .video-bg iframe {{
    position: absolute; top:50%; left:50%;
    width: 100vw; height: 56.25vw;
    min-height: 100vh; min-width: 177.78vh;
    transform: translate(-50%,-50%);
    pointer-events: none;
  }}
  .video-bg img {{
    position: absolute; top:0; left:0; width:100%; height:100%;
    object-fit:cover;
  }}
  .overlay {{
    position: fixed; top:0; left:0; width:100%; height:100%;
    background: linear-gradient(135deg, rgba(0,0,0,0.25) 0%, rgba(0,0,0,0.05) 50%, rgba(0,0,0,0.35) 100%);
    z-index:0;
  }}
  /* ── Ambient left side ── */
  .ambient {{
    position: fixed; bottom: 50px; left: 50px; z-index:2;
    max-width: 720px;
    text-shadow: 0 2px 20px rgba(0,0,0,0.5), 0 1px 3px rgba(0,0,0,0.4);
  }}
  /* ── Panels right side ── */
  .panels {{
    position: fixed; top: 20px; right: 20px; z-index:2;
    width: 420px;
    max-height: calc(100vh - 40px);
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: rgba(255,255,255,0.1) transparent;
  }}
  .panels::-webkit-scrollbar {{ width: 4px; }}
  .panels::-webkit-scrollbar-thumb {{ background: rgba(255,255,255,0.1); border-radius:4px; }}
  .glass {{
    background: rgba(15, 15, 30, 0.5);
    backdrop-filter: blur(30px) saturate(1.4);
    -webkit-backdrop-filter: blur(30px) saturate(1.4);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 14px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.25);
    padding: 14px 16px;
    margin-bottom: 10px;
  }}
  .stitle {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 9px; font-weight: 600;
    letter-spacing: 0.14em; text-transform: uppercase;
    margin-bottom: 8px;
    display: flex; align-items: center; gap: 5px;
  }}
  a {{ color: #a29bfe; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .nbtn {{
    background:rgba(255,255,255,0.08); border:1px solid rgba(255,255,255,0.1);
    color:rgba(255,255,255,0.6); width:26px; height:26px; border-radius:7px;
    cursor:pointer; font-size:11px; display:inline-flex; align-items:center; justify-content:center; flex-shrink:0;
  }}
  .nbtn:hover {{ background:rgba(162,155,254,0.3); color:#fff; }}
  .reorder-btn {{
    display:none; background:rgba(255,255,255,0.08); border:1px solid rgba(255,255,255,0.12);
    color:rgba(255,255,255,0.5); width:28px; height:28px; border-radius:7px;
    cursor:pointer; font-size:14px; align-items:center; justify-content:center; margin-left:auto;
  }}
  .reorder-btn:active {{ background:rgba(162,155,254,0.4); color:#fff; }}
  #notepad-area {{
    width:100%; box-sizing:border-box; background:rgba(255,255,255,0.04);
    border:1px solid rgba(255,255,255,0.1); border-radius:10px; color:rgba(255,255,255,0.85);
    font-family:'JetBrains Mono',monospace; font-size:13px; padding:10px 12px;
    resize:none; outline:none; transition:border-color 0.2s;
    flex:1 1 auto; min-height:120px;
  }}
  [data-wid="notepad"] {{ display:flex; flex-direction:column; overflow:hidden !important; }}
  #notepad-area:focus {{ border-color:rgba(162,155,254,0.5); }}
  #notepad-area::placeholder {{ color:rgba(255,255,255,0.25); }}
  #notepad-status {{
    display:flex; align-items:center; justify-content:space-between;
    margin-top:6px; font-family:'JetBrains Mono',monospace; font-size:11px;
    color:rgba(255,255,255,0.35);
  }}
  #notepad-status > span {{ display:flex; align-items:center; gap:5px; }}
  .sync-dot {{
    display:inline-block; width:6px; height:6px; border-radius:50%;
    background:#ffeaa7; transition:background 0.3s;
  }}
  #notepad-mic.mic-on {{ background:rgba(255,71,87,0.4); border-color:rgba(255,71,87,0.6); color:#ff4757; animation:mic-pulse 1s infinite; }}
  #notepad-tts.tts-on {{ background:rgba(85,239,196,0.3); border-color:rgba(85,239,196,0.5); color:#55efc4; }}
  @keyframes mic-pulse {{ 0%,100% {{ opacity:1; }} 50% {{ opacity:0.5; }} }}
  .sync-dot.synced {{ background:#55efc4; }}
  .sync-dot.saving {{ background:#ffeaa7; }}
  .sync-dot.error {{ background:#ff7675; }}
  .drag.dragging {{ position:fixed; z-index:100; cursor:grabbing; box-shadow:0 12px 48px rgba(0,0,0,0.5); transition:none; }}
  .drag-handle:active {{ cursor:grabbing; }}
  .glass .resize-h {{
    position:absolute; bottom:0; left:0; right:0; height:10px; cursor:ns-resize;
    opacity:0; transition:opacity 0.2s;
    background:linear-gradient(transparent, rgba(162,155,254,0.15));
    border-radius:0 0 14px 14px;
  }}
  .glass:hover .resize-h {{ opacity:1; }}
  .glass .resize-h::after {{
    content:''; position:absolute; bottom:3px; left:50%; transform:translateX(-50%);
    width:30px; height:3px; border-radius:2px; background:rgba(255,255,255,0.2);
  }}
  .glass .resize-w {{
    position:absolute; top:0; right:0; bottom:10px; width:10px; cursor:ew-resize;
    opacity:0; transition:opacity 0.2s;
    background:linear-gradient(to right, transparent, rgba(162,155,254,0.15));
    border-radius:0 14px 14px 0;
  }}
  .glass:hover .resize-w {{ opacity:1; }}
  .glass .resize-w::after {{
    content:''; position:absolute; right:3px; top:50%; transform:translateY(-50%);
    width:3px; height:30px; border-radius:2px; background:rgba(255,255,255,0.2);
  }}
  .glass .resize-corner {{
    position:absolute; bottom:0; right:0; width:14px; height:14px; cursor:nwse-resize;
    opacity:0; transition:opacity 0.2s;
    border-radius:0 0 14px 0;
  }}
  .glass:hover .resize-corner {{ opacity:1; }}
  .glass .resize-corner::after {{
    content:''; position:absolute; bottom:3px; right:3px;
    width:8px; height:8px; border-right:2px solid rgba(255,255,255,0.25); border-bottom:2px solid rgba(255,255,255,0.25);
    border-radius:0 0 2px 0;
  }}
  .col-guide {{
    position:fixed; border-left:2px dashed rgba(162,155,254,0.25);
    top:0; bottom:0; z-index:99; pointer-events:none;
    transition:border-color 0.15s;
  }}
  .col-guide.active {{ border-color:rgba(162,155,254,0.6); }}
  @keyframes blink {{
    0%, 100% {{ opacity:1; }}
    50% {{ opacity:0.3; }}
  }}
  @keyframes redpulse {{
    0%   {{ border-color: rgba(255,60,60,0.1);  box-shadow: 0 0 15px rgba(255,60,60,0.05), inset 0 0 20px rgba(255,60,60,0.03); }}
    25%  {{ border-color: rgba(255,60,60,0.45); box-shadow: 0 0 30px rgba(255,60,60,0.12), inset 0 0 40px rgba(255,60,60,0.06); }}
    50%  {{ border-color: rgba(255,60,60,0.75); box-shadow: 0 0 50px rgba(255,60,60,0.2),  inset 0 0 60px rgba(255,60,60,0.1);  }}
    75%  {{ border-color: rgba(255,60,60,0.45); box-shadow: 0 0 30px rgba(255,60,60,0.12), inset 0 0 40px rgba(255,60,60,0.06); }}
    100% {{ border-color: rgba(255,60,60,0.1);  box-shadow: 0 0 15px rgba(255,60,60,0.05), inset 0 0 20px rgba(255,60,60,0.03); }}
  }}
  .countdown-glow {{
    border: 3px solid rgba(255,60,60,0.4);
    animation: redpulse 3s cubic-bezier(0.37, 0, 0.63, 1) infinite;
  }}
  #big-countdown {{
    display:none; position:fixed; top:0; left:0; right:0; bottom:0; z-index:9999;
    pointer-events:none;
    justify-content:center; align-items:center; flex-direction:column;
  }}
  #big-countdown.active {{
    display:flex;
  }}
  #big-countdown .cd-time {{
    font-family:'JetBrains Mono',monospace;
    font-size:min(30vw, 340px); font-weight:700; letter-spacing:-6px;
    color:#fff; text-shadow:0 0 80px rgba(255,80,80,0.6), 0 0 160px rgba(255,60,60,0.3);
    line-height:1;
  }}
  #big-countdown .cd-label {{
    font-family:'JetBrains Mono',monospace;
    font-size:min(4vw, 42px); font-weight:500;
    color:rgba(255,255,255,0.6); margin-top:16px;
    max-width:80vw; text-align:center; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
  }}
  #big-countdown .cd-location {{
    font-family:'JetBrains Mono',monospace;
    font-size:min(3vw, 32px); font-weight:400;
    color:rgba(255,255,255,0.45); margin-top:10px;
    max-width:80vw; text-align:center; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
  }}
  #big-countdown .cd-location a {{
    pointer-events:auto; color:#a29bfe; text-decoration:underline;
  }}
  #panel-menu {{
    display:none; position:fixed; bottom:66px; right:20px; z-index:20;
    background:rgba(15,15,30,0.85); backdrop-filter:blur(20px); -webkit-backdrop-filter:blur(20px);
    border:1px solid rgba(255,255,255,0.1); border-radius:14px;
    padding:10px 14px; max-height:60vh; overflow-y:auto; min-width:180px;
  }}
  #panel-menu.open {{ display:block; }}
  #panel-menu label {{
    display:flex; align-items:center; gap:8px; padding:6px 0;
    font-family:'JetBrains Mono',monospace; font-size:11px; color:rgba(255,255,255,0.7);
    border-bottom:1px solid rgba(255,255,255,0.05); cursor:pointer;
  }}
  #panel-menu label:last-child {{ border-bottom:none; }}
  #panel-menu input[type="checkbox"] {{ accent-color:#a29bfe; width:14px; height:14px; }}
  .pm-header {{
    font-family:'JetBrains Mono',monospace; font-size:9px; text-transform:uppercase;
    letter-spacing:0.1em; color:rgba(255,255,255,0.35); margin-bottom:6px;
  }}
  @media (max-width: 768px) {{
    body {{ height:auto; overflow:auto; }}
    .video-bg {{ position:absolute; height:300px; }}
    .video-bg iframe {{ display:none; }}
    .video-bg img {{ display:block; width:100%; height:100%; object-fit:cover; }}
    .overlay {{ position:absolute; height:300px; }}
    .ambient {{
      position:relative; bottom:auto; left:auto; max-width:100%;
      padding:24px 16px 16px; z-index:2;
    }}
    .panels {{
      position:relative; top:auto; right:auto; width:100%;
      max-height:none; overflow-y:visible; padding:0 8px 24px;
    }}
    .glass {{
      padding:10px 12px !important; border-radius:12px !important;
    }}
    .glass .resize-h, .glass .resize-w, .glass .resize-corner {{
      display:none !important;
    }}
    .glass, .drag-handle {{ cursor:default !important; }}
    .reorder-btn {{ display:inline-flex !important; }}
    #vid-select {{ display:none !important; }}
    #vid-pause {{ display:none !important; }}
    #grid-btn {{ display:none !important; }}
    .desktop-only {{ display:none !important; }}
    #clock {{ font-size:42px !important; letter-spacing:-1px !important; }}
    .ambient {{ padding:16px 14px 12px !important; }}
    .ambient .drag-handle > div:last-child {{ font-size:16px !important; margin-top:2px !important; }}
    #w-block {{ margin-top:12px !important; gap:8px !important; }}
    #w-emoji {{ font-size:28px !important; }}
    #w-temp {{ font-size:22px !important; }}
    #w-desc {{ font-size:13px !important; }}
    #w-hilo {{ font-size:12px !important; margin-top:1px !important; }}
    .ambient div[style*="max-width:630px"] {{ margin-top:14px !important; }}
    .ambient div[style*="max-width:630px"] > div:first-child {{ font-size:14px !important; line-height:1.4 !important; }}
    .ambient div[style*="max-width:630px"] > div:last-child {{ font-size:12px !important; margin-top:3px !important; }}
    #last-updated {{ font-size:10px !important; }}
    .ambient button {{ font-size:10px !important; padding:3px 10px !important; }}
    #now-meeting {{ margin-top:10px !important; padding:8px 12px !important; }}
    #now-meeting > div:first-child {{ font-size:9px !important; }}
    #now-meeting-title {{ font-size:14px !important; }}
    #now-meeting-link {{ font-size:13px !important; }}
    #now-meeting-remaining {{ font-size:11px !important; }}
    #big-countdown .cd-time {{ font-size:min(15vw,120px) !important; }}
    #big-countdown .cd-label {{ font-size:min(3.5vw,18px) !important; }}
    #big-countdown .cd-location {{ font-size:min(3vw,16px) !important; }}
  }}
</style>
<script src="https://www.gstatic.com/firebasejs/8.10.1/firebase-app.js"></script>
<script src="https://www.gstatic.com/firebasejs/8.10.1/firebase-database.js"></script>
<script>
  firebase.initializeApp({{
    apiKey: "AIzaSyDjN9Cx0HvLjYqvt6deDB837tu5pTQptIo",
    databaseURL: "https://dashboard-46d6b-default-rtdb.firebaseio.com"
  }});
</script>
</head>
<body>

<!-- Video background (desktop only — uses YT Player API for pause control) -->
<div class="video-bg" id="video-bg">
  <div id="yt-player"></div>
  <img src="{fallback_img}" alt="" style="z-index:-1;">
</div>
<div class="overlay"></div>
<script src="https://www.youtube.com/iframe_api"></script>
<script>
var ytPlayer = null;
var ytPaused = localStorage.getItem('lori_vid_paused') === '1';
var ytReady = false;

function onYouTubeIframeAPIReady() {{
  if (window.innerWidth <= 768) return;
  ytPlayer = new YT.Player('yt-player', {{
    videoId: '{video_id}',
    playerVars: {{
      autoplay: ytPaused ? 0 : 1, mute: 1, loop: 1, playlist: '{video_id}',
      controls: 0, showinfo: 0, modestbranding: 1, rel: 0,
      disablekb: 1, fs: 0, iv_load_policy: 3, start: 30
    }},
    events: {{
      onReady: function(e) {{
        ytReady = true;
        if (ytPaused) e.target.pauseVideo();
      }}
    }}
  }});
}}
</script>

<!-- ═══ Ambient left: clock, date, weather, quote ═══ -->
<div class="ambient drag" data-wid="ambient">
  <div class="drag-handle" style="cursor:grab;">
    <div id="clock" style="font-size:108px; font-weight:300; letter-spacing:-3px; line-height:1;">{now().strftime("%-I:%M")}</div>
    <div style="font-size:30px; font-weight:400; color:rgba(255,255,255,0.75); margin-top:6px;">{td.strftime("%A, %B %-d, %Y")}</div>
  </div>
  <div id="now-meeting" style="display:none; margin-top:16px; padding:12px 18px; background:rgba(85,239,196,0.08); border:1px solid rgba(85,239,196,0.2); border-radius:12px; max-width:630px;">
    <div style="font-family:'JetBrains Mono',monospace; font-size:13px; color:#55efc4; text-transform:uppercase; letter-spacing:0.1em; margin-bottom:6px;">&#9679; Now in progress</div>
    <div id="now-meeting-title" style="font-size:22px; font-weight:600; color:rgba(255,255,255,0.9);"></div>
    <div id="now-meeting-link" style="font-size:20px; margin-top:6px;"></div>
    <div id="now-meeting-remaining" style="font-family:'JetBrains Mono',monospace; font-size:16px; color:rgba(255,255,255,0.4); margin-top:6px;"></div>
  </div>

  {"" if not w_temp else f'''<div id="w-block" style="display:flex; align-items:center; gap:14px; margin-top:24px;">
    <span id="w-emoji" style="font-size:54px;">{w_emoji}</span>
    <div>
      <span id="w-temp" style="font-size:42px; font-weight:600;">{w_temp}°F</span>
      <span id="w-desc" style="font-size:22px; color:rgba(255,255,255,0.6); margin-left:10px;">{w_desc}</span>
    </div>
  </div>
  <div id="w-hilo" style="font-size:20px; color:rgba(255,255,255,0.4); margin-top:3px;">H:{w_hi}° L:{w_lo}° · {location}</div>'''}

  <div style="margin-top:32px; max-width:630px;">
    <div style="font-size:24px; font-weight:400; color:rgba(255,255,255,0.7); line-height:1.5; font-style:italic;">"{quote_text}"</div>
    <div style="font-size:20px; color:rgba(255,255,255,0.35); margin-top:6px;">— {quote_author}</div>
  </div>
  <div style="margin-top:16px; display:flex; align-items:center; gap:10px;">
    <span id="last-updated" style="font-family:'JetBrains Mono',monospace; font-size:15px; color:rgba(255,255,255,0.25); letter-spacing:0.05em;"></span>
    <button onclick="location.reload()" style="background:rgba(255,255,255,0.08); border:1px solid rgba(255,255,255,0.12); color:rgba(255,255,255,0.4); font-family:'JetBrains Mono',monospace; font-size:14px; padding:5px 14px; border-radius:8px; cursor:pointer; letter-spacing:0.05em; text-transform:uppercase; transition:all 0.2s;" onmouseover="this.style.background='rgba(255,255,255,0.15)';this.style.color='rgba(255,255,255,0.7)';" onmouseout="this.style.background='rgba(255,255,255,0.08)';this.style.color='rgba(255,255,255,0.4)';">&#8635; Refresh</button>
  </div>
</div>

<!-- ═══ Panels right side ═══ -->
<div class="panels">

  <!-- Today's Schedule -->
  <div class="glass drag" data-wid="today">
    <div class="stitle drag-handle" style="color:#a29bfe; cursor:grab;">&#9654; TODAY · {len(today_events)}{_rb_first}</div>
    {events_html if events_html else '<div style="color:rgba(255,255,255,0.3); font-size:12px;">No events</div>'}
    <div style="margin-top:8px; padding-top:8px; border-top:1px solid rgba(255,255,255,0.06); display:flex; justify-content:space-between;">
      <span style="font-family:'JetBrains Mono',monospace; font-size:9px; color:rgba(255,255,255,0.3); text-transform:uppercase;">Free</span>
      <span style="font-size:12px; font-weight:600; color:#a29bfe;">~{hours:.1f}h — {free_str}</span>
    </div>
  </div>

  <!-- Hourly Weather (right after today) -->
  {hourly_html}

  <!-- Forecast (right after hourly) -->
  {weather_html}

  <!-- Tasks -->
  <div class="glass drag" data-wid="tasks">
    <div class="stitle drag-handle" style="color:#55efc4; cursor:grab;">&#9889; TASKS{_rb_first}</div>
    {tasks_list_html if tasks_list_html else '<div style="color:rgba(255,255,255,0.3); font-size:12px;">All clear</div>'}
  </div>

  <!-- Markets (expanded tickers + sparklines) -->
  {"" if not stocks_compact_html else f'''
  <div class="glass drag" data-wid="stocks" style="padding:12px 16px;">
    <div class="stitle drag-handle" style="color:#f0c040; cursor:grab;">
      &#128200; MARKETS
      <button onclick="toggleStocks()" class="nbtn" style="margin-left:auto; font-size:9px;" id="stocks-btn" title="Expand/collapse">−</button>{_rb}
    </div>
    <div id="stocks-compact" style="display:none;">{stocks_compact_html}</div>
    <div id="stocks-full">{stocks_expanded_html}</div>
  </div>'''}

  <!-- HiPerGator -->
  {"" if not hpc_compact_html else f'''
  <div class="glass drag" data-wid="hpc" style="padding:12px 16px;">
    <div class="stitle drag-handle" style="color:#06b6d4; cursor:grab;">
      &#128421; HIPERGATOR
      <span id="hpc-updated" style="font-size:9px; color:rgba(255,255,255,0.3); font-weight:400; margin-left:6px;">{"Updated " + hpc_updated_fmt if hpc_updated_fmt else ""}</span>
      <button onclick="refreshHPC()" class="nbtn" style="margin-left:auto; font-size:9px;" id="hpc-refresh-btn" title="Refresh data">&#8635;</button>
      <button onclick="toggleHPC()" class="nbtn" style="font-size:9px;" id="hpc-btn" title="Expand/collapse">−</button>{_rb}
    </div>
    <div id="hpc-compact" style="display:none;">{hpc_compact_html}</div>
    <div id="hpc-full">{hpc_expanded_html}</div>
  </div>'''}

  <!-- Polymarket: Politics -->
  {"" if not pol_expanded_html else f'''
  <div class="glass drag" data-wid="poly-politics" style="padding:12px 16px;">
    <div class="stitle drag-handle" style="color:#a855f7; cursor:grab;">
      &#127922; POLY · POLITICS
      <span style="font-size:9px; color:rgba(255,255,255,0.3); font-weight:400; margin-left:4px;">{pol_count}</span>
      <button onclick="togglePolPol()" class="nbtn" style="margin-left:auto; font-size:9px;" id="polpol-btn" title="Toggle trend lines">&#8722;</button>{_rb}
    </div>
    <div id="polpol-compact" style="display:none; max-height:400px; overflow-y:auto;">{pol_compact_html}</div>
    <div id="polpol-full" style="max-height:400px; overflow-y:auto;">{pol_expanded_html}</div>
  </div>'''}

  <!-- Polymarket: Trending -->
  {"" if not trend_expanded_html else f'''
  <div class="glass drag" data-wid="poly-trending" style="padding:12px 16px;">
    <div class="stitle drag-handle" style="color:#ff6600; cursor:grab;">
      &#128293; POLY · TRENDING
      <span style="font-size:9px; color:rgba(255,255,255,0.3); font-weight:400; margin-left:4px;">{trend_count}</span>
      <button onclick="togglePolTrend()" class="nbtn" style="margin-left:auto; font-size:9px;" id="poltrend-btn" title="Toggle trend lines">&#8722;</button>{_rb}
    </div>
    <div id="poltrend-compact" style="display:none; max-height:400px; overflow-y:auto;">{trend_compact_html}</div>
    <div id="poltrend-full" style="max-height:400px; overflow-y:auto;">{trend_expanded_html}</div>
  </div>'''}

  <!-- News -->
  {"" if not news_html else f'''
  <div class="glass drag" data-wid="news">
    <div class="stitle drag-handle" style="color:#fd79a8; cursor:grab;">
      &#128240; HEADLINES
      <button onclick="toggleNews()" class="nbtn" style="margin-left:auto; font-size:9px;" id="news-btn" title="Expand/collapse">+</button>{_rb}
    </div>
    <div id="news-compact">{news_html}</div>
    <div id="news-full" style="display:none;">{news_expanded_html}</div>
  </div>'''}

  <!-- Science -->
  {"" if not science_html else f'''
  <div class="glass drag" data-wid="science" style="padding:12px 16px;">
    <div class="stitle drag-handle" style="color:#55efc4; cursor:grab;">&#128300; SCIENCE{_rb_first}</div>
    {science_html}
  </div>'''}

  <!-- Week Calendar -->
  <div class="glass drag" data-wid="calendar" style="padding:12px;">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
      <div class="stitle drag-handle" style="color:#a29bfe; margin-bottom:0; cursor:grab;">&#128197; <span id="cal-range"></span></div>
      <div style="display:flex; gap:4px; align-items:center;">
        <span style="font-family:'JetBrains Mono',monospace; font-size:10px; color:rgba(255,255,255,0.3);">{week_free_hours:.1f}h</span>
        <button class="nbtn" onclick="calDays(-1)" title="Show fewer days" style="font-size:11px; padding:2px 5px;">−</button>
        <span id="cal-days-count" style="font-family:'JetBrains Mono',monospace; font-size:9px; color:rgba(255,255,255,0.35); min-width:14px; text-align:center;"></span>
        <button class="nbtn" onclick="calDays(1)" title="Show more days" style="font-size:11px; padding:2px 5px;">+</button>
        <span style="width:4px;"></span>
        <button class="nbtn" onclick="calNav(-1)">&#9664;</button>
        <button class="nbtn" onclick="calNav(1)">&#9654;</button>{_rb}
      </div>
    </div>
    <div style="display:flex; margin-left:28px;" id="cal-headers">{day_headers}</div>
    <div style="display:flex; overflow:hidden; border-radius:6px; border:1px solid rgba(255,255,255,0.04); margin-top:3px;" id="cal-grid">
      <div style="width:28px; flex-shrink:0;">{time_gutter}</div>
      {day_columns}
    </div>
  </div>

  <!-- Entertainment (Rotten Tomatoes) -->
  {"" if not ent_expanded_html else f'''
  <div class="glass drag" data-wid="entertainment" style="padding:12px 16px;">
    <div class="stitle drag-handle" style="color:#ff6b6b; cursor:grab;">
      &#127871; ENTERTAINMENT
      <button onclick="toggleEnt()" class="nbtn" style="margin-left:auto; font-size:9px;" id="ent-btn" title="Show more">+</button>{_rb}
    </div>
    <div id="ent-compact">{ent_compact_html}</div>
    <div id="ent-full" style="display:none; max-height:400px; overflow-y:auto;">{ent_expanded_html}</div>
  </div>'''}


  <!-- Paul Graham Essay -->
  {"" if not pg_html else f'''
  <div class="glass drag" data-wid="essay" style="padding:12px 16px; position:relative;">
    <div class="stitle drag-handle" style="color:#f0c040; cursor:grab;">
      &#128214; PAUL GRAHAM
      <button onclick="randomPG()" class="nbtn" style="margin-left:auto; font-size:9px;" title="Random essay">&#127922;</button>{_rb}
    </div>
    {pg_html}
  </div>'''}


  <!-- Projects -->
  {"" if not projects_html else f'''
  <div class="glass drag" data-wid="projects">
    <div class="stitle drag-handle" style="color:#74b9ff; cursor:grab;">&#9881; PROJECTS · {len(active)}{_rb_first}</div>
    {projects_html}
  </div>'''}

  <!-- Notepad -->
  <div class="glass drag" data-wid="notepad" style="padding:12px 16px; display:flex; flex-direction:column; min-height:280px;">
    <div class="stitle drag-handle" style="color:#81ecec; cursor:grab;">&#128221; NOTEPAD
      <button id="notepad-tts" class="nbtn" style="margin-left:auto;" title="Read aloud incoming text">&#128263;</button>
      <button id="notepad-mic" class="nbtn" title="Voice input">&#127908;</button>
    </div>
    <textarea id="notepad-area" placeholder="Type anything... syncs across devices" spellcheck="false"></textarea>
    <div id="notepad-status">
      <span><span class="sync-dot" id="notepad-dot"></span><span id="notepad-sync-text">Connecting...</span></span>
      <span id="notepad-timestamp"></span>
    </div>
  </div>


</div>

<!-- Big countdown overlay -->
<div id="big-countdown">
  <div class="cd-time" id="big-cd-time"></div>
  <div class="cd-label" id="big-cd-label"></div>
  <div class="cd-location" id="big-cd-location"></div>
</div>

<!-- Panel visibility menu -->
<div id="panel-menu"><div class="pm-header">Toggle Panels</div></div>

<!-- Video selector + reset -->
<div style="position:fixed; bottom:20px; right:20px; z-index:10; display:flex; align-items:center; gap:8px;">
  <select id="vid-select" onchange="selectVideo(this.value)" style="
    background:rgba(15,15,30,0.6); backdrop-filter:blur(20px); -webkit-backdrop-filter:blur(20px);
    border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:6px 28px 6px 10px;
    font-family:'JetBrains Mono',monospace; font-size:9px; color:rgba(255,255,255,0.5);
    cursor:pointer; outline:none; appearance:none; -webkit-appearance:none;
    background-image:url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2210%22 height=%226%22><path d=%22M0 0l5 6 5-6z%22 fill=%22rgba(255,255,255,0.4)%22/></svg>');
    background-repeat:no-repeat; background-position:right 8px center; background-size:10px 6px;
    max-width:220px; transition:all 0.2s;"
    onmouseover="this.style.borderColor='rgba(162,155,254,0.5)';this.style.color='rgba(255,255,255,0.8)'"
    onmouseout="this.style.borderColor='rgba(255,255,255,0.12)';this.style.color='rgba(255,255,255,0.5)'"
    title="Select background video">
  </select>
  <button id="vid-pause" onclick="toggleVideoPause()" style="width:36px; height:36px; border-radius:50%;
    background:rgba(15,15,30,0.5); backdrop-filter:blur(20px); -webkit-backdrop-filter:blur(20px);
    border:1px solid rgba(255,255,255,0.08); color:rgba(255,255,255,0.4); font-size:16px;
    cursor:pointer; display:flex; align-items:center; justify-content:center; transition:all 0.2s;"
    onmouseover="this.style.background='rgba(162,155,254,0.3)';this.style.color='#fff'"
    onmouseout="this.style.background='rgba(15,15,30,0.5)';this.style.color='rgba(255,255,255,0.4)'"
    title="Pause/play background video">&#9208;</button>
  <button id="vis-btn" onclick="togglePanelMenu()" style="width:36px; height:36px; border-radius:50%;
    background:rgba(15,15,30,0.5); backdrop-filter:blur(20px); -webkit-backdrop-filter:blur(20px);
    border:1px solid rgba(255,255,255,0.08); color:rgba(255,255,255,0.4); font-size:16px;
    cursor:pointer; display:flex; align-items:center; justify-content:center; transition:all 0.2s;"
    onmouseover="this.style.background='rgba(162,155,254,0.3)';this.style.color='#fff'"
    onmouseout="this.style.background='rgba(15,15,30,0.5)';this.style.color='rgba(255,255,255,0.4)'"
    title="Toggle panel visibility">&#9881;</button>
  <button id="grid-btn" onclick="autoGridLayout()" style="width:36px; height:36px; border-radius:50%;
    background:rgba(15,15,30,0.5); backdrop-filter:blur(20px); -webkit-backdrop-filter:blur(20px);
    border:1px solid rgba(255,255,255,0.08); color:rgba(255,255,255,0.4); font-size:16px;
    cursor:pointer; display:flex; align-items:center; justify-content:center; transition:all 0.2s;"
    onmouseover="this.style.background='rgba(162,155,254,0.3)';this.style.color='#fff'"
    onmouseout="this.style.background='rgba(15,15,30,0.5)';this.style.color='rgba(255,255,255,0.4)'"
    title="Auto-grid layout">&#9638;</button>
  <button id="split-btn" onclick="autoGridSplit()" style="width:36px; height:36px; border-radius:50%;
    background:rgba(15,15,30,0.5); backdrop-filter:blur(20px); -webkit-backdrop-filter:blur(20px);
    border:1px solid rgba(255,255,255,0.08); color:rgba(255,255,255,0.4); font-size:16px;
    cursor:pointer; display:flex; align-items:center; justify-content:center; transition:all 0.2s;"
    onmouseover="this.style.background='rgba(162,155,254,0.3)';this.style.color='#fff'"
    onmouseout="this.style.background='rgba(15,15,30,0.5)';this.style.color='rgba(255,255,255,0.4)'"
    title="Split grid layout (halves left, fulls right)">&#9707;</button>
  <button onclick="resetWidgets()" style="width:36px; height:36px; border-radius:50%;
    background:rgba(15,15,30,0.5); backdrop-filter:blur(20px); -webkit-backdrop-filter:blur(20px);
    border:1px solid rgba(255,255,255,0.08); color:rgba(255,255,255,0.4); font-size:14px;
    cursor:pointer; display:flex; align-items:center; justify-content:center; transition:all 0.2s;"
    onmouseover="this.style.background='rgba(162,155,254,0.3)';this.style.color='#fff'"
    onmouseout="this.style.background='rgba(15,15,30,0.5)';this.style.color='rgba(255,255,255,0.4)'"
    title="Reset widget positions">&#8634;</button>
  <span style="width:1px; height:20px; background:rgba(255,255,255,0.1); margin:0 2px;" class="desktop-only"></span>
  <span class="desktop-only" style="font-size:8px; font-family:'JetBrains Mono',monospace; color:rgba(255,255,255,0.25); margin-right:2px; line-height:1.2; text-align:right;">LAYOUTS<br><span style="color:rgba(255,255,255,0.18);">shift=save</span></span>
  <button id="slot-1" onclick="onLayoutSlot(1,event)" style="width:28px; height:28px; border-radius:50%;
    background:rgba(15,15,30,0.5); backdrop-filter:blur(20px); -webkit-backdrop-filter:blur(20px);
    border:1px solid rgba(255,255,255,0.08); color:rgba(255,255,255,0.4); font-size:11px;
    font-family:'JetBrains Mono',monospace;
    cursor:pointer; display:flex; align-items:center; justify-content:center; transition:all 0.2s;"
    onmouseover="this.style.background='rgba(162,155,254,0.3)';this.style.color='#fff'"
    onmouseout="this.style.background='rgba(15,15,30,0.5)';this.style.color='rgba(255,255,255,0.4)'"
    title="Load layout 1 (Shift+click to save)" class="desktop-only">1</button>
  <button id="slot-2" onclick="onLayoutSlot(2,event)" style="width:28px; height:28px; border-radius:50%;
    background:rgba(15,15,30,0.5); backdrop-filter:blur(20px); -webkit-backdrop-filter:blur(20px);
    border:1px solid rgba(255,255,255,0.08); color:rgba(255,255,255,0.4); font-size:11px;
    font-family:'JetBrains Mono',monospace;
    cursor:pointer; display:flex; align-items:center; justify-content:center; transition:all 0.2s;"
    onmouseover="this.style.background='rgba(162,155,254,0.3)';this.style.color='#fff'"
    onmouseout="this.style.background='rgba(15,15,30,0.5)';this.style.color='rgba(255,255,255,0.4)'"
    title="Load layout 2 (Shift+click to save)" class="desktop-only">2</button>
  <button id="slot-3" onclick="onLayoutSlot(3,event)" style="width:28px; height:28px; border-radius:50%;
    background:rgba(15,15,30,0.5); backdrop-filter:blur(20px); -webkit-backdrop-filter:blur(20px);
    border:1px solid rgba(255,255,255,0.08); color:rgba(255,255,255,0.4); font-size:11px;
    font-family:'JetBrains Mono',monospace;
    cursor:pointer; display:flex; align-items:center; justify-content:center; transition:all 0.2s;"
    onmouseover="this.style.background='rgba(162,155,254,0.3)';this.style.color='#fff'"
    onmouseout="this.style.background='rgba(15,15,30,0.5)';this.style.color='rgba(255,255,255,0.4)'"
    title="Load layout 3 (Shift+click to save)" class="desktop-only">3</button>
</div>

<script>
(function() {{
  // ── Last-updated timestamp ──
  (function() {{
    var d = new Date();
    var h = d.getHours() % 12 || 12;
    var m = String(d.getMinutes()).padStart(2, '0');
    var ampm = d.getHours() >= 12 ? 'pm' : 'am';
    var el = document.getElementById('last-updated');
    if (el) el.textContent = 'Last updated ' + h + ':' + m + ampm;
  }})();

  // ── Live clock ──
  var countdownActive = false;
  function updateClock() {{
    if (countdownActive) return;
    var d = new Date();
    var h = d.getHours() % 12 || 12;
    var m = String(d.getMinutes()).padStart(2, '0');
    var el = document.getElementById('clock');
    if (el) el.textContent = h + ':' + m;
  }}
  setInterval(updateClock, 10000);

  // ── Event countdown timers (5 min before start) ──
  var bigCd = document.getElementById('big-countdown');
  var bigCdTime = document.getElementById('big-cd-time');
  var bigCdLabel = document.getElementById('big-cd-label');
  var bigCdLocation = document.getElementById('big-cd-location');
  var autoOpenedEvents = {{}};

  function updateCountdowns() {{
    var now = new Date();
    var soonestDiff = Infinity;
    var soonestTitle = '';
    var soonestLocation = '';
    document.querySelectorAll('.ev-row[data-start]').forEach(function(row) {{
      var s = row.dataset.start;
      if (!s) return;
      var start = new Date(s);
      var diff = start - now;
      var cd = row.querySelector('.ev-countdown');
      if (!cd) return;
      var titleEl = row.querySelector('.ev-title');
      var title = titleEl ? titleEl.textContent : '';
      // Show countdown if within 5 minutes (300000ms) and not yet started
      if (diff > 0 && diff <= 300000) {{
        var mins = Math.floor(diff / 60000);
        var secs = Math.floor((diff % 60000) / 1000);
        cd.textContent = mins + ':' + String(secs).padStart(2, '0');
        cd.style.display = '';
        cd.style.color = '#ff6b6b';
        if (diff <= 60000) {{
          cd.style.animation = 'blink 0.5s step-end infinite';
          cd.style.fontSize = '13px';
        }} else {{
          cd.style.animation = 'blink 1s step-end infinite';
          cd.style.fontSize = '11px';
        }}
        if (diff < soonestDiff) {{ soonestDiff = diff; soonestTitle = title; soonestLocation = row.dataset.location || ''; }}
      }} else if (diff > -60000 && diff <= 0) {{
        cd.textContent = 'NOW';
        cd.style.display = '';
        cd.style.color = '#55efc4';
        cd.style.animation = 'blink 0.5s step-end infinite';
        if (diff > -60000 && Math.abs(diff) < Math.abs(soonestDiff)) {{ soonestDiff = diff; soonestTitle = title; soonestLocation = row.dataset.location || ''; }}
      }} else {{
        cd.style.display = 'none';
      }}
    }});

    // Build location HTML for overlay
    function renderLocation(loc) {{
      if (!loc) return '';
      if (/zoom\.us|meet\.google|teams\.microsoft/i.test(loc)) {{
        var lbl = /zoom\.us/i.test(loc) ? 'Zoom' : /meet\.google/i.test(loc) ? 'Meet' : 'Teams';
        return '<a href="' + loc + '" target="_blank">' + lbl + ' — Join Meeting</a>';
      }} else if (/^https?:\/\//i.test(loc)) {{
        return '<a href="' + loc + '" target="_blank">' + loc + '</a>';
      }}
      return loc;
    }}

    // Big center countdown + red glow
    if (soonestDiff !== Infinity && soonestDiff > 0 && soonestDiff <= 300000) {{
      var m = Math.floor(soonestDiff / 60000);
      var s = Math.floor((soonestDiff % 60000) / 1000);
      bigCdTime.textContent = m + ':' + String(s).padStart(2, '0');
      bigCdLabel.textContent = soonestTitle;
      bigCdLocation.innerHTML = renderLocation(soonestLocation);
      bigCd.classList.add('active');
      document.body.classList.add('countdown-glow');
      countdownActive = true;
      // Faster border pulse in last minute
      document.body.style.animationDuration = soonestDiff <= 60000 ? '1.5s' : '3s';
    }} else if (soonestDiff <= 0 && soonestDiff > -60000) {{
      bigCdTime.textContent = 'NOW';
      bigCdTime.style.color = '#55efc4';
      bigCdTime.style.textShadow = '0 0 60px rgba(85,239,196,0.6), 0 0 120px rgba(85,239,196,0.3)';
      bigCdLabel.textContent = soonestTitle;
      bigCdLocation.innerHTML = renderLocation(soonestLocation);
      bigCd.classList.add('active');
      document.body.classList.remove('countdown-glow');
      countdownActive = true;
      // Auto-open meeting link when countdown hits zero
      if (soonestLocation && !autoOpenedEvents[soonestLocation + soonestTitle]) {{
        if (/zoom\.us|meet\.google|teams\.microsoft/i.test(soonestLocation)) {{
          autoOpenedEvents[soonestLocation + soonestTitle] = true;
          window.open(soonestLocation, '_blank');
        }}
      }}
    }} else {{
      bigCd.classList.remove('active');
      document.body.classList.remove('countdown-glow');
      bigCdTime.style.color = '';
      bigCdTime.style.textShadow = '';
      bigCdLocation.innerHTML = '';
      countdownActive = false;
      updateClock();
    }}
  }}

  // ── In-progress meeting indicator near clock ──
  var nowMtg = document.getElementById('now-meeting');
  var nowMtgTitle = document.getElementById('now-meeting-title');
  var nowMtgLink = document.getElementById('now-meeting-link');
  var nowMtgRemaining = document.getElementById('now-meeting-remaining');
  function updateNowMeeting() {{
    var now = new Date();
    var active = null;
    document.querySelectorAll('.ev-row[data-start]').forEach(function(row) {{
      var s = row.dataset.start, e = row.dataset.end;
      if (!s || !e) return;
      var start = new Date(s), end = new Date(e);
      if (now >= start && now < end) {{
        var titleEl = row.querySelector('.ev-title');
        var title = titleEl ? titleEl.textContent : '';
        var loc = row.dataset.location || '';
        var remaining = end - now;
        if (!active || start > new Date(active.start)) {{
          active = {{ title: title, loc: loc, start: s, end: end, remaining: remaining }};
        }}
      }}
    }});
    if (active) {{
      nowMtg.style.display = '';
      nowMtgTitle.textContent = active.title;
      var mins = Math.floor(active.remaining / 60000);
      var secs = Math.floor((active.remaining % 60000) / 1000);
      nowMtgRemaining.textContent = mins + ':' + String(secs).padStart(2, '0') + ' remaining';
      if (active.loc && /^https?:\/\//i.test(active.loc)) {{
        var lbl = /zoom\.us/i.test(active.loc) ? 'Zoom' : /meet\.google/i.test(active.loc) ? 'Meet' : /teams\.microsoft/i.test(active.loc) ? 'Teams' : 'Link';
        nowMtgLink.innerHTML = '<a href="' + active.loc + '" target="_blank" style="color:#a29bfe; text-decoration:underline; pointer-events:auto;">' + lbl + ' — Join Meeting</a>';
      }} else if (active.loc) {{
        nowMtgLink.textContent = active.loc;
      }} else {{
        nowMtgLink.innerHTML = '';
      }}
    }} else {{
      nowMtg.style.display = 'none';
    }}
  }}

  updateCountdowns();
  updateNowMeeting();
  setInterval(updateCountdowns, 1000);
  setInterval(updateNowMeeting, 1000);

  // ── Auto-reload page every 5 min for fresh data ──
  // (meta refresh handles this, but as backup)
  setTimeout(function() {{ location.reload(); }}, 300000);

  // ── Video selector ──
  var videos = [{videos_js}];
  var vidIdx = {video_idx};
  var vidSelect = document.getElementById('vid-select');

  // Populate dropdown
  videos.forEach(function(v, i) {{
    var opt = document.createElement('option');
    opt.value = i;
    opt.textContent = v.label;
    if (i === vidIdx) opt.selected = true;
    vidSelect.appendChild(opt);
  }});

  // Style dropdown options (dark background)
  var styleTag = document.createElement('style');
  styleTag.textContent = '#vid-select option {{ background:rgba(15,15,30,0.95); color:rgba(255,255,255,0.7); padding:4px 8px; }}';
  document.head.appendChild(styleTag);

  window.selectVideo = function(idx) {{
    idx = parseInt(idx);
    vidIdx = idx;
    var v = videos[idx];
    if (ytPlayer && ytReady) {{
      ytPlayer.loadVideoById({{videoId: v.id, startSeconds: 30}});
      ytPlayer.mute();
      if (ytPaused) setTimeout(function() {{ ytPlayer.pauseVideo(); }}, 1500);
    }}
    localStorage.setItem('lori_vid_idx', idx);
  }};

  window.toggleVideoPause = function() {{
    if (!ytPlayer || !ytReady) return;
    var btn = document.getElementById('vid-pause');
    if (ytPaused) {{
      ytPlayer.playVideo();
      ytPaused = false;
      localStorage.removeItem('lori_vid_paused');
      if (btn) {{ btn.innerHTML = '&#9208;'; btn.title = 'Pause background video'; }}
    }} else {{
      ytPlayer.pauseVideo();
      ytPaused = true;
      localStorage.setItem('lori_vid_paused', '1');
      if (btn) {{ btn.innerHTML = '&#9654;'; btn.title = 'Play background video'; }}
    }}
  }};

  // Update button icon on load if already paused
  if (ytPaused) {{
    var _pb = document.getElementById('vid-pause');
    if (_pb) {{ _pb.innerHTML = '&#9654;'; _pb.title = 'Play background video'; }}
  }}

  // Restore last selected video from localStorage
  var savedIdx = localStorage.getItem('lori_vid_idx');
  if (savedIdx !== null && parseInt(savedIdx) !== vidIdx && parseInt(savedIdx) < videos.length) {{
    vidSelect.value = savedIdx;
    vidIdx = parseInt(savedIdx);
    var _waitReady = setInterval(function() {{
      if (ytReady && ytPlayer) {{
        clearInterval(_waitReady);
        var sv = videos[parseInt(savedIdx)];
        ytPlayer.loadVideoById({{videoId: sv.id, startSeconds: 30}});
        ytPlayer.mute();
        if (ytPaused) setTimeout(function() {{ ytPlayer.pauseVideo(); }}, 1500);
      }}
    }}, 200);
  }};

  // ── Calendar navigation ──
  var calLabels = [{cal_labels_js}];
  var calStart = 0;
  var calShow = 2;
  try {{ var _cs = parseInt(localStorage.getItem('lori-cal-days')); if (_cs >= 1 && _cs <= {cal_num_days}) calShow = _cs; }} catch(e) {{}}
  var calTotal = {cal_num_days};

  function updateCal() {{
    document.querySelectorAll('.cal-hdr, .cal-col').forEach(function(el) {{
      var d = parseInt(el.dataset.day);
      el.style.display = (d >= calStart && d < calStart + calShow) ? '' : 'none';
    }});
    var r = document.getElementById('cal-range');
    if (r) r.textContent = calLabels[calStart] + ' – ' + calLabels[Math.min(calStart + calShow - 1, calTotal - 1)];
    var dc = document.getElementById('cal-days-count');
    if (dc) dc.textContent = calShow + 'd';
  }}
  updateCal();

  window.calNav = function(dir) {{
    calStart = Math.max(0, Math.min(calTotal - calShow, calStart + dir));
    updateCal();
  }};
  window.calDays = function(dir) {{
    calShow = Math.max(1, Math.min(calTotal, calShow + dir));
    calStart = Math.max(0, Math.min(calTotal - calShow, calStart));
    try {{ localStorage.setItem('lori-cal-days', calShow); }} catch(e) {{}}
    updateCal();
  }};

  // ── Current time red bar in calendar ──
  var CAL_START_H = {cal_start_hour}, CAL_HOURS = {cal_hours};
  function updateTimeBar() {{
    var now = new Date();
    var mins = now.getHours() * 60 + now.getMinutes() - CAL_START_H * 60;
    var totalMins = CAL_HOURS * 60;
    // Find today's column (data-day="0")
    var col = document.querySelector('.cal-col[data-day="0"]');
    if (!col) return;
    var bar = document.getElementById('cal-now-bar');
    if (mins < 0 || mins > totalMins) {{
      if (bar) bar.style.display = 'none';
      return;
    }}
    var pct = mins / totalMins * 100;
    if (!bar) {{
      bar = document.createElement('div');
      bar.id = 'cal-now-bar';
      bar.style.cssText = 'position:absolute; left:0; right:0; height:2px; background:#ff4757; z-index:10; pointer-events:none;';
      // Red dot on left edge
      var dot = document.createElement('div');
      dot.style.cssText = 'position:absolute; left:-4px; top:-3px; width:8px; height:8px; background:#ff4757; border-radius:50%;';
      bar.appendChild(dot);
      col.appendChild(bar);
    }}
    bar.style.display = '';
    bar.style.top = pct.toFixed(2) + '%';
  }}
  updateTimeBar();
  setInterval(updateTimeBar, 30000);

  // ── Toggle expand/collapse helpers with persistence ──
  var TOGGLE_KEY = 'lori-toggle-states';
  function _loadToggles() {{ try {{ return JSON.parse(localStorage.getItem(TOGGLE_KEY)) || {{}}; }} catch(e) {{ return {{}}; }} }}
  function _saveToggle(id, expanded) {{ try {{ var s = _loadToggles(); s[id] = expanded; localStorage.setItem(TOGGLE_KEY, JSON.stringify(s)); }} catch(e) {{}} }}
  function _toggle(compactId, fullId, btnId) {{
    var c = document.getElementById(compactId);
    var f = document.getElementById(fullId);
    var b = document.getElementById(btnId);
    if (!c || !f) return;
    if (f.style.display === 'none') {{
      c.style.display = 'none';
      f.style.display = '';
      if (b) b.textContent = '−';
      _saveToggle(fullId, true);
    }} else {{
      c.style.display = '';
      f.style.display = 'none';
      if (b) b.textContent = '+';
      _saveToggle(fullId, false);
    }}
  }}
  // Restore saved toggle states on load
  (function() {{
    var saved = _loadToggles();
    Object.keys(saved).forEach(function(fullId) {{
      var f = document.getElementById(fullId);
      if (!f) return;
      var compactId = fullId.replace('-full', '-compact');
      var btnId = fullId.replace('-full', '-btn');
      var c = document.getElementById(compactId);
      var b = document.getElementById(btnId);
      if (!c) return;
      if (saved[fullId]) {{
        c.style.display = 'none';
        f.style.display = '';
        if (b) b.textContent = '−';
      }} else {{
        c.style.display = '';
        f.style.display = 'none';
        if (b) b.textContent = '+';
      }}
    }});
  }})()
  window.toggleNews = function() {{ _toggle('news-compact', 'news-full', 'news-btn'); }};
  window.toggleStocks = function() {{ _toggle('stocks-compact', 'stocks-full', 'stocks-btn'); }};
  window.toggleHPC = function() {{ _toggle('hpc-compact', 'hpc-full', 'hpc-btn'); }};

  // ── HPC live refresh ──
  window.refreshHPC = function() {{
    var btn = document.getElementById('hpc-refresh-btn');
    if (btn) btn.textContent = '...';
    var urls = [
      'https://sgnoohc.github.io/hpg_librarian/data_avery.json',
      'https://sgnoohc.github.io/hpg_librarian/data_avery-b.json'
    ];
    Promise.all(urls.map(function(u) {{ return fetch(u).then(function(r) {{ return r.json(); }}); }}))
      .then(function(jsons) {{
        var compactH = '', expandedH = '', lastUp = '';
        jsons.forEach(function(data, idx) {{
          var qos = idx === 0 ? 'avery' : 'avery-b';
          var hasGpu = idx === 0;
          var obs = data.observables_snapshot || {{}};
          var thr = data.thresholds || {{}};
          var ncT = thr.NCPUS || 0, ngT = thr.NGPUS || 0;
          if (hasGpu && ngT === 0) hasGpu = false;
          var lu = (data.metadata || {{}}).last_updated || '';
          if (lu > lastUp) lastUp = lu;
          // Sum per-user NCPUS from snapshot
          var ncUsers = obs.NCPUS || {{}};
          var n = 0, ncTot = [];
          for (var u in ncUsers) {{ n = ncUsers[u].length; break; }}
          for (var i = 0; i < n; i++) ncTot.push(0);
          for (var u in ncUsers) {{ var v = ncUsers[u]; for (var i = 0; i < v.length; i++) if (v[i] != null) ncTot[i] += v[i]; }}
          var ngTot = [];
          if (hasGpu) {{
            var ngUsers = obs.NGPUS || {{}};
            for (var i = 0; i < n; i++) ngTot.push(0);
            for (var u in ngUsers) {{ var v = ngUsers[u]; for (var i = 0; i < v.length; i++) if (v[i] != null) ngTot[i] += v[i]; }}
          }}
          // Last snapshot can be 0 (partial); walk back to find last real value
          var ncCur = 0;
          for (var j = ncTot.length-1; j >= Math.max(0, ncTot.length-5); j--) {{ if (ncTot[j] > 0) {{ ncCur = ncTot[j]; break; }} }}
          var ngCur = 0;
          if (ngTot.length) {{ for (var j = ngTot.length-1; j >= Math.max(0, ngTot.length-5); j--) {{ if (ngTot[j] > 0) {{ ngCur = ngTot[j]; break; }} }} }}
          // Snapshot has ~1pt/min; grab last ~24h (1440 pts), downsample to ~48
          var tail = Math.min(1440, ncTot.length);
          var step = Math.max(1, Math.floor(tail / 48));
          var nc24 = [], ng24 = [];
          for (var i = ncTot.length - tail; i < ncTot.length; i += step) nc24.push(ncTot[i]);
          if (ngTot.length) {{ for (var i = ngTot.length - tail; i < ngTot.length; i += step) ng24.push(ngTot[i]); }}
          function hpcColor(val, th) {{
            if (th === 0) return 'rgba(255,255,255,0.6)';
            var r = val / th;
            return r > 0.8 ? '#ff6b6b' : r > 0.5 ? '#f0c040' : '#55efc4';
          }}
          function spark(vals) {{
            if (!vals || vals.length < 2) return '';
            var mn = Math.min.apply(null, vals), mx = Math.max.apply(null, vals);
            var rng = mx !== mn ? mx - mn : 1, w = 100, h = 24;
            var pts = vals.map(function(v, i) {{
              return (i / (vals.length-1) * w).toFixed(1) + ',' + (h - (v - mn) / rng * (h-2) - 1).toFixed(1);
            }});
            var col = vals[vals.length-1] >= vals[0] ? '#55efc4' : '#ff6b6b';
            return '<svg width="'+w+'" height="'+h+'" viewBox="0 0 '+w+' '+h+'" style="vertical-align:middle;" xmlns="http://www.w3.org/2000/svg"><polyline points="'+pts.join(' ')+'" fill="none" stroke="'+col+'" stroke-width="1.5"/></svg>';
          }}
          var cpuC = hpcColor(ncCur, ncT);
          var cpuRow = '<div style="display:flex;justify-content:space-between;align-items:center;padding:3px 0;"><span style="color:rgba(255,255,255,0.6);font-size:12px;">'+qos+' CPU</span><span style="font-size:12px;"><span style="color:'+cpuC+';font-weight:600;">'+Math.round(ncCur)+'</span><span style="color:rgba(255,255,255,0.35);"> / '+Math.round(ncT)+'</span></span></div>';
          compactH += cpuRow;
          expandedH += cpuRow;
          var cs = spark(nc24);
          if (cs) expandedH += '<div style="padding:0 0 4px 0;">'+cs+'</div>';
          if (hasGpu) {{
            var gpuC = hpcColor(ngCur, ngT);
            var gpuRow = '<div style="display:flex;justify-content:space-between;align-items:center;padding:3px 0;"><span style="color:rgba(255,255,255,0.6);font-size:12px;">'+qos+' GPU</span><span style="font-size:12px;"><span style="color:'+gpuC+';font-weight:600;">'+Math.round(ngCur)+'</span><span style="color:rgba(255,255,255,0.35);"> / '+Math.round(ngT)+'</span></span></div>';
            compactH += gpuRow;
            expandedH += gpuRow;
            var gs = spark(ng24);
            if (gs) expandedH += '<div style="padding:0 0 4px 0;">'+gs+'</div>';
          }}
        }});
        var ce = document.getElementById('hpc-compact');
        var fe = document.getElementById('hpc-full');
        if (ce) ce.innerHTML = compactH;
        if (fe) fe.innerHTML = expandedH;
        var upEl = document.getElementById('hpc-updated');
        if (upEl && lastUp) {{
          try {{
            var d = new Date(lastUp);
            var h = d.getHours(), m = d.getMinutes();
            var ampm = h >= 12 ? 'PM' : 'AM';
            h = h % 12 || 12;
            upEl.textContent = 'Updated ' + h + ':' + (m < 10 ? '0' : '') + m + ' ' + ampm;
          }} catch(e) {{ upEl.textContent = 'Updated ' + lastUp.slice(0,16); }}
        }}
      }})
      .catch(function(e) {{ console.error('HPC refresh failed', e); }})
      .finally(function() {{ if (btn) btn.textContent = '\\u21BB'; }});
  }};
  window.togglePolPol = function() {{ _toggle('polpol-compact', 'polpol-full', 'polpol-btn'); }};
  window.togglePolTrend = function() {{ _toggle('poltrend-compact', 'poltrend-full', 'poltrend-btn'); }};
  window.toggleEnt = function() {{ _toggle('ent-compact', 'ent-full', 'ent-btn'); }};

  // ── Random Paul Graham essay (fetches and swaps in-panel) ──
  var pgEssays = [{",".join(f'{{"s":"{s}","t":"{t.replace(chr(34),"")}"}}' for s, t in pg_essays)}];
  window.randomPG = function() {{
    if (!pgEssays.length) return;
    var e = pgEssays[Math.floor(Math.random() * pgEssays.length)];
    var url = 'http://www.paulgraham.com/' + e.s;
    var titleEl = document.getElementById('pg-title');
    var bodyEl = document.getElementById('pg-body');
    if (titleEl) {{
      titleEl.textContent = e.t;
      titleEl.href = url;
      titleEl.title = e.t;
    }}
    if (bodyEl) {{
      bodyEl.textContent = 'Loading...';
      // Use a CORS proxy to fetch the essay text
      fetch('https://corsproxy.io/?' + encodeURIComponent(url))
        .then(function(r) {{ return r.text(); }})
        .then(function(html) {{
          // Strip tags to get plain text
          var tmp = document.createElement('div');
          tmp.innerHTML = html.replace(/<script[^>]*>[\s\S]*?<\/script>/gi, '').replace(/<style[^>]*>[\s\S]*?<\/style>/gi, '');
          var text = tmp.textContent || tmp.innerText || '';
          // Find essay body after title
          var idx = text.indexOf(e.t);
          if (idx > 0) text = text.substring(idx + e.t.length);
          text = text.replace(/\s+/g, ' ').trim();
          bodyEl.textContent = text.substring(0, 4000);
          bodyEl.scrollTop = 0;
        }})
        .catch(function() {{ bodyEl.textContent = 'Could not load essay. Click title to read on site.'; }});
    }}
  }};

  // ── Reorder panels (mobile) ──
  window.movePanel = function(btn, dir) {{
    var card = btn.closest('.glass');
    if (!card) return;
    var container = card.parentElement;
    var cards = Array.from(container.querySelectorAll(':scope > .glass'));
    var idx = cards.indexOf(card);
    if (dir === -1 && idx > 0) {{
      container.insertBefore(card, cards[idx - 1]);
    }} else if (dir === 1 && idx < cards.length - 1) {{
      container.insertBefore(cards[idx + 1], card);
    }}
    // Save order
    var order = Array.from(container.querySelectorAll(':scope > .glass[data-wid]')).map(function(el) {{ return el.dataset.wid; }});
    try {{ localStorage.setItem('lori-panel-order', JSON.stringify(order)); }} catch(e) {{}}
  }};

  // ── Restore panel order from localStorage ──
  (function() {{
    try {{
      var order = JSON.parse(localStorage.getItem('lori-panel-order'));
      if (!order || !order.length) return;
      var container = document.querySelector('.panels');
      if (!container) return;
      order.forEach(function(wid) {{
        var el = container.querySelector('.glass[data-wid="' + wid + '"]');
        if (el) container.appendChild(el);
      }});
    }} catch(e) {{}}
  }})();

  // ── Draggable widgets ──
  var STORE_KEY = 'lori-widget-pos';
  function loadPositions() {{
    try {{ return JSON.parse(localStorage.getItem(STORE_KEY)) || {{}}; }}
    catch(e) {{ return {{}}; }}
  }}
  function savePositions(pos) {{
    try {{ localStorage.setItem(STORE_KEY, JSON.stringify(pos)); }} catch(e) {{}}
  }}

  window.resetWidgets = function() {{
    localStorage.removeItem(STORE_KEY);
    localStorage.removeItem('lori-panel-order');
    localStorage.removeItem('lori-cal-days');
    localStorage.removeItem('lori-toggle-states');
    location.reload();
  }};

  // ── Layout slots (save/load 1-3) ──
  var LAYOUT_KEY = 'lori-layout-slot-';
  window.saveLayoutSlot = function(n) {{
    var data = {{
      pos: loadPositions(),
      hidden: JSON.parse(localStorage.getItem('lori-hidden-panels') || '[]'),
      widths: JSON.parse(localStorage.getItem('lori-panel-widths') || '{{}}')
    }};
    try {{ localStorage.setItem(LAYOUT_KEY + n, JSON.stringify(data)); }} catch(e) {{}}
    var btn = document.getElementById('slot-' + n);
    if (btn) {{ btn.style.borderColor = 'rgba(162,155,254,0.7)'; setTimeout(function() {{ btn.style.borderColor = ''; }}, 600); }}
    // Flash a save toast
    var toast = document.createElement('div');
    toast.textContent = 'Layout ' + n + ' saved';
    toast.style.cssText = 'position:fixed;bottom:80px;left:50%;transform:translateX(-50%);background:rgba(162,155,254,0.85);color:#fff;padding:6px 16px;border-radius:8px;font-family:JetBrains Mono,monospace;font-size:12px;z-index:10000;pointer-events:none;transition:opacity 0.4s;';
    document.body.appendChild(toast);
    setTimeout(function(){{ toast.style.opacity='0'; }}, 800);
    setTimeout(function(){{ toast.remove(); }}, 1200);
  }};
  window.loadLayoutSlot = function(n) {{
    try {{
      var raw = localStorage.getItem(LAYOUT_KEY + n);
      if (!raw) return;
      var data = JSON.parse(raw);
      if (data.pos) savePositions(data.pos);
      if (data.hidden) localStorage.setItem('lori-hidden-panels', JSON.stringify(data.hidden));
      if (data.widths) localStorage.setItem('lori-panel-widths', JSON.stringify(data.widths));
      location.reload();
    }} catch(e) {{}}
  }};
  window.onLayoutSlot = function(n, e) {{
    if (e.shiftKey) {{ saveLayoutSlot(n); }}
    else {{ loadLayoutSlot(n); }}
  }};

  // ── Panel visibility toggle ──
  var HIDDEN_KEY = 'lori-hidden-panels';
  var WIDGET_NAMES = {{
    today:'Today Schedule', tasks:'Tasks', stocks:'Markets', hpc:'HiPerGator',
    'poly-politics':'Poly · Politics', 'poly-trending':'Poly · Trending',
    news:'Headlines', science:'Science', calendar:'Week Calendar',
    entertainment:'Entertainment', essay:'Paul Graham', projects:'Projects',
    forecast:'Weather', 'hourly-weather':'Hourly Weather', notepad:'Notepad'
  }};

  var DEFAULT_VISIBLE = ['today','tasks','hpc','news','calendar','hourly-weather','forecast','notepad'];
  function loadHidden() {{
    try {{
      var raw = localStorage.getItem(HIDDEN_KEY);
      if (raw !== null) return JSON.parse(raw) || [];
      // First visit: hide everything not in DEFAULT_VISIBLE
      var allWids = [];
      document.querySelectorAll('.panels .glass[data-wid]').forEach(function(el) {{ allWids.push(el.dataset.wid); }});
      var h = allWids.filter(function(w) {{ return DEFAULT_VISIBLE.indexOf(w) === -1; }});
      saveHidden(h);
      return h;
    }} catch(e) {{ return []; }}
  }}
  function saveHidden(arr) {{
    try {{ localStorage.setItem(HIDDEN_KEY, JSON.stringify(arr)); }} catch(e) {{}}
  }}
  function applyHiddenState() {{
    var hidden = loadHidden();
    document.querySelectorAll('.panels .glass[data-wid]').forEach(function(el) {{
      el.style.display = hidden.indexOf(el.dataset.wid) !== -1 ? 'none' : '';
    }});
    // Also hide ambient widget if hidden
    document.querySelectorAll('.ambient[data-wid]').forEach(function(el) {{
      el.style.display = hidden.indexOf(el.dataset.wid) !== -1 ? 'none' : '';
    }});
  }}
  function buildPanelMenu() {{
    var menu = document.getElementById('panel-menu');
    var header = menu.querySelector('.pm-header');
    menu.innerHTML = '';
    menu.appendChild(header);
    var hidden = loadHidden();
    var panels = document.querySelectorAll('.drag[data-wid]');
    panels.forEach(function(el) {{
      var wid = el.dataset.wid;
      if (wid === 'ambient') return;
      var lbl = document.createElement('label');
      var cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = hidden.indexOf(wid) === -1;
      cb.addEventListener('change', function() {{
        var h = loadHidden();
        if (this.checked) {{
          h = h.filter(function(w) {{ return w !== wid; }});
        }} else {{
          if (h.indexOf(wid) === -1) h.push(wid);
        }}
        saveHidden(h);
        applyHiddenState();
      }});
      lbl.appendChild(cb);
      lbl.appendChild(document.createTextNode(WIDGET_NAMES[wid] || wid));
      // Half-width toggle
      var halfCb = document.createElement('input');
      halfCb.type = 'checkbox';
      halfCb.checked = isHalfWidth(wid);
      halfCb.title = 'Half width';
      halfCb.style.cssText = 'margin-left:auto; cursor:pointer;';
      halfCb.addEventListener('change', (function(w, hcb) {{ return function() {{
        var widths = loadWidths();
        widths[w] = hcb.checked ? 1 : 0;
        saveWidths(widths);
        autoGridLayout();
      }}; }})(wid, halfCb));
      var halfLbl = document.createElement('span');
      halfLbl.textContent = '½';
      halfLbl.style.cssText = 'margin-left:4px; font-size:0.85em; opacity:0.6;';
      lbl.style.cssText = 'display:flex; align-items:center;';
      lbl.appendChild(halfCb);
      lbl.appendChild(halfLbl);
      menu.appendChild(lbl);
    }});
  }}
  window.togglePanelMenu = function() {{
    var menu = document.getElementById('panel-menu');
    if (menu.classList.contains('open')) {{
      menu.classList.remove('open');
    }} else {{
      buildPanelMenu();
      menu.classList.add('open');
    }}
  }};
  document.addEventListener('click', function(e) {{
    var menu = document.getElementById('panel-menu');
    var btn = document.getElementById('vis-btn');
    if (menu && menu.classList.contains('open') && !menu.contains(e.target) && e.target !== btn && !btn.contains(e.target)) {{
      menu.classList.remove('open');
    }}
  }});

  // ── Panel width preferences (localStorage) ──
  var WIDTH_KEY = 'lori-panel-widths';
  var DEFAULT_HALF = {{hpc:1, projects:1, forecast:1}};
  function loadWidths() {{ try {{ return JSON.parse(localStorage.getItem(WIDTH_KEY)) || {{}}; }} catch(e) {{ return {{}}; }} }}
  function saveWidths(obj) {{ try {{ localStorage.setItem(WIDTH_KEY, JSON.stringify(obj)); }} catch(e) {{}} }}
  function isHalfWidth(wid) {{ var w = loadWidths(); return w.hasOwnProperty(wid) ? !!w[wid] : !!DEFAULT_HALF[wid]; }}

  // ── Auto-grid layout ──
  function _restoreColWraps() {{
    var container = document.querySelector('.panels');
    document.querySelectorAll('.col-wrap').forEach(function(wrap) {{
      // Move glass panels back (skip flex-row wrappers)
      var children = Array.from(wrap.querySelectorAll('.glass[data-wid]'));
      children.forEach(function(el) {{
        el.style.position = '';
        el.style.left = '';
        el.style.top = '';
        el.style.width = '';
        el.style.height = '';
        el.style.overflow = '';
        el.style.zIndex = '';
        el.style.margin = '';
        container.appendChild(el);
      }});
      wrap.remove();
    }});
  }}

  window.autoGridLayout = function() {{
    if (window.innerWidth <= 768) return;
    _restoreColWraps();
    var hidden = loadHidden();
    var panels = [];
    document.querySelectorAll('.panels .glass[data-wid]').forEach(function(el) {{
      if (hidden.indexOf(el.dataset.wid) === -1 && el.style.display !== 'none') panels.push(el);
    }});
    if (!panels.length) return;
    var vw = window.innerWidth, vh = window.innerHeight;
    var leftOffset = Math.max(vw * 0.35, 500);
    var usableW = vw - leftOffset - 20;
    var cols = Math.max(2, Math.min(4, Math.floor(usableW / 330)));
    var gap = 10;
    var cardW = (usableW - (cols - 1) * gap) / cols;
    var halfW = (cardW - gap) / 2;
    var pos = loadPositions();
    // Get each panel's preferred height: saved manual resize > scrollHeight
    var heights = [];
    panels.forEach(function(el) {{
      var wid = el.dataset.wid;
      var savedH = pos[wid] && pos[wid].h ? pos[wid].h : 0;
      // Temporarily make panel visible at auto height to measure content
      var origH = el.style.height, origOv = el.style.overflow;
      el.style.height = 'auto';
      el.style.overflow = 'visible';
      var contentH = el.scrollHeight;
      el.style.height = origH;
      el.style.overflow = origOv;
      // Use saved height if user has resized, otherwise use content height + padding
      heights.push(savedH > 0 ? savedH : contentH + 28);
    }});
    // Cap each height to viewport minus padding, with a minimum
    var maxH = vh - 40;
    heights = heights.map(function(h) {{ return Math.max(80, Math.min(h, maxH)); }});
    // Default column hints for reset view (col 0 = leftmost)
    var DEFAULT_COL = {{today:0, 'hourly-weather':0, forecast:0,
                        news:1, hpc:1, calendar:1, notepad:1,
                        tasks:0, stocks:1, projects:1}};
    var hasSavedOrder = false;
    try {{ hasSavedOrder = !!localStorage.getItem('lori-panel-order'); }} catch(e) {{}}
    // Place panels in DOM order (priority), filling columns
    var colHeights = [];
    for (var c = 0; c < cols; c++) colHeights.push(0);
    var colPanels = [];
    for (var c = 0; c < cols; c++) colPanels.push([]);
    panels.forEach(function(el, i) {{
      var wid = el.dataset.wid;
      var col;
      if (!hasSavedOrder && DEFAULT_COL.hasOwnProperty(wid) && DEFAULT_COL[wid] < cols) {{
        col = DEFAULT_COL[wid];
      }} else {{
        col = cols - 1;
        for (var c = cols - 2; c >= 0; c--) {{
          if (colHeights[c] < colHeights[col] - 10) col = c;
        }}
      }}
      colPanels[col].push(i);
      colHeights[col] += heights[i] + gap;
    }});
    // Create scrollable column wrappers and place panels inside
    colPanels.forEach(function(idxs, col) {{
      if (!idxs.length) return;
      var x = leftOffset + col * (cardW + gap);
      var wrap = document.createElement('div');
      wrap.className = 'col-wrap';
      wrap.style.cssText = 'position:fixed; top:20px; left:' + x + 'px; width:' + cardW + 'px; max-height:calc(100vh - 40px); overflow-y:auto; overflow-x:hidden; z-index:50; scrollbar-width:thin; scrollbar-color:rgba(255,255,255,0.1) transparent;';
      document.body.appendChild(wrap);
      var j = 0;
      while (j < idxs.length) {{
        var i = idxs[j];
        var el = panels[i];
        var wid = el.dataset.wid;
        var isHalf = isHalfWidth(wid);
        // Reset any prior fixed positioning
        el.style.position = 'relative';
        el.style.left = '';
        el.style.top = '';
        el.style.zIndex = '';
        // Try to pair two adjacent half-width panels side-by-side
        if (isHalf && j + 1 < idxs.length && isHalfWidth(panels[idxs[j+1]].dataset.wid)) {{
          var i2 = idxs[j+1];
          var el2 = panels[i2];
          var h = Math.max(heights[i], heights[i2]);
          var row = document.createElement('div');
          row.style.cssText = 'display:flex; gap:' + gap + 'px; margin-bottom:' + gap + 'px;';
          el.style.width = halfW + 'px';
          el.style.height = h + 'px';
          el.style.overflow = 'auto';
          el.style.margin = '0';
          el2.style.position = 'relative';
          el2.style.left = '';
          el2.style.top = '';
          el2.style.zIndex = '';
          el2.style.width = halfW + 'px';
          el2.style.height = h + 'px';
          el2.style.overflow = 'auto';
          el2.style.margin = '0';
          row.appendChild(el);
          row.appendChild(el2);
          wrap.appendChild(row);
          j += 2;
        }} else if (isHalf) {{
          el.style.width = halfW + 'px';
          el.style.height = heights[i] + 'px';
          el.style.overflow = 'auto';
          el.style.margin = '0 0 ' + gap + 'px 0';
          wrap.appendChild(el);
          j++;
        }} else {{
          el.style.width = cardW + 'px';
          el.style.height = heights[i] + 'px';
          el.style.overflow = 'auto';
          el.style.margin = '0 0 ' + gap + 'px 0';
          wrap.appendChild(el);
          j++;
        }}
      }}
    }});
    savePositions(pos);
  }};

  // ── Split grid layout (halves left, fulls right) ──
  window.autoGridSplit = function() {{
    if (window.innerWidth <= 768) return;
    _restoreColWraps();
    var hidden = loadHidden();
    var allPanels = [];
    document.querySelectorAll('.panels .glass[data-wid]').forEach(function(el) {{
      if (hidden.indexOf(el.dataset.wid) === -1 && el.style.display !== 'none') allPanels.push(el);
    }});
    if (!allPanels.length) return;
    var vw = window.innerWidth, vh = window.innerHeight;
    var leftOffset = Math.max(vw * 0.35, 500);
    var usableW = vw - leftOffset - 20;
    var gap = 10;
    // One column width for the left zone
    var leftColW = Math.max(330, Math.floor(usableW / Math.max(2, Math.min(4, Math.floor(usableW / 330)))));
    var halfW = (leftColW - gap) / 2;
    var pos = loadPositions();
    var maxH = vh - 40;
    // Separate into halves and fulls, preserving DOM order
    var halves = [], fulls = [];
    allPanels.forEach(function(el) {{
      if (isHalfWidth(el.dataset.wid)) halves.push(el);
      else fulls.push(el);
    }});
    // Measure heights for all panels
    function measureH(el) {{
      var wid = el.dataset.wid;
      var savedH = pos[wid] && pos[wid].h ? pos[wid].h : 0;
      var origH = el.style.height, origOv = el.style.overflow;
      el.style.height = 'auto';
      el.style.overflow = 'visible';
      var contentH = el.scrollHeight;
      el.style.height = origH;
      el.style.overflow = origOv;
      var h = savedH > 0 ? savedH : contentH + 28;
      return Math.max(80, Math.min(h, maxH));
    }}
    // ── Left zone: half-width panels paired 2-up ──
    var leftX = leftOffset;
    var leftY = 20;
    for (var i = 0; i < halves.length; i += 2) {{
      var el = halves[i];
      var wid = el.dataset.wid;
      var h1 = measureH(el);
      if (i + 1 < halves.length) {{
        var el2 = halves[i + 1];
        var wid2 = el2.dataset.wid;
        var h2 = measureH(el2);
        var h = Math.max(h1, h2);
        el.style.position = 'fixed';
        el.style.left = leftX + 'px';
        el.style.top = leftY + 'px';
        el.style.width = halfW + 'px';
        el.style.height = h + 'px';
        el.style.overflow = 'auto';
        el.style.zIndex = '50';
        el.style.margin = '0';
        pos[wid] = {{ x: leftX, y: leftY, w: halfW, h: h }};
        el2.style.position = 'fixed';
        el2.style.left = (leftX + halfW + gap) + 'px';
        el2.style.top = leftY + 'px';
        el2.style.width = halfW + 'px';
        el2.style.height = h + 'px';
        el2.style.overflow = 'auto';
        el2.style.zIndex = '50';
        el2.style.margin = '0';
        pos[wid2] = {{ x: leftX + halfW + gap, y: leftY, w: halfW, h: h }};
        leftY += h + gap;
      }} else {{
        // Odd remaining half-panel
        el.style.position = 'fixed';
        el.style.left = leftX + 'px';
        el.style.top = leftY + 'px';
        el.style.width = halfW + 'px';
        el.style.height = h1 + 'px';
        el.style.overflow = 'auto';
        el.style.zIndex = '50';
        el.style.margin = '0';
        pos[wid] = {{ x: leftX, y: leftY, w: halfW, h: h1 }};
        leftY += h1 + gap;
      }}
    }}
    // ── Right zone: full-width panels ──
    var rightX = leftOffset + leftColW + gap;
    var rightUsableW = vw - rightX - 20;
    var rightCols = Math.max(1, Math.floor(rightUsableW / 330));
    var rightCardW = (rightUsableW - (rightCols - 1) * gap) / rightCols;
    var rightColH = [];
    for (var c = 0; c < rightCols; c++) rightColH.push(0);
    fulls.forEach(function(el) {{
      var wid = el.dataset.wid;
      var h = measureH(el);
      // Find shortest column (prefer rightmost on tie)
      var minCol = rightCols - 1;
      for (var c = rightCols - 2; c >= 0; c--) {{
        if (rightColH[c] < rightColH[minCol] - 10) minCol = c;
      }}
      var x = rightX + minCol * (rightCardW + gap);
      var y = 20 + rightColH[minCol];
      el.style.position = 'fixed';
      el.style.left = x + 'px';
      el.style.top = y + 'px';
      el.style.width = rightCardW + 'px';
      el.style.height = h + 'px';
      el.style.overflow = 'auto';
      el.style.zIndex = '50';
      el.style.margin = '0';
      pos[wid] = {{ x: x, y: y, w: rightCardW, h: h }};
      rightColH[minCol] += h + gap;
    }});
    savePositions(pos);
  }};

  // Restore saved positions
  var saved = loadPositions();
  document.querySelectorAll('.drag[data-wid]').forEach(function(el) {{
    var wid = el.dataset.wid;
    if (saved[wid]) {{
      el.style.position = 'fixed';
      el.style.left = saved[wid].x + 'px';
      el.style.top = saved[wid].y + 'px';
      el.style.width = saved[wid].w ? saved[wid].w + 'px' : '420px';
      el.style.zIndex = '50';
      el.style.margin = '0';
    }}
  }});

  // Apply hidden panel state
  applyHiddenState();

  // Mark layout slot buttons that have saved data
  [1,2,3].forEach(function(n) {{
    var btn = document.getElementById('slot-' + n);
    if (btn && localStorage.getItem(LAYOUT_KEY + n)) {{
      btn.style.borderColor = 'rgba(162,155,254,0.35)';
    }}
  }});

  // Drag logic
  var dragEl = null, dragOffX = 0, dragOffY = 0;

  document.addEventListener('mousedown', function(e) {{
    if (window.innerWidth <= 768) return;
    var handle = e.target.closest('.drag-handle');
    if (!handle) return;
    var panel = handle.closest('.drag');
    if (!panel) return;
    e.preventDefault();
    dragEl = panel;
    var rect = panel.getBoundingClientRect();
    dragOffX = e.clientX - rect.left;
    dragOffY = e.clientY - rect.top;
    // Capture current width before going fixed
    var w = rect.width;
    panel.style.position = 'fixed';
    panel.style.left = rect.left + 'px';
    panel.style.top = rect.top + 'px';
    panel.style.width = w + 'px';
    panel.style.zIndex = '100';
    panel.style.margin = '0';
    panel.classList.add('dragging');
    showColumnGuides();
  }});

  // ── Column-snap system ──
  var colGuideEls = [];
  var colData = [];
  var activeColIdx = -1;

  function computeColumns() {{
    var vw = window.innerWidth, vh = window.innerHeight;
    var leftOffset = Math.max(vw * 0.35, 500);
    var usableW = vw - leftOffset - 20;
    var cols = Math.max(2, Math.min(4, Math.floor(usableW / 330)));
    var gap = 10;
    var cardW = (usableW - (cols - 1) * gap) / cols;
    var result = [];
    for (var c = 0; c < cols; c++) {{
      result.push({{ x: leftOffset + c * (cardW + gap), w: cardW }});
    }}
    return result;
  }}

  function findSnapColumn(cx) {{
    if (!colData.length) return -1;
    var best = 0, bestDist = 1e9;
    for (var i = 0; i < colData.length; i++) {{
      var mid = colData[i].x + colData[i].w / 2;
      var d = Math.abs(cx - mid);
      if (d < bestDist) {{ bestDist = d; best = i; }}
    }}
    return best;
  }}

  function showColumnGuides() {{
    removeColumnGuides();
    colData = computeColumns();
    activeColIdx = -1;
    colData.forEach(function(col) {{
      var el = document.createElement('div');
      el.className = 'col-guide';
      el.style.left = col.x + 'px';
      el.style.width = col.w + 'px';
      el.style.borderRight = '2px dashed rgba(162,155,254,0.25)';
      document.body.appendChild(el);
      colGuideEls.push(el);
    }});
  }}

  function removeColumnGuides() {{
    colGuideEls.forEach(function(el) {{ el.remove(); }});
    colGuideEls = [];
    colData = [];
    activeColIdx = -1;
  }}

  function highlightColumn(cx) {{
    var idx = findSnapColumn(cx);
    if (idx !== activeColIdx) {{
      colGuideEls.forEach(function(el) {{ el.classList.remove('active'); }});
      if (idx >= 0 && colGuideEls[idx]) colGuideEls[idx].classList.add('active');
      activeColIdx = idx;
    }}
  }}

  function getColumnStack(colIdx, excludeEl) {{
    if (colIdx < 0 || colIdx >= colData.length) return [];
    var col = colData[colIdx];
    var pos = loadPositions();
    var hidden = loadHidden();
    var stack = [];
    document.querySelectorAll('.panels .glass[data-wid]').forEach(function(el) {{
      if (el === excludeEl) return;
      if (hidden.indexOf(el.dataset.wid) !== -1 || el.style.display === 'none') return;
      var p = pos[el.dataset.wid];
      if (!p) return;
      // Panel belongs to this column if its x overlaps the column's x range
      var px = p.x, pw = p.w || parseInt(el.style.width) || col.w;
      if (px < col.x + col.w && px + pw > col.x) {{
        stack.push({{ el: el, y: p.y, h: p.h || parseInt(el.style.height) || 200 }});
      }}
    }});
    stack.sort(function(a, b) {{ return a.y - b.y; }});
    return stack;
  }}

  function findInsertY(colIdx, cursorY, excludeEl) {{
    var stack = getColumnStack(colIdx, excludeEl);
    var gap = 10, topPad = 20;
    if (!stack.length) return topPad;
    // Above first panel?
    if (cursorY < stack[0].y + stack[0].h / 2) return topPad;
    // Between or after panels — insert after the one whose midpoint is above cursor
    var insertAfter = stack[stack.length - 1];
    for (var i = 0; i < stack.length - 1; i++) {{
      var mid = stack[i].y + stack[i].h / 2;
      var midNext = stack[i+1].y + stack[i+1].h / 2;
      if (cursorY >= mid && cursorY < midNext) {{
        insertAfter = stack[i];
        break;
      }}
    }}
    return insertAfter.y + insertAfter.h + gap;
  }}

  function reflowColumn(colIdx) {{
    if (colIdx < 0 || colIdx >= colData.length) return;
    var col = colData[colIdx];
    var stack = getColumnStack(colIdx, null);
    var gap = 10, y = 20;
    var halfW = (col.w - gap) / 2;
    var pos = loadPositions();
    var j = 0;
    while (j < stack.length) {{
      var item = stack[j];
      var wid = item.el.dataset.wid;
      var half = isHalfWidth(wid);
      // Pair two consecutive half-width panels side-by-side
      if (half && j + 1 < stack.length && isHalfWidth(stack[j+1].el.dataset.wid)) {{
        var item2 = stack[j+1];
        var wid2 = item2.el.dataset.wid;
        var h = Math.max(item.h, item2.h);
        item.el.style.left = col.x + 'px';
        item.el.style.top = y + 'px';
        item.el.style.width = halfW + 'px';
        item.el.style.height = h + 'px';
        item.el.style.overflow = 'auto';
        pos[wid] = {{ x: col.x, y: y, w: halfW, h: h }};
        item2.el.style.left = (col.x + halfW + gap) + 'px';
        item2.el.style.top = y + 'px';
        item2.el.style.width = halfW + 'px';
        item2.el.style.height = h + 'px';
        item2.el.style.overflow = 'auto';
        pos[wid2] = {{ x: col.x + halfW + gap, y: y, w: halfW, h: h }};
        y += h + gap;
        j += 2;
      }} else if (half) {{
        // Lone half-width panel
        item.el.style.left = col.x + 'px';
        item.el.style.top = y + 'px';
        item.el.style.width = halfW + 'px';
        pos[wid] = {{ x: col.x, y: y, w: halfW, h: item.h }};
        y += item.h + gap;
        j++;
      }} else {{
        // Full-width panel
        item.el.style.left = col.x + 'px';
        item.el.style.top = y + 'px';
        item.el.style.width = col.w + 'px';
        pos[wid] = {{ x: col.x, y: y, w: col.w, h: item.h }};
        y += item.h + gap;
        j++;
      }}
    }}
    savePositions(pos);
  }}

  document.addEventListener('mousemove', function(e) {{
    if (!dragEl) return;
    e.preventDefault();
    dragEl.style.left = (e.clientX - dragOffX) + 'px';
    dragEl.style.top = (e.clientY - dragOffY) + 'px';
    highlightColumn(e.clientX);
  }});

  document.addEventListener('mouseup', function(e) {{
    if (!dragEl) return;
    dragEl.classList.remove('dragging');
    dragEl.style.zIndex = '50';
    var wid = dragEl.dataset.wid;
    // Remember source column before snap
    var srcColIdx = -1;
    var pos = loadPositions();
    if (pos[wid]) {{
      colData = colData.length ? colData : computeColumns();
      srcColIdx = findSnapColumn(pos[wid].x + (pos[wid].w || 0) / 2);
    }}
    var targetColIdx = activeColIdx;
    if (targetColIdx >= 0 && colData[targetColIdx]) {{
      var col = colData[targetColIdx];
      var gap = 10;
      var half = isHalfWidth(wid);
      var w = half ? (col.w - gap) / 2 : col.w;
      var insertY = findInsertY(targetColIdx, e.clientY, dragEl);
      dragEl.style.left = col.x + 'px';
      dragEl.style.top = insertY + 'px';
      dragEl.style.width = w + 'px';
      dragEl.style.overflow = 'auto';
    }}
    removeColumnGuides();
    if (wid) {{
      pos = loadPositions();
      pos[wid] = {{
        x: parseInt(dragEl.style.left),
        y: parseInt(dragEl.style.top),
        w: parseInt(dragEl.style.width),
        h: parseInt(dragEl.style.height) || 0
      }};
      savePositions(pos);
      // Reflow target column + source column
      if (targetColIdx >= 0) {{
        colData = computeColumns();
        reflowColumn(targetColIdx);
        if (srcColIdx >= 0 && srcColIdx !== targetColIdx) reflowColumn(srcColIdx);
      }}
    }}
    dragEl = null;
  }});

  // Touch support
  document.addEventListener('touchstart', function(e) {{
    if (window.innerWidth <= 768) return;
    var handle = e.target.closest('.drag-handle');
    if (!handle) return;
    var panel = handle.closest('.drag');
    if (!panel) return;
    var touch = e.touches[0];
    var rect = panel.getBoundingClientRect();
    dragEl = panel;
    dragOffX = touch.clientX - rect.left;
    dragOffY = touch.clientY - rect.top;
    var w = rect.width;
    panel.style.position = 'fixed';
    panel.style.left = rect.left + 'px';
    panel.style.top = rect.top + 'px';
    panel.style.width = w + 'px';
    panel.style.zIndex = '100';
    panel.style.margin = '0';
    panel.classList.add('dragging');
    showColumnGuides();
  }}, {{passive: false}});

  document.addEventListener('touchmove', function(e) {{
    if (!dragEl) return;
    e.preventDefault();
    var touch = e.touches[0];
    dragEl.style.left = (touch.clientX - dragOffX) + 'px';
    dragEl.style.top = (touch.clientY - dragOffY) + 'px';
    highlightColumn(touch.clientX);
  }}, {{passive: false}});

  document.addEventListener('touchend', function(e) {{
    if (!dragEl) return;
    dragEl.classList.remove('dragging');
    dragEl.style.zIndex = '50';
    var wid = dragEl.dataset.wid;
    var lastTouch = e.changedTouches && e.changedTouches[0];
    var cx = lastTouch ? lastTouch.clientX : parseInt(dragEl.style.left);
    var cy = lastTouch ? lastTouch.clientY : parseInt(dragEl.style.top);
    // Remember source column before snap
    var srcColIdx = -1;
    var pos = loadPositions();
    if (pos[wid]) {{
      colData = colData.length ? colData : computeColumns();
      srcColIdx = findSnapColumn(pos[wid].x + (pos[wid].w || 0) / 2);
    }}
    var targetColIdx = activeColIdx;
    if (targetColIdx >= 0 && colData[targetColIdx]) {{
      var col = colData[targetColIdx];
      var gap = 10;
      var half = isHalfWidth(wid);
      var w = half ? (col.w - gap) / 2 : col.w;
      var insertY = findInsertY(targetColIdx, cy, dragEl);
      dragEl.style.left = col.x + 'px';
      dragEl.style.top = insertY + 'px';
      dragEl.style.width = w + 'px';
      dragEl.style.overflow = 'auto';
    }}
    removeColumnGuides();
    if (wid) {{
      pos = loadPositions();
      pos[wid] = {{
        x: parseInt(dragEl.style.left),
        y: parseInt(dragEl.style.top),
        w: parseInt(dragEl.style.width),
        h: parseInt(dragEl.style.height) || 0
      }};
      savePositions(pos);
      if (targetColIdx >= 0) {{
        colData = computeColumns();
        reflowColumn(targetColIdx);
        if (srcColIdx >= 0 && srcColIdx !== targetColIdx) reflowColumn(srcColIdx);
      }}
    }}
    dragEl = null;
  }});
  // ── Panel resize handles (height, width, corner) ──
  function applyPanelHeight(panel, h) {{
    panel.style.height = h + 'px';
    panel.style.overflow = 'auto';
    panel.querySelectorAll('[style*="max-height"]').forEach(function(inner) {{
      inner.style.maxHeight = 'none';
    }});
  }}
  function savePanelSize(panel) {{
    var wid = panel.dataset.wid;
    if (wid) {{
      var pos = loadPositions();
      if (!pos[wid]) pos[wid] = {{}};
      if (panel.style.height) pos[wid].h = parseInt(panel.style.height);
      if (panel.style.width) pos[wid].w = parseInt(panel.style.width);
      savePositions(pos);
    }}
  }}

  document.querySelectorAll('.glass').forEach(function(panel) {{
    panel.style.position = panel.style.position || 'relative';

    // Bottom resize (height)
    var hHandle = document.createElement('div');
    hHandle.className = 'resize-h';
    panel.appendChild(hHandle);

    // Right resize (width)
    var wHandle = document.createElement('div');
    wHandle.className = 'resize-w';
    panel.appendChild(wHandle);

    // Corner resize (both)
    var cHandle = document.createElement('div');
    cHandle.className = 'resize-corner';
    panel.appendChild(cHandle);

    function startResize(e, mode) {{
      e.preventDefault();
      e.stopPropagation();
      var isTouch = e.touches !== undefined;
      var startX = isTouch ? e.touches[0].clientX : e.clientX;
      var startY = isTouch ? e.touches[0].clientY : e.clientY;
      var startW = panel.getBoundingClientRect().width;
      var startH = panel.getBoundingClientRect().height;
      function onMove(ev) {{
        var cx = isTouch ? ev.touches[0].clientX : ev.clientX;
        var cy = isTouch ? ev.touches[0].clientY : ev.clientY;
        ev.preventDefault();
        if (mode === 'h' || mode === 'c') {{
          applyPanelHeight(panel, Math.max(60, startH + cy - startY));
        }}
        if (mode === 'w' || mode === 'c') {{
          panel.style.width = Math.max(200, startW + cx - startX) + 'px';
        }}
      }}
      function onEnd() {{
        document.removeEventListener(isTouch ? 'touchmove' : 'mousemove', onMove);
        document.removeEventListener(isTouch ? 'touchend' : 'mouseup', onEnd);
        savePanelSize(panel);
      }}
      document.addEventListener(isTouch ? 'touchmove' : 'mousemove', onMove, {{passive:false}});
      document.addEventListener(isTouch ? 'touchend' : 'mouseup', onEnd);
    }}

    hHandle.addEventListener('mousedown', function(e) {{ startResize(e, 'h'); }});
    hHandle.addEventListener('touchstart', function(e) {{ startResize(e, 'h'); }}, {{passive:false}});
    wHandle.addEventListener('mousedown', function(e) {{ startResize(e, 'w'); }});
    wHandle.addEventListener('touchstart', function(e) {{ startResize(e, 'w'); }}, {{passive:false}});
    cHandle.addEventListener('mousedown', function(e) {{ startResize(e, 'c'); }});
    cHandle.addEventListener('touchstart', function(e) {{ startResize(e, 'c'); }}, {{passive:false}});
  }});

  // Restore saved sizes
  var s2 = loadPositions();
  document.querySelectorAll('.drag[data-wid]').forEach(function(el) {{
    var wid = el.dataset.wid;
    if (s2[wid] && s2[wid].h) {{
      applyPanelHeight(el, s2[wid].h);
    }}
    if (s2[wid] && s2[wid].w) {{
      el.style.width = s2[wid].w + 'px';
    }}
  }});

  // ── Helper: sparkline SVG builder ──
  function _spark(vals, w, h) {{
    if (!vals || vals.length < 2) return '';
    var mn = Math.min.apply(null, vals), mx = Math.max.apply(null, vals), rng = mx - mn || 1;
    var pts = vals.map(function(v, i) {{
      return (i / (vals.length - 1) * w).toFixed(1) + ',' + (h - (v - mn) / rng * (h - 2) - 1).toFixed(1);
    }}).join(' ');
    var c = vals[vals.length - 1] >= vals[0] ? '#55efc4' : '#ff6b6b';
    return '<svg width="'+w+'" height="'+h+'" viewBox="0 0 '+w+' '+h+'" style="vertical-align:middle" xmlns="http://www.w3.org/2000/svg"><polyline points="'+pts+'" fill="none" stroke="'+c+'" stroke-width="1.5"/></svg>';
  }}
  function _sparkMulti(series, w, h) {{
    if (!series || !series.length) return '';
    var all = []; series.forEach(function(s) {{ if (s[0] && s[0].length >= 2) all = all.concat(s[0]); }});
    if (!all.length) return '';
    var dmin = Math.min.apply(null, all), dmax = Math.max.apply(null, all);
    var pad = Math.max((dmax - dmin) * 0.1, 2);
    var ymin = Math.max(dmin - pad, 0), ymax = Math.min(dmax + pad, 100), yrng = ymax - ymin || 1;
    var lines = '';
    series.forEach(function(s) {{
      var v = s[0], c = s[1]; if (!v || v.length < 2) return;
      var pts = v.map(function(val, i) {{ return (i/(v.length-1)*w).toFixed(1)+','+(h-(val-ymin)/yrng*(h-2)-1).toFixed(1); }}).join(' ');
      lines += '<polyline points="'+pts+'" fill="none" stroke="'+c+'" stroke-width="1.2" opacity="0.8"/>';
    }});
    if (!lines) return '';
    return '<svg width="'+w+'" height="'+h+'" viewBox="0 0 '+w+' '+h+'" style="vertical-align:middle;display:block" xmlns="http://www.w3.org/2000/svg">'
      +'<text x="'+(w-1)+'" y="9" text-anchor="end" font-size="7" fill="rgba(255,255,255,0.25)" font-family="JetBrains Mono,monospace">'+ymax.toFixed(0)+'%</text>'
      +'<text x="'+(w-1)+'" y="'+(h-2)+'" text-anchor="end" font-size="7" fill="rgba(255,255,255,0.25)" font-family="JetBrains Mono,monospace">'+ymin.toFixed(0)+'%</text>'
      +lines+'</svg>';
  }}

  // ── Live stock ticker updates ──
  var stockSyms = {{
    'S&P 500': '^GSPC', 'Dow': '^DJI', 'Nasdaq': '^IXIC',
    'WTI Oil': 'CL=F', 'Brent': 'BZ=F', 'Gold': 'GC=F',
    'Bitcoin': 'BTC-USD', '10Y Yield': '^TNX'
  }};
  function fmtStockPrice(name, price) {{
    if (name === '10Y Yield') return price.toFixed(2) + '%';
    if (name === 'Bitcoin') return price.toLocaleString('en-US', {{maximumFractionDigits:0}});
    if (name === 'WTI Oil' || name === 'Brent' || name === 'Gold') return '$' + price.toLocaleString('en-US', {{minimumFractionDigits:2, maximumFractionDigits:2}});
    return price.toLocaleString('en-US', {{maximumFractionDigits:0}});
  }}
  function refreshStocks() {{
    Object.keys(stockSyms).forEach(function(name) {{
      var sym = stockSyms[name];
      fetch('https://corsproxy.io/?' + encodeURIComponent('https://query1.finance.yahoo.com/v8/finance/chart/' + sym + '?interval=1d&range=2d'))
        .then(function(r) {{ return r.json(); }}).then(function(data) {{
        var m = data.chart.result[0].meta;
        var price = m.regularMarketPrice, prev = m.chartPreviousClose;
        var pct = prev ? ((price - prev) / prev) * 100 : 0;
        var arrow = pct >= 0 ? '\u25B2' : '\u25BC', c = pct >= 0 ? '#55efc4' : '#ff6b6b';
        document.querySelectorAll('.stock-row[data-sym="' + name + '"] .stock-val').forEach(function(el) {{
          el.innerHTML = '<span style="color:rgba(255,255,255,0.8);">' + fmtStockPrice(name, price) + '</span> <span style="color:' + c + ';">' + arrow + ' ' + Math.abs(pct).toFixed(1) + '%</span>';
        }});
      }}).catch(function() {{}});
    }});
  }}

  // ── Live weather updates (Open-Meteo, CORS-friendly) ──
  var _wCity = '{location.split(",")[0].strip()}';
  var _wLoc = '{location}';
  var WMO = {{0:['☀️','Clear Sky'],1:['🌤️','Mainly Clear'],2:['⛅','Partly Cloudy'],3:['☁️','Overcast'],45:['🌫️','Fog'],48:['🌫️','Rime Fog'],51:['🌦️','Light Drizzle'],53:['🌦️','Drizzle'],55:['🌦️','Heavy Drizzle'],61:['🌧️','Light Rain'],63:['🌧️','Rain'],65:['🌧️','Heavy Rain'],71:['❄️','Light Snow'],73:['❄️','Snow'],75:['❄️','Heavy Snow'],80:['🌧️','Light Showers'],81:['🌧️','Showers'],82:['🌧️','Heavy Showers'],95:['⛈️','Thunderstorm'],96:['⛈️','Hail Storm'],99:['⛈️','Hail Storm']}};
  var _geoCache = null;
  function refreshWeather() {{
    function _go(lat, lon) {{
      fetch('https://api.open-meteo.com/v1/forecast?latitude='+lat+'&longitude='+lon+'&current=temperature_2m,weather_code&daily=temperature_2m_max,temperature_2m_min,weather_code&hourly=temperature_2m,weather_code,precipitation_probability,wind_speed_10m&temperature_unit=fahrenheit&forecast_days=4&timezone=auto')
        .then(function(r) {{ return r.json(); }}).then(function(wr) {{
        var wmo = WMO[wr.current.weather_code] || ['🌤️',''];
        var temp = Math.round(wr.current.temperature_2m);
        var hi = Math.round(wr.daily.temperature_2m_max[0]), lo = Math.round(wr.daily.temperature_2m_min[0]);
        // Ambient
        var we = document.getElementById('w-emoji'); if (we) we.textContent = wmo[0];
        var wt = document.getElementById('w-temp'); if (wt) wt.textContent = temp + '\u00B0F';
        var wd = document.getElementById('w-desc'); if (wd) wd.textContent = wmo[1];
        var wh = document.getElementById('w-hilo'); if (wh) wh.textContent = 'H:' + hi + '\u00B0 L:' + lo + '\u00B0 \u00B7 ' + _wLoc;
        // Forecast card
        var fc = document.querySelector('[data-wid="forecast"]');
        if (fc) {{
          var st = fc.querySelector('.stitle');
          var h = '<div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;"><span style="font-size:42px;line-height:1;">'+wmo[0]+'</span><div><div style="font-size:28px;font-weight:700;color:#fff;">'+temp+'\u00B0F</div><div style="font-size:13px;color:rgba(255,255,255,0.5);">'+wmo[1]+' \u00B7 H:'+hi+'\u00B0 L:'+lo+'\u00B0</div></div></div>';
          h += '<div style="display:flex;gap:8px;flex-wrap:wrap;">';
          var days = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
          for (var i = 1; i < wr.daily.time.length; i++) {{
            var d = new Date(wr.daily.time[i]+'T12:00:00');
            var fw = WMO[wr.daily.weather_code[i]] || ['🌤️',''];
            h += '<div style="flex:1;min-width:70px;padding:10px;background:rgba(255,255,255,0.06);border-radius:10px;text-align:center;"><div style="font-size:26px;">'+fw[0]+'</div><div style="font-size:13px;font-weight:600;color:rgba(255,255,255,0.7);">'+days[d.getDay()]+'</div><div style="font-size:17px;color:#a29bfe;font-weight:600;">'+Math.round(wr.daily.temperature_2m_max[i])+'\u00B0/'+Math.round(wr.daily.temperature_2m_min[i])+'\u00B0</div></div>';
          }}
          h += '</div>';
          Array.from(fc.children).forEach(function(ch) {{ if (ch !== st && !ch.classList.contains('resize-h') && !ch.classList.contains('resize-w') && !ch.classList.contains('resize-corner')) ch.remove(); }});
          st.insertAdjacentHTML('afterend', h);
        }}
        // Hourly card
        var hc = document.querySelector('[data-wid="hourly-weather"]');
        if (hc) {{
          var st2 = hc.querySelector('.stitle');
          var now2 = new Date(), curH = now2.getHours();
          var si = 0;
          for (var j = 0; j < wr.hourly.time.length; j++) {{
            var ht = new Date(wr.hourly.time[j]);
            if (ht.getHours() === curH && ht.getDate() === now2.getDate()) {{ si = j; break; }}
          }}
          var hh = '<div style="display:flex;overflow-x:auto;gap:2px;padding-bottom:4px;scrollbar-width:thin;scrollbar-color:rgba(255,255,255,0.1) transparent;">';
          var temps = [];
          for (var k = si; k < Math.min(si + 24, wr.hourly.time.length); k++) {{
            var ht2 = new Date(wr.hourly.time[k]);
            var lbl = k === si ? 'Now' : ht2.toLocaleTimeString('en-US', {{hour:'numeric'}}).toLowerCase().replace(' ','');
            var hw = WMO[wr.hourly.weather_code[k]] || ['🌤️',''];
            var ht3 = Math.round(wr.hourly.temperature_2m[k]);
            var hp = wr.hourly.precipitation_probability[k];
            var hwnd = Math.round(wr.hourly.wind_speed_10m[k]);
            temps.push(ht3);
            hh += '<div style="min-width:52px;padding:6px 4px;text-align:center;flex-shrink:0;"><div style="font-size:10px;color:rgba(255,255,255,0.45);font-weight:600;">'+lbl+'</div><div style="font-size:22px;margin:2px 0;">'+hw[0]+'</div>';
            if (hp > 0) hh += '<div style="font-size:8px;color:#74b9ff;">'+hp+'%</div>';
            hh += '<div style="font-size:13px;font-weight:600;color:rgba(255,255,255,0.85);">'+ht3+'\u00B0</div><div style="font-size:9px;color:rgba(255,255,255,0.3);">'+hwnd+'mph</div></div>';
          }}
          hh += '</div><div style="margin-top:4px;"><div style="font-size:8px;color:rgba(255,255,255,0.3);margin-bottom:2px;">24H TEMP</div>' + _spark(temps, 100, 24) + '</div>';
          Array.from(hc.children).forEach(function(ch) {{ if (ch !== st2 && !ch.classList.contains('resize-h') && !ch.classList.contains('resize-w') && !ch.classList.contains('resize-corner')) ch.remove(); }});
          st2.insertAdjacentHTML('afterend', hh);
        }}
      }}).catch(function() {{}});
    }}
    if (_geoCache) {{ _go(_geoCache[0], _geoCache[1]); return; }}
    fetch('https://geocoding-api.open-meteo.com/v1/search?name=' + encodeURIComponent(_wCity) + '&count=1')
      .then(function(r) {{ return r.json(); }}).then(function(d) {{
      if (d.results && d.results.length) {{ _geoCache = [d.results[0].latitude, d.results[0].longitude]; _go(_geoCache[0], _geoCache[1]); }}
    }}).catch(function() {{}});
  }}

  // ── Live news updates ──
  var _nColors = {{ HN:'#ff6600', NYT:'#a29bfe', WSJ:'#55efc4', Reuters:'#fd79a8', CNN:'#ff6b6b', BBC:'#bb1919', NBC:'#74b9ff', Fox:'#f0c040' }};
  var _nFeeds = [
    ['NYT','https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml'],
    ['WSJ','https://feeds.content.dowjones.io/public/rss/mw_topstories'],
    ['Reuters','https://news.google.com/rss/search?q=site:reuters.com&hl=en-US&gl=US&ceid=US:en'],
    ['CNN','http://rss.cnn.com/rss/cnn_topstories.rss'],
    ['BBC','https://feeds.bbci.co.uk/news/rss.xml'],
    ['NBC','https://feeds.nbcnews.com/nbcnews/public/news'],
    ['Fox','https://moxie.foxnews.com/google-publisher/latest.xml']
  ];
  function refreshNews() {{
    var all = [], pending = 1 + _nFeeds.length, done = 0;
    function _check() {{
      done++;
      if (done < pending) return;
      // Group by source, render
      var byS = {{}}, order = ['HN','NYT','WSJ','Reuters','CNN','BBC','NBC','Fox'];
      all.forEach(function(a) {{ if (!byS[a[0]]) byS[a[0]] = []; byS[a[0]].push(a); }});
      var compact = '', full = '';
      order.forEach(function(src) {{
        var items = byS[src]; if (!items || !items.length) return;
        var c = _nColors[src] || '#fff';
        items.forEach(function(it, i) {{
          var t = it[1].length > 85 ? it[1].substring(0,85)+'\u2026' : it[1];
          var row = '<div style="padding:3px 0;border-bottom:1px solid rgba(255,255,255,0.04);"><span style="color:'+c+';font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;min-width:48px;display:inline-block;">'+src+'</span><a href="'+(it[2]||'#')+'" target="_blank" style="color:rgba(255,255,255,0.8);font-size:12px;text-decoration:none;" title="'+it[1].replace(/"/g,'&quot;')+'">'+t+'</a></div>';
          if (i === 0) compact += row;
          full += row;
        }});
      }});
      var ce = document.getElementById('news-compact'), fe = document.getElementById('news-full');
      if (ce) ce.innerHTML = compact;
      if (fe) fe.innerHTML = full;
    }}
    // HN
    fetch('https://hacker-news.firebaseio.com/v0/topstories.json')
      .then(function(r) {{ return r.json(); }}).then(function(ids) {{
      var hnD = 0, hnT = Math.min(5, ids.length);
      ids.slice(0, hnT).forEach(function(id) {{
        fetch('https://hacker-news.firebaseio.com/v0/item/' + id + '.json')
          .then(function(r) {{ return r.json(); }}).then(function(it) {{
          if (it && it.title) all.push(['HN', it.title, it.url || 'https://news.ycombinator.com/item?id='+id]);
          hnD++; if (hnD >= hnT) _check();
        }}).catch(function() {{ hnD++; if (hnD >= hnT) _check(); }});
      }});
    }}).catch(function() {{ _check(); }});
    // RSS
    _nFeeds.forEach(function(f) {{
      fetch('https://corsproxy.io/?' + encodeURIComponent(f[1]))
        .then(function(r) {{ return r.text(); }}).then(function(xml) {{
        var doc = new DOMParser().parseFromString(xml, 'text/xml');
        var items = doc.querySelectorAll('item');
        var n = 0;
        items.forEach(function(it) {{
          if (n >= 5) return;
          var ti = it.querySelector('title'), li = it.querySelector('link');
          if (ti) {{
            var href = '';
            if (li) {{ href = li.textContent.trim(); if (!href && li.nextSibling) href = li.nextSibling.textContent.trim(); }}
            all.push([f[0], ti.textContent.trim(), href]);
            n++;
          }}
        }});
        _check();
      }}).catch(function() {{ _check(); }});
    }});
  }}

  // ── Live Polymarket updates ──
  var _pColors = ['#a29bfe','#55efc4','#f0c040','#fd79a8','#74b9ff','#ff6b6b'];
  var _polKW = /trump|president|congress|senate|house rep|gop|republican|democrat|nomine|cabinet|impeach|veto|speaker|approval|fed |us |u\\.s\\.|america|white house|scotus|supreme court|tariff|election|governor|geopolitical|china|russia|ukraine|iran|war|nato|eu |trade deal/i;
  function _renderPoly(events, cId, fId) {{
    var html = '';
    events.forEach(function(ev) {{
      var title = ev.title || '', slug = ev.slug || '';
      var link = slug ? 'https://polymarket.com/event/' + slug : '#';
      var choices = [];
      (ev.markets || []).forEach(function(mkt) {{
        var lbl = mkt.groupItemTitle || mkt.question || '';
        var bid = parseFloat(mkt.bestBid || 0), ask = parseFloat(mkt.bestAsk || 0);
        if (bid === 0 && ask >= 0.99) return;
        var prob = Math.round(((bid + ask) / 2) * 100);
        if (prob === 0) {{ try {{ var p = JSON.parse(mkt.outcomePrices || '[]'); if (p[0]) prob = Math.round(parseFloat(p[0]) * 100); }} catch(e) {{}} }}
        if (prob > 0 && lbl) choices.push({{ l: lbl.length > 30 ? lbl.substring(0,30)+'\u2026' : lbl, p: prob }});
      }});
      choices.sort(function(a, b) {{ return b.p - a.p; }});
      choices = choices.slice(0, 4);
      if (!choices.length) return;
      var t = title.length > 65 ? title.substring(0,65)+'\u2026' : title;
      var h = '<div style="padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.06);"><a href="'+link+'" target="_blank" style="color:rgba(255,255,255,0.9);font-size:13px;font-weight:500;text-decoration:none;" title="'+title.replace(/"/g,'&quot;')+'">'+t+'</a>';
      choices.forEach(function(ch, ci) {{
        var cc = _pColors[ci % _pColors.length];
        h += '<div style="display:flex;align-items:center;gap:6px;padding:2px 0;"><span style="color:'+cc+';font-size:10px;min-width:80px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'+ch.l+'</span><div style="flex:1;background:rgba(255,255,255,0.06);border-radius:99px;height:5px;overflow:hidden;"><div style="background:'+cc+';width:'+ch.p+'%;height:100%;border-radius:99px;"></div></div><span style="color:'+cc+';font-size:11px;font-weight:600;min-width:32px;text-align:right;">'+ch.p+'%</span></div>';
      }});
      html += h + '</div>';
    }});
    var ce = document.getElementById(cId), fe = document.getElementById(fId);
    if (ce) ce.innerHTML = html;
    if (fe) fe.innerHTML = html;
  }}
  function refreshPoly() {{
    // Politics
    fetch('https://corsproxy.io/?' + encodeURIComponent('https://gamma-api.polymarket.com/events?limit=25&active=true&order=volume24hr&ascending=false&tag_slug=politics'))
      .then(function(r) {{ return r.json(); }}).then(function(evs) {{
      _renderPoly(evs.filter(function(e) {{ return _polKW.test(e.title || ''); }}), 'polpol-compact', 'polpol-full');
    }}).catch(function() {{}});
    // Trending
    fetch('https://corsproxy.io/?' + encodeURIComponent('https://gamma-api.polymarket.com/events?limit=25&active=true&order=volume24hr&ascending=false'))
      .then(function(r) {{ return r.json(); }}).then(function(evs) {{
      _renderPoly(evs.filter(function(e) {{ return !_polKW.test(e.title || ''); }}).slice(0, 7), 'poltrend-compact', 'poltrend-full');
    }}).catch(function() {{}});
  }}

  // ── Schedule all live refreshes ──
  setTimeout(refreshStocks, 5000);
  setTimeout(refreshWeather, 6000);
  setTimeout(refreshNews, 8000);
  setTimeout(refreshPoly, 10000);
  setInterval(refreshStocks, 60000);    // every 1 min
  setInterval(refreshWeather, 600000);  // every 10 min
  setInterval(refreshNews, 300000);     // every 5 min
  setInterval(refreshPoly, 180000);     // every 3 min

  // ── Notepad Firebase sync ──
  (function() {{
    var ta = document.getElementById('notepad-area');
    var dot = document.getElementById('notepad-dot');
    var stxt = document.getElementById('notepad-sync-text');
    var tstamp = document.getElementById('notepad-timestamp');
    if (!ta || typeof firebase === 'undefined') return;
    var ref = firebase.database().ref('lori-notepad');
    var isLocalChange = false;
    var saveTimer = null;

    function setStatus(cls, text) {{
      dot.className = 'sync-dot ' + cls;
      stxt.textContent = text;
    }}

    function fmtTime(ms) {{
      if (!ms) return '';
      var d = new Date(ms);
      return d.toLocaleTimeString([], {{hour:'2-digit', minute:'2-digit'}});
    }}

    // Listen for remote changes
    ref.on('value', function(snap) {{
      var val = snap.val() || {{}};
      var remote = !isLocalChange;
      if (remote) {{
        ta.value = val.text || '';
      }}
      if (window._loriTtsCheck) window._loriTtsCheck(val.text || '', remote);
      isLocalChange = false;
      setStatus('synced', 'Synced');
      tstamp.textContent = fmtTime(val.ts);
    }}, function() {{
      setStatus('error', 'Offline');
    }});

    // Debounced save on input
    ta.addEventListener('input', function() {{
      isLocalChange = true;
      setStatus('saving', 'Saving...');
      clearTimeout(saveTimer);
      saveTimer = setTimeout(function() {{
        ref.set({{
          text: ta.value,
          ts: firebase.database.ServerValue.TIMESTAMP
        }}).then(function() {{
          setStatus('synced', 'Synced');
        }}).catch(function() {{
          setStatus('error', 'Error');
        }});
      }}, 800);
    }});

    // Reconnect when tab becomes visible
    document.addEventListener('visibilitychange', function() {{
      if (!document.hidden) firebase.database().goOnline();
    }});

    // Text-to-speech for incoming remote text
    var ttsBtn = document.getElementById('notepad-tts');
    var ttsEnabled = localStorage.getItem('lori-notepad-tts') === '1';
    var lastSpokenText = ta.value;
    function updateTtsBtn() {{
      ttsBtn.innerHTML = ttsEnabled ? '&#128266;' : '&#128263;';
      ttsBtn.classList.toggle('tts-on', ttsEnabled);
    }}
    updateTtsBtn();
    ttsBtn.addEventListener('click', function() {{
      ttsEnabled = !ttsEnabled;
      localStorage.setItem('lori-notepad-tts', ttsEnabled ? '1' : '0');
      updateTtsBtn();
      if (!ttsEnabled) speechSynthesis.cancel();
    }});
    function speakText(text) {{
      if (!text || !window.speechSynthesis) return;
      speechSynthesis.cancel();
      var u = new SpeechSynthesisUtterance(text);
      u.rate = 1; u.pitch = 1;
      speechSynthesis.speak(u);
    }}
    window._loriTtsCheck = function(newText, remote) {{
      if (!remote || !ttsEnabled) {{ lastSpokenText = newText; return; }}
      if (newText === lastSpokenText) return;
      // If new text starts with old text, speak only the appended part
      if (newText.indexOf(lastSpokenText) === 0) {{
        speakText(newText.slice(lastSpokenText.length).trim());
      }} else {{
        speakText(newText);
      }}
      lastSpokenText = newText;
    }};

    // Speech-to-text
    var SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    var micBtn = document.getElementById('notepad-mic');
    if (SpeechRec && micBtn) {{
      var rec = new SpeechRec();
      rec.continuous = true;
      rec.interimResults = true;
      rec.lang = 'en-US';
      var listening = false;
      var finalText = '';

      micBtn.addEventListener('click', function() {{
        if (listening) {{
          rec.stop();
        }} else {{
          finalText = ta.value;
          rec.start();
        }}
      }});

      rec.onstart = function() {{
        listening = true;
        micBtn.classList.add('mic-on');
      }};

      rec.onend = function() {{
        listening = false;
        micBtn.classList.remove('mic-on');
      }};

      rec.onresult = function(e) {{
        var interim = '';
        for (var i = e.resultIndex; i < e.results.length; i++) {{
          var t = e.results[i][0].transcript;
          if (e.results[i].isFinal) {{
            finalText += (finalText && !finalText.endsWith('\\n') ? ' ' : '') + t;
          }} else {{
            interim = t;
          }}
        }}
        ta.value = finalText + (interim ? ' ' + interim : '');
        ta.dispatchEvent(new Event('input'));
      }};

      rec.onerror = function() {{
        listening = false;
        micBtn.classList.remove('mic-on');
      }};
    }} else if (micBtn) {{
      micBtn.style.display = 'none';
    }}
  }})();

  // ── Keyboard shortcuts ──
  (function() {{
    // Help overlay
    var helpEl = document.createElement('div');
    helpEl.id = 'kb-help';
    helpEl.style.cssText = 'display:none;position:fixed;inset:0;z-index:10001;background:rgba(0,0,0,0.55);align-items:center;justify-content:center;';
    helpEl.innerHTML = '<div style="background:rgba(15,15,30,0.92);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);border:1px solid rgba(255,255,255,0.12);border-radius:16px;padding:28px 36px;max-width:340px;font-family:JetBrains Mono,monospace;color:rgba(255,255,255,0.85);font-size:13px;line-height:2;">'
      + '<div style="font-size:11px;text-transform:uppercase;letter-spacing:0.12em;color:rgba(255,255,255,0.4);margin-bottom:12px;">Keyboard Shortcuts</div>'
      + '<div><kbd style="display:inline-block;min-width:28px;text-align:center;background:rgba(255,255,255,0.1);border-radius:4px;padding:1px 6px;margin-right:8px;font-size:12px;">g</kbd> Auto-grid layout</div>'
      + '<div><kbd style="display:inline-block;min-width:28px;text-align:center;background:rgba(255,255,255,0.1);border-radius:4px;padding:1px 6px;margin-right:8px;font-size:12px;">s</kbd> Split-grid layout</div>'
      + '<div><kbd style="display:inline-block;min-width:28px;text-align:center;background:rgba(255,255,255,0.1);border-radius:4px;padding:1px 6px;margin-right:8px;font-size:12px;">v</kbd> Toggle panel menu</div>'
      + '<div><kbd style="display:inline-block;min-width:28px;text-align:center;background:rgba(255,255,255,0.1);border-radius:4px;padding:1px 6px;margin-right:8px;font-size:12px;">m</kbd> Toggle notepad mic</div>'
      + '<div><kbd style="display:inline-block;min-width:28px;text-align:center;background:rgba(255,255,255,0.1);border-radius:4px;padding:1px 6px;margin-right:8px;font-size:12px;">1-3</kbd> Load layout slot</div>'
      + '<div><kbd style="display:inline-block;min-width:28px;text-align:center;background:rgba(255,255,255,0.1);border-radius:4px;padding:1px 6px;margin-right:8px;font-size:12px;">&#8679;1-3</kbd> Save layout slot</div>'
      + '<div><kbd style="display:inline-block;min-width:28px;text-align:center;background:rgba(255,255,255,0.1);border-radius:4px;padding:1px 6px;margin-right:8px;font-size:12px;">p</kbd> Pause/play video</div>'
      + '<div><kbd style="display:inline-block;min-width:28px;text-align:center;background:rgba(255,255,255,0.1);border-radius:4px;padding:1px 6px;margin-right:8px;font-size:12px;">?</kbd> This help</div>'
      + '<div style="margin-top:14px;font-size:10px;color:rgba(255,255,255,0.3);">Press any key or click to close</div>'
      + '</div>';
    document.body.appendChild(helpEl);

    var helpVisible = false;
    function showHelp() {{ helpEl.style.display = 'flex'; helpVisible = true; }}
    function hideHelp() {{ helpEl.style.display = 'none'; helpVisible = false; }}
    helpEl.addEventListener('click', hideHelp);

    document.addEventListener('keydown', function(e) {{
      var tag = (e.target.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.target.isContentEditable) return;

      // If help is open, any key closes it
      if (helpVisible) {{ hideHelp(); e.preventDefault(); return; }}

      var key = e.key;
      // Shift+1/2/3 produce ! @ # on US keyboards
      if (e.shiftKey && (key === '!' || key === '@' || key === '#')) {{
        var slotMap = {{'!':1, '@':2, '#':3}};
        if (typeof saveLayoutSlot === 'function') saveLayoutSlot(slotMap[key]);
        e.preventDefault();
        return;
      }}
      if (key === '1' || key === '2' || key === '3') {{
        if (typeof loadLayoutSlot === 'function') loadLayoutSlot(parseInt(key));
        e.preventDefault();
        return;
      }}
      if (key === 'g') {{
        if (typeof autoGridLayout === 'function') autoGridLayout();
        e.preventDefault();
        return;
      }}
      if (key === 's') {{
        if (typeof autoGridSplit === 'function') autoGridSplit();
        e.preventDefault();
        return;
      }}
      if (key === 'm') {{
        var micBtn = document.getElementById('notepad-mic');
        if (micBtn) micBtn.click();
        e.preventDefault();
        return;
      }}
      if (key === 'v') {{
        if (typeof togglePanelMenu === 'function') togglePanelMenu();
        e.preventDefault();
        return;
      }}
      if (key === 'p') {{
        if (typeof toggleVideoPause === 'function') toggleVideoPause();
        e.preventDefault();
        return;
      }}
      if (key === '?') {{
        showHelp();
        e.preventDefault();
        return;
      }}
    }});
  }})();

}})();
</script>
</body>
</html>"""
    return html


def _resolve_date(s):
    """Parse date string, supporting relative words like 'tomorrow', '+3'."""
    if not s:
        return None
    low = s.strip().lower()
    td = today()
    if low == "today":
        return td
    if low == "tomorrow":
        return td + datetime.timedelta(days=1)
    if low == "yesterday":
        return td - datetime.timedelta(days=1)
    if low.startswith("+") and low[1:].isdigit():
        return td + datetime.timedelta(days=int(low[1:]))
    if low.startswith("-") and low[1:].isdigit():
        return td - datetime.timedelta(days=int(low[1:]))
    # Day names: "monday", "next monday", etc.
    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    target_name = low.replace("next ", "")
    if target_name in day_names:
        target_idx = day_names.index(target_name)
        current_idx = td.weekday()
        delta = (target_idx - current_idx) % 7
        if delta == 0:
            delta = 7
        return td + datetime.timedelta(days=delta)
    return parse_date(s)


def cmd_html(args):
    target_date = _resolve_date(args.date) if getattr(args, "date", None) else None
    html = generate_dashboard_html(target_date=target_date)
    DASHBOARD_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DASHBOARD_FILE, "w") as f:
        f.write(html)
    label = f" for {target_date}" if target_date else ""
    print(f"  Dashboard{label} saved to {DASHBOARD_FILE}")


def cmd_email(args):
    config = load_config()
    to_addr = config.get("email", {}).get("to")
    if not to_addr:
        print("  No email configured. Edit ~/.lori/config.yaml")
        return

    html = generate_dashboard_html()

    # Also save locally
    DASHBOARD_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DASHBOARD_FILE, "w") as f:
        f.write(html)

    date_str = today().strftime("%a %b %-d")
    send_email(to_addr, f"[lori] Daily Briefing — {date_str}", html, config)
    print(f"  Dashboard emailed to {to_addr}")


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI: edit
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_edit(args):
    editor = os.environ.get("EDITOR", "vim")
    files = [str(CONFIG_FILE), str(PROJECTS_FILE), str(SCHEDULE_FILE), str(LOCATIONS_FILE)]
    if args.file:
        match = [f for f in files if args.file.lower() in f.lower()]
        if match:
            files = match[:1]
    subprocess.run([editor] + files)


# ═══════════════════════════════════════════════════════════════════════════════
#  Interactive hub menu
# ═══════════════════════════════════════════════════════════════════════════════



# ═══════════════════════════════════════════════════════════════════════════════
#  Argparse
# ═══════════════════════════════════════════════════════════════════════════════

def build_parser():
    parser = argparse.ArgumentParser(prog="lori", description="Life Orchestration & Routine Intelligence")
    parser.add_argument("--short", action="store_true", help="Compact briefing")
    parser.add_argument("--check-alerts", action="store_true", help="Check and send alerts (for scrontab)")
    parser.add_argument("--force", action="store_true", help="Force overwrite (for init)")

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="First-run setup")
    sub.add_parser("setup", help="Interactive configuration wizard")
    sub.add_parser("week", help="Weekly overview")
    sub.add_parser("projects", help="List projects").add_argument("--all", action="store_true", help="Include non-active")

    show_p = sub.add_parser("show", help="Show project details")
    show_p.add_argument("name", help="Project name (fuzzy match)")

    checkin_p = sub.add_parser("checkin", help="Interactive project check-in")

    # add subcommand with its own sub-subcommands
    add_p = sub.add_parser("add", help="Add project/event/task/milestone")
    add_sub = add_p.add_subparsers(dest="add_type")

    add_sub.add_parser("project", help="Add project (guided Q&A)")
    add_sub.add_parser("event", help="Add event (guided Q&A)")

    add_task = add_sub.add_parser("task", help="Add task to project")
    add_task.add_argument("project", help="Project name")
    add_task.add_argument("desc", help="Task description")
    add_task.add_argument("--due", help="Due date (YYYY-MM-DD)")

    add_ms = add_sub.add_parser("milestone", help="Add milestone to project")
    add_ms.add_argument("project", help="Project name")
    add_ms.add_argument("name", help="Milestone name")
    add_ms.add_argument("--due", required=True, help="Due date")

    done_p = sub.add_parser("done", help="Mark item complete")
    done_p.add_argument("item", help="Item to complete (fuzzy match)")

    sub.add_parser("undone", help="Undo a completed milestone")

    drive_p = sub.add_parser("drive", help="Query driving time")
    drive_p.add_argument("src", metavar="from", help="Origin location")
    drive_p.add_argument("to", help="Destination location")

    reschedule_p = sub.add_parser("reschedule", help="Reschedule project milestones")
    reschedule_p.add_argument("project", help="Project name")

    timeline_p = sub.add_parser("timeline", help="Visual milestone timeline")
    timeline_p.add_argument("project", help="Project name")

    html_p = sub.add_parser("html", help="Generate HTML dashboard")
    html_p.add_argument("--date", help="Target date (e.g. 2026-04-01, 'tomorrow', 'next monday')")
    sub.add_parser("email", help="Email HTML dashboard")

    edit_p = sub.add_parser("edit", help="Open YAML files in editor")
    edit_p.add_argument("file", nargs="?", help="Specific file (config/projects/schedule/locations)")

    alert_p = sub.add_parser("alert", help="Alert management")
    alert_sub = alert_p.add_subparsers(dest="alert_action")
    alert_sub.add_parser("setup", help="Install scrontab entry")

    cron_p = sub.add_parser("cron", help="Cron job management")
    cron_sub = cron_p.add_subparsers(dest="cron_action")
    cron_sub.add_parser("setup", help="Install daily dashboard scrontab entry")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.check_alerts:
        cmd_check_alerts(args)
        return

    cmd = args.command

    if cmd is None:
        # Default: daily briefing
        if not LORI_DIR.exists():
            print("  Run `lori init` first to set up ~/.lori/")
            return
        cmd_briefing(args)
        if not args.short and sys.stdin.isatty():
            from tui import run_tui
            run_tui()
    elif cmd == "init":
        cmd_init(args)
    elif cmd == "setup":
        cmd_setup(args)
    elif cmd == "week":
        cmd_week(args)
    elif cmd == "projects":
        cmd_projects(args)
    elif cmd == "show":
        cmd_show(args)
    elif cmd == "checkin":
        cmd_checkin(args)
    elif cmd == "add":
        if args.add_type == "project":
            cmd_add_project(args)
        elif args.add_type == "event":
            cmd_add_event(args)
        elif args.add_type == "task":
            cmd_add_task(args)
        elif args.add_type == "milestone":
            cmd_add_milestone(args)
        else:
            print("Usage: lori add {project|event|task|milestone}")
    elif cmd == "done":
        cmd_done(args)
    elif cmd == "undone":
        cmd_undone(args)
    elif cmd == "drive":
        cmd_drive(args)
    elif cmd == "reschedule":
        cmd_reschedule(args)
    elif cmd == "timeline":
        cmd_timeline(args)
    elif cmd == "html":
        cmd_html(args)
    elif cmd == "email":
        cmd_email(args)
    elif cmd == "edit":
        cmd_edit(args)
    elif cmd == "alert":
        if args.alert_action == "setup":
            cmd_alert_setup(args)
        else:
            print("Usage: lori alert setup")
    elif cmd == "cron":
        if args.cron_action == "setup":
            cmd_cron_setup(args)
        else:
            print("Usage: lori cron setup")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
