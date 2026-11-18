#!/usr/bin/env python3
"""Fetch the 30-year MBA mortgage rate from FRED and report its SMAs and trend."""

from pathlib import Path

import pandas as pd
import requests

API_KEY="***"  # FRED API key — treat as [REDACTED]
SERIES = "OBMMIVA30YF" # https://fred.stlouisfed.org/series/OBMMIVA30YF or another series ID from https://fred.stlouisfed.org/categories/22
LOG_FILE = Path(__file__).with_name("fred_api.log")
OBSERVATIONS = 250
SMA_PERIODS = [20, 50, 200]


def fetch_observations():
    url = (
        f"https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={SERIES}"
        f"&api_key={API_KEY}"
        f"&file_type=json"
        f"&sort_order=desc"
        f"&limit={OBSERVATIONS + 10}"
    )
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    obs = data.get("observations", [])
    valid = [
        (o["date"], float(o["value"]))
        for o in obs
        if o.get("value") not in (".", None, "")
    ]
    valid.sort(key=lambda x: x[0])
    return valid[-OBSERVATIONS:]


def compute_smas(values):
    smas = {}
    for period in SMA_PERIODS:
        if len(values) >= period:
            smas[f"sma_{period}"] = round(sum(values[-period:]) / period, 4)
        else:
            smas[f"sma_{period}"] = None
    return smas


def main():
    obs = fetch_observations()
    if not obs:
        output = "No valid observations"
        LOG_FILE.write_text(f"{output}\n", encoding="utf-8")
        print(output)
        return

    dates = [d for d, _ in obs]
    values = [v for _, v in obs]
    smas = compute_smas(values)

    latest_date = dates[-1]
    latest_rate = values[-1]

    output_lines = [
        f"Date: {latest_date}",
        f"Latest mortgage rate: {latest_rate:.4f}%",
    ]
    for period in SMA_PERIODS:
        key = f"sma_{period}"
        sma = smas.get(key)
        if sma is None:
            output_lines.append(f"{period}-day SMA: unavailable")
            continue

        difference = latest_rate - sma
        comparison = (
            "above" if difference > 0 else "below" if difference < 0 else "at"
        )
        percent_difference = difference / sma * 100 if sma else 0
        output_lines.append(
            f"{period}-day SMA: {sma:.4f}% "
            f"(rate is {abs(difference):.4f} percentage points {comparison}, "
            f"{percent_difference:+.2f}%)"
        )

    sma_20 = smas["sma_20"]
    if sma_20 is None:
        output_lines.append("Trend: unavailable (need at least 20 observations)")
    elif latest_rate > sma_20:
        output_lines.append("^ Rate increasing trend")
    elif latest_rate < sma_20:
        output_lines.append("v Rate decreasing trend")
    else:
        output_lines.append("Rate is at the 20-day SMA; no trend signal")

    output = "\n".join(output_lines)
    LOG_FILE.write_text(f"{output}\n", encoding="utf-8")
    print(output)

if __name__ == "__main__":
    main()