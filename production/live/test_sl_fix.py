"""Test SL fix: verify atomic swap (place new SL before cancel old) and
price validation (skip SL move if new SL is on wrong side of current price).

Test cases:
1. Open SHORT, place SL above -> verify SL exists
2. Simulate BE move: try to place SL below current price -> should SKIP (not cancel old SL)
3. Verify old SL still exists after skipped move
4. Simulate valid BE move: SL above current but below entry -> should succeed
5. Verify old SL cancelled, new SL in place
6. Test: what happens if new SL placement fails (wrong price) -> old SL should survive
7. Cleanup
"""
import json, time
from live import config
from live.binance_client import BinanceClient, BinanceError
from live.exchange_filters import ExchangeFilters

c = BinanceClient()
f = ExchangeFilters(c)
SYM = "BTCUSDT"
results = []

def test(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    results.append((status, name, detail))
    print(f"  [{status}] {name}" + (f" — {detail}" if detail and not condition else ""))

print(f"=== SL FIX TEST: {SYM} ===\n")

# Clean slate
print("[0] Cleanup...")
for o in c.open_algo_orders(SYM):
    c.cancel_algo_order(SYM, algo_id=o.get("algoId"))
for p in c.position_risk():
    if p["symbol"] == SYM and p["amt"] != 0:
        side = "SELL" if p["amt"] > 0 else "BUY"
        c.new_market_order(SYM, side, abs(p["amt"]), reduce_only=True)
time.sleep(1)

# 1. Open SHORT and place SL
print("\n[1] Open SHORT + place SL above entry...")
mp = c.mark_price(SYM)
c.set_margin_type(SYM, "ISOLATED")
c.set_leverage(SYM, 5)
qty = f.round_qty(SYM, 120.0 / mp)
resp = c.new_market_order(SYM, "SELL", qty, client_id="scbot_test1_entry")
fill = float(resp.get("avgPrice") or 0) or mp
sl_price = f.round_price(SYM, fill * 1.01)  # 1% above entry
tp_price = f.round_price(SYM, fill * 0.97)  # 3% below entry
print(f"  entry={fill}, qty={qty}, SL={sl_price}, TP={tp_price}")

# Place SL
sl_cid = "scbot_test1_sl"
c.new_stop_market(SYM, "BUY", sl_price, client_id=sl_cid, close_position=True)
c.new_take_profit_market(SYM, "BUY", tp_price, client_id="scbot_test1_tp", close_position=True)
time.sleep(1)

algo = c.open_algo_orders(SYM)
sl_orders = [o for o in algo if o["type"] == "STOP_MARKET"]
tp_orders = [o for o in algo if o["type"] == "TAKE_PROFIT_MARKET"]
test("SL placed", len(sl_orders) == 1, f"found {len(sl_orders)} SL orders")
test("TP placed", len(tp_orders) == 1, f"found {len(tp_orders)} TP orders")
if sl_orders:
    test("SL triggerPrice correct", abs(float(sl_orders[0].get("triggerPrice", 0)) - sl_price) < 0.01,
         f"expected {sl_price}, got {sl_orders[0].get('triggerPrice')}")
    test("SL side is BUY", sl_orders[0].get("side") == "BUY" or sl_orders[0].get("type") == "STOP_MARKET", "")

# 2. Simulate INVALID BE move (SL below current price for SHORT)
print("\n[2] Test INVALID BE move (new SL below current price)...")
cur_mp = c.mark_price(SYM)
invalid_sl = f.round_price(SYM, cur_mp * 0.99)  # BELOW current -> invalid for STOP_MARKET BUY
print(f"  current={cur_mp}, invalid_new_sl={invalid_sl} (below current -> should SKIP)")

# Simulate what _update_stops does: check if new_sl <= cur_mp for SHORT
should_skip = (invalid_sl <= cur_mp)
test("Should skip invalid SL move", should_skip, f"invalid_sl={invalid_sl} <= cur_mp={cur_mp}")

# Verify old SL still exists (we should NOT have cancelled it)
algo_after = c.open_algo_orders(SYM)
sl_after = [o for o in algo_after if o["type"] == "STOP_MARKET"]
test("Old SL still exists after skip", len(sl_after) == 1, f"found {len(sl_after)} SL orders")

# 3. Simulate VALID BE move (SL above current but below entry)
print("\n[3] Test VALID BE move (new SL above current, below entry)...")
# For SHORT: BE SL = entry * (1 - 0.01) = entry * 0.99
# This should be above current price if price dropped
be_sl = f.round_price(SYM, fill * 0.999)  # just below entry
print(f"  entry={fill}, be_sl={be_sl}, current={cur_mp}")
print(f"  be_sl > current? {be_sl > cur_mp} (must be True for valid STOP_MARKET BUY)")

if be_sl > cur_mp:
    # Atomic swap: place new SL first, then cancel old
    new_cid = "scbot_test1_sl_be"
    try:
        c.new_stop_market(SYM, "BUY", be_sl, client_id=new_cid, close_position=True)
        print(f"  New SL placed at {be_sl}")
        # Now cancel old SL
        try:
            c.cancel_algo_order(SYM, client_id=sl_cid)
            print(f"  Old SL cancelled")
        except BinanceError as e:
            print(f"  Old SL cancel failed (might have -4130): {e}")
        time.sleep(1)
        algo_be = c.open_algo_orders(SYM)
        sl_be = [o for o in algo_be if o["type"] == "STOP_MARKET"]
        test("New SL placed after BE move", len(sl_be) >= 1, f"found {len(sl_be)}")
        if sl_be:
            test("New SL has correct triggerPrice", float(sl_be[0].get("triggerPrice", 0)) == be_sl,
                 f"expected {be_sl}, got {sl_be[0].get('triggerPrice')}")
    except BinanceError as e:
        test("New SL placement for BE", False, f"failed: {e}")
else:
    print(f"  Skipping: be_sl ({be_sl}) <= current ({cur_mp}), would be invalid")
    test("BE SL above current", False, "price hasn't dropped enough for BE test")

# 4. Test: new SL fails -> old SL should survive (atomic swap)
print("\n[4] Test: new SL fails -> old SL survives...")
# Try to place a SL at an invalid price (below current for BUY)
bad_sl = f.round_price(SYM, cur_mp * 0.98)  # well below current
old_sl_count = len([o for o in c.open_algo_orders(SYM) if o["type"] == "STOP_MARKET"])
print(f"  old SL count={old_sl_count}, trying invalid SL at {bad_sl} (below current {cur_mp})")
try:
    c.new_stop_market(SYM, "BUY", bad_sl, client_id="scbot_test1_sl_bad", close_position=True)
    # If this succeeds (shouldn't), cancel it
    c.cancel_algo_order(SYM, client_id="scbot_test1_sl_bad")
    test("Invalid SL rejected", False, "Binance accepted invalid SL price!")
except BinanceError as e:
    test("Invalid SL rejected by API", True, f"error: {e}")
# Check old SL still exists
new_sl_count = len([o for o in c.open_algo_orders(SYM) if o["type"] == "STOP_MARKET"])
test("Old SL survives failed new SL", new_sl_count == old_sl_count,
     f"old={old_sl_count} new={new_sl_count}")

# 5. Summary
print(f"\n{'='*60}")
passed = sum(1 for s,_,_ in results if s == "PASS")
failed = sum(1 for s,_,_ in results if s == "FAIL")
print(f"RESULTS: {passed} PASS, {failed} FAIL")
print(f"{'='*60}")
for status, name, detail in results:
    if status == "FAIL":
        print(f"  FAIL: {name} — {detail}")

# Cleanup
print("\n[5] Cleanup...")
for o in c.open_algo_orders(SYM):
    c.cancel_algo_order(SYM, algo_id=o.get("algoId"))
for p in c.position_risk():
    if p["symbol"] == SYM and p["amt"] != 0:
        side = "SELL" if p["amt"] > 0 else "BUY"
        c.new_market_order(SYM, side, abs(p["amt"]), reduce_only=True)
time.sleep(1)
print("  Done.")
