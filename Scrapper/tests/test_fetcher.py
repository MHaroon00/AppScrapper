from datetime import date, datetime

import pytest

from fetcher import REVIEW_FIELDS, ScrapeOptions, fetch_all_reviews, fetch_app_details, normalize_reviews
from tests.conftest import FakeStore, make_review


def run(store, no_sleep, **kw):
    return fetch_all_reviews("com.example.app", "Example", ScrapeOptions(**kw), reviews_fn=store, sleep_fn=no_sleep)


def test_collects_all_star_ratings_not_just_positive_negative(store, no_sleep):
    res = run(store, no_sleep, total_reviews=500)
    assert len(res.reviews) == 500
    assert {r["rating"] for r in res.reviews} == {1, 2, 3, 4, 5}   # 3★ included
    assert "sentiment_group" not in res.reviews[0]
    assert res.stop_reason == "target_reached"


def test_exact_total_is_respected_including_odd_numbers(store, no_sleep):
    assert len(run(store, no_sleep, total_reviews=1).reviews) == 1
    assert len(run(store, no_sleep, total_reviews=333).reviews) == 333


def test_scrape_everything_when_total_is_none_or_zero(no_sleep):
    for total in (None, 0):
        store = FakeStore(n=750)
        res = run(store, no_sleep, total_reviews=total)
        assert len(res.reviews) == 750
        assert res.stop_reason == "exhausted"
        assert res.scanned == 750


def test_rows_have_every_column_and_sequential_ids(store, no_sleep):
    rows = run(store, no_sleep, total_reviews=25).reviews
    assert list(rows[0].keys()) == REVIEW_FIELDS
    assert [r["review_id"] for r in rows[:3]] == ["R000001", "R000002", "R000003"]
    assert rows[0]["app_name"] == "Example" and rows[0]["app_id"] == "com.example.app"
    assert rows[0]["review_date"] == "2026-06-30"
    assert rows[0]["review_datetime"] == "2026-06-30 12:00:00"
    assert rows[0]["has_reply"] is True and rows[0]["replied_at"].startswith("2026-07-01")
    assert rows[1]["has_reply"] is False and rows[1]["reply_content"] == ""


def test_date_range_filter_and_early_stop(no_sleep):
    # 5000 hourly reviews from 2026-06-30 back ≈ 208 days
    store = FakeStore(n=5000)
    res = run(store, no_sleep, total_reviews=None, start_date=date(2026, 6, 1), end_date=date(2026, 6, 10))
    dates = {r["review_date"] for r in res.reviews}
    assert min(dates) == "2026-06-01" and max(dates) == "2026-06-10"
    assert len(res.reviews) == 10 * 24
    assert res.stop_reason == "reached_start_date"
    assert res.scanned < 5000          # stopped early instead of reading everything


def test_most_relevant_sort_does_not_stop_early(no_sleep):
    store = FakeStore(n=1200)
    res = run(store, no_sleep, total_reviews=None, sort="most_relevant", start_date=date(2026, 6, 25))
    assert res.scanned == 1200
    assert all(r["review_date"] >= "2026-06-25" for r in res.reviews)


def test_rating_subset_filters_locally(store, no_sleep):
    res = run(store, no_sleep, total_reviews=100, ratings=(3, 4))
    assert {r["rating"] for r in res.reviews} == {3, 4}
    assert all(c["filter_score_with"] is None for c in store.calls)


def test_single_rating_uses_server_side_filter(store, no_sleep):
    res = run(store, no_sleep, total_reviews=50, ratings=(1,))
    assert {r["rating"] for r in res.reviews} == {1}
    assert store.calls[0]["filter_score_with"] == 1


def test_min_words(store, no_sleep):
    res = run(store, no_sleep, total_reviews=100, min_words=20)
    assert all(r["word_count"] >= 20 for r in res.reviews)


