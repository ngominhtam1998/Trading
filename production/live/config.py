"""Live bot configuration.

Modes:
- "testnet": Binance Futures Testnet (fake money, full order execution) -- START HERE
- "dry"    : Real API for market data, but NO real orders (paper). Logs intended orders.
- "live"   : Real money on Binance Futures mainnet. USE ONLY AFTER TESTNET VERIFIED.

Strategy levels (set via BOT_STRATEGY env var):
- "opus": multi-timeframe, BTC-aware, 1m-managed scalper → uses lv4 account
  (legacy v6/v7/v8 strategies have been retired)

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
# Supported: opus (lv4), glm (lv5). Legacy v6/v7/v8 strategies have been retired
# (they lost money on testnet despite profitable backtests).
STRATEGY_LEVEL = os.environ.get("BOT_STRATEGY", "opus").lower()
if STRATEGY_LEVEL not in ("opus", "glm"):
    raise ValueError(f"Invalid BOT_STRATEGY='{STRATEGY_LEVEL}'. Supported: 'opus', 'glm'.")

# Map strategy level -> module name
STRATEGY_MODULE = {
    "opus": "strategy_opus",          # multi-timeframe, BTC-aware, 1m-managed scalper
    "glm":  "strategy_glm",           # opus variant: pullback entry + dynamic universe
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
    """Return (key, secret). For testnet/live, prefer a per-account key
    (e.g. BINANCE_TESTNET_KEY_LV4) so the bot runs on its OWN account.
    opus runs on the lv4 account; override with BOT_ACCOUNT if needed."""
    account = os.environ.get("BOT_ACCOUNT", "")
    if account:
        suffix = account.upper()
    else:  # opus -> lv4 account
        suffix = "LV4"
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

# Neutral concurrent cap
MAX_CONCURRENT_NEUTRAL = _strat_mod.MAX_CONCURRENT
DAILY_LOSS_LIMIT = _strat_mod.DAILY_LOSS_LIMIT
MIN_SCORE = _strat_mod.MIN_SCORE
COINS_UNIVERSE_SIZE = 60     # how many top-volume symbols to scan each cycle

# v6+ score-based position sizing
POS_SCORE_HIGH = getattr(_strat_mod, "POS_SCORE_HIGH", POSITION_PCT)
POS_SCORE_MID = getattr(_strat_mod, "POS_SCORE_MID", POSITION_PCT)
POS_SCORE_LOW = getattr(_strat_mod, "POS_SCORE_LOW", POSITION_PCT)

# Strategy-specific BE/Trail R multiples (from strategy module)
BE_R_MULTIPLE = _strat_mod.BE_R
TRAIL_R_MULTIPLE = _strat_mod.TRAIL_R

# === EXECUTION CONSTRAINTS ===
MIN_NOTIONAL_FALLBACK = 5.0  # used if exchange doesn't report; real value from exchangeInfo
QUOTE_ASSET = "USDT"

# === TIMING ===
BAR_INTERVAL = "15m"
HTF_INTERVAL = "1h"
BAR_SECONDS = 15 * 60
DECISION_EVERY_BARS = getattr(_strat_mod, "DECISION_EVERY_BARS", 4)  # default 1h; strategy may override
MAX_HOLD_BARS = getattr(_strat_mod, "MAX_HOLD_BARS", 72)

# === LIVE LOOP CADENCE ===
# LOOP_SECONDS: how often the main loop wakes to MANAGE positions (BE/trail/SL).
#   Legacy strategies leave it at BAR_SECONDS (15m). opus sets it to 60s so that
#   breakeven/trailing actually track price instead of lagging 15 minutes.
# ENTRY_EVERY_LOOPS: if set, scan for new entries every N loops (decouples entry
#   cadence from management cadence). When None, fall back to the 15m-bar logic.
LOOP_SECONDS = int(getattr(_strat_mod, "LOOP_SECONDS", BAR_SECONDS))
ENTRY_EVERY_LOOPS = getattr(_strat_mod, "ENTRY_EVERY_LOOPS", None)
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
