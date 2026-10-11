#!/usr/bin/env python3
"""Command-line scraper: collect ALL Google Play reviews (every star rating).

Examples
--------
  # 500 newest reviews of one app
  python scraper.py --app-id com.spotify.music --app-name Spotify --total-reviews 500

  # every review posted in 2025, saved as CSV + Excel
  python scraper.py --app-id com.whatsapp --total-reviews 0 \
      --start-date 2025-01-01 --end-date 2025-12-31 --formats csv,xlsx

  # every app listed in apps_list.txt
  python scraper.py --apps apps_list.txt --total-reviews 1000
"""

from __future__ import annotations

import argparse
import os
import sys

from fetcher import SORT_OPTIONS, ScrapeOptions, fetch_all_reviews
from utils import extract_app_id, parse_date, validate_request
from writer import append_combined_csv, update_log, write_outputs


def load_app_inputs(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Scrape overall Google Play Store reviews (all ratings).")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--app-id", help="Single app ID or Play Store URL")
    src.add_argument("--apps", default="apps_list.txt", help="File with one app ID/URL per line")
    p.add_argument("--app-name", default=None, help="Name written into the app_name column (single app only)")
    p.add_argument("--total-reviews", type=int, default=200, help="Reviews per app; 0 = every available review")
    p.add_argument("--start-date", default=None, help="Only reviews on/after this date (YYYY-MM-DD)")
    p.add_argument("--end-date", default=None, help="Only reviews on/before this date (YYYY-MM-DD)")
    p.add_argument("--sort", choices=sorted(SORT_OPTIONS), default="newest")
    p.add_argument("--lang", default="en", help="Review language code (default: en)")
    p.add_argument("--country", default="us", help="Store country code (default: us)")
    p.add_argument("--ratings", default="1,2,3,4,5", help="Comma-separated star ratings to keep")
    p.add_argument("--min-words", type=int, default=0, help="Drop reviews shorter than this many words")
    p.add_argument("--english-only", action="store_true", help="Keep only reviews detected as English")
    p.add_argument("--anonymize", action="store_true", help="Replace reviewer names with hashed IDs")
    p.add_argument("--formats", default="csv,json", help="Output formats: csv,json,xlsx")
    p.add_argument("--output", default="./output", help="Output directory")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        start = parse_date(args.start_date, "--start-date")
        end = parse_date(args.end_date, "--end-date")
        ratings = tuple(int(x) for x in args.ratings.split(",") if x.strip())
    except ValueError as exc:
        print(f"Invalid arguments: {exc}")
        return 2

    error = validate_request(args.total_reviews, start, end, ratings)
    if error:
        print(f"Invalid arguments: {error}")
        return 2

    inputs = [args.app_id] if args.app_id else load_app_inputs(args.apps)
    if not inputs:
        print("No app IDs or Play Store URLs found.")
        return 2
    if args.app_name and len(inputs) > 1:
        print("--app-name can only be used with a single app.")
        return 2

    formats = tuple(f.strip().lower() for f in args.formats.split(",") if f.strip())
    opts = ScrapeOptions(
        total_reviews=args.total_reviews or None,
        start_date=start,
        end_date=end,
        sort=args.sort,
        lang=args.lang,
        country=args.country,
        ratings=ratings,
        min_words=args.min_words,
        english_only=args.english_only,
        anonymize_users=args.anonymize,
    )

    goal = "all available" if not opts.target else str(opts.target)
    print(f"Scraping {len(inputs)} app(s) | {goal} reviews each | ratings {ratings} | "
          f"dates {start or 'any'} → {end or 'any'} | sort {args.sort}")
    print(f"Output → {os.path.abspath(args.output)}\n")

    ok = failed = total = 0
    for raw in inputs:
        app_id = extract_app_id(raw)
        if not app_id:
            print(f"✗ {raw}: not a valid app ID or Play Store URL")
            failed += 1
            continue

        def show(collected, scanned, target, _id=app_id):
            goal_txt = f"/{target}" if target else ""
            sys.stdout.write(f"\r  {_id}: {collected}{goal_txt} kept · {scanned} scanned")
            sys.stdout.flush()

        result = fetch_all_reviews(app_id, args.app_name or app_id, opts, progress=show)
        print()
        if result.reviews:
            paths = write_outputs(app_id, result.reviews, args.output, formats)
            append_combined_csv(result.reviews, args.output)
            update_log(app_id, "success", len(result.reviews), args.output, {"stop_reason": result.stop_reason})
            print(f"✓ {app_id}: {len(result.reviews)} reviews ({result.stop_message}) → {', '.join(paths)}")
            ok += 1
            total += len(result.reviews)
        else:
            update_log(app_id, "empty" if not result.error else "failed", 0, args.output, {"error": result.error})
            print(f"✗ {app_id}: no reviews matched. {result.stop_message}")
            failed += 1

    print(f"\nDone — {ok} succeeded, {failed} failed, {total} reviews total.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
