"""Fetch ALL Google Play reviews for an app — every star rating, no sentiment split.

The main entry point is :func:`fetch_all_reviews`. It pages through the Play Store
(200 reviews per request), applies your optional filters (date range, star ratings,
minimum words, English-only) and stops as soon as it has enough reviews, runs out
of reviews, or — when sorting newest-first — walks past your start date.

Both network functions accept an injectable ``reviews_fn`` / ``app_fn`` so the
whole pipeline can be unit-tested offline.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable

from google_play_scraper import Sort
from google_play_scraper import app as gp_app
from google_play_scraper import reviews as gp_reviews

from utils import to_datetime, word_count

try:  # optional — only used when english_only=True
    from langdetect import DetectorFactory, LangDetectException, detect

    DetectorFactory.seed = 0
except ImportError:  # pragma: no cover
    detect = None
    LangDetectException = Exception

logger = logging.getLogger(__name__)

# ── constants ────────────────────────────────────────────────────────────────

BATCH_SIZE = 200            # Play Store's maximum page size
MAX_RETRIES = 3
MAX_SCANNED_DEFAULT = 200_000  # safety valve so "scrape everything" can't run forever

SORT_OPTIONS = {
    "newest": Sort.NEWEST,
    "most_relevant": Sort.MOST_RELEVANT,
}

REVIEW_FIELDS = [
    "review_id",        # sequential ID in this dataset (R000001 …)
    "play_review_id",   # Google's own review ID
    "app_id",
    "app_name",
    "user_name",
    "rating",           # 1–5 stars
    "content",
    "word_count",
    "char_count",
    "thumbs_up",        # "helpful" votes
    "app_version",      # version the reviewer was using (may be blank)
    "review_date",      # YYYY-MM-DD
    "review_datetime",  # YYYY-MM-DD HH:MM:SS
    "has_reply",        # did the developer reply?
    "reply_content",
    "replied_at",
]

# Backwards-compatible alias (older code imported RESEARCH_FIELDS)
RESEARCH_FIELDS = REVIEW_FIELDS

ProgressFn = Callable[[int, int, int | None], None]  # (collected, scanned, target)


@dataclass
class ScrapeOptions:
    total_reviews: int | None = 200          # None or 0 → every available review
    start_date: date | None = None
    end_date: date | None = None
    sort: str = "newest"                     # "newest" | "most_relevant"
    lang: str = "en"
    country: str = "us"
    ratings: tuple[int, ...] = (1, 2, 3, 4, 5)
    min_words: int = 0
    english_only: bool = False
    anonymize_users: bool = False
    max_scanned: int = MAX_SCANNED_DEFAULT

    @property
    def target(self) -> int | None:
        return int(self.total_reviews) if self.total_reviews else None


@dataclass
class ScrapeResult:
    reviews: list[dict] = field(default_factory=list)
    scanned: int = 0                 # raw reviews downloaded from the store
    stop_reason: str = ""            # target_reached | exhausted | reached_start_date | scan_limit | error
    elapsed_seconds: float = 0.0
    error: str = ""

    @property
    def stop_message(self) -> str:
        return {
            "target_reached": "Reached the number of reviews you asked for.",
            "exhausted": "Collected every review the Play Store returned for these settings.",
            "reached_start_date": "Reached your start date — older reviews were skipped.",
            "scan_limit": "Stopped at the safety limit of scanned reviews.",
            "error": f"The Play Store stopped responding: {self.error}",
        }.get(self.stop_reason, "")


# ── public API ───────────────────────────────────────────────────────────────

def fetch_all_reviews(
    app_id: str,
    app_name: str,
    options: ScrapeOptions | None = None,
    progress: ProgressFn | None = None,
    reviews_fn: Callable = gp_reviews,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> ScrapeResult:
    """Collect overall reviews (all ratings) for ``app_id``.

    Returns a :class:`ScrapeResult` whose ``reviews`` are dicts keyed by
    :data:`REVIEW_FIELDS`, in the order the store returned them (newest first
    by default).
    """
    opts = options or ScrapeOptions()
    if opts.sort not in SORT_OPTIONS:
        raise ValueError(f"sort must be one of {sorted(SORT_OPTIONS)}")
    if opts.start_date and opts.end_date and opts.start_date > opts.end_date:
        raise ValueError("start_date cannot be after end_date")

    started = time.monotonic()
    target = opts.target
    ratings = set(opts.ratings or (1, 2, 3, 4, 5))
    # The API can filter one star value server-side; for several we filter locally.
    score_filter = next(iter(ratings)) if len(ratings) == 1 else None
    newest_first = opts.sort == "newest"

    result = ScrapeResult()
    kept_raw: list[dict] = []
    seen_ids: set[str] = set()
    token = None

    while True:
        if target and len(kept_raw) >= target:
            result.stop_reason = "target_reached"
            break
        if result.scanned >= opts.max_scanned:
            result.stop_reason = "scan_limit"
            break

        try:
            batch, token = _fetch_page(
                reviews_fn, sleep_fn, app_id, opts, score_filter, token
            )
        except Exception as exc:  # network died after retries — keep what we have
            result.stop_reason = "error"
            result.error = str(exc)
            break

        if not batch:
            result.stop_reason = "exhausted"
            break

        result.scanned += len(batch)
        batch_all_older = True

        for raw in batch:
            at = to_datetime(raw.get("at"))
            if at is None or not opts.start_date or at.date() >= opts.start_date:
                batch_all_older = False

            rid = raw.get("reviewId") or ""
            if rid and rid in seen_ids:
                continue
            if not _passes_filters(raw, at, opts, ratings):
                continue
            if rid:
                seen_ids.add(rid)
            kept_raw.append(raw)
            if target and len(kept_raw) >= target:
                break

        if progress:
            progress(len(kept_raw), result.scanned, target)

        if newest_first and opts.start_date and batch_all_older:
            result.stop_reason = "reached_start_date"
            break
        if token is None or getattr(token, "token", "") is None:
            result.stop_reason = "exhausted"
            break

    if target and len(kept_raw) >= target and not result.stop_reason:
        result.stop_reason = "target_reached"

    result.reviews = normalize_reviews(kept_raw[:target] if target else kept_raw, app_id, app_name, opts.anonymize_users)
    result.elapsed_seconds = round(time.monotonic() - started, 2)
    return result


def fetch_app_details(
    app_id: str, lang: str = "en", country: str = "us", app_fn: Callable = gp_app
) -> dict | None:
    """Return store metadata (title, icon, rating, installs, …) or None on failure."""
    try:
        info = app_fn(app_id, lang=lang, country=country)
    except Exception as exc:
        logger.warning("Could not load app details for %s: %s", app_id, exc)
        return None
    return {
        "title": info.get("title") or app_id,
        "developer": info.get("developer") or "",
        "icon": info.get("icon") or "",
        "genre": info.get("genre") or "",
        "score": info.get("score"),
        "ratings": info.get("ratings"),
        "reviews": info.get("reviews"),
        "installs": info.get("installs") or "",
        "histogram": info.get("histogram") or [],
        "updated": info.get("updated"),
        "version": info.get("version") or "",
        "url": info.get("url") or f"https://play.google.com/store/apps/details?id={app_id}",
    }


def normalize_reviews(raw_reviews: list[dict], app_id: str, app_name: str, anonymize: bool = False) -> list[dict]:
    """Turn google-play-scraper dicts into flat, analysis-ready rows."""
    rows = []
    for i, r in enumerate(raw_reviews, start=1):
        content = (r.get("content") or "").strip()
        reply = (r.get("replyContent") or "").strip()
        at = to_datetime(r.get("at"))
        replied = to_datetime(r.get("repliedAt"))
        user = (r.get("userName") or "").strip()
        if anonymize:
            user = "user_" + hashlib.sha1(f"{app_id}:{user}".encode()).hexdigest()[:10]
        rows.append({
            "review_id": f"R{i:06d}",
            "play_review_id": r.get("reviewId") or "",
            "app_id": app_id,
            "app_name": app_name,
            "user_name": user,
            "rating": int(r.get("score") or 0),
            "content": content,
            "word_count": word_count(content),
            "char_count": len(content),
            "thumbs_up": int(r.get("thumbsUpCount") or 0),
            "app_version": r.get("reviewCreatedVersion") or r.get("appVersion") or "",
            "review_date": at.strftime("%Y-%m-%d") if at else "",
            "review_datetime": at.strftime("%Y-%m-%d %H:%M:%S") if at else "",
            "has_reply": bool(reply),
            "reply_content": reply,
            "replied_at": replied.strftime("%Y-%m-%d %H:%M:%S") if replied else "",
        })
    return rows


# ── internals ────────────────────────────────────────────────────────────────

def _fetch_page(reviews_fn, sleep_fn, app_id, opts: ScrapeOptions, score_filter, token):
    """One page of reviews with exponential-backoff retries."""
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return reviews_fn(
                app_id,
                lang=opts.lang,
                country=opts.country,
                sort=SORT_OPTIONS[opts.sort],
                count=BATCH_SIZE,
                filter_score_with=score_filter,
                continuation_token=token,
            )
        except Exception as exc:
            last_exc = exc
            logger.warning("%s: page request failed (attempt %d/%d): %s", app_id, attempt, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES:
                sleep_fn(2 ** attempt)
    raise RuntimeError(str(last_exc))


def _passes_filters(raw: dict, at: datetime | None, opts: ScrapeOptions, ratings: set[int]) -> bool:
    if int(raw.get("score") or 0) not in ratings:
        return False
    if opts.start_date or opts.end_date:
        if at is None:
            return False
        if opts.start_date and at.date() < opts.start_date:
            return False
        if opts.end_date and at.date() > opts.end_date:
            return False
    text = (raw.get("content") or "").strip()
    if opts.min_words and word_count(text) < opts.min_words:
        return False
    if opts.english_only and not _is_english(text):
        return False
    return True


def _is_english(text: str) -> bool:
    if not text:
        return False
    if detect is None:  # pragma: no cover
        return True
    try:
        return detect(text) == "en"
    except LangDetectException:
        return False
