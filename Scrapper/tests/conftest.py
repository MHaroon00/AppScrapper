"""Shared fixtures: a fake Play Store that behaves like google-play-scraper's `reviews()`."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WORDS = "great app but it crashes sometimes when I open the camera and the ads are annoying".split()


@dataclass
class FakeToken:
    token: str | None
    offset: int
    score: int | None


def make_review(i: int, at: datetime, score: int, words: int = 12, reply: bool = False, rid: str | None = None) -> dict:
    return {
        "reviewId": rid or f"gp-{i}",
        "userName": f"User {i % 37}",
        "userImage": "",
        "content": " ".join(WORDS[j % len(WORDS)] for j in range(words)),
        "score": score,
        "thumbsUpCount": (i * 7) % 50,
        "reviewCreatedVersion": f"1.{i % 4}.0" if i % 5 else None,
        "at": at,
        "replyContent": "Thanks for the feedback!" if reply else None,
        "repliedAt": at + timedelta(days=1) if reply else None,
        "appVersion": None,
    }


class FakeStore:
    """Serves `n` reviews, newest first, one per hour going back from `newest`."""

    def __init__(self, n: int = 1000, newest: datetime = datetime(2026, 6, 30, 12, 0), fail_times: int = 0):
        self.data = [
            make_review(i, newest - timedelta(hours=i), score=(i % 5) + 1, words=(i % 30) + 1, reply=(i % 4 == 0))
            for i in range(n)
        ]
        self.calls: list[dict] = []
        self.fail_times = fail_times

    def __call__(self, app_id, lang="en", country="us", sort=None, count=100,
                 filter_score_with=None, continuation_token=None, **_):
        self.calls.append({"app_id": app_id, "lang": lang, "country": country, "count": count,
                           "filter_score_with": filter_score_with, "token": continuation_token})
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ConnectionError("temporary network error")
        pool = [r for r in self.data if filter_score_with is None or r["score"] == filter_score_with]
        start = continuation_token.offset if continuation_token else 0
        page = pool[start:start + count]
        end = start + len(page)
        next_token = FakeToken(token="more" if end < len(pool) else None, offset=end, score=filter_score_with)
        return page, next_token


@pytest.fixture
def store():
    return FakeStore()


@pytest.fixture
def no_sleep():
    return lambda _seconds: None
