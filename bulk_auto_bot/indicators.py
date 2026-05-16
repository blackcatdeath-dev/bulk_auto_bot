from __future__ import annotations

from math import isnan


def ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(values: list[float], period: int = 14) -> float:
    if len(values) <= period:
        return 50.0
    gains = []
    losses = []
    for i in range(-period, 0):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(abs(min(diff, 0.0)))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def atr_pct(candles: list[dict[str, float]], period: int = 14) -> float:
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(-period, 0):
        h = candles[i]["high"]
        l = candles[i]["low"]
        pc = candles[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    close = candles[-1]["close"]
    if close <= 0:
        return 0.0
    return (sum(trs) / len(trs)) / close


def bullish_engulfing(prev: dict[str, float], curr: dict[str, float]) -> bool:
    return prev["close"] < prev["open"] and curr["close"] > curr["open"] and curr["close"] > prev["open"] and curr["open"] < prev["close"]


def bearish_engulfing(prev: dict[str, float], curr: dict[str, float]) -> bool:
    return prev["close"] > prev["open"] and curr["close"] < curr["open"] and curr["open"] > prev["close"] and curr["close"] < prev["open"]


def hammer(curr: dict[str, float]) -> bool:
    body = abs(curr["close"] - curr["open"])
    rng = max(curr["high"] - curr["low"], 1e-12)
    lower = min(curr["open"], curr["close"]) - curr["low"]
    upper = curr["high"] - max(curr["open"], curr["close"])
    return body / rng < 0.35 and lower / rng > 0.45 and upper / rng < 0.25


def shooting_star(curr: dict[str, float]) -> bool:
    body = abs(curr["close"] - curr["open"])
    rng = max(curr["high"] - curr["low"], 1e-12)
    upper = curr["high"] - max(curr["open"], curr["close"])
    lower = min(curr["open"], curr["close"]) - curr["low"]
    return body / rng < 0.35 and upper / rng > 0.45 and lower / rng < 0.25
