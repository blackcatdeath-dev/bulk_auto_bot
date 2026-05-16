from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable

from .bulk_client_adapter import is_probable_bulk_symbol
from .market import parse_book, ticker_price
from .settings import SETTINGS

log = logging.getLogger(__name__)

# Common USD perp/crypto symbols. Bulk currently accepts formats like BTC-USD and ETH-USD.
DEFAULT_CANDIDATES = [
    "BTC-USD", "ETH-USD", "SOL-USD", "HYPE-USD", "XRP-USD", "DOGE-USD", "BNB-USD",
    "SUI-USD", "ADA-USD", "AVAX-USD", "LINK-USD", "LTC-USD", "BCH-USD", "TRX-USD",
    "TON-USD", "DOT-USD", "NEAR-USD", "APT-USD", "ARB-USD", "OP-USD", "MATIC-USD",
    "POL-USD", "AAVE-USD", "UNI-USD", "ENA-USD", "WIF-USD", "PEPE-USD", "BONK-USD",
    "FET-USD", "INJ-USD", "TIA-USD", "SEI-USD", "JUP-USD", "PYTH-USD", "ONDO-USD",
    "WLD-USD", "TAO-USD", "ORDI-USD", "FIL-USD", "ETC-USD", "ATOM-USD", "RUNE-USD",
    "CRV-USD", "MKR-USD", "LDO-USD", "PENDLE-USD", "JTO-USD", "JASMY-USD", "MEME-USD",
]


def _dedupe(items: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        s = item.strip().upper()
        if not s or s in seen or not is_probable_bulk_symbol(s):
            continue
        seen.add(s)
        out.append(s)
    return out


def candidate_symbols() -> list[str]:
    raw = SETTINGS.discovery_candidates.strip()
    if raw:
        return _dedupe(raw.split(","))
    return _dedupe(DEFAULT_CANDIDATES)


def load_cached_symbols() -> list[str]:
    path = Path(SETTINGS.symbol_cache_path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        symbols = data.get("symbols", []) if isinstance(data, dict) else data
        if isinstance(symbols, list):
            return _dedupe([str(x) for x in symbols])
    except Exception as exc:
        log.warning("could not read symbol cache %s: %s", path, exc)
    return []


def save_cached_symbols(symbols: list[str]) -> None:
    path = Path(SETTINGS.symbol_cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"symbols": _dedupe(symbols)}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def validate_symbol(adapter, symbol: str, require_orderbook: bool = True) -> bool:
    try:
        ticker = adapter.get_ticker(symbol)
        price = ticker_price(ticker)
        if price <= 0:
            return False
        if require_orderbook:
            book = adapter.get_orderbook(symbol, nlevels=1)
            bid, ask, *_ = parse_book(book)
            if bid <= 0 or ask <= 0 or ask <= bid:
                return False
        return True
    except Exception as exc:
        log.debug("symbol rejected %s: %s", symbol, exc)
        return False


def static_fallback_symbols() -> list[str]:
    raw = SETTINGS.static_fallback_symbols.strip()
    return _dedupe(raw.split(",")) if raw else []


def discover_symbols(adapter, config: dict | None = None, force_refresh: bool = False) -> list[str]:
    """Load symbols with strict market-symbol validation.

    exchangeInfo includes enum arrays like orderTypes/timeInForces. Those must never be treated as symbols.
    The adapter now returns only strict market specs such as BTC-USD. If metadata is down, use cache/probing/static fallback.
    """
    # 1. Try official metadata first.
    try:
        meta_symbols = adapter.get_symbols()
        # Avoid returning manual fallback from adapter as if metadata worked when manual is empty.
        if meta_symbols:
            save_cached_symbols(meta_symbols)
            log.info("symbol discovery: loaded %d symbols from exchange metadata/manual adapter", len(meta_symbols))
            return meta_symbols
    except Exception as exc:
        log.warning("symbol discovery: metadata failed: %s", exc)

    # 2. Use cache unless refresh requested.
    if not force_refresh and not SETTINGS.refresh_symbols_each_start:
        cached = load_cached_symbols()
        if cached:
            log.info("symbol discovery: loaded %d cached symbols from %s", len(cached), SETTINGS.symbol_cache_path)
            return cached

    # 3. Active probing.
    if not SETTINGS.auto_discover_symbols:
        return []
    valid: list[str] = []
    candidates = candidate_symbols()
    log.info("symbol discovery: probing %d candidate symbols", len(candidates))
    for sym in candidates:
        if validate_symbol(adapter, sym, require_orderbook=True):
            valid.append(sym)
            log.info("symbol discovery: valid %s", sym)
    valid = _dedupe(valid)
    if valid:
        save_cached_symbols(valid)
        log.info("symbol discovery: saved %d valid symbols to %s", len(valid), SETTINGS.symbol_cache_path)
        return valid

    log.warning("symbol discovery: no valid symbols found from candidate list")

    # 4. If active probing failed because the API was temporarily unstable, fall back to cache
    # even when force_refresh was requested. This keeps the bot bootable during Bulk 502s.
    cached = load_cached_symbols()
    if cached:
        log.warning("symbol discovery: probing failed; using stale cached symbols from %s: %s", SETTINGS.symbol_cache_path, cached)
        return cached

    # 5. Final static fallback. The scan loop still validates market data per symbol, so invalid
    # or temporarily-down symbols will be skipped without crashing the whole bot.
    if SETTINGS.use_static_fallback_symbols:
        fallback = static_fallback_symbols()
        if fallback:
            save_cached_symbols(fallback)
            log.warning("symbol discovery: using STATIC_FALLBACK_SYMBOLS because metadata/probing failed: %s", fallback)
            return fallback

    return []
