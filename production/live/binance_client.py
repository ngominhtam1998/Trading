"""Binance USDT-M Futures REST client with robust error handling.

Design goals:
- Never crash the bot on a transient error: retry with exponential backoff.
- Resync server time on -1021 (timestamp) errors.
- Respect rate limits: back off hard on 429/418.
- Surface permanent errors (bad params, insufficient funds) as exceptions the
  caller can handle, but transient/network errors are retried internally.

All order placement uses deterministic newClientOrderId where possible so that
a retry after an uncertain failure does not create duplicate orders.
"""
import time
import hmac
import hashlib
import logging
import urllib.parse
import requests
import urllib3

from . import config

urllib3.disable_warnings()
log = logging.getLogger("binance")


class BinanceError(Exception):
    """Permanent API error (won't be retried)."""
    def __init__(self, code, msg):
        self.code = code
        self.msg = msg
        super().__init__(f"[{code}] {msg}")


# Binance error codes that are PERMANENT (do not retry; caller must handle)
PERMANENT_CODES = {
    -1100, -1101, -1102, -1104, -1111,  # bad params / precision
    -1116, -1117, -1121,                # invalid order type / side / symbol
    -2010,                              # NEW_ORDER_REJECTED (e.g. would trigger immediately)
    -2019,                              # margin insufficient
    -2021,                              # order would immediately trigger
    -4003, -4164,                      # qty/notional too small
    -4131,                             # PERCENT_PRICE filter
}
# Codes that mean "the thing isn't there" -- treat as success-ish for idempotency
NOT_FOUND_CODES = {-2011, -2013}  # cancel/query order does not exist


