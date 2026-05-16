from __future__ import annotations

import logging
from html import escape
from typing import Iterable

import requests

from .settings import SETTINGS

log = logging.getLogger(__name__)


class Telegram:
    def __init__(self) -> None:
        self.enabled = SETTINGS.telegram_enabled and bool(SETTINGS.telegram_bot_token) and bool(SETTINGS.telegram_chat_id)
        self.base = f"https://api.telegram.org/bot{SETTINGS.telegram_bot_token}"

    def send(self, text: str) -> bool:
        if not self.enabled:
            return False
        if not text or not text.strip():
            log.debug("telegram skipped empty message")
            return False
        try:
            r = requests.post(
                f"{self.base}/sendMessage",
                json={
                    "chat_id": SETTINGS.telegram_chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            r.raise_for_status()
            return True
        except Exception as exc:
            log.warning("telegram send failed: %s", exc)
            return False


SEP = "━━━━━━━━━━━━━━━━━━━━"
THIN = "────────────────────"


def _bar(score: float, width: int = 12) -> str:
    filled = max(0, min(width, int(round(score * width))))
    return "▰" * filled + "▱" * (width - filled)


def _pnl_icon(pnl: float) -> str:
    if pnl > 0:
        return "🟢"
    if pnl < 0:
        return "🔴"
    return "⚪"


def _side_label(side: str) -> str:
    return "🟢 <b>LONG</b>" if side.upper() == "BUY" else "🔴 <b>SHORT</b>"


def _mode_label() -> str:
    return "🔴 LIVE FAUCET" if SETTINGS.enable_live_trading and not SETTINGS.dry_run else "🧪 DRY RUN"


def fmt_start(mode: str, symbols: list[str]) -> str:
    sym_text = ", ".join(symbols[:10]) if symbols else "loading"
    more = f" +{len(symbols)-10}" if len(symbols) > 10 else ""
    live = SETTINGS.enable_live_trading and not SETTINGS.dry_run
    lev = f"{SETTINGS.target_leverage}x" if SETTINGS.target_leverage > 0 else "not set"
    return (
        "🤖 <b>BULK AUTO BOT</b>\n"
        f"{SEP}\n"
        f"Status      : <b>{'LIVE FAUCET' if live else 'DRY RUN'}</b>\n"
        f"Engine      : <code>AGGRESSIVE / realized ROI</code>\n"
        f"Symbols     : <code>{escape(sym_text + more)}</code>\n"
        f"Min score   : <code>{SETTINGS.min_signal_score:.2f}</code>\n"
        f"TP / SL     : <code>{SETTINGS.take_profit_pct*100:.2f}% / {SETTINGS.stop_loss_pct*100:.2f}%</code>\n"
        f"Timeout     : <code>{SETTINGS.timeout_seconds}s</code>\n"
        f"Leverage    : <code>{escape(lev)}</code>\n"
        f"Pyramiding  : <code>{'ON' if SETTINGS.allow_pyramiding_same_symbol else 'OFF'}</code>\n"
        f"{THIN}\n"
        "<i>Scanner active. Waiting for high-confluence setups.</i>"
    )


def fmt_discovery(symbols: list[str]) -> str:
    lines = []
    for i, s in enumerate(symbols[:30], 1):
        lines.append(f"{i:02d}. <code>{escape(s)}</code>")
    more = f"\n…and <b>{len(symbols)-30}</b> more" if len(symbols) > 30 else ""
    return (
        "🔎 <b>SYMBOL DISCOVERY</b>\n"
        f"{SEP}\n"
        f"Valid pairs: <b>{len(symbols)}</b>\n"
        f"{THIN}\n"
        + "\n".join(lines)
        + more
    )


def fmt_signal(symbol: str, side: str, score: float, price: float, reason: str) -> str:
    score_pct = score * 100
    notional = SETTINGS.assumed_equity * (
        SETTINGS.extreme_equity_fraction if score >= 0.82 else SETTINGS.strong_equity_fraction if score >= 0.75 else SETTINGS.base_equity_fraction
    )
    return (
        "⚡ <b>ENTRY TRIGGERED</b>\n"
        f"{SEP}\n"
        f"Pair        : <code>{escape(symbol)}</code>\n"
        f"Direction   : {_side_label(side)}\n"
        f"Score       : <code>{score:.3f}</code> {_bar(score)} <b>{score_pct:.0f}%</b>\n"
        f"Entry ref   : <code>{price:.8g}</code>\n"
        f"Est notional: <code>{notional:.2f}</code>\n"
        f"Mode        : <code>AGGRESSIVE</code>\n"
        f"{THIN}\n"
        f"<b>Setup notes</b>\n<code>{escape(reason[:900])}</code>"
    )


def fmt_close(symbol: str, side: str, pnl: float, exit_price: float, reason: str) -> str:
    icon = _pnl_icon(pnl)
    roi = (pnl / max(SETTINGS.assumed_equity, 1e-12)) * 100
    return (
        f"{icon} <b>POSITION CLOSED</b>\n"
        f"{SEP}\n"
        f"Pair        : <code>{escape(symbol)}</code>\n"
        f"Closed side : <b>{escape(side)}</b>\n"
        f"Exit ref    : <code>{exit_price:.8g}</code>\n"
        f"PnL approx  : <b>{pnl:+.6f}</b>\n"
        f"ROI approx  : <b>{roi:+.4f}%</b>\n"
        f"Reason      : <code>{escape(reason)}</code>"
    )


def fmt_error(context: str, error: str) -> str:
    return (
        "⚠️ <b>BOT WARNING</b>\n"
        f"{SEP}\n"
        f"Context: <code>{escape(context)}</code>\n"
        f"Error:\n<code>{escape(error[:900])}</code>"
    )


def fmt_leverage(symbols: list[str], leverage: int, live: bool) -> str:
    sym_text = ", ".join(symbols[:12]) if symbols else "none"
    more = f" +{len(symbols)-12}" if len(symbols) > 12 else ""
    return (
        "🎚️ <b>LEVERAGE CONFIG</b>\n"
        f"{SEP}\n"
        f"Target      : <b>{leverage}x</b>\n"
        f"Apply mode  : <code>{'LIVE API' if live else 'DRY RUN ONLY'}</code>\n"
        f"Symbols     : <code>{escape(sym_text + more)}</code>\n"
        f"{THIN}\n"
        "<i>Leverage must be confirmed by Bulk API before relying on live execution.</i>"
    )


def fmt_scan_summary(
    scanned: int,
    total: int,
    candidates: int,
    entered: int,
    skipped_spread: int,
    failed: int,
    top: Iterable[tuple[str, str, float]],
) -> str:
    top_lines = []
    for rank, (sym, side, score) in enumerate(top, 1):
        side_icon = "🟢" if side.upper() == "BUY" else "🔴"
        top_lines.append(f"{rank}. {side_icon} <code>{escape(sym)}</code> <b>{score:.3f}</b> {_bar(score, 8)}")
    if not top_lines:
        top_lines.append("<i>No candidate above threshold</i>")
    if failed == 0:
        health = "🟢 <b>Clean</b>"
    elif scanned > 0:
        health = "🟡 <b>Partial</b>"
    else:
        health = "🔴 <b>API issue</b>"
    coverage_pct = (scanned / max(total, 1)) * 100
    return (
        "📡 <b>SCAN REPORT</b>\n"
        f"{SEP}\n"
        f"Health      : {health}\n"
        f"Coverage    : <b>{scanned}</b>/<code>{total}</code> symbols <code>({coverage_pct:.0f}%)</code>\n"
        f"Candidates  : <b>{candidates}</b>\n"
        f"Entries     : <b>{entered}</b>\n"
        f"Spread skip : <code>{skipped_spread}</code>\n"
        f"API misses  : <code>{failed}</code>\n"
        f"{THIN}\n"
        "<b>Top ranked</b>\n" + "\n".join(top_lines)
    )
