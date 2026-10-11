"""Small, dependency-free helpers shared by the web app, the CLI and the tests."""

from __future__ import annotations

import re
from datetime import date, datetime

_ID_IN_URL = re.compile(r"[?&]id=([a-zA-Z0-9._]+)")
_BARE_ID = re.compile(r"[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+")


def extract_app_id(raw: str | None) -> str:
    """Return the package name from a bare app ID or a Play Store URL ("" if invalid).

    >>> extract_app_id("https://play.google.com/store/apps/details?id=com.spotify.music&hl=en")
    'com.spotify.music'
    >>> extract_app_id("com.king.candycrushsaga")
    'com.king.candycrushsaga'
    """
    raw = (raw or "").strip()
    if not raw:
        return ""
    match = _ID_IN_URL.search(raw)
    if match:
        return match.group(1)
    if _BARE_ID.fullmatch(raw):
        return raw
    return ""


def parse_date(value: str | date | datetime | None, label: str = "date") -> date | None:
    """Accept None / "" / date / datetime / "YYYY-MM-DD" and return a ``date`` or None."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError(f"{label} must use YYYY-MM-DD format") from exc
    raise ValueError(f"{label} must be a YYYY-MM-DD string or a date")


def validate_request(
    total_reviews: int | None,
    start_date: date | None,
    end_date: date | None,
    ratings: list[int] | tuple[int, ...] | None = None,
) -> str:
    """Return a human-readable error message, or "" when the request is valid.

    ``total_reviews`` of ``None`` or ``0`` means "scrape every available review".
    """
    if total_reviews is not None:
        try:
            total = int(total_reviews)
        except (TypeError, ValueError):
            return "Total reviews must be a whole number."
        if total < 0:
            return "Total reviews cannot be negative."
    if start_date and end_date and start_date > end_date:
        return "Start date cannot be after the end date."
    if ratings is not None:
        if not ratings:
            return "Select at least one star rating."
        if any(r not in (1, 2, 3, 4, 5) for r in ratings):
            return "Star ratings must be between 1 and 5."
    return ""


def word_count(text: str | None) -> int:
    return len(text.split()) if text else 0


def to_datetime(value: object) -> datetime | None:
    """Coerce whatever google-play-scraper hands back for a timestamp into a datetime."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip())
        except ValueError:
            return None
    return None
