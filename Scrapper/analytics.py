"""Summary statistics and Altair charts for a scraped review dataset."""

from __future__ import annotations

import altair as alt
import pandas as pd

ACCENT = "#1faa7c"      # validated single-series mark color for the dark surface
TEXT = "#e8edf3"
MUTED = "#93a1b2"
GRID = "rgba(255,255,255,0.06)"
FONT = "Plus Jakarta Sans, system-ui, sans-serif"


def to_frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["review_dt"] = pd.to_datetime(df["review_datetime"], errors="coerce")
    df["rating"] = pd.to_numeric(df["rating"], errors="coerce").fillna(0).astype(int)
    return df


def summarize(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"count": 0}
    dates = df["review_dt"].dropna()
    first, last = (dates.min(), dates.max()) if not dates.empty else (None, None)
    return {
        "count": int(len(df)),
        "avg_rating": round(float(df["rating"].mean()), 2),
        "first_date": first.strftime("%d %b %Y") if first is not None else "—",
        "last_date": last.strftime("%d %b %Y") if last is not None else "—",
        "span_days": int((last - first).days) + 1 if first is not None else 0,
        "avg_words": round(float(df["word_count"].mean()), 1),
        "median_words": int(df["word_count"].median()),
        "reply_rate": round(100 * float(df["has_reply"].astype(bool).mean()), 1),
        "total_thumbs": int(df["thumbs_up"].sum()),
        "rating_counts": {s: int((df["rating"] == s).sum()) for s in (5, 4, 3, 2, 1)},
    }


def time_grain(span_days: int) -> tuple[str, str, str]:
    """(pandas freq, label, d3 time format) suited to the date span."""
    if span_days <= 62:
        return "D", "day", "%d %b"
    if span_days <= 730:
        return "W-MON", "week", "%d %b %y"
    return "MS", "month", "%b %Y"


def _style(chart: alt.Chart, height: int = 260) -> alt.Chart:
    return (
        chart.properties(height=height, background="transparent")
        .configure(font=FONT)
        .configure_view(stroke=None)
        .configure_axis(
            labelColor=MUTED, titleColor=MUTED, gridColor=GRID, domainColor=GRID,
            tickColor=GRID, labelFontSize=11, titleFontSize=11, titleFontWeight=500,
        )
    )


def rating_chart(df: pd.DataFrame) -> alt.Chart:
    total = max(len(df), 1)
    data = pd.DataFrame({"stars": [5, 4, 3, 2, 1]})
    data["count"] = data["stars"].map(lambda s: int((df["rating"] == s).sum()))
    data["share"] = data["count"] / total
    data["label"] = data["stars"].astype(str) + " ★"
    data["text"] = data.apply(lambda r: f"{r['count']:,}  ·  {r['share']:.0%}", axis=1)

    base = alt.Chart(data).encode(
        y=alt.Y("label:N", sort=None, title=None, axis=alt.Axis(labelFontSize=12, labelColor=TEXT, ticks=False, domain=False)),
        x=alt.X("count:Q", title=None, axis=None, scale=alt.Scale(domainMax=max(data["count"].max(), 1) * 1.3)),
        tooltip=[alt.Tooltip("label:N", title="Rating"), alt.Tooltip("count:Q", title="Reviews", format=","),
                 alt.Tooltip("share:Q", title="Share", format=".1%")],
    )
    bars = base.mark_bar(color=ACCENT, cornerRadiusEnd=4, height=22)
    labels = base.mark_text(align="left", dx=8, color=TEXT, fontSize=12).encode(text="text:N")
    return _style(bars + labels, height=230)


def _line_with_hover(data: pd.DataFrame, y: str, y_title: str, fmt: str, x_fmt: str, y_scale=None, extra_tip=None) -> alt.Chart:
    hover = alt.selection_point(fields=["period"], nearest=True, on="pointerover", empty=False, clear="pointerout")
    x = alt.X("period:T", title=None, axis=alt.Axis(format=x_fmt, labelAngle=0, tickCount=6, grid=False))
    y_enc = alt.Y(f"{y}:Q", title=y_title, scale=y_scale or alt.Undefined, axis=alt.Axis(tickCount=5))
    tips = [alt.Tooltip("period:T", title="Period", format="%d %b %Y"), alt.Tooltip(f"{y}:Q", title=y_title, format=fmt)]
    if extra_tip:
        tips.append(extra_tip)

    line = alt.Chart(data).mark_line(color=ACCENT, strokeWidth=2, interpolate="monotone").encode(x=x, y=y_enc)
    points = alt.Chart(data).mark_point(size=80, filled=True, color=ACCENT, stroke="#0b0f14", strokeWidth=2).encode(
        x=x, y=y_enc, opacity=alt.condition(hover, alt.value(1), alt.value(0))
    )
    rule = alt.Chart(data).mark_rule(color="rgba(255,255,255,0.25)", strokeWidth=1).encode(
        x=x, opacity=alt.condition(hover, alt.value(1), alt.value(0)), tooltip=tips
    ).add_params(hover)
    return _style(line + points + rule)


def volume_chart(df: pd.DataFrame, span_days: int) -> alt.Chart:
    freq, _, x_fmt = time_grain(span_days)
    data = (df.dropna(subset=["review_dt"]).set_index("review_dt").resample(freq)["rating"].count()
            .rename("reviews").reset_index().rename(columns={"review_dt": "period"}))
    return _line_with_hover(data, "reviews", "Reviews", ",", x_fmt)


def avg_rating_chart(df: pd.DataFrame, span_days: int) -> alt.Chart:
    freq, _, x_fmt = time_grain(span_days)
    grouped = df.dropna(subset=["review_dt"]).set_index("review_dt").resample(freq)["rating"]
    data = pd.DataFrame({"avg": grouped.mean(), "n": grouped.count()}).dropna().reset_index()
    data = data.rename(columns={"review_dt": "period"})
    return _line_with_hover(
        data, "avg", "Avg rating", ".2f", x_fmt,
        y_scale=alt.Scale(domain=[1, 5]), extra_tip=alt.Tooltip("n:Q", title="Reviews", format=","),
    )


def version_chart(df: pd.DataFrame, top: int = 8) -> alt.Chart | None:
    versions = df.loc[df["app_version"].astype(str).str.len() > 0]
    if versions.empty:
        return None
    data = (versions.groupby("app_version")
            .agg(count=("rating", "size"), avg=("rating", "mean"))
            .sort_values("count", ascending=False).head(top).reset_index())
    base = alt.Chart(data).encode(
        y=alt.Y("app_version:N", sort="-x", title=None, axis=alt.Axis(labelColor=TEXT, ticks=False, domain=False, labelLimit=120)),
        x=alt.X("count:Q", title=None, axis=None, scale=alt.Scale(domainMax=data["count"].max() * 1.35)),
        tooltip=[alt.Tooltip("app_version:N", title="Version"), alt.Tooltip("count:Q", title="Reviews", format=","),
                 alt.Tooltip("avg:Q", title="Avg rating", format=".2f")],
    )
    bars = base.mark_bar(color=ACCENT, cornerRadiusEnd=4, height=16)
    labels = base.mark_text(align="left", dx=8, color=TEXT, fontSize=11).encode(
        text=alt.Text("count:Q", format=",")
    )
    return _style(bars + labels, height=max(160, 30 * len(data)))
