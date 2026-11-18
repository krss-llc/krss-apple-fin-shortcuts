#!/usr/bin/env python3
import sys
import warnings
from pathlib import Path

# Dependencies: python3 -m pip install yfinance pandas

warnings.filterwarnings(
    "ignore",
    message=r"urllib3 v2 only supports OpenSSL.*",
)

import yfinance as yf

TICKERS = [
    # Core sectors
    "XLP", "XLU", "XLV", "XLF", "XLI", "XLE", "XLK", "XLY", "XLC",
    "XBI", "IBB", "VEA", "IEFA",
    # Factor / Style
    "USMV", "SPLV", "QUAL", "VTV",
    # Rate-hike direct
    "KRE", "KBE", "IAK", "TFLO",
    # Inflation / Real asset
    "XLB", "GDX", "COPX",
    # Intl diversifiers
    "EFAV", "SCZ",
    # Income overlay
    "JEPI", "QYLD",
]
WINDOW = 20
SMA_WINDOWS = (20, 50, 200)
THRESHOLD = 0.01
STOP_LOSS_PERCENT = 0.02
TARGET_PERCENT = 0.045
LOG_PATH = Path(__file__).with_name("sma_alert.log")


def get_oco_order(entry_price):
    stop_price = entry_price * (1 - STOP_LOSS_PERCENT)
    target_price = entry_price * (1 + TARGET_PERCENT)
    return round(stop_price, 2), round(target_price, 2)


def get_sma_summary(closes):
    summaries = []
    for window in SMA_WINDOWS:
        if len(closes) >= window:
            sma = sum(float(close) for close in closes[-window:]) / window
            summaries.append(f"SMA{window} {sma:.2f}")
        else:
            summaries.append(f"SMA{window} N/A ({len(closes)}/{window} closes)")
    return ", ".join(summaries)


def get_20_day_high_data(closes):
    if len(closes) < WINDOW + 1:
        return None

    latest_price = float(closes[-1])
    high = max(float(close) for close in closes[-(WINDOW + 1):-1])
    return latest_price, high


def main():
    qualifying_tickers = []
    errors = []
    evaluated_data = []

    for ticker in TICKERS:
        try:
            data = yf.download(
                ticker,
                period="2y",
                interval="1d",
                auto_adjust=True,
                progress=False,
                multi_level_index=False,
            )

            if data.empty or "Close" not in data:
                message = f"{ticker}: no price data"
                errors.append(message)
                evaluated_data.append(message)
                continue

            close_series = data["Close"].dropna()
            if close_series.empty:
                message = f"{ticker}: no closing prices"
                errors.append(message)
                evaluated_data.append(message)
                continue

            closes = close_series.tolist()
            date = close_series.index[-1].strftime("%Y-%m-%d")
            sma_summary = get_sma_summary(closes)
            high_data = get_20_day_high_data(closes)
            if high_data is None:
                evaluated_data.append(
                    f"{ticker} {date}: {sma_summary}; insufficient price history "
                    f"({len(closes)} closes; need {WINDOW + 1})"
                )
                continue

            latest_price, high = high_data
            if high <= 0:
                evaluated_data.append(
                    f"{ticker} {date}: price {latest_price:.2f}, "
                    f"20-day high {high:.2f} (invalid high); {sma_summary}"
                )
                continue

            percent_above = (latest_price / high - 1) * 100
            is_breakout = latest_price >= high * (1 + THRESHOLD)
            status = "BREAKOUT" if is_breakout else "no breakout"
            oco_summary = ""
            if is_breakout:
                stop_price, target_price = get_oco_order(latest_price)
                oco_summary = (
                    f"; OCO entry {latest_price:.2f}, "
                    f"stop {stop_price:.2f}, target {target_price:.2f}"
                )
            evaluated_data.append(
                f"{ticker} {date}: price {latest_price:.2f}, "
                f"20-day high {high:.2f} ({percent_above:.2f}% above), "
                f"{status}; {sma_summary}{oco_summary}"
            )
            if is_breakout:
                qualifying_tickers.append(
                    f"{ticker} {date}: {latest_price:.2f}, "
                    f"20-day high {high:.2f} ({percent_above:.2f}% above)"
                    f"{oco_summary}"
                )
        except Exception as exc:
            message = f"{ticker}: {exc}"
            errors.append(message)
            evaluated_data.append(message)

    output = "\n".join(qualifying_tickers) or "No break outs today"
    log_output = "\n".join(evaluated_data)
    LOG_PATH.write_text(f"{log_output}\n" if log_output else "", encoding="utf-8")
    print(output)

    if errors:
        print("Data issues:\n" + "\n".join(errors), file=sys.stderr)


if __name__ == "__main__":
    main()
