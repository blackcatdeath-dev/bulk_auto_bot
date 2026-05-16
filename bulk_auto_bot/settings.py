from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    bulk_api_url: str = os.getenv("BULK_API_URL", "https://exchange-api.bulk.trade/api/v1")
    bulk_private_key: str = os.getenv("BULK_PRIVATE_KEY", "")
    bulk_account: str = os.getenv("BULK_ACCOUNT", "")
    bulk_signer: str = os.getenv("BULK_SIGNER", "")
    manual_symbols: str = os.getenv("MANUAL_SYMBOLS", "")
    auto_discover_symbols: bool = _bool("AUTO_DISCOVER_SYMBOLS", True)
    symbol_cache_path: str = os.getenv("SYMBOL_CACHE_PATH", "data/symbols_cache.json")
    discovery_candidates: str = os.getenv("DISCOVERY_CANDIDATES", "")
    discovery_timeout_seconds: int = _int("DISCOVERY_TIMEOUT_SECONDS", 8)
    refresh_symbols_each_start: bool = _bool("REFRESH_SYMBOLS_EACH_START", False)
    static_fallback_symbols: str = os.getenv("STATIC_FALLBACK_SYMBOLS", "BTC-USD,ETH-USD,SOL-USD,XRP-USD,DOGE-USD,BNB-USD,SUI-USD")
    use_static_fallback_symbols: bool = _bool("USE_STATIC_FALLBACK_SYMBOLS", True)

    enable_live_trading: bool = _bool("ENABLE_LIVE_TRADING", False)
    dry_run: bool = _bool("DRY_RUN", True)
    use_isolated: bool = _bool("USE_ISOLATED", False)
    target_leverage: int = _int("TARGET_LEVERAGE", 0)
    apply_leverage_on_start: bool = _bool("APPLY_LEVERAGE_ON_START", False)
    use_leverage_in_sizing: bool = _bool("USE_LEVERAGE_IN_SIZING", True)
    allow_min_notional_upsize: bool = _bool("ALLOW_MIN_NOTIONAL_UPSIZE", True)

    telegram_enabled: bool = _bool("TELEGRAM_ENABLED", False)
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    telegram_allowed_user_ids: str = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "")
    telegram_pretty: bool = _bool("TELEGRAM_PRETTY", True)
    telegram_scan_summary: bool = _bool("TELEGRAM_SCAN_SUMMARY", False)
    telegram_summary_every_scans: int = _int("TELEGRAM_SUMMARY_EVERY_SCANS", 20)

    scan_interval_seconds: int = _int("SCAN_INTERVAL_SECONDS", 20)
    top_n_symbols: int = _int("TOP_N_SYMBOLS", 5)
    min_signal_score: float = _float("MIN_SIGNAL_SCORE", 0.68)

    base_equity_fraction: float = _float("BASE_EQUITY_FRACTION", 0.15)
    strong_equity_fraction: float = _float("STRONG_EQUITY_FRACTION", 0.25)
    extreme_equity_fraction: float = _float("EXTREME_EQUITY_FRACTION", 0.40)
    assumed_equity: float = _float("ASSUMED_EQUITY", 100.0)

    take_profit_pct: float = _float("TAKE_PROFIT_PCT", 0.0035)
    stop_loss_pct: float = _float("STOP_LOSS_PCT", 0.0025)
    timeout_seconds: int = _int("TIMEOUT_SECONDS", 180)

    max_spread_pct: float = _float("MAX_SPREAD_PCT", 0.002)
    min_candles: int = _int("MIN_CANDLES", 60)
    order_cooldown_seconds: int = _int("ORDER_COOLDOWN_SECONDS", 15)
    stale_order_cancel_seconds: int = _int("STALE_ORDER_CANCEL_SECONDS", 30)
    allow_pyramiding_same_symbol: bool = _bool("ALLOW_PYRAMIDING_SAME_SYMBOL", False)
    close_on_signal_reversal: bool = _bool("CLOSE_ON_SIGNAL_REVERSAL", True)



SETTINGS = Settings()
