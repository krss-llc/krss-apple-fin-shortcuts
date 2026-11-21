#!/usr/bin/env python3
"""Update the earnings calendar using dates published by Yahoo Finance."""

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import yfinance as yf

from sma_alert import TICKERS

CSV_PATH = Path(__file__).with_name("earnings_calendar.csv")
CSV_FIELDS = ["ticker", "earnings_date"]


def _earnings_date(value):
    """Convert a Yahoo earnings date value into YYYY-MM-DD."""
    parsed = pd.to_datetime(str(value).split(" at ", 1)[0], errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def _dates_from_frame(frame, as_of):
    if frame is None or frame.empty:
        return []

    # Yahoo commonly puts earnings dates in the index, but some responses
    # expose an "Earnings Date" column instead.
    values = (
        frame["Earnings Date"].tolist()
        if "Earnings Date" in frame.columns
        else frame.index.tolist()
    )
    upcoming = {
        earnings_date
        for value in values
        if (earnings_date := _earnings_date(value)) is not None
        and earnings_date >= as_of.isoformat()
    }
    return sorted(upcoming)


def build_earnings_csv(csv_path=CSV_PATH, tickers=None, as_of=None):
    """Fetch upcoming earnings dates and write all tickers to the CSV."""
    output_path = Path(csv_path)
    if not output_path.is_absolute():
        output_path = Path(__file__).resolve().parent / output_path

    as_of = as_of or date.today()
    rows = []
    errors = []

    for ticker in tickers if tickers is not None else TICKERS:
        ticker = ticker.strip().upper()
        if not ticker:
            continue
        try:
            frame = yf.Ticker(ticker).get_earnings_dates(limit=12)
            dates = _dates_from_frame(frame, as_of)[:4]
            rows.append({
                "ticker": ticker,
                "earnings_date": ";".join(dates),
            })
        except Exception as exc:
            errors.append(f"{ticker}: {exc}")
            rows.append({"ticker": ticker, "earnings_date": ""})

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} tickers to {output_path}")
    if errors:
        print("Could not fetch earnings dates:\n" + "\n".join(errors), file=sys.stderr)
    return errors


def main():
    parser = argparse.ArgumentParser(
        description="Update earnings_calendar.csv from Yahoo Finance."
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=CSV_PATH,
        help="Output CSV path (default: earnings_calendar.csv beside this script).",
    )
    args = parser.parse_args()
    errors = build_earnings_csv(csv_path=args.csv)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
