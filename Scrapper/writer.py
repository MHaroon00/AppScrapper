"""Turn review rows into downloadable files (CSV / Excel / JSON) and write CLI output."""

from __future__ import annotations

import csv
import io
import json
import os
import re
from datetime import datetime, timezone

from fetcher import REVIEW_FIELDS

# Characters Excel refuses to store (control chars except tab/newline/CR)
_ILLEGAL_XLSX = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


# ── in-memory exports (used by the web app) ──────────────────────────────────

def to_csv_bytes(rows: list[dict], fields: list[str] | None = None) -> bytes:
    """UTF-8 CSV with BOM so Excel shows emoji / Urdu / Arabic text correctly."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields or REVIEW_FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


def to_json_bytes(rows: list[dict], fields: list[str] | None = None) -> bytes:
    keys = fields or REVIEW_FIELDS
    clean = [{k: _jsonable(r.get(k)) for k in keys} for r in rows]
    return json.dumps(clean, ensure_ascii=False, indent=2).encode("utf-8")


def to_excel_bytes(rows: list[dict], fields: list[str] | None = None, summary: dict | None = None) -> bytes:
    import pandas as pd  # local import keeps the CLI light

    keys = fields or REVIEW_FIELDS
    df = pd.DataFrame([{k: r.get(k) for k in keys} for r in rows], columns=keys)
    for col in df.columns:
        df[col] = df[col].map(lambda v: _ILLEGAL_XLSX.sub("", v) if isinstance(v, str) else v)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        df.to_excel(xl, sheet_name="Reviews", index=False)
        ws = xl.sheets["Reviews"]
        widths = {"content": 80, "reply_content": 60, "user_name": 22, "app_name": 22, "review_datetime": 20, "replied_at": 20}
        for idx, col in enumerate(keys, start=1):
            letter = ws.cell(row=1, column=idx).column_letter
            ws.column_dimensions[letter].width = widths.get(col, max(12, len(col) + 2))
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        if summary:
            pd.DataFrame(list(summary.items()), columns=["metric", "value"]).to_excel(
                xl, sheet_name="Summary", index=False
            )
            xl.sheets["Summary"].column_dimensions["A"].width = 28
            xl.sheets["Summary"].column_dimensions["B"].width = 40
    return buf.getvalue()


# ── on-disk outputs (used by the CLI) ────────────────────────────────────────

def write_outputs(app_id: str, rows: list[dict], output_dir: str, formats: tuple[str, ...] = ("csv", "json")) -> list[str]:
    os.makedirs(output_dir, exist_ok=True)
    written = []
    makers = {"csv": to_csv_bytes, "json": to_json_bytes, "xlsx": to_excel_bytes}
    for fmt in formats:
        if fmt not in makers:
            raise ValueError(f"Unknown format: {fmt}")
        path = os.path.join(output_dir, f"reviews_{app_id}.{fmt}")
        with open(path, "wb") as f:
            f.write(makers[fmt](rows))
        written.append(path)
    return written


def append_combined_csv(rows: list[dict], output_dir: str) -> str:
    path = os.path.join(output_dir, "combined_reviews.csv")
    same_header = os.path.isfile(path) and _existing_header(path) == REVIEW_FIELDS
    with open(path, "a" if same_header else "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_FIELDS, extrasaction="ignore")
        if not same_header:
            writer.writeheader()
        writer.writerows(rows)
    return path


def update_log(app_id: str, status: str, count: int, output_dir: str, extra: dict | None = None) -> None:
    path = os.path.join(output_dir, "scrape_log.json")
    log = {}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                log = json.load(f)
        except json.JSONDecodeError:
            log = {}
    log[app_id] = {
        "status": status,
        "review_count": count,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **(extra or {}),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)


def _jsonable(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def _existing_header(path: str) -> list[str]:
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        return next(csv.reader(f), [])
