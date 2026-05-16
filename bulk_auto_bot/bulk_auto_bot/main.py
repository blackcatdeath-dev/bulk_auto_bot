from __future__ import annotations

import argparse
import logging
import time
from typing import Any

import yaml

from . import db
from .bulk_client_adapter import BulkAdapter, is_probable_bulk_symbol
from .discovery import discover_symbols, save_cached_symbols, load_cached_symbols, static_fallback_symbols
from .execution import Executor, now_s
from .logging_setup import setup_logging
from .market import anchor_candles_to_live_price, parse_book, parse_candles, ticker_price
from .settings import SETTINGS
from .strategy import build_signal, diagnose_signal
from .telegram import Telegram, fmt_close, fmt_discovery, fmt_scan_summary, fmt_signal, fmt_start, fmt_leverage

log = logging.getLogger(__name__)


def load_config() -> dict[str, Any]:
    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def symbol_allowed(symbol: str, config: dict[str, Any]) -> bool:
    sconf = config.get("symbols", {}) or {}
    whitelist = sconf.get("whitelist") or []
    blacklist = sconf.get("blacklist") or []
    if whitelist and symbol not in whitelist:
        return False
    return symbol not in blacklist


def resolve_symbols(adapter: BulkAdapter, args: argparse.Namespace, config: dict[str, Any]) -> list[str]:
    if args.symbols:
        raw_symbols = [x.strip().upper() for x in args.symbols.split(",") if x.strip()]
        symbols = [x for x in raw_symbols if is_probable_bulk_symbol(x)]
        rejected = [x for x in raw_symbols if not is_probable_bulk_symbol(x)]
        if rejected:
            log.warning("rejected invalid --symbols entries: %s", rejected)
        log.info("using symbols from --symbols: %s", symbols)
        save_cached_symbols(symbols)
        return symbols

    if SETTINGS.manual_symbols:
        raw_symbols = [x.strip().upper() for x in SETTINGS.manual_symbols.split(",") if x.strip()]
        symbols = [x for x in raw_symbols if is_probable_bulk_symbol(x)]
        rejected = [x for x in raw_symbols if not is_probable_bulk_symbol(x)]
        if rejected:
            log.warning("rejected invalid MANUAL_SYMBOLS entries: %s", rejected)
        log.info("using symbols from MANUAL_SYMBOLS: %s", symbols)
        save_cached_symbols(symbols)
        return symbols

    symbols = discover_symbols(adapter, config=config, force_refresh=args.discover_symbols)
    if symbols:
        return symbols

    cached = load_cached_symbols()
    if cached:
        log.warning("resolve symbols: discovery empty; using cached symbols: %s", cached)
        return cached

    fallback = static_fallback_symbols()
    if fallback:
        log.warning("resolve symbols: discovery empty; using static fallback symbols: %s", fallback)
        save_cached_symbols(fallback)
        return fallback

    raise RuntimeError(
        "No valid symbols found. Set MANUAL_SYMBOLS=BTC-USD,ETH-USD,SOL-USD,XRP-USD,DOGE-USD,BNB-USD,SUI-USD "
        "in .env or run python -m bulk_auto_bot.main --discover-symbols --debug-scores"
    )


