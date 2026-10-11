"""Play Store Review Scraper — Streamlit web app.

Collects the overall reviews (every star rating) of any Google Play app and
lets you explore and export them as CSV, Excel or JSON.

Run locally:  streamlit run streamlit_app.py
"""

from __future__ import annotations

import html
import os
import sys
from datetime import date, datetime
from pathlib import Path

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import analytics  # noqa: E402
from fetcher import REVIEW_FIELDS, ScrapeOptions, fetch_all_reviews, fetch_app_details  # noqa: E402
from utils import extract_app_id, validate_request  # noqa: E402
from writer import to_csv_bytes, to_excel_bytes, to_json_bytes  # noqa: E402

ROOT = Path(__file__).parent

LANGUAGES = {
    "en": "English", "ur": "Urdu", "ar": "Arabic", "hi": "Hindi", "es": "Spanish", "fr": "French",
    "de": "German", "pt": "Portuguese", "ru": "Russian", "tr": "Turkish", "id": "Indonesian",
    "it": "Italian", "ja": "Japanese", "ko": "Korean", "zh": "Chinese",
}
COUNTRIES = {
    "us": "United States", "gb": "United Kingdom", "pk": "Pakistan", "in": "India", "ca": "Canada",
    "au": "Australia", "ae": "UAE", "sa": "Saudi Arabia", "de": "Germany", "fr": "France",
    "es": "Spain", "br": "Brazil", "id": "Indonesia", "tr": "Türkiye", "ng": "Nigeria",
}
SORTS = {"Newest first": "newest", "Most relevant": "most_relevant"}
EXAMPLES = {
    "WhatsApp": ("com.whatsapp", "WhatsApp"),
    "Spotify": ("com.spotify.music", "Spotify"),
    "Candy Crush": ("com.king.candycrushsaga", "Candy Crush Saga"),
    "Duolingo": ("com.duolingo", "Duolingo"),
}

# ── page setup ───────────────────────────────────────────────────────────────

st.set_page_config(page_title="Play Store Review Scraper", page_icon="⭐", layout="wide")
st.markdown(f"<style>{(ROOT / 'assets' / 'style.css').read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

st.session_state.setdefault("raw_input", "")
st.session_state.setdefault("app_name", "")
st.session_state.setdefault("result", None)


def use_example(app_id: str, name: str) -> None:
    st.session_state.raw_input = app_id
    st.session_state.app_name = name


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""))


def stars_html(n: int) -> str:
    n = max(0, min(5, int(n)))
    return "★" * n + f"<span class='off'>{'★' * (5 - n)}</span>"


# ── hero ─────────────────────────────────────────────────────────────────────