def test_duplicates_are_removed(no_sleep):
    store = FakeStore(n=10)
    store.data += [make_review(99, datetime(2026, 1, 1), 5, rid="gp-0")]  # duplicate Google ID
    res = run(store, no_sleep, total_reviews=None)
    assert len(res.reviews) == 10


def test_language_country_and_page_size_passed_through(store, no_sleep):
    run(store, no_sleep, total_reviews=10, lang="ur", country="pk")
    assert store.calls[0]["lang"] == "ur" and store.calls[0]["country"] == "pk"
    assert store.calls[0]["count"] == 200


def test_retries_then_succeeds(no_sleep):
    store = FakeStore(n=50, fail_times=2)
    res = run(store, no_sleep, total_reviews=None)
    assert len(res.reviews) == 50


def test_persistent_failure_keeps_partial_results():
    class Flaky(FakeStore):
        def __call__(self, *a, **kw):
            if len(self.calls) >= 1:
                self.calls.append({})
                raise ConnectionError("blocked")
            return super().__call__(*a, **kw)

    res = fetch_all_reviews("x.y", "X", ScrapeOptions(total_reviews=None), reviews_fn=Flaky(n=1000), sleep_fn=lambda s: None)
    assert len(res.reviews) == 200
    assert res.stop_reason == "error" and "blocked" in res.error


def test_scan_limit(no_sleep):
    store = FakeStore(n=2000)
    res = run(store, no_sleep, total_reviews=None, max_scanned=400)
    assert res.scanned == 400 and res.stop_reason == "scan_limit"


def test_progress_callback(store, no_sleep):
    seen = []
    fetch_all_reviews("a.b", "A", ScrapeOptions(total_reviews=450), progress=lambda c, s, t: seen.append((c, s, t)),
                      reviews_fn=store, sleep_fn=no_sleep)
    assert seen[-1][0] == 450 and seen[-1][2] == 450
    assert [s for _, s, _ in seen] == sorted(s for _, s, _ in seen)


def test_anonymize_users(store, no_sleep):
    rows = run(store, no_sleep, total_reviews=40, anonymize_users=True).reviews
    assert all(r["user_name"].startswith("user_") for r in rows)
    same_user = [r["user_name"] for r in rows if r["play_review_id"] in ("gp-0", "gp-37")]
    assert same_user[0] == same_user[1]   # stable hash per person


def test_invalid_options(store, no_sleep):
    with pytest.raises(ValueError):
        run(store, no_sleep, sort="random")
    with pytest.raises(ValueError):
        run(store, no_sleep, start_date=date(2026, 2, 1), end_date=date(2026, 1, 1))


def test_english_only(no_sleep):
    store = FakeStore(n=4)
    store.data[1]["content"] = "یہ ایپ بہت اچھی ہے لیکن اشتہارات بہت زیادہ ہیں اور یہ کبھی کبھی بند ہو جاتی ہے"
    store.data[2]["content"] = "Esta aplicación es muy buena pero tiene demasiados anuncios y a veces se cierra sola"
    store.data[0]["content"] = store.data[3]["content"] = "This app is really good but it has far too many ads and it crashes sometimes"
    res = run(store, no_sleep, total_reviews=None, english_only=True)
    assert [r["play_review_id"] for r in res.reviews] == ["gp-0", "gp-3"]


def test_normalize_handles_missing_fields():
    rows = normalize_reviews([{"reviewId": "a", "score": None, "content": None, "at": None}], "x.y", "X")
    assert rows[0]["rating"] == 0 and rows[0]["content"] == "" and rows[0]["review_date"] == ""


def test_fetch_app_details():
    fake = lambda app_id, lang, country: {"title": "Demo", "developer": "Dev Co", "score": 4.31, "installs": "1,000+"}
    d = fetch_app_details("com.demo", app_fn=fake)
    assert d["title"] == "Demo" and d["score"] == 4.31
    assert d["url"].endswith("id=com.demo")

    def broken(*a, **kw):
        raise RuntimeError("404")
    assert fetch_app_details("com.demo", app_fn=broken) is None
