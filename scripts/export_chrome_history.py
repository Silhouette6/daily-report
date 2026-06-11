#!/usr/bin/env python3

import argparse
import json
import shutil
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


EPOCH_START = datetime(1601, 1, 1)
DEFAULT_HISTORY = Path("~/Library/Application Support/Google/Chrome/Default/History").expanduser()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export one day's Chrome visits to JSON.")
    parser.add_argument("--date", required=True, help="Target date in YYYY-MM-DD.")
    parser.add_argument("--output", required=True, help="Output JSON path.")
    parser.add_argument(
        "--history",
        default=str(DEFAULT_HISTORY),
        help="Path to Chrome History sqlite database.",
    )
    parser.add_argument(
        "--timezone",
        default="Asia/Shanghai",
        help="IANA timezone used to filter the date.",
    )
    return parser.parse_args()


def chrome_time_to_local(microseconds: int, timezone: ZoneInfo) -> datetime:
    utc_dt = EPOCH_START + timedelta(microseconds=microseconds)
    return utc_dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(timezone)


def fetch_rows(history_path: Path) -> list[tuple]:
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_db = Path(tmpdir) / "History"
        shutil.copy2(history_path, temp_db)
        conn = sqlite3.connect(temp_db)
        try:
            cursor = conn.execute(
                """
                SELECT
                    urls.url,
                    urls.title,
                    visits.visit_time,
                    urls.visit_count,
                    urls.typed_count
                FROM visits
                JOIN urls ON visits.url = urls.id
                ORDER BY visits.visit_time ASC
                """
            )
            return list(cursor.fetchall())
        finally:
            conn.close()


def main() -> int:
    args = parse_args()
    target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    timezone = ZoneInfo(args.timezone)
    history_path = Path(args.history).expanduser()
    output_path = Path(args.output)

    if not history_path.exists():
        raise FileNotFoundError(f"Chrome history DB not found: {history_path}")

    visits = []
    unique_urls = set()

    for url, title, visit_time, visit_count, typed_count in fetch_rows(history_path):
        visited_at = chrome_time_to_local(visit_time, timezone)
        if visited_at.date() != target_date:
            continue

        unique_urls.add(url)
        visits.append(
            {
                "title": title or "",
                "url": url,
                "domain": url.split("/")[2] if "://" in url else "",
                "visited_at": visited_at.isoformat(),
                "visit_count": visit_count,
                "typed_count": typed_count,
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": args.date,
        "timezone": args.timezone,
        "source": str(history_path),
        "visit_count": len(visits),
        "unique_url_count": len(unique_urls),
        "visits": visits,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