class BinanceClient:
    def __init__(self):
        self.base = config.base_url()
        self.key, self.secret = config.get_api_keys()
        self.session = requests.Session()
        self.session.headers.update({"X-MBX-APIKEY": self.key})
        self.time_offset = 0  # serverTime - localTime (ms)
        self._sync_time()

    # ---------------- low level ----------------
    def _sync_time(self):
        try:
            r = self.session.get(f"{self.base}/fapi/v1/time", timeout=10, verify=False)
            server = r.json()["serverTime"]
            self.time_offset = server - int(time.time() * 1000)
            log.info(f"Time synced, offset={self.time_offset}ms")
        except Exception as e:
            log.warning(f"Time sync failed: {e}")
            self.time_offset = 0

    def _ts(self):
        return int(time.time() * 1000) + self.time_offset

    def _sign(self, params):
        query = urllib.parse.urlencode(params)
        sig = hmac.new(self.secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        return query + "&signature=" + sig

    def _request(self, method, path, params=None, signed=False, retries=None):
        """Core request with retry/backoff. Returns parsed JSON or raises BinanceError."""
        if retries is None:
            retries = config.MAX_RETRIES
        params = dict(params or {})
        attempt = 0
        while True:
            attempt += 1
            try:
                if signed:
                    params["timestamp"] = self._ts()
                    params["recvWindow"] = config.RECV_WINDOW
                    url = f"{self.base}{path}?{self._sign(params)}"
                    r = self.session.request(method, url, timeout=15, verify=False)
                else:
                    url = f"{self.base}{path}"
                    r = self.session.request(method, url, params=params, timeout=15, verify=False)

                # Rate limit / ban
                if r.status_code in (429, 418):
                    wait = int(r.headers.get("Retry-After", "5"))
                    log.warning(f"Rate limited ({r.status_code}), sleeping {wait}s")
                    time.sleep(wait + 1)
                    continue

                data = r.json()

                # Binance error envelope
                if isinstance(data, dict) and "code" in data and "msg" in data and r.status_code != 200:
                    code = data["code"]
                    msg = data["msg"]
                    if code == -1021:  # timestamp outside recvWindow -> resync and retry
                        log.warning("Timestamp error -1021, resyncing time")
                        self._sync_time()
                        if attempt <= retries:
                            continue
                    if code in NOT_FOUND_CODES:
                        raise BinanceError(code, msg)  # caller decides (often benign)
                    if code in PERMANENT_CODES:
                        raise BinanceError(code, msg)  # permanent, don't retry
                    # unknown server error -> retry a few times
                    log.warning(f"API error [{code}] {msg} (attempt {attempt}/{retries})")
                    if attempt <= retries:
                        time.sleep(config.RETRY_BACKOFF_BASE ** attempt)
                        continue
                    raise BinanceError(code, msg)

                return data

            except (requests.exceptions.RequestException, ValueError) as e:
                # network error, timeout, JSON decode error -> retry
                log.warning(f"Network/parse error: {e} (attempt {attempt}/{retries})")
                if attempt <= retries:
                    time.sleep(config.RETRY_BACKOFF_BASE ** attempt)
                    continue
                raise BinanceError(-1, f"Network failure after {retries} retries: {e}")

    # ---------------- public market data ----------------
    def exchange_info(self):
        return self._request("GET", "/fapi/v1/exchangeInfo")

    def klines(self, symbol, interval, limit=260):
        return self._request("GET", "/fapi/v1/klines",
                             {"symbol": symbol, "interval": interval, "limit": limit})

    def ticker_24h(self):
        """All symbols 24h stats (for volume ranking)."""
        return self._request("GET", "/fapi/v1/ticker/24hr")

    def mark_price(self, symbol):
        d = self._request("GET", "/fapi/v1/premiumIndex", {"symbol": symbol})
        return float(d["markPrice"])

    # ---------------- account / positions ----------------
    def balance(self):
        """Returns dict asset->{balance, availableBalance}."""
        data = self._request("GET", "/fapi/v2/balance", signed=True)
        out = {}
        for item in data:
            out[item["asset"]] = {
                "balance": float(item["balance"]),
                "available": float(item["availableBalance"]),
            }
        return out

    def equity_usdt(self):
        """Total wallet balance + unrealized PnL for USDT (account equity)."""
        data = self._request("GET", "/fapi/v2/account", signed=True)
        # totalWalletBalance + totalUnrealizedProfit = equity
        return float(data["totalWalletBalance"]) + float(data["totalUnrealizedProfit"]), \
               float(data["availableBalance"])

    def position_risk(self):
        """All open positions (positionAmt != 0). Returns list of dicts."""
        try:
            data = self._request("GET", "/fapi/v3/positionRisk", signed=True)
        except BinanceError:
            data = self._request("GET", "/fapi/v2/positionRisk", signed=True)
        out = []
        for p in data:
            amt = float(p.get("positionAmt", 0))
            if abs(amt) > 0:
                out.append({
                    "symbol": p["symbol"],
                    "amt": amt,
                    "dir": "LONG" if amt > 0 else "SHORT",
                    "entry": float(p.get("entryPrice", 0)),
                    "mark": float(p.get("markPrice", 0) or 0),
                    "upnl": float(p.get("unRealizedProfit", 0) or 0),
                    "leverage": int(float(p.get("leverage", 0) or 0)) if "leverage" in p else None,
                    "liq": float(p.get("liquidationPrice", 0) or 0),
                })
        return out

    def open_orders(self, symbol=None):
        params = {"symbol": symbol} if symbol else {}
        return self._request("GET", "/fapi/v1/openOrders", params, signed=True)

    # ---------------- trading ----------------
    def set_leverage(self, symbol, leverage):
        try:
            return self._request("POST", "/fapi/v1/leverage",
                                 {"symbol": symbol, "leverage": leverage}, signed=True)
        except BinanceError as e:
            log.warning(f"set_leverage {symbol} {leverage}x failed: {e}")
            return None

    def set_margin_type(self, symbol, margin_type="ISOLATED"):
        try:
            return self._request("POST", "/fapi/v1/marginType",
                                 {"symbol": symbol, "marginType": margin_type}, signed=True)
        except BinanceError as e:
            # -4046 = no need to change margin type (already set) -> benign
            if e.code != -4046:
                log.warning(f"set_margin_type {symbol} failed: {e}")
            return None

    def new_market_order(self, symbol, side, qty, client_id=None, reduce_only=False):
        params = {
            "symbol": symbol, "side": side, "type": "MARKET",
            "quantity": qty, "newOrderRespType": "RESULT",
        }
        if reduce_only:
            params["reduceOnly"] = "true"
        if client_id:
            params["newClientOrderId"] = client_id
        return self._request("POST", "/fapi/v1/order", params, signed=True)

    def new_stop_market(self, symbol, side, stop_price, client_id=None, close_position=True, qty=None):
        """STOP_MARKET reduce-only order (stop loss)."""
        params = {
            "symbol": symbol, "side": side, "type": "STOP_MARKET",
            "stopPrice": stop_price, "workingType": "MARK_PRICE",
        }
        if close_position:
            params["closePosition"] = "true"
        else:
            params["quantity"] = qty
            params["reduceOnly"] = "true"
        if client_id:
            params["newClientOrderId"] = client_id
        return self._request("POST", "/fapi/v1/order", params, signed=True)

    def new_take_profit_market(self, symbol, side, stop_price, client_id=None, close_position=True, qty=None):
        """TAKE_PROFIT_MARKET reduce-only order (take profit)."""
        params = {
            "symbol": symbol, "side": side, "type": "TAKE_PROFIT_MARKET",
            "stopPrice": stop_price, "workingType": "MARK_PRICE",
        }
        if close_position:
            params["closePosition"] = "true"
        else:
            params["quantity"] = qty
            params["reduceOnly"] = "true"
        if client_id:
            params["newClientOrderId"] = client_id
        return self._request("POST", "/fapi/v1/order", params, signed=True)

    def cancel_order(self, symbol, order_id=None, client_id=None):
        params = {"symbol": symbol}
        if order_id:
            params["orderId"] = order_id
        elif client_id:
            params["origClientOrderId"] = client_id
        try:
            return self._request("DELETE", "/fapi/v1/order", params, signed=True)
        except BinanceError as e:
            if e.code in NOT_FOUND_CODES:
                return None  # already gone, fine
            raise

    def cancel_all_orders(self, symbol):
        try:
            return self._request("DELETE", "/fapi/v1/allOpenOrders", {"symbol": symbol}, signed=True)
        except BinanceError as e:
            log.warning(f"cancel_all {symbol}: {e}")
            return None

    # ---------------- user data stream (listenKey) ----------------
    def create_listen_key(self):
        d = self._request("POST", "/fapi/v1/listenKey", signed=False)
        return d["listenKey"]

    def keepalive_listen_key(self):
        try:
            return self._request("PUT", "/fapi/v1/listenKey", signed=False)
        except BinanceError as e:
            log.warning(f"listenKey keepalive failed: {e}")
            return None
