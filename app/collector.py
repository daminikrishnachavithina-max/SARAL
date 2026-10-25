"""SARAL collector: fetches official pages politely and safely.

Rules it follows:
- checks robots.txt first and obeys it
- never tries to get around logins, CAPTCHAs or paywalls (401/403 = blocked)
- retries a few times on temporary errors, then reports the failure
- never crashes: every problem comes back as a FetchResult
"""
import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

CONTACT = "saral-project-contact@example.com"  
USER_AGENT = f"SARAL-bot/0.1 (education support finder; {CONTACT})"
TIMEOUT = 20
MAX_BYTES = 5_000_000


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class FetchResult:
    status: str                 # ok, blocked, error
    http_status: int = None
    content: str = ""
    content_type: str = ""
    error: str = ""
    fetched_at: str = ""


def content_hash(text):
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def robots_allows(url, session):
    """True = allowed, False = not allowed, None = could not find out."""
    parts = urlparse(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"

    try:
        r = session.get(
            robots_url,
            timeout=TIMEOUT,
            allow_redirects=False,
        )
    except requests.RequestException:
        return None

    if 300 <= r.status_code < 400:
        return None
    if r.status_code in (401, 403):
        return False
    if r.status_code >= 500:
        return None
    if r.status_code >= 400:
        return True

    parser = RobotFileParser()
    parser.parse(r.text.splitlines())
    return parser.can_fetch(USER_AGENT, url)

def fetch_url(url, retries=2, backoff=2.0, session=None):
    session = session or requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    stamp = now_iso()

    allowed = robots_allows(url, session)
    if allowed is None:
        return FetchResult("error", error="Could not read robots.txt, so the page was not fetched.", fetched_at=stamp)
    if allowed is False:
        return FetchResult("blocked", error="robots.txt does not allow automated access to this page.", fetched_at=stamp)

    last_error = ""
    for attempt in range(retries + 1):
        try:
            r = session.get(url, timeout=TIMEOUT,allow_redirects=False)
        except requests.RequestException as exc:
            last_error = f"Network problem: {type(exc).__name__}"
        else:
            if 300 <= r.status_code < 400:
                return FetchResult(
                    "blocked",
                    r.status_code,
                    error="Redirect received; refusing to follow it automatically.",
                    fetched_at=stamp,
                )
            if r.status_code in (401, 403):
                return FetchResult("blocked", r.status_code, error="Access is restricted (login or permission needed).", fetched_at=stamp)
            if r.status_code == 429:
                return FetchResult("error", 429, error="The site asked us to slow down (rate limited).", fetched_at=stamp)
            if r.status_code >= 500:
                last_error = f"Server error {r.status_code}"
            elif r.status_code >= 400:
                return FetchResult("error", r.status_code, error=f"Page returned HTTP {r.status_code}.", fetched_at=stamp)
            else:
                if len(r.content) > MAX_BYTES:
                    return FetchResult("error", r.status_code, error="Page is too large to process.", fetched_at=stamp)
                if not r.encoding:
                    r.encoding = "utf-8"
                return FetchResult("ok", r.status_code, r.text, r.headers.get("Content-Type", ""), "", stamp)
        if attempt < retries:
            time.sleep(backoff * (attempt + 1))
    return FetchResult("error", error=last_error or "Unknown problem.", fetched_at=stamp)

