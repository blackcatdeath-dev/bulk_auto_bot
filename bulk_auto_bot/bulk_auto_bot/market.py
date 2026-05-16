from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _num(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def ticker_price(ticker: dict[str, Any]) -> float:
    for key in ("markPrice", "mark_price", "lastPrice", "last", "price", "mid"):
        if key in ticker:
            val = _num(ticker[key])
            if val > 0:
                return val
    # Try nested fields.
    for v in ticker.values():
        if isinstance(v, dict):
            p = ticker_price(v)
            if p > 0:
                return p
    return 0.0


def parse_book(book: dict[str, Any]) -> tuple[float, float, float, float]:
    """Return best_bid, best_ask, bid_depth, ask_depth."""
    bids = book.get("bids") or book.get("bid") or []
    asks = book.get("asks") or book.get("ask") or []
    if not bids and "levels" in book:
        levels = book["levels"]
        # Docs/README example uses levels[0][0] for best bid, but shape may vary.
        if isinstance(levels, list) and len(levels) >= 2:
            bids, asks = levels[0], levels[1]

    def price_size(level: Any) -> tuple[float, float]:
        if isinstance(level, dict):
            return _num(level.get("px") or level.get("price")), _num(level.get("sz") or level.get("size"))
        if isinstance(level, (list, tuple)) and len(level) >= 2:
            return _num(level[0]), _num(level[1])
        return 0.0, 0.0

    best_bid, _ = price_size(bids[0]) if bids else (0.0, 0.0)
    best_ask, _ = price_size(asks[0]) if asks else (0.0, 0.0)
    bid_depth = sum(price_size(x)[0] * price_size(x)[1] for x in bids[:5]) if bids else 0.0
    ask_depth = sum(price_size(x)[0] * price_size(x)[1] for x in asks[:5]) if asks else 0.0
    return best_bid, best_ask, bid_depth, ask_depth


def parse_candles(raw: list[dict[str, Any]]) -> list[dict[str, float]]:
    out: list[dict[str, float]] = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        out.append({
            "open": _num(c.get("open") or c.get("o")),
            "high": _num(c.get("high") or c.get("h")),
            "low": _num(c.get("low") or c.get("l")),
            "close": _num(c.get("close") or c.get("c")),
            "volume": _num(c.get("volume") or c.get("v")),
        })
    return [x for x in out if x["close"] > 0]


def anchor_candles_to_live_price(candles: list[dict[str, float]], price: float) -> list[dict[str, float]]:
    """Append a synthetic live candle when Bulk klines are stale versus ticker.

    In current Bulk early environment, get_klines may return candles whose last
    close is far from live markPrice/lastPrice. The strategy must use live price
    for current signal scoring, so we anchor the final candle to ticker price.
    """
    if not candles or price <= 0:
        return candles
    last = candles[-1]
    last_close = last.get("close", 0.0) or 0.0
    if last_close <= 0:
        return candles
    rel_diff = abs(price - last_close) / price
    # Always append if the live ticker is meaningfully different from last kline.
    if rel_diff < 0.0002:
        return candles
    prev_close = last_close
    synthetic = {
        "open": prev_close,
        "high": max(prev_close, price),
        "low": min(prev_close, price),
        "close": price,
        "volume": max(last.get("volume", 0.0), 1.0),
    }
    return candles + [synthetic]
