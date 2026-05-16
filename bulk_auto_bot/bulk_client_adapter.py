from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from typing import Any

from .settings import SETTINGS

log = logging.getLogger(__name__)

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,20}-(USD|USDC|USDT)$")


def is_probable_bulk_symbol(value: str) -> bool:
    """Strict symbol filter for Bulk perp symbols like BTC-USD.

    This intentionally rejects metadata enum values such as LIMIT, MARKET, GTC,
    IOC, TRADING, etc. If Bulk later lists non-USD quote formats, add them here
    explicitly rather than walking every string in exchangeInfo.
    """
    return bool(_SYMBOL_RE.match(str(value).strip().upper()))


@dataclass
class MarketSpec:
    symbol: str
    base_asset: str = ""
    quote_asset: str = ""
    status: str = ""
    price_precision: int | None = None
    size_precision: int | None = None
    tick_size: float | None = None
    lot_size: float | None = None
    min_notional: float | None = None
    max_leverage: float | None = None
    order_types: list[str] | None = None
    time_in_forces: list[str] | None = None
    raw: dict[str, Any] | None = None


@dataclass
class OrderResult:
    ok: bool
    raw: Any
    dry_run: bool = False


class BulkAdapter:
    """Thin wrapper around the official bulk-client SDK.

    Public market data is unsigned. Trading actions are signed by the official
    SDK when initialized with a private key. This adapter keeps all exchange-
    specific parsing and market-rule handling in one place.
    """

    def __init__(self) -> None:
        try:
            from bulk_client import BulkHttpClient  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("bulk-client is not installed. Run: pip install bulk-client") from exc

        if SETTINGS.enable_live_trading and not SETTINGS.dry_run:
            if not SETTINGS.bulk_private_key or "PUT_YOUR" in SETTINGS.bulk_private_key:
                raise RuntimeError("Live faucet execution requires BULK_PRIVATE_KEY in .env")
            self.client = BulkHttpClient(base_url=SETTINGS.bulk_api_url, private_key=SETTINGS.bulk_private_key)
        else:
            self.client = BulkHttpClient(base_url=SETTINGS.bulk_api_url)

        self._exchange_info: Any | None = None
        self._market_specs: dict[str, MarketSpec] | None = None

    def get_exchange_info(self) -> Any:
        """Fetch exchange metadata from SDK, then raw REST fallbacks."""
        if self._exchange_info is not None:
            return self._exchange_info

        errors: list[str] = []
        if hasattr(self.client, "get_exchange_info"):
            try:
                info = self.client.get_exchange_info()
                if info not in (None, [], {}):
                    self._exchange_info = info
                    return info
                errors.append("sdk get_exchange_info returned empty")
            except Exception as exc:
                errors.append(f"sdk get_exchange_info failed: {exc}")

        import requests
        endpoints = ["exchangeInfo", "exchange-info", "markets", "instruments", "meta"]
        for endpoint in endpoints:
            try:
                r = requests.get(f"{SETTINGS.bulk_api_url.rstrip('/')}/{endpoint}", timeout=10)
                if r.status_code == 404:
                    continue
                r.raise_for_status()
                data = r.json()
                if data not in (None, [], {}):
                    log.info("loaded exchange metadata from /%s", endpoint)
                    self._exchange_info = data
                    return data
                errors.append(f"/{endpoint} returned empty")
            except Exception as exc:
                errors.append(f"/{endpoint} failed: {exc}")

        log.warning("exchange metadata empty; tried SDK and raw REST fallbacks: %s", "; ".join(errors[:5]))
        self._exchange_info = []
        return []

    def _parse_market_spec_dict(self, item: dict[str, Any]) -> MarketSpec | None:
        symbol = item.get("symbol") or item.get("c") or item.get("coin") or item.get("marketSymbol")
        if not isinstance(symbol, str):
            return None
        symbol = symbol.strip().upper()
        if not is_probable_bulk_symbol(symbol):
            return None

        status = str(item.get("status", "TRADING")).upper()
        if status and status not in {"TRADING", "ACTIVE", "LISTED"}:
            return None

        def f(*keys: str) -> float | None:
            for key in keys:
                v = item.get(key)
                if v is not None:
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        return None
            return None

        def i(*keys: str) -> int | None:
            val = f(*keys)
            return int(val) if val is not None else None

        base = item.get("baseAsset") or item.get("base") or item.get("base_asset") or symbol.split("-")[0]
        quote = item.get("quoteAsset") or item.get("quote") or item.get("quote_asset") or symbol.split("-")[-1]
        order_types = item.get("orderTypes") if isinstance(item.get("orderTypes"), list) else []
        tifs = item.get("timeInForces") if isinstance(item.get("timeInForces"), list) else []

        return MarketSpec(
            symbol=symbol,
            base_asset=str(base),
            quote_asset=str(quote),
            status=status,
            price_precision=i("pricePrecision", "price_precision"),
            size_precision=i("sizePrecision", "size_precision"),
            tick_size=f("tickSize", "tick_size"),
            lot_size=f("lotSize", "lot_size"),
            min_notional=f("minNotional", "min_notional"),
            max_leverage=f("maxLeverage", "max_leverage"),
            order_types=[str(x).upper() for x in order_types],
            time_in_forces=[str(x).upper() for x in tifs],
            raw=item,
        )

    def _walk_market_specs(self, obj: Any, out: dict[str, MarketSpec]) -> None:
        if isinstance(obj, list):
            for item in obj:
                self._walk_market_specs(item, out)
            return
        if not isinstance(obj, dict):
            return

        spec = self._parse_market_spec_dict(obj)
        if spec:
            out[spec.symbol] = spec
            return

        # Only recurse through likely containers. Do NOT recursively collect every
        # string, because exchangeInfo contains orderTypes/timeInForces enums.
        for key in ("markets", "symbols", "instruments", "data", "universe"):
            child = obj.get(key)
            if isinstance(child, (list, dict)):
                self._walk_market_specs(child, out)

    def get_market_specs(self, force_refresh: bool = False) -> dict[str, MarketSpec]:
        if self._market_specs is not None and not force_refresh:
            return self._market_specs
        info = self.get_exchange_info()
        specs: dict[str, MarketSpec] = {}
        self._walk_market_specs(info, specs)
        self._market_specs = specs
        if specs:
            log.info("loaded %d strict market specs from exchangeInfo", len(specs))
        return specs

    def get_market_spec(self, symbol: str) -> MarketSpec | None:
        return self.get_market_specs().get(symbol.strip().upper())

    def get_symbols(self) -> list[str]:
        specs = self.get_market_specs()
        if specs:
            return list(specs.keys())

        manual = [x.strip().upper() for x in SETTINGS.manual_symbols.split(",") if x.strip()]
        manual = [x for x in manual if is_probable_bulk_symbol(x)]
        if manual:
            log.warning("exchangeInfo returned no strict market specs; using MANUAL_SYMBOLS=%s", manual)
            return manual

        sample = self._exchange_info[:3] if isinstance(self._exchange_info, list) else repr(self._exchange_info)[:500]
        raise RuntimeError(
            "Could not load valid Bulk market symbols from exchange metadata. "
            "Use --symbols BTC-USD,ETH-USD or set MANUAL_SYMBOLS=BTC-USD,ETH-USD. "
            f"exchangeInfo sample={sample}"
        )

    def get_ticker(self, symbol: str) -> dict[str, Any]:
        if not is_probable_bulk_symbol(symbol):
            raise ValueError(f"Invalid Bulk symbol rejected before API call: {symbol}")
        return self.client.get_ticker(symbol)

    def get_orderbook(self, symbol: str, nlevels: int = 5) -> dict[str, Any]:
        if not is_probable_bulk_symbol(symbol):
            raise ValueError(f"Invalid Bulk symbol rejected before API call: {symbol}")
        try:
            return self.client.get_orderbook(symbol, nlevels=nlevels)
        except Exception as exc:
            log.debug("SDK get_orderbook failed for %s, using raw REST fallback: %r", symbol, exc)

        import requests
        r = requests.get(
            f"{SETTINGS.bulk_api_url.rstrip('/')}/l2book",
            params={"type": "l2book", "coin": symbol, "nlevels": nlevels},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict):
            raise RuntimeError(f"Unexpected l2book response for {symbol}: {type(data)}")
        return data

    def get_candles(self, symbol: str, interval: str = "1m", limit: int = 100) -> list[dict[str, Any]]:
        if not is_probable_bulk_symbol(symbol):
            raise ValueError(f"Invalid Bulk symbol rejected before API call: {symbol}")
        if hasattr(self.client, "get_klines"):
            attempts = [
                lambda: self.client.get_klines(symbol, interval, limit),
                lambda: self.client.get_klines(symbol, interval=interval, limit=limit),
                lambda: self.client.get_klines(symbol=symbol, interval=interval, limit=limit),
            ]
            last_error: Exception | None = None
            for attempt in attempts:
                try:
                    data = attempt()
                    if isinstance(data, list):
                        return data
                    if isinstance(data, dict):
                        inner = data.get("klines") or data.get("candles") or data.get("data") or []
                        return inner if isinstance(inner, list) else []
                    return []
                except TypeError as exc:
                    last_error = exc
                    continue
                except Exception as exc:
                    last_error = exc
                    break
            raise RuntimeError(f"get_klines failed for {symbol}: {last_error!r}")
        raise RuntimeError(f"No candle/klines method worked for {symbol}")

    def cap_leverage(self, symbol: str, requested: int | float) -> float:
        try:
            requested_f = float(requested)
        except Exception:
            requested_f = 1.0
        requested_f = max(1.0, min(50.0, requested_f))
        spec = self.get_market_spec(symbol)
        if spec and spec.max_leverage:
            return max(1.0, min(requested_f, float(spec.max_leverage)))
        return requested_f

    def tick_size(self, symbol: str) -> float | None:
        spec = self.get_market_spec(symbol)
        return spec.tick_size if spec else None

    def lot_size(self, symbol: str) -> float | None:
        spec = self.get_market_spec(symbol)
        return spec.lot_size if spec else None

    def min_notional(self, symbol: str) -> float | None:
        spec = self.get_market_spec(symbol)
        return spec.min_notional if spec else None

    @staticmethod
    def _decimals_from_step(step: float) -> int:
        if step <= 0:
            return 8
        text = f"{step:.16f}".rstrip("0")
        return len(text.split(".")[1]) if "." in text else 0

    def round_price(self, symbol: str, price: float, side: str | None = None) -> float:
        tick = self.tick_size(symbol)
        if not tick or tick <= 0:
            return float(price)
        units = price / tick
        if side and side.upper() == "BUY":
            rounded = math.ceil(units) * tick
        elif side and side.upper() == "SELL":
            rounded = math.floor(units) * tick
        else:
            rounded = round(units) * tick
        return round(rounded, self._decimals_from_step(tick))

    def round_size(self, symbol: str, size: float, min_price: float | None = None) -> float:
        lot = self.lot_size(symbol)
        min_notional = self.min_notional(symbol)
        desired = max(float(size), 0.0)
        if min_price and min_notional and min_notional > 0:
            min_size = min_notional / max(min_price, 1e-12)
            if desired < min_size:
                if SETTINGS.allow_min_notional_upsize:
                    desired = min_size
                else:
                    return 0.0
        if lot and lot > 0:
            units = math.ceil(desired / lot) if SETTINGS.allow_min_notional_upsize else math.floor(desired / lot)
            desired = units * lot
            return round(desired, self._decimals_from_step(lot))
        spec = self.get_market_spec(symbol)
        if spec and spec.size_precision is not None:
            return round(desired, int(spec.size_precision))
        return desired

    def inspect_sdk(self) -> dict[str, str]:
        """Return readable SDK signatures for debugging version mismatches."""
        import inspect
        out: dict[str, str] = {}
        for name in ("update_leverage", "place_orders", "get_klines", "get_orderbook", "get_ticker"):
            fn = getattr(self.client, name, None)
            if fn is None:
                out[name] = "MISSING"
                continue
            try:
                out[name] = str(inspect.signature(fn))
            except Exception as exc:
                out[name] = f"signature unavailable: {exc!r}"
        try:
            from bulk_api.messages import LimitOrder  # type: ignore
            out["LimitOrder"] = str(inspect.signature(LimitOrder))
        except Exception as exc:
            out["LimitOrder"] = f"unavailable: {exc!r}"
        return out

    def update_leverage(self, symbol: str, leverage: int | float) -> OrderResult:
        """Best-effort leverage update.

        Bulk docs define leverage as updateUserSettings.m = {symbol: leverage}
        via the unified signed /order transaction. Different bulk-client builds
        expose different helper signatures, so this function tries the safest
        SDK shapes first. It deliberately avoids pretending success in LIVE mode.
        """
        if leverage <= 0:
            return OrderResult(ok=True, raw={"skipped": "TARGET_LEVERAGE <= 0"}, dry_run=SETTINGS.dry_run)
        if not is_probable_bulk_symbol(symbol):
            raise ValueError(f"Invalid Bulk symbol rejected before leverage update: {symbol}")

        capped = self.cap_leverage(symbol, leverage)
        spec = self.get_market_spec(symbol)
        if capped < float(leverage):
            log.warning(
                "leverage capped for %s: requested=%sx market_cap=%sx applied=%sx",
                symbol, leverage, spec.max_leverage if spec else "unknown", capped,
            )
        if SETTINGS.dry_run or not SETTINGS.enable_live_trading:
            log.info(
                "DRY_RUN update_leverage %s requested=%sx applied=%sx maxLev=%s isolated=%s",
                symbol, leverage, capped, spec.max_leverage if spec else None, SETTINGS.use_isolated,
            )
            return OrderResult(ok=True, raw={"dry_run": True, "symbol": symbol, "requested": leverage, "applied": capped}, dry_run=True)
        if not hasattr(self.client, "update_leverage"):
            raise RuntimeError("Installed bulk-client has no update_leverage method; set leverage in Bulk UI or update SDK.")

        # Your installed SDK signature is:
        #   update_leverage(leverage_settings: List[tuple]) -> Dict
        # The first attempt below is therefore the canonical path for this bot.
        # Other attempts are kept only for compatibility with older/newer SDK builds.
        attempts: list[tuple[str, Any]] = [
            ("list_tuple_symbol_leverage", lambda: self.client.update_leverage([(symbol, float(capped))])),
            ("list_tuple_symbol_leverage_iso", lambda: self.client.update_leverage([(symbol, float(capped), SETTINGS.use_isolated)])),
            ("list_tuple_string_leverage", lambda: self.client.update_leverage([(str(symbol), str(capped))])),
            ("map_only", lambda: self.client.update_leverage({symbol: float(capped)})),
            ("pos_symbol_leverage", lambda: self.client.update_leverage(symbol, capped)),
            ("pos_symbol_leverage_isolated", lambda: self.client.update_leverage(symbol, capped, SETTINGS.use_isolated)),
            ("kw_leverages", lambda: self.client.update_leverage(leverages={symbol: float(capped)})),
            ("kw_m", lambda: self.client.update_leverage(m={symbol: float(capped)})),
            ("kw_market", lambda: self.client.update_leverage(market=symbol, leverage=capped)),
            ("kw_coin", lambda: self.client.update_leverage(coin=symbol, leverage=capped)),
            ("kw_symbol", lambda: self.client.update_leverage(symbol=symbol, leverage=capped)),
        ]
        errors: list[str] = []
        for label, attempt in attempts:
            try:
                resp = attempt()
                log.info("updated leverage %s to %sx via %s", symbol, capped, label)
                return OrderResult(ok=True, raw=resp)
            except TypeError as exc:
                errors.append(f"{label}: {exc}")
                continue
            except Exception as exc:
                errors.append(f"{label}: {exc}")
                # keep trying other SDK helper shapes; some versions raise HTTP
                # errors for one helper shape but accept another.
                continue

        sig = self.inspect_sdk().get("update_leverage", "unknown")
        raise RuntimeError(
            "update_leverage failed for "
            f"{symbol}. SDK signature={sig}. Tried: " + " | ".join(errors[:8])
        )

    def cancel_all(self, symbols: list[str] | None = None) -> OrderResult:
        symbols = [s for s in (symbols or []) if is_probable_bulk_symbol(s)]
        if SETTINGS.dry_run or not SETTINGS.enable_live_trading:
            log.info("DRY_RUN cancel_all symbols=%s", symbols)
            return OrderResult(ok=True, raw={"dry_run": True, "symbols": symbols}, dry_run=True)
        from bulk_api.messages import CancelAll  # type: ignore
        resp = self.client.place_orders([CancelAll(symbols=symbols)])
        return OrderResult(ok=True, raw=resp)

    def place_ioc_limit(self, symbol: str, side: str, price: float, size: float, reduce_only: bool = False) -> OrderResult:
        """Use IOC limit as a marketable order with bounded slippage."""
        if not is_probable_bulk_symbol(symbol):
            raise ValueError(f"Invalid Bulk symbol rejected before order: {symbol}")
        rounded_price = self.round_price(symbol, float(price), side=side)
        rounded_size = self.round_size(symbol, float(size), min_price=rounded_price)
        if rounded_size <= 0:
            raise RuntimeError(f"Order size below lot/minNotional for {symbol}: raw_size={size}, price={rounded_price}")
        if SETTINGS.dry_run or not SETTINGS.enable_live_trading:
            spec = self.get_market_spec(symbol)
            log.info(
                "DRY_RUN order %s %s size=%s price=%s reduce_only=%s lot=%s minNotional=%s maxLev=%s",
                side, symbol, rounded_size, rounded_price, reduce_only,
                spec.lot_size if spec else None, spec.min_notional if spec else None, spec.max_leverage if spec else None,
            )
            return OrderResult(ok=True, raw={"dry_run": True, "size": rounded_size, "price": rounded_price}, dry_run=True)

        from bulk_api.common import Side, TimeInForce  # type: ignore
        from bulk_api.messages import LimitOrder  # type: ignore
        side_obj = Side.BUY if side.upper() == "BUY" else Side.SELL
        try:
            order = LimitOrder(
                symbol=symbol,
                side=side_obj,
                price=float(rounded_price),
                size=float(rounded_size),
                time_in_force=TimeInForce.IOC,
                reduce_only=bool(reduce_only),
                iso=bool(SETTINGS.use_isolated),
            )
        except TypeError:
            if reduce_only:
                raise RuntimeError("Installed bulk-client LimitOrder does not expose reduce_only; upgrade SDK or implement raw signed action.")
            order = LimitOrder(symbol=symbol, side=side_obj, price=float(rounded_price), size=float(rounded_size), time_in_force=TimeInForce.IOC)
        resp = self.client.place_orders([order])
        return OrderResult(ok=True, raw=resp)
