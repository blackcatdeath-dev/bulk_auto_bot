from __future__ import annotations

from dataclasses import dataclass

from .indicators import atr_pct, bearish_engulfing, bullish_engulfing, ema, hammer, rsi, shooting_star
from .settings import SETTINGS


@dataclass
class Signal:
    symbol: str
    side: str  # BUY or SELL
    score: float
    price: float
    reason: str
    size_fraction: float


@dataclass
class SignalDiagnostics:
    symbol: str
    price: float
    spread_pct: float
    candle_count: int
    bull_score: float
    bear_score: float
    best_side: str
    best_score: float
    reason: str


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def snd_score(candles: list[dict[str, float]], side: str) -> tuple[float, str]:
    """Simple supply/demand proxy.

    Demand: price near recent swing-low area.
    Supply: price near recent swing-high area.
    This is intentionally aggressive and usable even when Bulk klines have zero volume.
    """
    if len(candles) < 25:
        return 0.0, "not_enough_candles"
    close = candles[-1]["close"]
    lookback = candles[-35:-3] if len(candles) >= 38 else candles[:-3]
    if len(lookback) < 10 or close <= 0:
        return 0.0, "not_enough_snd_window"
    lows = [c["low"] for c in lookback]
    highs = [c["high"] for c in lookback]
    recent_low = min(lows)
    recent_high = max(highs)
    ap = max(atr_pct(candles, 14), 0.0006)  # avoid dead scores on flat/zero-volume klines

    if side == "BUY":
        dist = abs(close - recent_low) / close
        score = _clip(1 - dist / (ap * 3.0))
        return score, f"demand_dist={dist:.4%}"
    else:
        dist = abs(recent_high - close) / close
        score = _clip(1 - dist / (ap * 3.0))
        return score, f"supply_dist={dist:.4%}"


def momentum_scores(candles: list[dict[str, float]]) -> tuple[float, float, str]:
    closes = [c["close"] for c in candles]
    vols = [c["volume"] for c in candles]
    if len(closes) < 24:
        return 0.0, 0.0, "not_enough_candles"
    e9_series = ema(closes, 9)
    e21_series = ema(closes, 21)
    e9 = e9_series[-1]
    e21 = e21_series[-1]
    e9_prev = e9_series[-4] if len(e9_series) >= 4 else e9_series[0]
    vol_now = vols[-1]
    vol_avg = sum(vols[-21:-1]) / max(len(vols[-21:-1]), 1)
    if vol_avg <= 0:
        volume_boost = 0.0
    else:
        volume_boost = _clip((vol_now / max(vol_avg, 1e-12) - 1) / 1.5)
    trend = abs(e9 - e21) / max(closes[-1], 1e-12)
    slope = abs(e9 - e9_prev) / max(closes[-1], 1e-12)
    trend_score = _clip((trend + slope * 2.0) / 0.003)
    if e9 > e21:
        return _clip(0.50 + 0.40 * trend_score + 0.10 * volume_boost), 0.0, f"ema_bull trend={trend_score:.2f} vol_boost={volume_boost:.2f}"
    if e9 < e21:
        return 0.0, _clip(0.50 + 0.40 * trend_score + 0.10 * volume_boost), f"ema_bear trend={trend_score:.2f} vol_boost={volume_boost:.2f}"
    return 0.0, 0.0, "flat"


def candle_scores(candles: list[dict[str, float]]) -> tuple[float, float, str]:
    if len(candles) < 3:
        return 0.0, 0.0, "not_enough_candles"
    prev, curr = candles[-2], candles[-1]
    bull = 0.0
    bear = 0.0
    reasons = []
    if bullish_engulfing(prev, curr):
        bull = max(bull, 0.80); reasons.append("bullish_engulfing")
    if bearish_engulfing(prev, curr):
        bear = max(bear, 0.80); reasons.append("bearish_engulfing")
    if hammer(curr):
        bull = max(bull, 0.65); reasons.append("hammer")
    if shooting_star(curr):
        bear = max(bear, 0.65); reasons.append("shooting_star")
    rng = max(curr["high"] - curr["low"], 1e-12)
    close_pos = (curr["close"] - curr["low"]) / rng
    if close_pos > 0.72:
        bull = max(bull, 0.60); reasons.append("strong_bull_close")
    if close_pos < 0.28:
        bear = max(bear, 0.60); reasons.append("strong_bear_close")
    return bull, bear, "+".join(reasons) or "none"


