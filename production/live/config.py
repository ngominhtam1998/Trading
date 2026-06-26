"""Live bot configuration.

Modes:
- "testnet": Binance Futures Testnet (fake money, full order execution) -- START HERE
- "dry"    : Real API for market data, but NO real orders (paper). Logs intended orders.
- "live"   : Real money on Binance Futures mainnet. USE ONLY AFTER TESTNET VERIFIED.

Strategy levels (set via BOT_STRATEGY env var):
- "lv1": LV1    (conservative, 0 LIQ, +39%/mo avg)
- "lv2": LV2    (aggressive, 0 LIQ, +74%/mo avg)
- "lv3": LV3    (high risk, 9 LIQ, +182%/mo avg)
- "lv4": LV4    (very high risk, 23 LIQ, +283%/mo avg)
- "lv5": LV5    (extreme risk, 34 LIQ, +645%/mo avg)
- "lv6": LV6    (maximum risk, 35 LIQ, +719%/mo avg)

API keys are read from environment variables (never hard-code real keys):
  BINANCE_TESTNET_KEY / BINANCE_TESTNET_SECRET
  BINANCE_LIVE_KEY    / BINANCE_LIVE_SECRET

Telegram notifications (optional):
  TELEGRAM_BOT_TOKEN          - bot token from @BotFather
  TELEGRAM_CHAT_<LEVEL>       - channel chat_id per strategy level
"""
import os

# === AUTO-LOAD .env (simple parser, no external dependency) ===
def _load_dotenv():
    """Load KEY=VALUE lines from live/.env into os.environ if not already set.
    Existing environment variables take precedence (so CLI overrides .env)."""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip(); v = v.strip().strip('"').strip("'")
                # CLI/parent env wins; .env only fills what's missing
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass

_load_dotenv()

# === MODE ===
MODE = os.environ.get("BOT_MODE", "testnet")  # testnet | dry | live

# === STRATEGY LEVEL ===
# Must be one of: lv1, lv2, lv3, lv4, lv5, lv6, lv6plus, v6_3m
STRATEGY_LEVEL = os.environ.get("BOT_STRATEGY", "lv1").lower()
if STRATEGY_LEVEL not in ("lv1", "lv2", "lv3", "lv4", "lv5", "lv6", "lv6plus", "v6_3m"):
    raise ValueError(f"Invalid BOT_STRATEGY='{STRATEGY_LEVEL}'. Must be lv1|...|lv6|lv6plus|v6_3m")

# Map strategy level -> module name
STRATEGY_MODULE = {
    "lv1": "strategy_aggressive_lv1",      # LV1 baseline (was V15r2)
    "lv2": "strategy_aggressive_lv2",
    "lv3": "strategy_aggressive_lv3",
    "lv4": "strategy_aggressive_lv4",
    "lv5": "strategy_aggressive_lv5",
    "lv6": "strategy_aggressive_lv6",
    "lv6plus": "strategy_aggressive_lv6plus",  # LV6+ enhanced (score sizing + max hold 72)
    "v6_3m": "strategy_v6_3m",                 # V6 with 3m monitoring (realistic, MDD 22.6%)
}[STRATEGY_LEVEL]

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
    """Return (key, secret). For testnet/live, prefer a per-strategy key
    (e.g. BINANCE_TESTNET_KEY_LV4) so each bot runs on its OWN account and
    never adopts a sibling bot's positions. Falls back to the generic key.
    lv6plus reuses lv4's account (temporary test).
    v6_3m reuses lv5's account."""
    suffix = STRATEGY_LEVEL.upper()  # lv1->LV1, lv4->LV4, lv6plus->LV6PLUS
    if STRATEGY_LEVEL == "lv6plus":
        suffix = "LV4"  # borrow lv4's testnet account
    if STRATEGY_LEVEL == "v6_3m":
        suffix = "LV5"  # borrow lv5's testnet account
    if MODE == "live":
        key = os.environ.get(f"BINANCE_LIVE_KEY_{suffix}", "") or os.environ.get("BINANCE_LIVE_KEY", "")
        sec = os.environ.get(f"BINANCE_LIVE_SECRET_{suffix}", "") or os.environ.get("BINANCE_LIVE_SECRET", "")
    elif MODE == "testnet":
        key = os.environ.get(f"BINANCE_TESTNET_KEY_{suffix}", "") or os.environ.get("BINANCE_TESTNET_KEY", "")
        sec = os.environ.get(f"BINANCE_TESTNET_SECRET_{suffix}", "") or os.environ.get("BINANCE_TESTNET_SECRET", "")
    else:  # dry: keys optional (only needed for account endpoints)
        key = (os.environ.get(f"BINANCE_TESTNET_KEY_{suffix}", "")
               or os.environ.get("BINANCE_LIVE_KEY", "") or os.environ.get("BINANCE_TESTNET_KEY", ""))
        sec = (os.environ.get(f"BINANCE_TESTNET_SECRET_{suffix}", "")
               or os.environ.get("BINANCE_LIVE_SECRET", "") or os.environ.get("BINANCE_TESTNET_SECRET", ""))
    return key, sec

