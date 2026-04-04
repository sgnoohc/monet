#!/usr/bin/env python3
"""Fetch UF GatorMail emails via IMAP + OAuth2 device code flow."""

import argparse
import base64
import email
import email.header
import imaplib
import json
import os
import quopri
import re
import sys
from datetime import datetime, timedelta, timezone

import msal

CLIENT_ID = "9e5f94bc-e8a4-4e73-b8be-63364c29d753"  # Thunderbird (IMAP client)
AUTHORITY = "https://login.microsoftonline.com/organizations"
SCOPES = ["https://outlook.office365.com/IMAP.AccessAsUser.All"]
IMAP_HOST = "outlook.office365.com"

CACHE_DIR = os.path.expanduser("~/.lori")
CACHE_FILE = os.path.join(CACHE_DIR, "mail_tokens.json")


def get_token_cache():
    cache = msal.SerializableTokenCache()
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            cache.deserialize(f.read())
    return cache


def save_token_cache(cache):
    if cache.has_state_changed:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(CACHE_FILE, "w") as f:
            f.write(cache.serialize())
        os.chmod(CACHE_FILE, 0o600)


def authenticate(cache, force=False):
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)

    if not force:
        accounts = app.get_accounts()
        if accounts:
            result = app.acquire_token_silent(SCOPES, account=accounts[0])
            if result and "access_token" in result:
                return result["access_token"], accounts[0]["username"]

    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        print(f"Error initiating device flow: {flow.get('error_description', 'unknown error')}", file=sys.stderr)
        sys.exit(1)

    print(flow["message"], file=sys.stderr)
    result = app.acquire_token_by_device_flow(flow)

    if "access_token" not in result:
        print(f"Authentication failed: {result.get('error_description', 'unknown error')}", file=sys.stderr)
        sys.exit(1)

    # Extract username from id_token_claims
    username = result.get("id_token_claims", {}).get("preferred_username", "")
    return result["access_token"], username


def decode_header(raw):
    parts = email.header.decode_header(raw or "")
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def clean_preview(raw_bytes):
    """Decode MIME content and strip HTML to get plain text preview."""
    if not raw_bytes:
        return ""
    text = raw_bytes.decode("utf-8", errors="replace")

    # Try quoted-printable decode
    try:
        text = quopri.decodestring(text.encode()).decode("utf-8", errors="replace")
    except Exception:
        pass

    # Try base64 decode if it looks like base64
    if re.match(r'^[A-Za-z0-9+/\s=]+$', text.strip()):
        try:
            text = base64.b64decode(text).decode("utf-8", errors="replace")
        except Exception:
            pass

    # Strip MIME boundaries and headers within body
    text = re.sub(r'--+.*?Content-[^\n]*\n', ' ', text, flags=re.DOTALL)
    text = re.sub(r'Content-\S+:.*?\n', ' ', text)
    # Strip HTML tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Strip common email noise
    text = re.sub(r'^\[External Email\]\s*', '', text)
    return text[:300]


# ─── Reusable IMAP building blocks ──────────────────────────────────────────


def connect_imap(token, username):
    """Return an authenticated IMAP4_SSL connection."""
    auth_string = f"user={username}\x01auth=Bearer {token}\x01\x01"
    imap = imaplib.IMAP4_SSL(IMAP_HOST)
    imap.authenticate("XOAUTH2", lambda _: auth_string.encode())
    return imap


def fetch_email_list(imap, unread=False, days=None, top=50):
    """Fetch email list with UIDs for stable references.

    Returns list of dicts with keys: uid, subject, from, date, preview, isRead.
    """
    imap.select("INBOX", readonly=True)

    criteria = []
    if unread:
        criteria.append("UNSEEN")
    if days:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%d-%b-%Y")
        criteria.append(f"SINCE {since}")
    if not criteria:
        criteria.append("ALL")

    _, msg_nums = imap.uid("search", None, *criteria)
    uids = msg_nums[0].split()
    if not uids:
        return []

    # Most recent first
    uids = uids[-top:]
    uids.reverse()

    emails_out = []
    for uid in uids:
        _, data = imap.uid("fetch", uid,
                           "(FLAGS BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)] BODY.PEEK[TEXT]<0.2000>)")
        if not data or data[0] is None:
            continue

        flags_raw = ""
        headers_raw = b""
        body_raw = b""

        for part in data:
            if isinstance(part, tuple):
                desc = part[0].decode() if isinstance(part[0], bytes) else str(part[0])
                if "HEADER.FIELDS" in desc:
                    headers_raw = part[1]
                elif "BODY[TEXT]" in desc:
                    body_raw = part[1]
            elif isinstance(part, bytes):
                flags_raw = part.decode(errors="replace")

        msg = email.message_from_bytes(headers_raw)
        subject = decode_header(msg.get("Subject", ""))
        from_addr = decode_header(msg.get("From", ""))
        date_str = msg.get("Date", "")
        is_read = "\\Seen" in flags_raw or "\\Seen" in str(data)

        preview = clean_preview(body_raw)

        emails_out.append({
            "uid": uid.decode() if isinstance(uid, bytes) else str(uid),
            "subject": subject,
            "from": from_addr,
            "date": date_str,
            "preview": preview,
            "isRead": is_read,
        })

    return emails_out


