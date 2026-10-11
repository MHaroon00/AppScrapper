"""Click through the Streamlit UI headlessly with a fake Play Store."""

import os

import pytest
from streamlit.testing.v1 import AppTest

import fetcher
from tests.conftest import FakeStore

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "streamlit_app.py")


@pytest.fixture
def fake_network(monkeypatch):
    real = fetcher.fetch_all_reviews

    def fake_fetch(app_id, app_name, options=None, progress=None, **_):
        return real(app_id, app_name, options, progress=progress, reviews_fn=FakeStore(n=900), sleep_fn=lambda s: None)

    monkeypatch.setattr(fetcher, "fetch_all_reviews", fake_fetch)
    monkeypatch.setattr(fetcher, "fetch_app_details", lambda app_id, **kw: {
        "title": "Demo App", "developer": "Demo Studio", "icon": "", "genre": "Tools", "score": 4.2,
        "ratings": 12345, "reviews": 999, "installs": "1,000,000+", "histogram": [], "updated": None,
        "version": "1.0", "url": f"https://play.google.com/store/apps/details?id={app_id}",
    })


def button(at, label):
    return next(b for b in at.button if b.label == label)


def test_initial_render_has_no_errors():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert [t.label for t in at.text_input][:2] == ["App ID or Play Store URL", "App name"]
    assert at.number_input[0].value == 500


def test_empty_input_shows_error():
    at = AppTest.from_file(APP, default_timeout=30).run()
    button(at, "Scrape reviews").click().run()
    assert "Please enter an app ID" in at.error[0].value


def test_bad_dates_show_error():
    from datetime import date
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.text_input[0].input("com.demo.app")
    at.date_input[0].set_value(date(2026, 6, 10))
    at.date_input[1].set_value(date(2026, 6, 1))
    button(at, "Scrape reviews").click().run()
    assert "Start date cannot be after" in at.error[0].value


def test_full_scrape_flow(fake_network):
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.text_input[0].input("https://play.google.com/store/apps/details?id=com.demo.app&hl=en")
    at.number_input[0].set_value(250)
    button(at, "Scrape reviews").click().run()

    assert not at.exception
    res = at.session_state["result"]
    assert res["app_id"] == "com.demo.app"
    assert res["app_name"] == "Demo App"           # filled from store details when name left blank
    assert len(res["rows"]) == 250
    assert {r["rating"] for r in res["rows"]} == {1, 2, 3, 4, 5}
    assert [t.label for t in at.tabs] == ["📊  Overview", "🔎  Explore reviews", "⬇️  Export"]
    assert len(at.dataframe) >= 1


def test_example_button_fills_inputs():
    at = AppTest.from_file(APP, default_timeout=30).run()
    button(at, "Spotify").click().run()
    assert at.text_input[0].value == "com.spotify.music"
    assert at.text_input[1].value == "Spotify"
