from datetime import date, datetime

import pytest

from utils import extract_app_id, parse_date, to_datetime, validate_request, word_count


@pytest.mark.parametrize("raw, expected", [
    ("com.king.candycrushsaga", "com.king.candycrushsaga"),
    ("  com.whatsapp  ", "com.whatsapp"),
    ("https://play.google.com/store/apps/details?id=com.spotify.music", "com.spotify.music"),
    ("https://play.google.com/store/apps/details?id=com.spotify.music&hl=en_US&gl=PK", "com.spotify.music"),
    ("https://play.google.com/store/apps/details?hl=en&id=com.duolingo", "com.duolingo"),
    ("", ""),
    (None, ""),
    ("whatsapp", ""),
    ("not a url at all", ""),
    ("123.abc", ""),
])
def test_extract_app_id(raw, expected):
    assert extract_app_id(raw) == expected


def test_parse_date_variants():
    assert parse_date(None) is None
    assert parse_date("") is None
    assert parse_date("2025-03-01") == date(2025, 3, 1)
    assert parse_date(date(2025, 3, 1)) == date(2025, 3, 1)
    assert parse_date(datetime(2025, 3, 1, 10, 5)) == date(2025, 3, 1)
    with pytest.raises(ValueError):
        parse_date("01/03/2025", "start")


def test_validate_request():
    assert validate_request(200, None, None) == ""
    assert validate_request(None, None, None) == ""            # scrape all
    assert validate_request(0, None, None) == ""               # scrape all
    assert validate_request(201, None, None) == ""             # odd numbers are fine now
    assert "negative" in validate_request(-5, None, None)
    assert "after" in validate_request(10, date(2025, 2, 1), date(2025, 1, 1))
    assert "at least one" in validate_request(10, None, None, ratings=[])
    assert "between 1 and 5" in validate_request(10, None, None, ratings=[6])


def test_word_count_and_to_datetime():
    assert word_count("") == 0
    assert word_count("  hello   world ") == 2
    assert to_datetime("2025-01-02 03:04:05") == datetime(2025, 1, 2, 3, 4, 5)
    assert to_datetime(date(2025, 1, 2)) == datetime(2025, 1, 2)
    assert to_datetime("garbage") is None
    assert to_datetime(None) is None