def scan_once(
    adapter: BulkAdapter,
    executor: Executor,
    tg: Telegram,
    symbols: list[str],
    config: dict[str, Any],
    debug_scores: bool = False,
    scan_index: int = 0,
) -> None:
    candidates = []
    price_by_symbol: dict[str, float] = {}
    scanned = 0
    skipped_spread = 0
    failed = 0

    for symbol in symbols:
        if not symbol_allowed(symbol, config):
            continue
        try:
            ticker = adapter.get_ticker(symbol)
            price = ticker_price(ticker)
            if price <= 0:
                failed += 1
                continue
            book = adapter.get_orderbook(symbol, nlevels=5)
            bid, ask, bid_depth, ask_depth = parse_book(book)
            if bid <= 0 or ask <= 0 or ask <= bid:
                failed += 1
                continue
            mid = (bid + ask) / 2
            spread_pct = (ask - bid) / mid
            if spread_pct > SETTINGS.max_spread_pct:
                skipped_spread += 1
                if debug_scores:
                    log.info("skip %s spread %.4f > max %.4f", symbol, spread_pct, SETTINGS.max_spread_pct)
                continue
            raw_candles = adapter.get_candles(symbol, interval="1m", limit=max(SETTINGS.min_candles + 5, 80))
            candles = anchor_candles_to_live_price(parse_candles(raw_candles), price)
            if len(candles) < SETTINGS.min_candles:
                failed += 1
                if debug_scores:
                    log.info("skip %s candles %d < min %d", symbol, len(candles), SETTINGS.min_candles)
                continue
            price_by_symbol[symbol] = price
            scanned += 1
            diag = diagnose_signal(symbol, price, spread_pct, candles)
            if debug_scores:
                log.info(
                    "score %s side=%s best=%.3f bull=%.3f bear=%.3f candles=%d spread=%.4f reason=%s",
                    symbol, diag.best_side, diag.best_score, diag.bull_score, diag.bear_score,
                    diag.candle_count, spread_pct, diag.reason,
                )
            signal = build_signal(symbol, price, spread_pct, candles)
            if signal:
                candidates.append((signal.score, spread_pct, signal))
        except Exception as exc:
            failed += 1
            log.warning("scan fail %s: %s", symbol, exc) if debug_scores else log.debug("scan fail %s: %s", symbol, exc)
            continue

    closed = executor.manage_exits(price_by_symbol)
    for symbol, side, pnl, price, reason in closed:
        tg.send(fmt_close(symbol, side, pnl, price, reason))

    candidates.sort(key=lambda x: x[0], reverse=True)
    entered = 0
    for _, spread_pct, signal in candidates[: SETTINGS.top_n_symbols]:
        db.insert_signal(now_s(), signal.symbol, signal.side, signal.score, signal.price, signal.reason)
        accepted = executor.maybe_enter(signal, spread_pct)
        if accepted:
            entered += 1
            tg.send(fmt_signal(signal.symbol, signal.side, signal.score, signal.price, signal.reason))

    if candidates:
        top = ", ".join([f"{s.symbol}:{s.side}:{s.score:.2f}" for _, _, s in candidates[:5]])
        log.info("top signals: %s", top)
    else:
        log.info("no signal this scan")

    if SETTINGS.telegram_scan_summary and scan_index % max(1, SETTINGS.telegram_summary_every_scans) == 0:
        top_for_msg = [(s.symbol, s.side, s.score) for _, _, s in candidates[:5]]
        tg.send(fmt_scan_summary(scanned, len(symbols), len(candidates), entered, skipped_spread, failed, top_for_msg))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="run one scan and exit")
    parser.add_argument("--symbols", default="", help="comma-separated symbols override")
    parser.add_argument("--debug-scores", action="store_true", help="print per-symbol scores even when no signal")
    parser.add_argument("--discover-symbols", action="store_true", help="probe candidate pairs and write data/symbols_cache.json")
    parser.add_argument("--telegram-test", action="store_true", help="send a Telegram test card and exit")
    parser.add_argument("--leverage-test", action="store_true", help="best-effort update leverage test for resolved symbols")
    parser.add_argument("--dump-market-specs", action="store_true", help="print strict exchangeInfo specs: symbol, lotSize, minNotional, maxLeverage")
    parser.add_argument("--inspect-bulk-sdk", action="store_true", help="print installed bulk-client helper signatures and exit")
    args = parser.parse_args()

    setup_logging()
    config = load_config()

    if SETTINGS.enable_live_trading and not SETTINGS.dry_run:
        log.warning("LIVE FAUCET EXECUTION ENABLED. Do not use this with real funds.")
    else:
        log.info("DRY RUN mode: no live orders will be sent")

    adapter = BulkAdapter()
    executor = Executor(adapter)
    tg = Telegram()

    if args.inspect_bulk_sdk:
        for name, sig in adapter.inspect_sdk().items():
            log.info("sdk %s %s", name, sig)
        return

    if args.telegram_test:
        tg.send(fmt_start(mode="LIVE" if SETTINGS.enable_live_trading and not SETTINGS.dry_run else "DRY RUN", symbols=[]))
        tg.send(fmt_signal("ETH-USD", "BUY", 0.72, 2225.12, "demo: demand zone + RSI recovery + strong bullish close"))
        tg.send(fmt_close("ETH-USD", "BUY", 0.123456, 2229.42, "demo_take_profit"))
        tg.send(fmt_leverage(["BTC-USD", "ETH-USD"], SETTINGS.target_leverage or 5, SETTINGS.enable_live_trading and not SETTINGS.dry_run))
        log.info("telegram test sent if TELEGRAM_ENABLED=true and credentials are valid")
        return

    symbols = resolve_symbols(adapter, args, config)
    specs = adapter.get_market_specs()
    if args.dump_market_specs:
        for sym in symbols:
            spec = specs.get(sym)
            if spec:
                log.info("spec %s tick=%s lot=%s minNotional=%s maxLev=%s orderTypes=%s tif=%s", sym, spec.tick_size, spec.lot_size, spec.min_notional, spec.max_leverage, spec.order_types, spec.time_in_forces)
            else:
                log.info("spec %s unavailable; will use runtime fallback", sym)
        return
    log.info("loaded %d symbols", len(symbols))
    if args.leverage_test:
        lev = SETTINGS.target_leverage
        if lev <= 0:
            raise RuntimeError("Set TARGET_LEVERAGE=5 or another positive number in .env before --leverage-test")
        ok_syms: list[str] = []
        failed_syms: list[str] = []
        for sym in symbols:
            try:
                adapter.update_leverage(sym, lev)
                ok_syms.append(sym)
            except Exception as exc:
                failed_syms.append(sym)
                log.error("leverage test failed for %s: %s", sym, exc)
        tg.send(fmt_leverage(ok_syms, lev, SETTINGS.enable_live_trading and not SETTINGS.dry_run))
        if failed_syms:
            log.warning("leverage test partial: ok=%d failed=%d failed_symbols=%s", len(ok_syms), len(failed_syms), failed_syms)
        else:
            log.info("leverage test completed for %d symbols", len(ok_syms))
        return
    tg.send(fmt_start(mode="LIVE" if SETTINGS.enable_live_trading and not SETTINGS.dry_run else "DRY RUN", symbols=symbols))
    if args.discover_symbols:
        tg.send(fmt_discovery(symbols))

    scan_index = 0
    while True:
        scan_index += 1
        started = time.time()
        scan_once(adapter, executor, tg, symbols, config, debug_scores=args.debug_scores, scan_index=scan_index)
        if args.once or args.discover_symbols:
            break
        elapsed = time.time() - started
        time.sleep(max(1, SETTINGS.scan_interval_seconds - elapsed))


if __name__ == "__main__":
    main()
