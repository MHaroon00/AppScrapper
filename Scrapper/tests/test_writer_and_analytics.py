import csv
import io
import json

import pandas as pd

import analytics
from fetcher import REVIEW_FIELDS, ScrapeOptions, fetch_all_reviews
from scraper import main as cli_main
from tests.conftest import FakeStore
from writer import append_combined_csv, to_csv_bytes, to_excel_bytes, to_json_bytes, update_log, write_outputs


def sample_rows(n=300):
    return fetch_all_reviews("com.demo", "Demo", ScrapeOptions(total_reviews=n),
                             reviews_fn=FakeStore(n=n), sleep_fn=lambda s: None).reviews


def test_csv_has_bom_header_and_unicode():
    rows = sample_rows(5)
    rows[0]["content"] = "بہت اچھی ایپ 👍"
    data = to_csv_bytes(rows)
    assert data.startswith(b"\xef\xbb\xbf")
    parsed = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    assert list(parsed[0].keys()) == REVIEW_FIELDS
    assert parsed[0]["content"] == "بہت اچھی ایپ 👍"
    assert len(parsed) == 5


def test_json_roundtrip():
    rows = sample_rows(3)
    loaded = json.loads(to_json_bytes(rows))
    assert len(loaded) == 3 and loaded[0]["review_id"] == "R000001"


def test_excel_handles_control_characters_and_summary():
    rows = sample_rows(10)
    rows[0]["content"] = "bad\x07char\x0bhere"
    data = to_excel_bytes(rows, summary={"reviews": 10})
    book = pd.read_excel(io.BytesIO(data), sheet_name=None)
    assert set(book) == {"Reviews", "Summary"}
    assert len(book["Reviews"]) == 10
    assert book["Reviews"].loc[0, "content"] == "badcharhere"


def test_write_outputs_and_log(tmp_path):
    rows = sample_rows(20)
    paths = write_outputs("com.demo", rows, str(tmp_path), ("csv", "json", "xlsx"))
    assert all((tmp_path / p.split("/")[-1]).exists() for p in paths)
    append_combined_csv(rows, str(tmp_path))
    append_combined_csv(rows, str(tmp_path))
    with open(tmp_path / "combined_reviews.csv", encoding="utf-8") as f:
        assert len(list(csv.DictReader(f))) == 40
    update_log("com.demo", "success", 20, str(tmp_path))
    assert json.loads((tmp_path / "scrape_log.json").read_text())["com.demo"]["review_count"] == 20


def test_summary_and_charts_build():
    df = analytics.to_frame(sample_rows(300))
    s = analytics.summarize(df)
    assert s["count"] == 300
    assert 1 <= s["avg_rating"] <= 5
    assert sum(s["rating_counts"].values()) == 300
    for chart in (analytics.rating_chart(df), analytics.volume_chart(df, s["span_days"]),
                  analytics.avg_rating_chart(df, s["span_days"]), analytics.version_chart(df)):
        spec = chart.to_dict()
        assert "layer" in spec


def test_time_grain():
    assert analytics.time_grain(10)[1] == "day"
    assert analytics.time_grain(200)[1] == "week"
    assert analytics.time_grain(2000)[1] == "month"


def test_cli_end_to_end(tmp_path, monkeypatch):
    import scraper
    monkeypatch.setattr(scraper, "fetch_all_reviews",
                        lambda app_id, name, opts, progress=None: fetch_all_reviews(
                            app_id, name, opts, progress=progress, reviews_fn=FakeStore(n=400), sleep_fn=lambda s: None))
    code = cli_main(["--app-id", "https://play.google.com/store/apps/details?id=com.demo",
                     "--app-name", "Demo", "--total-reviews", "150", "--formats", "csv,xlsx",
                     "--output", str(tmp_path)])
    assert code == 0
    with open(tmp_path / "reviews_com.demo.csv", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 150 and rows[0]["app_name"] == "Demo"
    assert (tmp_path / "reviews_com.demo.xlsx").exists()


def test_cli_rejects_bad_dates(tmp_path, capsys):
    assert cli_main(["--app-id", "com.demo", "--start-date", "2025-05-01", "--end-date", "2025-01-01",
                     "--output", str(tmp_path)]) == 2
    assert "Start date cannot be after" in capsys.readouterr().out