def rsi_scores(candles: list[dict[str, float]]) -> tuple[float, float, str]:
    closes = [c["close"] for c in candles]
    val = rsi(closes, 14)
    bull = 0.0
    bear = 0.0
    if val < 35:
        bull = _clip((35 - val) / 15)
    elif 42 <= val <= 62:
        bull = 0.42
    if val > 65:
        bear = _clip((val - 65) / 15)
    elif 38 <= val <= 58:
        bear = 0.42
    return bull, bear, f"rsi={val:.1f}"


def _score_components(candles: list[dict[str, float]], spread_pct: float) -> tuple[float, float, str, str]:
    mom_bull, mom_bear, mom_reason = momentum_scores(candles)
    candle_bull, candle_bear, candle_reason = candle_scores(candles)
    rsi_bull, rsi_bear, rsi_reason = rsi_scores(candles)
    snd_bull, snd_bull_reason = snd_score(candles, "BUY")
    snd_bear, snd_bear_reason = snd_score(candles, "SELL")
    spread_score = _clip(1 - spread_pct / max(SETTINGS.max_spread_pct, 1e-12))

    bull = snd_bull * 0.30 + mom_bull * 0.25 + candle_bull * 0.20 + rsi_bull * 0.15 + spread_score * 0.10
    bear = snd_bear * 0.30 + mom_bear * 0.25 + candle_bear * 0.20 + rsi_bear * 0.15 + spread_score * 0.10
    bull_reason = f"BUY score={bull:.2f}; {snd_bull_reason}; {mom_reason}; {candle_reason}; {rsi_reason}; spread={spread_pct:.3%}"
    bear_reason = f"SELL score={bear:.2f}; {snd_bear_reason}; {mom_reason}; {candle_reason}; {rsi_reason}; spread={spread_pct:.3%}"
    return bull, bear, bull_reason, bear_reason


def diagnose_signal(symbol: str, price: float, spread_pct: float, candles: list[dict[str, float]]) -> SignalDiagnostics:
    if len(candles) < SETTINGS.min_candles or price <= 0:
        reason = f"blocked: candles={len(candles)} min={SETTINGS.min_candles} price={price}"
        return SignalDiagnostics(symbol, price, spread_pct, len(candles), 0.0, 0.0, "NONE", 0.0, reason)
    if spread_pct > SETTINGS.max_spread_pct:
        reason = f"blocked: spread={spread_pct:.3%} max={SETTINGS.max_spread_pct:.3%}"
        return SignalDiagnostics(symbol, price, spread_pct, len(candles), 0.0, 0.0, "NONE", 0.0, reason)
    bull, bear, bull_reason, bear_reason = _score_components(candles, spread_pct)
    if bull >= bear:
        return SignalDiagnostics(symbol, price, spread_pct, len(candles), bull, bear, "BUY", bull, bull_reason)
    return SignalDiagnostics(symbol, price, spread_pct, len(candles), bull, bear, "SELL", bear, bear_reason)


def build_signal(symbol: str, price: float, spread_pct: float, candles: list[dict[str, float]]) -> Signal | None:
    diag = diagnose_signal(symbol, price, spread_pct, candles)
    if diag.best_score < SETTINGS.min_signal_score:
        return None

    score = diag.best_score
    side = diag.best_side
    reason = diag.reason

    if score >= 0.82:
        frac = SETTINGS.extreme_equity_fraction
    elif score >= 0.75:
        frac = SETTINGS.strong_equity_fraction
    else:
        frac = SETTINGS.base_equity_fraction

    return Signal(symbol=symbol, side=side, score=score, price=price, reason=reason, size_fraction=frac)
