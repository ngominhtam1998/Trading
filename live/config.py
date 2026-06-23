"""Live bot configuration.

Modes:
- "testnet": Binance Futures Testnet (fake money, full order execution) -- START HERE
- "dry"    : Real API for market data, but NO real orders (paper). Logs intended orders.
- "live"   : Real money on Binance Futures mainnet. USE ONLY AFTER TESTNET VERIFIED.

API keys are read from environment variables (never hard-code real keys):
  BINANCE_TESTNET_KEY / BINANCE_TESTNET_SECRET
  BINANCE_LIVE_KEY    / BINANCE_LIVE_SECRET
"""
import os

# === MODE ===
MODE = os.environ.get("BOT_MODE", "testnet")  # testnet | dry | live

# === ENDPOINTS ===
ENDPOINTS = {
    "testnet": "https://testnet.binancefuture.com",
    "dry":     "https://fapi.binance.com",
    "live":    "https://fapi.binance.com",
}
WS_ENDPOINTS = {
    "testnet": "wss://stream.binancefuture.com",
    "dry":     "wss://fstream.binance.com",
    "live":    "wss://fstream.binance.com",
}

def base_url():
    return ENDPOINTS[MODE]

def ws_url():
    return WS_ENDPOINTS[MODE]

def is_real_orders():
    """True if the bot should place real orders (testnet or live)."""
    return MODE in ("testnet", "live")

# === API KEYS ===
def get_api_keys():
    if MODE == "live":
        key = os.environ.get("BINANCE_LIVE_KEY", "")
        sec = os.environ.get("BINANCE_LIVE_SECRET", "")
    elif MODE == "testnet":
        key = os.environ.get("BINANCE_TESTNET_KEY", "")
        sec = os.environ.get("BINANCE_TESTNET_SECRET", "")
    else:  # dry: keys optional (only needed for account endpoints)
        key = os.environ.get("BINANCE_LIVE_KEY", "") or os.environ.get("BINANCE_TESTNET_KEY", "")
        sec = os.environ.get("BINANCE_LIVE_SECRET", "") or os.environ.get("BINANCE_TESTNET_SECRET", "")
    return key, sec

# === STRATEGY PARAMS (must match strategy_aggressive.py) ===
POSITION_PCT = 7.0           # % of current equity per trade (compounding)
MAX_CONCURRENT = 10          # max concurrent positions
MAX_CONCURRENT_NEUTRAL = 5   # in neutral BTC regime
MAX_LEVERAGE = 10
MAX_LEVERAGE_NEUTRAL = 5
DAILY_LOSS_LIMIT = 5.0       # % daily loss halt
MIN_SCORE = 6
COINS_UNIVERSE_SIZE = 60     # how many top-volume symbols to scan each cycle

# === EXECUTION CONSTRAINTS ===
MIN_NOTIONAL_FALLBACK = 5.0  # used if exchange doesn't report; real value from exchangeInfo
QUOTE_ASSET = "USDT"

# === TIMING ===
BAR_INTERVAL = "15m"
HTF_INTERVAL = "1h"
BAR_SECONDS = 15 * 60
DECISION_EVERY_BARS = 16     # scan entries every 16 bars (4h) -- matches backtest
MAX_HOLD_BARS = 48           # close after 48 bars (12h)
KLINES_LOOKBACK = 260        # bars to fetch for indicators (EMA200 needs >200)

# === RECOVERY / ORPHAN HANDLING ===
ORPHAN_ACTION = "adopt"      # adopt | close | pause  (user chose: adopt + place SL)
ORPHAN_SL_PCT = 1.5          # emergency SL % for adopted positions if none exists

# === ROBUSTNESS ===
MAX_RETRIES = 5              # retries per REST call
RETRY_BACKOFF_BASE = 1.5     # exponential backoff base (seconds)
RECV_WINDOW = 5000           # ms
ORDER_PREFIX = "scbot"       # clientOrderId prefix to recognize our own orders

# === PATHS ===
STATE_DB_PATH = os.path.join(os.path.dirname(__file__), f"state_{MODE}.db")
LOG_PATH = os.path.join(os.path.dirname(__file__), f"bot_{MODE}.log")