def fetch_email_body(imap, uid):
    """Fetch full message by UID, return plain text body."""
    uid_bytes = uid.encode() if isinstance(uid, str) else uid
    _, data = imap.uid("fetch", uid_bytes, "(BODY.PEEK[])")
    if not data or data[0] is None:
        return ""

    raw = b""
    for part in data:
        if isinstance(part, tuple):
            raw = part[1]
            break

    if not raw:
        return ""

    msg = email.message_from_bytes(raw)

    # Walk MIME tree, prefer text/plain
    if msg.is_multipart():
        text_parts = []
        html_parts = []
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    text_parts.append(payload.decode(charset, errors="replace"))
            elif ct == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    html_parts.append(payload.decode(charset, errors="replace"))
        if text_parts:
            return "\n".join(text_parts)
        if html_parts:
            # Strip HTML as fallback
            text = "\n".join(html_parts)
            text = re.sub(r'<br\s*/?\s*>', '\n', text, flags=re.IGNORECASE)
            text = re.sub(r'<[^>]+>', '', text)
            text = re.sub(r'&nbsp;', ' ', text)
            text = re.sub(r'&amp;', '&', text)
            text = re.sub(r'&lt;', '<', text)
            text = re.sub(r'&gt;', '>', text)
            return text
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                text = re.sub(r'<br\s*/?\s*>', '\n', text, flags=re.IGNORECASE)
                text = re.sub(r'<[^>]+>', '', text)
                text = re.sub(r'&nbsp;', ' ', text)
                text = re.sub(r'&amp;', '&', text)
                text = re.sub(r'&lt;', '<', text)
                text = re.sub(r'&gt;', '>', text)
            return text
    return ""


def set_flag(imap, uid, flag, enable=True):
    """Set or clear an IMAP flag on a message by UID.

    Common flags: '\\Seen', '\\Flagged', '\\Deleted'
    """
    uid_bytes = uid.encode() if isinstance(uid, str) else uid
    cmd = "+FLAGS" if enable else "-FLAGS"
    imap.uid("store", uid_bytes, cmd, f"({flag})")


# ─── Original CLI function (now uses building blocks) ───────────────────────


def fetch_emails(token, username, unread=False, days=None, top=50):
    imap = connect_imap(token, username)
    emails = fetch_email_list(imap, unread=unread, days=days, top=top)
    imap.logout()
    # Strip uid key for backward compatibility with CLI output
    for e in emails:
        e.pop("uid", None)
    return emails


def main():
    parser = argparse.ArgumentParser(description="Fetch GatorMail emails via IMAP + OAuth2")
    parser.add_argument("--unread", action="store_true", help="Unread emails only")
    parser.add_argument("--days", type=int, help="Emails from last N days")
    parser.add_argument("--top", type=int, default=50, help="Max emails to fetch (default 50)")
    parser.add_argument("--auth", action="store_true", help="Force re-authentication")
    parser.add_argument("--save", action="store_true", help="Save to ~/.lori/emails.json")
    args = parser.parse_args()

    cache = get_token_cache()
    token, username = authenticate(cache, force=args.auth)
    save_token_cache(cache)

    emails = fetch_emails(token, username, unread=args.unread, days=args.days, top=args.top)
    output = json.dumps(emails, indent=2)

    if args.save:
        os.makedirs(CACHE_DIR, exist_ok=True)
        outpath = os.path.join(CACHE_DIR, "emails.json")
        with open(outpath, "w") as f:
            f.write(output)
        print(f"Saved {len(emails)} emails to {outpath}", file=sys.stderr)

    print(output)


if __name__ == "__main__":
    main()
