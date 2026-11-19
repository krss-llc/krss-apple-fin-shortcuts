#!/usr/bin/env python3
import sys
import warnings
from pathlib import Path

# Dependencies: python3 -m pip install yfinance pandas

warnings.filterwarnings(
    "ignore",
    message=r"urllib3 v2 only supports OpenSSL.*",
)

import pandas as pd
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

SMA_20 = 20
SMA_50 = 50
VOLUME_WINDOW = 20
ATR_WINDOW = 14
BREAKOUT_THRESHOLD = 0.01
VOLUME_MULTIPLE = 1.5
MAX_AVG_DOLLAR_VOLUME = 20_000_000
TARGET_PERCENT = 0.045
LOG_PATH = Path(__file__).with_name("sma_alert.log")


def extract_series(data, field):
    if field in data.columns:
        series = data[field]
    else:
        matching_columns = [
            column for column in data.columns
            if isinstance(column, tuple) and field in column
        ]
        if not matching_columns:
            raise KeyError(f"Missing {field} price data")
        series = data[matching_columns[0]]
    if isinstance(series, pd.DataFrame):
        series = series.iloc[:, 0]
    return pd.to_numeric(series, errors="coerce")


def get_bars(data):
    bars = pd.concat(
        {
            field.lower(): extract_series(data, field)
            for field in ("Close", "High", "Low", "Volume")
        },
        axis=1,
    )
    return bars.dropna()


def download_history(ticker):
    return yf.download(
        ticker,
        period="2y",
        interval="1d",
        auto_adjust=True,
        progress=False,
        multi_level_index=False,
    )


def average(values):
    return sum(values) / len(values) if values else None


def compute_atr(highs, lows, closes):
    if min(len(highs), len(lows), len(closes)) < ATR_WINDOW + 1:
        return None

    true_ranges = []
    for index in range(1, len(closes)):
        true_ranges.append(max(
            highs[index] - lows[index],
            abs(highs[index] - closes[index - 1]),
            abs(lows[index] - closes[index - 1]),
        ))
    return average(true_ranges[-ATR_WINDOW:])


def evaluate_ticker(ticker, bars):
    closes = bars["close"].astype(float).tolist()
    highs = bars["high"].astype(float).tolist()
    lows = bars["low"].astype(float).tolist()
    volumes = bars["volume"].astype(float).tolist()
    as_of = pd.Timestamp(bars.index[-1]).date().isoformat()
    price = closes[-1]
    reasons = []

    # Rule 1 — Close must be at least 1% above the current 20-day SMA.
    sma20 = average(closes[-SMA_20:]) if len(closes) >= SMA_20 else None
    if sma20 is None:
        reasons.append("SMA20_DATA_UNAVAILABLE")
    elif price < sma20 * (1 + BREAKOUT_THRESHOLD):
        reasons.append("BREAKOUT_PRICE_FAIL")

    # Rule 2 — Today's volume must be at least 1.5x its 20-day average.
    # The average includes today's bar, matching the specified yfinance test.
    avg_volume = (
        average(volumes[-VOLUME_WINDOW:])
        if len(volumes) >= VOLUME_WINDOW else None
    )
    volume_ratio = (
        volumes[-1] / avg_volume
        if avg_volume is not None and avg_volume > 0 else None
    )
    if volume_ratio is None:
        reasons.append("VOLUME_DATA_UNAVAILABLE")
    elif volumes[-1] < VOLUME_MULTIPLE * avg_volume:
        reasons.append("VOLUME_CONFIRMATION_FAIL")

    # Rule 3 — Close must exceed SMA50, and SMA50 must rise from the prior session.
    if len(closes) < SMA_50 + 1:
        sma50 = None
        reasons.append("SMA50_TREND_DATA_UNAVAILABLE")
    else:
        sma50 = average(closes[-SMA_50:])
        sma50_previous = average(closes[-(SMA_50 + 1):-1])
        if price <= sma50:
            reasons.append("PRICE_NOT_ABOVE_SMA50")
        if sma50 <= sma50_previous:
            reasons.append("SMA50_NOT_RISING")

    # Rule 4 — Today's SMA20 must be above the SMA20 from five sessions ago.
    if len(closes) < SMA_20 + 5:
        reasons.append("SMA20_MOMENTUM_DATA_UNAVAILABLE")
    elif average(closes[-SMA_20:]) <= average(closes[-(SMA_20 + 5):-5]):
        reasons.append("SMA20_MOMENTUM_FAIL")

    # Rule 5 — Close must be no more than 1.5 ATR(14) above SMA20.
    atr14 = compute_atr(highs, lows, closes)
    if sma20 is None or atr14 is None:
        reasons.append("ATR_EXTENSION_DATA_UNAVAILABLE")
    elif price > sma20 + 1.5 * atr14:
        reasons.append("PRICE_EXTENDED")

    # Rule 7 — Average daily dollar volume must exceed $20M.
    dollar_volumes = [
        close * volume
        for close, volume in zip(
            closes[-VOLUME_WINDOW:], volumes[-VOLUME_WINDOW:]
        )
    ]
    avg_daily_dollar_volume = (
        average(dollar_volumes)
        if len(dollar_volumes) == VOLUME_WINDOW else None
    )
    if avg_daily_dollar_volume is None:
        reasons.append("DOLLAR_VOLUME_DATA_UNAVAILABLE")
    elif avg_daily_dollar_volume <= MAX_AVG_DOLLAR_VOLUME:
        reasons.append("DOLLAR_VOLUME_NOT_ABOVE_20M")

    metrics = {
        "date": as_of,
        "ticker": ticker,
        "close": price,
        "sma20": sma20,
        "sma50": sma50,
        "atr14": atr14,
        "volume_ratio": volume_ratio,
        "avg_daily_dollar_volume": avg_daily_dollar_volume,
    }
    return metrics, reasons


