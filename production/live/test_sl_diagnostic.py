"""Diagnostic: open a real SHORT on testnet, place SL+TP, dump EVERYTHING
about the algo orders to find why SL doesn't trigger.

Tests:
1. Open SHORT BTCUSDT (tiny)
2. Place SL (STOP_MARKET BUY, closePosition=true) ABOVE entry
3. Place TP (TAKE_PROFIT_MARKET BUY, closePosition=true) BELOW entry
4. Dump raw algo order response + openAlgoOrders response
5. Verify: triggerPrice is correct side, workingType, status
6. Check if price has already crossed SL (would explain invalid)
7. Try placing SL with CONTRACT_PRICE workingType (last price) vs MARK_PRICE
8. Also test: what happens if we place SL BELOW current price (should fail)
"""
import os, time, json
from . import config
from .binance_client import BinanceClient, BinanceError
from .exchange_filters import ExchangeFilters

c = BinanceClient()
f = ExchangeFilters(c)
SYM = "BTCUSDT"

print(f"=== SL DIAGNOSTIC: {SYM} STRATEGY={config.STRATEGY_LEVEL} ===\n")

# Clean slate
print("[0] Cleanup...")
for o in c.open_algo_orders(SYM):
    c.cancel_algo_order(SYM, algo_id=o.get("algoId"))
for p in c.position_risk():
    if p["symbol"] == SYM and p["amt"] != 0:
        side = "SELL" if p["amt"] > 0 else "BUY"
        c.new_market_order(SYM, side, abs(p["amt"]), reduce_only=True)
        time.sleep(1)

# Get current price
mp = c.mark_price(SYM)
print(f"\n[1] Current mark_price: {mp}")

# Open SHORT
c.set_margin_type(SYM, "ISOLATED")
c.set_leverage(SYM, 5)
notional = 120.0
qty = f.round_qty(SYM, notional / mp)
print(f"[2] Opening SHORT qty={qty} (~${qty*mp:.2f})")
resp = c.new_market_order(SYM, "SELL", qty, client_id="scbot_diag_entry")
fill = float(resp.get("avgPrice") or 0) or mp
print(f"    filled @ {fill}, status={resp.get('status')}")
print(f"    raw resp: {json.dumps(resp, indent=2)}")

# SL for SHORT = ABOVE entry (e.g. +1%)
sl_pct = 1.0
tp_pct = 3.0
sl_price = f.round_price(SYM, fill * (1 + sl_pct / 100))
tp_price = f.round_price(SYM, fill * (1 - tp_pct / 100))
print(f"\n[3] SL calculation:")
print(f"    entry={fill}, sl_pct={sl_pct}%, sl_price={sl_price} (ABOVE entry, correct for SHORT)")
print(f"    entry={fill}, tp_pct={tp_pct}%, tp_price={tp_price} (BELOW entry, correct for SHORT)")
print(f"    current mark_price={mp}")
print(f"    sl_price > mp? {sl_price > mp} (must be True for STOP_MARKET BUY)")
print(f"    tp_price < mp? {tp_price < mp} (must be True for TAKE_PROFIT_MARKET BUY)")

# Place SL with MARK_PRICE (current default)
print(f"\n[4] Placing SL (STOP_MARKET, workingType=MARK_PRICE)...")
try:
    sl_resp = c.new_stop_market(SYM, "BUY", sl_price,
                                 client_id="scbot_diag_sl_mark",
                                 close_position=True)
    print(f"    SUCCESS: {json.dumps(sl_resp, indent=2)}")
except BinanceError as e:
    print(f"    FAILED: code={e.code} msg={e}")

# Place TP with MARK_PRICE
print(f"\n[5] Placing TP (TAKE_PROFIT_MARKET, workingType=MARK_PRICE)...")
try:
    tp_resp = c.new_take_profit_market(SYM, "BUY", tp_price,
                                        client_id="scbot_diag_tp_mark",
                                        close_position=True)
    print(f"    SUCCESS: {json.dumps(tp_resp, indent=2)}")
except BinanceError as e:
    print(f"    FAILED: code={e.code} msg={e}")

# Check open algo orders - RAW response
print(f"\n[6] Raw openAlgoOrders response:")
try:
    raw = c._request("GET", "/fapi/v1/openAlgoOrders", {"symbol": SYM}, signed=True)
    print(json.dumps(raw, indent=2))
except BinanceError as e:
    print(f"    FAILED: {e}")

# Also try the openOrders endpoint to see if algo orders show up there
print(f"\n[7] Regular openOrders (for comparison):")
try:
    raw2 = c._request("GET", "/fapi/v1/openOrders", {"symbol": SYM}, signed=True)
    print(json.dumps(raw2, indent=2))
except BinanceError as e:
    print(f"    FAILED: {e}")

# Check position
print(f"\n[8] Position risk:")
for p in c.position_risk():
    if p["symbol"] == SYM:
        print(f"    {p}")

# Now test: place SL with CONFLICTING price (below current) - should fail
bad_sl = f.round_price(SYM, mp * 0.99)  # BELOW current price
print(f"\n[9] Trying to place STOP_MARKET BUY with trigger BELOW current ({bad_sl} < {mp})...")
print(f"    This should FAIL (stop BUY must be above current price)")
try:
    bad_resp = c.new_stop_market(SYM, "BUY", bad_sl,
                                  client_id="scbot_diag_sl_bad",
                                  close_position=True)
    print(f"    UNEXPECTED SUCCESS: {json.dumps(bad_resp, indent=2)}")
except BinanceError as e:
    print(f"    EXPECTED FAIL: code={e.code} msg={e}")

# Test with CONFLICT price already crossed (SL price between entry and current)
# If price moved up past SL, placing SL would fail
print(f"\n[10] Summary:")
print(f"     entry={fill}, current={mp}")
print(f"     SL={sl_price} ({'ABOVE' if sl_price > mp else 'BELOW'} current)")
print(f"     TP={tp_price} ({'ABOVE' if tp_price > mp else 'BELOW'} current)")
print(f"     SL valid? {'YES' if sl_price > mp else 'NO - price already crossed!'}")

# Cleanup
print(f"\n[11] Cleanup...")
for o in c.open_algo_orders(SYM):
    c.cancel_algo_order(SYM, algo_id=o.get("algoId"))
for p in c.position_risk():
    if p["symbol"] == SYM and p["amt"] != 0:
        side = "SELL" if p["amt"] > 0 else "BUY"
        c.new_market_order(SYM, side, abs(p["amt"]), reduce_only=True)
time.sleep(1)
print("    Done.")
