#!/usr/bin/env python3
"""Fetch volatility indexes via yfinance and report their 90-day SMAs."""
import sys
from pathlib import Path

sys.path.insert(0, '/opt/data/.venv/lib/python3.11/site-packages')
import yfinance as yf

SYMBOLS = ['^VIX', '^OVX', '^MOVE']
LOG_FILE = Path(__file__).with_name('volatility_check.log')
SMA_PERIOD = 90

def compute_sma(sym):
    try:
        t = yf.Ticker(sym)
        hist = t.history(period=f'{SMA_PERIOD + 10}d')
        if len(hist) < SMA_PERIOD:
            return None, len(hist), None
        closes = hist['Close'].dropna().tail(SMA_PERIOD)
        sma = round(closes.mean(), 4)
        return sma, len(closes), None
    except Exception as e:
        return None, 0, f'  {sym} SMA error: {e}'

def main():
    output_lines = []
    for sym in SYMBOLS:
        try:
            t = yf.Ticker(sym)
            info = t.info
            price = info.get('currentPrice') or info.get('regularMarketPrice')
            name = info.get('longName') or info.get('shortName') or sym
            sma, n, error = compute_sma(sym)
            if error:
                output_lines.append(error)
            pct_off = None
            if sma and price:
                pct_off = round(((price - sma) / sma) * 100, 2)
            sma_str = f"SMA90={sma} ({pct_off:+}%)" if sma else f"SMA90=N/A({n}d)"
            output_lines.append(f'{sym}: {price} ({name})  {sma_str}')
        except Exception as e:
            output_lines.append(f'{sym}: ERROR - {e}')

    output = '\n'.join(output_lines)
    LOG_FILE.write_text(f'{output}\n' if output else '', encoding='utf-8')
    print(output)

if __name__ == '__main__':
    main()