def get_order_plan(entry, atr14):
    # Rule 8 — Profit target is 4.5% above the planned entry.
    target = entry * (1 + TARGET_PERCENT)

    # Rule 9 — The protective stop is below entry by the larger of 2% or 1.5 ATR.
    stop_distance = max(entry * 0.02, 1.5 * atr14)
    stop = entry - stop_distance
    return stop, target


def format_reasons(metrics, reasons):
    descriptions = []
    for reason in reasons:
        if reason == "BREAKOUT_PRICE_FAIL" and metrics["sma20"] is not None:
            threshold = metrics["sma20"] * (1 + BREAKOUT_THRESHOLD)
            descriptions.append(
                f"close ${metrics['close']:.2f} below breakout level ${threshold:.2f}"
            )
        elif reason == "VOLUME_CONFIRMATION_FAIL":
            descriptions.append(
                f"volume {metrics['volume_ratio']:.2f}x below {VOLUME_MULTIPLE:.1f}x"
            )
        elif reason == "PRICE_NOT_ABOVE_SMA50":
            descriptions.append("close not above SMA50")
        elif reason == "SMA50_NOT_RISING":
            descriptions.append("SMA50 not rising")
        elif reason == "SMA20_MOMENTUM_FAIL":
            descriptions.append("SMA20 momentum is negative")
        elif reason == "PRICE_EXTENDED":
            descriptions.append("price is extended above SMA20 + 1.5 ATR")
        elif reason == "DOLLAR_VOLUME_NOT_ABOVE_20M":
            descriptions.append("average dollar volume is not above $20M")
        elif reason.endswith("DATA_UNAVAILABLE"):
            descriptions.append("insufficient price or volume data")
    return "; ".join(descriptions) if descriptions else "rule check failed"


def main():
    entry_setups = []
    rejected = []
    errors = []
    dates = []

    for ticker in TICKERS:
        try:
            bars = get_bars(download_history(ticker))
            if bars.empty:
                raise ValueError("no complete OHLCV bars")

            metrics, reasons = evaluate_ticker(ticker, bars)
            dates.append(metrics["date"])
            if reasons:
                rejected.append(
                    f"{ticker} — {format_reasons(metrics, reasons)}"
                )
                continue

            stop, target = get_order_plan(metrics["close"], metrics["atr14"])
            entry_setups.append(
                f"{ticker} — close ${metrics['close']:.2f}; "
                f"SMA20 ${metrics['sma20']:.2f}; SMA50 ${metrics['sma50']:.2f}; "
                f"ATR14 ${metrics['atr14']:.2f}; "
                f"volume {metrics['volume_ratio']:.2f}x; "
                f"avg $ volume ${metrics['avg_daily_dollar_volume'] / 1_000_000:.1f}M; "
                f"stop ${stop:.2f}; target ${target:.2f}"
            )
        except Exception as exc:
            errors.append(f"{ticker} — {exc}")

    as_of = max(dates) if dates else "unavailable"
    output_lines = [
        f"SMA Entry Screen — {as_of}",
        f"Potential setups: {len(entry_setups)} of {len(TICKERS)}",
        "",
        "Rules checked:",
        "  1. Close at least 1% above the 20-day SMA.",
        "  2. Volume at least 1.5x the 20-day average (including today).",
        "  3. Close above the 50-day SMA, with the 50-day SMA rising.",
        "  4. 20-day SMA above its value five sessions ago.",
        "  5. Close no higher than SMA20 + 1.5x ATR(14).",
        "  6. Average daily dollar volume above $20M.",
        "  Passing setups also show a stop and a 4.5% target.",
        "",
    ]
    if entry_setups:
        output_lines.append("Potential entries (review; no orders are placed):")
        output_lines.extend(f"  {item}" for item in entry_setups)
    else:
        output_lines.append("No tickers passed the entry rules.")

    if rejected:
        output_lines.extend(["", "Did not qualify:"])
        output_lines.extend(f"  {item}" for item in rejected)
    if errors:
        output_lines.extend(["", "Data errors:"])
        output_lines.extend(f"  {item}" for item in errors)

    output = "\n".join(output_lines)
    LOG_PATH.write_text(f"{output}\n", encoding="utf-8")
    print(output)

    if errors:
        print("Data issues:\n" + "\n".join(errors), file=sys.stderr)


if __name__ == "__main__":
    main()