st.markdown(
    """
    <div class="hero">
      <span class="eyebrow"><span class="dot"></span>Review intelligence for Google Play</span>
      <h1>Play Store <em>Review</em> Scraper</h1>
      <p class="lead">Collect the overall reviews of any Android app, across every star rating,
      within the dates you choose. Explore them here, then export a clean dataset for your analysis.</p>
      <div class="chips">
        <span class="chip"><b>1–5★</b>Every rating, no sentiment split</span>
        <span class="chip"><b>📅</b>Date-range filtering</span>
        <span class="chip"><b>16</b>Analysis-ready columns</span>
        <span class="chip"><b>⬇</b>CSV · Excel · JSON</span>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ── configuration card ───────────────────────────────────────────────────────

with st.container(border=True, key="config_card"):
    st.markdown("<div class='section-label'><span class='num'>01</span>Choose the app</div>", unsafe_allow_html=True)

    c1, c2 = st.columns([3, 2], gap="medium")
    with c1:
        raw_input = st.text_input(
            "App ID or Play Store URL",
            key="raw_input",
            placeholder="com.king.candycrushsaga  or  https://play.google.com/store/apps/details?id=…",
        )
        detected = extract_app_id(raw_input)
        if raw_input.strip():
            if detected:
                st.markdown(f"<div class='hint ok'>✓ Detected app ID <code>{esc(detected)}</code></div>", unsafe_allow_html=True)
            else:
                st.markdown("<div class='hint bad'>✗ That doesn't look like an app ID or Play Store link.</div>", unsafe_allow_html=True)
    with c2:
        app_name = st.text_input("App name", key="app_name", placeholder="e.g. Candy Crush Saga (optional)")

    with st.container(horizontal=True, gap="small", vertical_alignment="center", key="examples"):
        st.markdown("<div class='hint' style='margin:0'>Try an example:</div>", unsafe_allow_html=True, width="content")
        for label, (ex_id, ex_name) in EXAMPLES.items():
            st.button(label, key=f"ex_{ex_id}", type="tertiary", on_click=use_example, args=(ex_id, ex_name))

    st.write("")
    st.markdown("<div class='section-label'><span class='num'>02</span>How many reviews, and from when?</div>", unsafe_allow_html=True)

    d1, d2, d3 = st.columns([1.3, 1, 1], gap="medium")
    with d1:
        scrape_all = st.session_state.get("scrape_all", False)
        total_reviews = st.number_input(
            "Total reviews", min_value=1, max_value=100_000, value=500, step=50,
            disabled=scrape_all, help="Maximum number of reviews to collect.",
        )
        scrape_all = st.toggle("Scrape every available review", key="scrape_all",
                               help="Ignore the limit and keep going until the Play Store runs out "
                                    "(or your start date is reached).")
    today = date.today()
    with d2:
        start_date = st.date_input("Start date", value=None, min_value=date(2008, 1, 1), max_value=today, format="YYYY/MM/DD")
    with d3:
        end_date = st.date_input("End date", value=None, min_value=date(2008, 1, 1), max_value=today, format="YYYY/MM/DD")

    with st.expander("⚙️  Advanced options — language, country, ratings, filters"):
        a1, a2, a3 = st.columns(3, gap="medium")
        with a1:
            sort_label = st.radio("Sort order", list(SORTS), horizontal=True,
                                  help="'Newest first' lets the scraper stop early once it passes your start date.")
        with a2:
            lang = st.selectbox("Review language", list(LANGUAGES), format_func=lambda k: f"{LANGUAGES[k]} ({k})")
        with a3:
            country = st.selectbox("Store country", list(COUNTRIES), format_func=lambda k: f"{COUNTRIES[k]} ({k})")

        b1, b2 = st.columns([2, 1], gap="medium")
        with b1:
            ratings = st.pills("Star ratings to include", [5, 4, 3, 2, 1], selection_mode="multi",
                               default=[5, 4, 3, 2, 1], format_func=lambda s: f"{s} ★")
        with b2:
            min_words = st.number_input("Minimum words per review", min_value=0, max_value=500, value=0, step=5,
                                        help="0 keeps everything, including one-word reviews.")
        t1, t2 = st.columns(2, gap="medium")
        with t1:
            english_only = st.toggle("English-detected reviews only", value=False,
                                     help="Runs language detection on each review (slower).")
        with t2:
            anonymize = st.toggle("Anonymize reviewer names", value=False,
                                  help="Replace names with stable hashed IDs (user_xxxxxxxxxx).")

    ratings = sorted(ratings or [], reverse=True)
    goal = "every available review" if scrape_all else f"up to {int(total_reviews):,} reviews"
    period = f"{start_date or 'earliest'} → {end_date or 'today'}"
    stars_txt = "all ratings" if len(ratings) == 5 else (", ".join(f"{r}★" for r in ratings) or "no ratings")
    st.markdown(
        f"""<div class="summary">Plan:
            <span class="tag">{esc(goal)}</span><span class="tag">{esc(stars_txt)}</span>
            <span class="tag">{esc(period)}</span><span class="tag">{esc(sort_label.lower())}</span>
            <span class="tag">{esc(LANGUAGES[lang])} · {esc(country.upper())}</span></div>""",
        unsafe_allow_html=True,
    )

    go = st.button("Scrape reviews", type="primary", width="stretch", icon="🚀")

# ── run the scrape ───────────────────────────────────────────────────────────

if go:
    app_id = extract_app_id(raw_input)
    error = ""
    if not raw_input.strip():
        error = "Please enter an app ID or a Play Store URL."
    elif not app_id:
        error = "Couldn't recognise that app. Use an ID like `com.spotify.music` or the full Play Store link."
    else:
        error = validate_request(None if scrape_all else int(total_reviews), start_date, end_date, ratings)

    if error:
        st.error(error, icon="⚠️")
    else:
        opts = ScrapeOptions(
            total_reviews=None if scrape_all else int(total_reviews),
            start_date=start_date, end_date=end_date, sort=SORTS[sort_label],
            lang=lang, country=country, ratings=tuple(ratings), min_words=int(min_words),
            english_only=english_only, anonymize_users=anonymize,
        )
        with st.status(f"Scraping reviews for **{app_id}** …", expanded=True) as status:
            st.write("Loading app details …")
            details = fetch_app_details(app_id, lang=lang, country=country)
            display_name = app_name.strip() or (details or {}).get("title") or app_id
            bar = st.progress(0.0, text="Requesting the first page of reviews …")

            def on_progress(collected: int, scanned: int, target: int | None) -> None:
                if target:
                    bar.progress(min(collected / target, 1.0), text=f"{collected:,} / {target:,} reviews kept · {scanned:,} scanned")
                else:
                    bar.progress((scanned % 2000) / 2000, text=f"{collected:,} reviews kept · {scanned:,} scanned")

            result = fetch_all_reviews(app_id, display_name, opts, progress=on_progress)
            bar.progress(1.0, text=f"{len(result.reviews):,} reviews kept · {result.scanned:,} scanned")

            if result.reviews:
                status.update(label=f"Collected {len(result.reviews):,} reviews in {result.elapsed_seconds:.1f}s",
                              state="complete", expanded=False)
                st.session_state.result = {
                    "rows": result.reviews, "app_id": app_id, "app_name": display_name, "details": details,
                    "scanned": result.scanned, "stop": result.stop_message, "elapsed": result.elapsed_seconds,
                    "options": opts, "created": datetime.now().strftime("%Y%m%d_%H%M"),
                }
            else:
                status.update(label="No reviews matched", state="error", expanded=True)
                st.session_state.result = None
                hint = result.stop_message or ""
                st.warning(
                    f"No reviews matched for `{app_id}`. {hint} Check the app ID, widen the date range, "
                    "or try another language/country in Advanced options.", icon="🔍",
                )

# ── results ──────────────────────────────────────────────────────────────────

res = st.session_state.result

if not res:
    st.write("")
    st.markdown(
        """
        <div class="steps">
          <div class="step"><div class="n">STEP 1</div><h4>Paste the app</h4>
            <p>Use a package name like <b>com.whatsapp</b> or copy the link from the Play Store page.</p></div>
          <div class="step"><div class="n">STEP 2</div><h4>Set the scope</h4>
            <p>Pick how many reviews and an optional date window. Every star rating is included by default.</p></div>
          <div class="step"><div class="n">STEP 3</div><h4>Explore &amp; export</h4>
            <p>See rating mix and trends, search the text, then download CSV, Excel or JSON.</p></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    rows = res["rows"]
    df = analytics.to_frame(rows)
    stats = analytics.summarize(df)
    d = res["details"] or {}

    st.write("")
    st.markdown("<div class='section-label'><span class='num'>03</span>Results "
                f"<small>· {esc(res['stop'])}</small></div>", unsafe_allow_html=True)

    icon = f"<img src='{esc(d['icon'])}' alt=''>" if d.get("icon") else "<div class='icon-fallback'>📱</div>"
    pills = []
    if d.get("score"):
        pills.append(f"<span class='pill'><span class='star'>★</span> {d['score']:.1f} store rating</span>")
    if d.get("ratings"):
        pills.append(f"<span class='pill'>{int(d['ratings']):,} ratings</span>")
    if d.get("installs"):
        pills.append(f"<span class='pill'>{esc(d['installs'])} installs</span>")
    if d.get("genre"):
        pills.append(f"<span class='pill'>{esc(d['genre'])}</span>")
    store_url = d.get("url") or f"https://play.google.com/store/apps/details?id={res['app_id']}"
    st.markdown(
        f"""<div class="app-card">{icon}
              <div class="meta"><h3>{esc(res['app_name'])}</h3>
                <div class="sub">{esc(d.get('developer') or res['app_id'])} · <code>{esc(res['app_id'])}</code></div>
                <div class="pills">{''.join(pills)}</div></div>
              <a class="store" href="{esc(store_url)}" target="_blank" rel="noopener">Open in Play Store ↗</a>
            </div>""",
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""<div class="kpis">
          <div class="kpi"><div class="label">Reviews collected</div><div class="value">{stats['count']:,}</div>
            <div class="note">{res['scanned']:,} scanned in {res['elapsed']:.1f}s</div></div>
          <div class="kpi"><div class="label">Average rating</div><div class="value">{stats['avg_rating']:.2f} <span class="star">★</span></div>
            <div class="note">across this sample</div></div>
          <div class="kpi"><div class="label">Date range</div><div class="value small">{esc(stats['first_date'])}<br>→ {esc(stats['last_date'])}</div>
            <div class="note">{stats['span_days']:,} days</div></div>
          <div class="kpi"><div class="label">Avg length</div><div class="value">{stats['avg_words']:.0f}</div>
            <div class="note">words · median {stats['median_words']}</div></div>
          <div class="kpi"><div class="label">Developer replies</div><div class="value">{stats['reply_rate']:.0f}%</div>
            <div class="note">of reviews answered</div></div>
        </div>""",
        unsafe_allow_html=True,
    )

    tab_overview, tab_explore, tab_export = st.tabs(["📊  Overview", "🔎  Explore reviews", "⬇️  Export"])

    # ── overview ──
    with tab_overview:
        grain = analytics.time_grain(stats["span_days"])[1]
        r1a, r1b = st.columns(2, gap="medium")
        with r1a, st.container(border=True):
            st.markdown("<div class='chart-title'>Rating distribution</div>"
                        "<div class='chart-sub'>Number and share of reviews per star rating</div>", unsafe_allow_html=True)
            st.altair_chart(analytics.rating_chart(df), width="stretch", theme=None)
        with r1b, st.container(border=True):
            st.markdown(f"<div class='chart-title'>Review volume</div>"
                        f"<div class='chart-sub'>Reviews per {grain}</div>", unsafe_allow_html=True)
            st.altair_chart(analytics.volume_chart(df, stats["span_days"]), width="stretch", theme=None)

        r2a, r2b = st.columns(2, gap="medium")
        with r2a, st.container(border=True):
            st.markdown(f"<div class='chart-title'>Average rating over time</div>"
                        f"<div class='chart-sub'>Mean stars per {grain}</div>", unsafe_allow_html=True)
            st.altair_chart(analytics.avg_rating_chart(df, stats["span_days"]), width="stretch", theme=None)
        with r2b, st.container(border=True):
            st.markdown("<div class='chart-title'>Most-reviewed app versions</div>"
                        "<div class='chart-sub'>Top 8 versions by review count</div>", unsafe_allow_html=True)
            vchart = analytics.version_chart(df)
            if vchart is None:
                st.caption("The Play Store didn't report app versions for these reviews.")
            else:
                st.altair_chart(vchart, width="stretch", theme=None)

        st.markdown("<div class='section-label' style='margin-top:1rem'>👍 Most helpful reviews "
                    "<small>· ranked by thumbs-up votes</small></div>", unsafe_allow_html=True)
        top = df.sort_values(["thumbs_up", "word_count"], ascending=False).head(3)
        cards = "".join(
            f"""<div class="review"><div class="top"><span class="stars">{stars_html(r.rating)}</span>
                <span>{esc(r.review_date)}</span></div>
                <div class="body">{esc(r.content) or '<i>(no text)</i>'}</div>
                <div class="foot"><span>👍 {int(r.thumbs_up):,}</span><span>{esc(r.user_name)}</span>
                {'<span>💬 dev replied</span>' if r.has_reply else ''}</div></div>"""
            for r in top.itertuples()
        )
        st.markdown(f"<div class='reviews'>{cards}</div>", unsafe_allow_html=True)

    # ── explore ──
    with tab_explore:
        f1, f2, f3 = st.columns([2, 1.4, 1], gap="medium")
        with f1:
            query = st.text_input("Search review text", placeholder="e.g. crash, ads, login, battery …")
        with f2:
            star_filter = st.pills("Ratings", [5, 4, 3, 2, 1], selection_mode="multi", default=[5, 4, 3, 2, 1],
                                   format_func=lambda s: f"{s}★", key="explore_stars")
        with f3:
            order = st.selectbox("Sort by", ["Newest", "Oldest", "Most helpful", "Longest", "Lowest rating", "Highest rating"])
        only_replied = st.toggle("Only reviews with a developer reply", value=False)

        view = df[df["rating"].isin(star_filter or [])]
        if query.strip():
            view = view[view["content"].str.contains(query.strip(), case=False, na=False, regex=False)]
        if only_replied:
            view = view[view["has_reply"].astype(bool)]
        sort_map = {
            "Newest": ("review_dt", False), "Oldest": ("review_dt", True), "Most helpful": ("thumbs_up", False),
            "Longest": ("word_count", False), "Lowest rating": ("rating", True), "Highest rating": ("rating", False),
        }
        col, asc = sort_map[order]
        view = view.sort_values(col, ascending=asc)

        st.caption(f"Showing **{len(view):,}** of {len(df):,} reviews")
        st.dataframe(
            view[["review_date", "rating", "content", "thumbs_up", "word_count", "app_version", "user_name", "has_reply"]],
            width="stretch", hide_index=True, height=520,
            column_config={
                "review_date": st.column_config.TextColumn("Date", width="small"),
                "rating": st.column_config.NumberColumn("Rating", format="%d ★", width="small"),
                "content": st.column_config.TextColumn("Review", width="large"),
                "thumbs_up": st.column_config.NumberColumn("👍", width="small"),
                "word_count": st.column_config.NumberColumn("Words", width="small"),
                "app_version": st.column_config.TextColumn("Version", width="small"),
                "user_name": st.column_config.TextColumn("Reviewer", width="small"),
                "has_reply": st.column_config.CheckboxColumn("Dev reply", width="small"),
            },
        )
        if len(view) != len(df):
            st.download_button(
                f"Download these {len(view):,} filtered reviews (CSV)",
                data=to_csv_bytes(view[REVIEW_FIELDS].to_dict("records")),
                file_name=f"reviews_{res['app_id']}_filtered_{res['created']}.csv", mime="text/csv",
                width="stretch",
            )

    # ── export ──
    with tab_export:
        stem = f"reviews_{res['app_id']}_{res['created']}"
        opts = res["options"]
        summary = {
            "app_id": res["app_id"], "app_name": res["app_name"], "reviews": stats["count"],
            "average_rating": stats["avg_rating"], "first_review": stats["first_date"],
            "last_review": stats["last_date"], "developer_reply_rate_%": stats["reply_rate"],
            "requested_total": opts.target or "all available", "start_date": str(opts.start_date or ""),
            "end_date": str(opts.end_date or ""), "sort": opts.sort, "language": opts.lang,
            "country": opts.country, "ratings": ",".join(map(str, opts.ratings)), "min_words": opts.min_words,
            "english_only": opts.english_only, "anonymized": opts.anonymize_users,
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        st.markdown(f"Download all **{len(rows):,}** reviews with **{len(REVIEW_FIELDS)} columns**. "
                    "The CSV opens cleanly in Excel, even with emoji or Urdu/Arabic text.")
        e1, e2, e3 = st.columns(3, gap="medium")
        e1.download_button("📄  CSV", to_csv_bytes(rows), f"{stem}.csv", "text/csv", width="stretch")
        e2.download_button("📗  Excel (.xlsx)", to_excel_bytes(rows, summary=summary), f"{stem}.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
        e3.download_button("🧾  JSON", to_json_bytes(rows), f"{stem}.json", "application/json", width="stretch")

        with st.expander("📚  Column dictionary"):
            st.markdown(
                """
| Column | Meaning |
|---|---|
| `review_id` | Sequential ID in this dataset (R000001 …) |
| `play_review_id` | Google's own unique review ID |
| `app_id` / `app_name` | Package name and display name |
| `user_name` | Reviewer's public name (hashed if anonymized) |
| `rating` | Star rating, 1–5 |
| `content` | Full review text |
| `word_count` / `char_count` | Length of the review |
| `thumbs_up` | "Helpful" votes from other users |
| `app_version` | App version the reviewer had installed (can be blank) |
| `review_date` / `review_datetime` | When the review was posted |
| `has_reply` / `reply_content` / `replied_at` | Developer response, if any |
"""
            )

        if st.button("Clear results and start over", type="secondary"):
            st.session_state.result = None
            st.rerun()

st.markdown("<div class='foot-note'>Uses public Google Play data via google-play-scraper. "
            "Respect the Play Store's terms and reviewers' privacy when publishing results.</div>",
            unsafe_allow_html=True)
