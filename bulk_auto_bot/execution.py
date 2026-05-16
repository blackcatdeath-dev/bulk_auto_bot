from __future__ import annotations

import logging
import time

from . import db
from .bulk_client_adapter import BulkAdapter
from .settings import SETTINGS
from .strategy import Signal

log = logging.getLogger(__name__)


def now_ms() -> int:
    return int(time.time() * 1000)


def now_s() -> int:
    return int(time.time())


class Executor:
    def __init__(self, adapter: BulkAdapter) -> None:
        self.adapter = adapter
        self.leverage_applied: set[str] = set()

    def signal_to_size(self, signal: Signal) -> float:
        leverage = self.adapter.cap_leverage(signal.symbol, SETTINGS.target_leverage or 1)
        multiplier = leverage if SETTINGS.use_leverage_in_sizing else 1.0
        notional = SETTINGS.assumed_equity * signal.size_fraction * multiplier
        size = notional / max(signal.price, 1e-12)
        return self.adapter.round_size(signal.symbol, max(size, 0.0), min_price=signal.price)

    def entry_limit_price(self, signal: Signal, spread_pct: float) -> float:
        # Marketable IOC limit with small slippage allowance, not unlimited market.
        slip = max(spread_pct * 1.5, 0.0005)
        if signal.side == "BUY":
            return self.adapter.round_price(signal.symbol, signal.price * (1 + slip), side="BUY")
        return self.adapter.round_price(signal.symbol, signal.price * (1 - slip), side="SELL")

    def _close_position_row(self, p, price: float, reason: str) -> tuple[str, str, float, float, str] | None:
        symbol = p["symbol"]
        side = p["side"]
        entry = float(p["entry_price"])
        size = float(p["size"])
        if side == "BUY":
            pnl = (price - entry) * size
            close_side = "SELL"
            close_px = price * (1 - 0.0007)
        else:
            pnl = (entry - price) * size
            close_side = "BUY"
            close_px = price * (1 + 0.0007)
        try:
            self.adapter.place_ioc_limit(symbol, close_side, close_px, size, reduce_only=True)
        except Exception as exc:
            if SETTINGS.enable_live_trading and not SETTINGS.dry_run:
                log.error("live close failed for %s: %s", symbol, exc)
                return None
            log.warning("dry/sim close fallback: %s", exc)
        db.close_position(int(p["id"]), now_s(), price, pnl, reason)
        log.info("closed %s %s pnl=%.6f reason=%s", symbol, side, pnl, reason)
        return (symbol, side, pnl, price, reason)

    def maybe_enter(self, signal: Signal, spread_pct: float) -> bool:
        open_for_symbol = db.get_open_positions(signal.symbol)
        if open_for_symbol and not SETTINGS.allow_pyramiding_same_symbol:
            same_side = [p for p in open_for_symbol if p["side"] == signal.side]
            opposite = [p for p in open_for_symbol if p["side"] != signal.side]
            if same_side:
                log.info("duplicate skip %s %s: open position already exists", signal.symbol, signal.side)
                return False
            if opposite:
                if not SETTINGS.close_on_signal_reversal:
                    log.info("reversal skip %s %s: opposite position still open", signal.symbol, signal.side)
                    return False
                for p in opposite:
                    closed = self._close_position_row(p, signal.price, "signal_reversal")
                    if closed is None:
                        return False

        last = db.last_open_ts(signal.symbol)
        if last and now_s() - last < SETTINGS.order_cooldown_seconds:
            log.info("cooldown skip %s", signal.symbol)
            return False

        if SETTINGS.apply_leverage_on_start and SETTINGS.target_leverage > 0 and signal.symbol not in self.leverage_applied:
            try:
                self.adapter.update_leverage(signal.symbol, SETTINGS.target_leverage)
                self.leverage_applied.add(signal.symbol)
            except Exception as exc:
                log.error("leverage update failed for %s: %s", signal.symbol, exc)
                if SETTINGS.enable_live_trading and not SETTINGS.dry_run:
                    return False

        size = self.signal_to_size(signal)
        if size <= 0:
            return False
        price = self.entry_limit_price(signal, spread_pct)
        result = self.adapter.place_ioc_limit(signal.symbol, signal.side, price, size, reduce_only=False)
        if isinstance(result.raw, dict):
            size = float(result.raw.get("size", size))
            price = float(result.raw.get("price", price))
        if result.ok:
            tp = signal.price * (1 + SETTINGS.take_profit_pct) if signal.side == "BUY" else signal.price * (1 - SETTINGS.take_profit_pct)
            sl = signal.price * (1 - SETTINGS.stop_loss_pct) if signal.side == "BUY" else signal.price * (1 + SETTINGS.stop_loss_pct)
            db.open_position(now_s(), signal.symbol, signal.side, signal.price, size, tp, sl, signal.reason)
            log.info("opened virtual/live position %s %s score=%.2f", signal.symbol, signal.side, signal.score)
            return True
        return False

    def manage_exits(self, price_by_symbol: dict[str, float]) -> list[tuple[str, str, float, float, str]]:
        closed = []
        for p in db.get_open_positions():
            symbol = p["symbol"]
            price = price_by_symbol.get(symbol)
            if not price:
                continue
            side = p["side"]
            entry = float(p["entry_price"])
            size = float(p["size"])
            age = now_s() - int(p["opened_ts"])
            reason = None
            if side == "BUY":
                if price >= float(p["take_profit"]):
                    reason = "take_profit"
                elif price <= float(p["stop_loss"]):
                    reason = "stop_loss"
                pnl = (price - entry) * size
                close_side = "SELL"
                close_px = price * (1 - 0.0007)
            else:
                if price <= float(p["take_profit"]):
                    reason = "take_profit"
                elif price >= float(p["stop_loss"]):
                    reason = "stop_loss"
                pnl = (entry - price) * size
                close_side = "BUY"
                close_px = price * (1 + 0.0007)

            if reason is None and age >= SETTINGS.timeout_seconds:
                reason = "timeout_realize_or_cut"
            if reason is None:
                continue

            result = self._close_position_row(p, price, reason)
            if result is not None:
                closed.append(result)
        return closed