# === STRATEGY PARAMS (auto-loaded from strategy module) ===
# Import the strategy module to pull its params (single source of truth)
import importlib as _il
_strat_mod = _il.import_module(f"..{STRATEGY_MODULE}", package="live.config") \
    if False else None  # placeholder; real import done in strategy_adapter
# We import here using importlib with proper path
import sys as _sys, os as _os
_PARENT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _PARENT not in _sys.path:
    _sys.path.insert(0, _PARENT)
_strat_mod = _il.import_module(STRATEGY_MODULE)

POSITION_PCT = _strat_mod.POSITION_PCT
MAX_CONCURRENT = _strat_mod.MAX_CONCURRENT
MAX_LEVERAGE = _strat_mod.MAX_LEVERAGE
MAX_LEVERAGE_NEUTRAL = int(MAX_LEVERAGE * 0.75)

# Neutral concurrent cap: must match backtest hard-coded values per level
# (backtest sets a fixed cap, not a % of MAX_CONCURRENT)
_MAX_CONCURRENT_NEUTRAL = {"lv1": 7, "lv2": 8, "lv3": 10, "lv4": 12, "lv5": 15, "lv6": 18, "lv6plus": 18, "v6_3m": 18}
MAX_CONCURRENT_NEUTRAL = _MAX_CONCURRENT_NEUTRAL[STRATEGY_LEVEL]
DAILY_LOSS_LIMIT = _strat_mod.DAILY_LOSS_LIMIT
MIN_SCORE = _strat_mod.MIN_SCORE
COINS_UNIVERSE_SIZE = 60     # how many top-volume symbols to scan each cycle

# v6+ score-based position sizing
POS_SCORE_HIGH = getattr(_strat_mod, "POS_SCORE_HIGH", POSITION_PCT)
POS_SCORE_MID = getattr(_strat_mod, "POS_SCORE_MID", POSITION_PCT)
POS_SCORE_LOW = getattr(_strat_mod, "POS_SCORE_LOW", POSITION_PCT)

# Strategy-specific BE/Trail R multiples (for live SL management)
# These must match the backtest logic in each strategy module
_BE_R = {"lv1": 0.5, "lv2": 0.7, "lv3": 0.9, "lv4": 1.1, "lv5": 1.3, "lv6": 1.5, "lv6plus": 1.5, "v6_3m": 1.5}
_TRAIL_R = {"lv1": 1.2, "lv2": 1.5, "lv3": 2.0, "lv4": 2.5, "lv5": 3.0, "lv6": 3.5, "lv6plus": 3.5, "v6_3m": 3.5}
BE_R_MULTIPLE = _BE_R[STRATEGY_LEVEL]
TRAIL_R_MULTIPLE = _TRAIL_R[STRATEGY_LEVEL]

# === EXECUTION CONSTRAINTS ===
MIN_NOTIONAL_FALLBACK = 5.0  # used if exchange doesn't report; real value from exchangeInfo
QUOTE_ASSET = "USDT"

# === TIMING ===
BAR_INTERVAL = "15m"
HTF_INTERVAL = "1h"
BAR_SECONDS = 15 * 60
DECISION_EVERY_BARS = {"lv1": 16, "lv2": 12, "lv3": 8, "lv4": 6, "lv5": 4, "lv6": 4, "lv6plus": 4, "v6_3m": 4}[STRATEGY_LEVEL]
MAX_HOLD_BARS = getattr(_strat_mod, "MAX_HOLD_BARS", 48)  # v6+ uses 72, v6_3m uses 72
KLINES_LOOKBACK = 260        # bars to fetch for indicators (EMA200 needs >200)

# === RECOVERY / ORPHAN HANDLING ===
ORPHAN_ACTION = "adopt"      # adopt | close | pause  (user chose: adopt + place SL)
ORPHAN_SL_PCT = 1.5          # emergency SL % for adopted positions if none exists

# === COOLDOWN (match backtest: skip re-entry after consecutive SLs) ===
COOLDOWN_CONSEC_SL_THRESHOLD = 2   # trigger cooldown after N consecutive SLs on same symbol
COOLDOWN_BARS = 6                  # cooldown duration in bars (6 × 15m = 90 min)

# === LIQUIDATION WARNING ===
LIQ_WARN_THRESHOLD_PCT = 20.0  # warn when price is within X% of liquidation price

# === FUNDING COST TRACKING ===
FUNDING_DAILY_WARN_PCT = 5.0   # warn when daily funding cost exceeds X% of equity

# === ROBUSTNESS ===
MAX_RETRIES = 5              # retries per REST call
RETRY_BACKOFF_BASE = 1.5     # exponential backoff base (seconds)
RECV_WINDOW = 5000           # ms
ORDER_PREFIX = "scbot"       # clientOrderId prefix to recognize our own orders

# === PATHS ===
STATE_DB_PATH = os.path.join(os.path.dirname(__file__), f"state_{MODE}_{STRATEGY_LEVEL}.db")
LOG_PATH = os.path.join(os.path.dirname(__file__), f"bot_{MODE}_{STRATEGY_LEVEL}.log")
