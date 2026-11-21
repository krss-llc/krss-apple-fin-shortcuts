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

SECTOR_MAP = {
    "XLK": ["SMH", "CIBR", "SKYY", "IGV", "ARKF"],
    "XLF": ["KRE", "KBE", "IAK"],
    "XLE": ["XLB", "GDX", "COPX", "URA", "LIT"],
    "XLI": ["XLI"],
    "XLY": ["XLY"],
    "XLC": ["XLC"],
    "XBI": ["XBI"],
    "IBB": ["IBB"],
    "XLP": ["XLP"],
    "XLU": ["XLU"],
    "XLV": ["XLV"],
    "XLB": ["XLB"],
    "GDX": ["GDX"],
    "COPX": ["COPX"],
    "URA": ["URA"],
    "LIT": ["LIT"],
    "ICLN": ["ICLN"],
    "TAN": ["TAN"],
    "JEPI": ["JEPI"],
    "QYLD": ["QYLD"],
    "USMV": ["USMV"],
    "SPLV": ["SPLV"],
    "QUAL": ["QUAL"],
    "VTV": ["VTV"],
    "MTUM": ["MTUM"],
    "XSMO": ["IWM"],
}


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
            for field in ("Close", "High", "Low", "Open", "Volume")
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


def compute_rs_excess(ticker_closes, spy_closes, lookback=63):
    ticker_closes = list(ticker_closes)
    spy_closes = list(spy_closes)
    if len(ticker_closes) < lookback or len(spy_closes) < lookback:
        return None
    ticker_ret = ticker_closes[-1] / ticker_closes[-lookback] - 1
    spy_ret = spy_closes[-1] / spy_closes[-lookback] - 1
    return ticker_ret - spy_ret


def compute_adx(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return None

    true_ranges = []
    plus_dm = []
    minus_dm = []
    for index in range(1, len(closes)):
        true_ranges.append(max(
            highs[index] - lows[index],
            abs(highs[index] - closes[index - 1]),
            abs(lows[index] - closes[index - 1]),
        ))
        plus_dm.append(max(highs[index] - highs[index - 1], 0))
        minus_dm.append(max(lows[index - 1] - lows[index], 0))

    if len(true_ranges) < period:
        return None
    tr14 = sum(true_ranges[-period:])
    plus14 = sum(plus_dm[-period:])
    minus14 = sum(minus_dm[-period:])
    plus_di = 100 * plus14 / tr14 if tr14 else 0
    minus_di = 100 * minus14 / tr14 if tr14 else 0
    di_sum = plus_di + minus_di
    dx = 100 * abs(plus_di - minus_di) / di_sum if di_sum else 0
    return dx


def compute_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains = []
    losses = []
    for index in range(1, len(closes)):
        change = closes[index] - closes[index - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    avg_gain = average(gains[-period:])
    avg_loss = average(losses[-period:])
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def weekly_trend_ok(daily_closes):
    closes = pd.Series(list(daily_closes), dtype="float64")
    closes.index = pd.date_range(
        end=pd.Timestamp.today().normalize(),
        periods=len(closes),
        freq="D",
    )
    weekly = closes.resample("W-MON").last()
    if len(weekly) < 10:
        return False
    sma10 = weekly.rolling(10).mean()
    return bool(weekly.iloc[-1] > sma10.iloc[-1])


def pullback_volume_dry(volumes, closes, lookback=10):
    if len(volumes) < lookback + 5 or len(closes) < lookback + 5:
        return None
    breakout_vol = volumes[-1]
    pullback_volumes = []
    for index in range(len(closes) - lookback, len(closes) - 1):
        if closes[index] < closes[index - 1]:
            pullback_volumes.append(volumes[index])
    if not pullback_volumes:
        return True
    return average(pullback_volumes) < breakout_vol * 0.7


def gap_type(opens, closes):
    if len(opens) < 2 or len(closes) < 2:
        return "none"
    pct = (opens[-1] - closes[-2]) / closes[-2]
    if pct > 0.015:
        return "gap_up"
    if pct < -0.015:
        return "gap_down"
    return "none"


def sector_confirmation(ticker, daily_closes, spy_closes=None, sector_cache=None):
    sectors = SECTOR_MAP.get(ticker.upper())
    if not sectors:
        return True
    sector_etf = sectors[0].upper()
    if sector_cache is not None and sector_etf in sector_cache:
        return sector_cache[sector_etf]
    try:
        sector_bars = get_bars(download_history(sector_etf))
        if sector_bars.empty:
            result = False
        else:
            _, sector_reasons = evaluate_ticker(
                sector_etf,
                sector_bars,
                spy_closes=spy_closes,
                skip_sector=True,
            )
            result = not sector_reasons
    except Exception:
        result = False
    if sector_cache is not None:
        sector_cache[sector_etf] = result
    return result


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


def evaluate_ticker(ticker, bars, spy_closes=None, skip_sector=False, sector_cache=None):
    closes = bars["close"].astype(float).tolist()
    highs = bars["high"].astype(float).tolist()
    lows = bars["low"].astype(float).tolist()
    opens = bars["open"].astype(float).tolist() if "open" in bars else closes[:-1] + [closes[-1]]
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

    breakout_confirmed = not any(
        reason in reasons
        for reason in (
            "BREAKOUT_PRICE_FAIL",
            "VOLUME_CONFIRMATION_FAIL",
            "SMA20_DATA_UNAVAILABLE",
            "VOLUME_DATA_UNAVAILABLE",
        )
    )

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

    # Rule 6 — Average daily dollar volume must exceed $20M.
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

    rs_excess = (
        compute_rs_excess(closes, spy_closes)
        if spy_closes is not None else None
    )
    if rs_excess is None:
        reasons.append("RS_DATA_UNAVAILABLE")
    elif rs_excess < 0:
        reasons.append("RS_VS_SPY_NEGATIVE")

    adx_val = compute_adx(highs, lows, closes, period=14)
    if adx_val is None:
        reasons.append("ADX_DATA_UNAVAILABLE")
    elif adx_val <= 20:
        reasons.append("ADX_NOT_TRENDING")

    rsi14 = compute_rsi(closes, period=14)
    if rsi14 is None:
        reasons.append("RSI_DATA_UNAVAILABLE")
    elif rsi14 > 70:
        reasons.append("RSI_OVERBOUGHT")

    if not weekly_trend_ok(closes):
        reasons.append("WEEKLY_TREND_NEGATIVE")

    if breakout_confirmed:
        dry_pullback = pullback_volume_dry(volumes, closes, lookback=10)
        if dry_pullback is None:
            reasons.append("PULLBACK_DATA_UNAVAILABLE")
        elif not dry_pullback:
            reasons.append("PULLBACK_VOLUME_NOT_DRY")

    gap = gap_type(opens, closes)

    if not skip_sector and not sector_confirmation(
        ticker,
        bars["close"],
        spy_closes=spy_closes,
        sector_cache=sector_cache,
    ):
        reasons.append("SECTOR_NOT_BREAKING")

    metrics = {
        "date": as_of,
        "ticker": ticker,
        "close": price,
        "sma20": sma20,
        "sma50": sma50,
        "atr14": atr14,
        "volume_ratio": volume_ratio,
        "avg_daily_dollar_volume": avg_daily_dollar_volume,
        "rs_excess": rs_excess,
        "adx14": adx_val,
        "rsi14": rsi14,
        "gap": gap,
    }
    return metrics, reasons


def get_order_plan(entry, atr14):
    # Rule 7 — Profit target is 4.5% above the planned entry.
    target = entry * (1 + TARGET_PERCENT)

    # Rule 8 — The protective stop is below entry by the larger of 2% or 1.5 ATR.
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
        elif reason == "RS_VS_SPY_NEGATIVE":
            descriptions.append("relative strength vs. SPY is negative")
        elif reason == "ADX_NOT_TRENDING":
            descriptions.append("ADX(14) is not above 20")
        elif reason == "RSI_OVERBOUGHT":
            descriptions.append("RSI(14) is above 70")
        elif reason == "WEEKLY_TREND_NEGATIVE":
            descriptions.append("weekly close is below the 10-week SMA")
        elif reason == "PULLBACK_VOLUME_NOT_DRY":
            descriptions.append("pull-back volume is not dry")
        elif reason == "SECTOR_NOT_BREAKING":
            descriptions.append("sector confirmation is not breaking out")
        elif reason.endswith("DATA_UNAVAILABLE"):
            descriptions.append("insufficient price or volume data")
    return "; ".join(descriptions) if descriptions else "rule check failed"


def main():
    try:
        spy_bars = get_bars(download_history("SPY"))
        spy_closes = (
            spy_bars["close"].astype(float).tolist()
            if not spy_bars.empty else None
        )
    except Exception:
        spy_closes = None
    sector_cache = {}
    entry_setups = []
    rejected = []
    errors = []
    dates = []

    for ticker in TICKERS:
        try:
            bars = get_bars(download_history(ticker))
            if bars.empty:
                raise ValueError("no complete OHLCV bars")

            metrics, reasons = evaluate_ticker(
                ticker,
                bars,
                spy_closes=spy_closes,
                sector_cache=sector_cache,
            )
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
                f"RS {metrics['rs_excess']:.2%}; ADX14 {metrics['adx14']:.1f}; "
                f"RSI14 {metrics['rsi14']:.1f}; gap {metrics['gap']}; "
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
        "  7. Relative strength vs. SPY must be positive.",
        "  8. ADX(14) must be above 20.",
        "  9. RSI(14) must be 70 or below.",
        " 10. The weekly close must be above the 10-week SMA.",
        " 11. After Rules 1 and 2 pass, pull-back volume must be below 70% of breakout volume.",
        " 12. The sector ETF must pass the same entry rules.",
        "  Passing setups also show a 1.5~2%stop and a 4.5% target.",
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
