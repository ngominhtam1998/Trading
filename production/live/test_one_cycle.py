"""Test: run bot for exactly 1 cycle, verify Telegram entry notification is sent.
Uses lv4 testnet, opens real positions, checks Telegram delivery."""
import os, sys, time, json, requests, signal, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set env BEFORE importing bot
os.environ["BOT_MODE"] = "testnet"
os.environ["BOT_STRATEGY"] = "lv4"

from live import config
from live import telegram as tg
from live.binance_client import BinanceClient

print(f"=== ONE CYCLE TEST: {config.STRATEGY_LEVEL} ===")

# Check Telegram config
print(f"Telegram enabled: {tg.is_enabled()}")
print(f"Bot token: {'set' if tg._BOT_TOKEN else 'empty'}")
print(f"Chat IDs: {tg._CHAT_IDS}")

# Send a test message first to verify delivery
print("\n[1] Pre-test: send simple message...")
tg.send("One-cycle test starting...", level="lv4")
time.sleep(5)

# Check if it was delivered (look for "delivered" in recent log)
# We can't easily check the log, so let's just wait and see

# Now import and run the bot for 1 cycle
print("\n[2] Starting bot for 1 cycle...")
from live.bot import Bot, RUNNING
import live.strategy_adapter as sa

bot = Bot()
bot.reconcile()

# Get equity
equity, avail = bot.get_equity()
print(f"  equity={equity} avail={avail}")

if equity:
    # Send startup notification
    tg.notify_startup(config.STRATEGY_LEVEL, config.MODE, equity)
    time.sleep(3)

    # Get BTC regime
    bot.btc_regime = sa.get_btc_regime_live(bot.client)
    print(f"  regime={bot.btc_regime}")

    # Get positions
    ex_positions = {p["symbol"]: p for p in bot.client.position_risk()}
    print(f"  open positions: {len(ex_positions)}")

    # Manage existing (none expected)
    bot.manage_positions(ex_positions)

    # Scan for entries
    print("\n[3] Scanning for entries...")
    bot.scan_entries(ex_positions, equity, avail)

    # Wait for Telegram delivery
    print("\n[4] Waiting 10s for Telegram delivery...")
    time.sleep(10)
    tg.flush(5)

    # Check final state
    ex_positions2 = {p["symbol"]: p for p in bot.client.position_risk()}
    print(f"\n[5] Final: {len(ex_positions2)} positions open")
    for p in ex_positions2:
        print(f"  {p}")

    # Check algo orders
    for sym in ex_positions2:
        algo = bot.client.open_algo_orders(sym)
        print(f"  {sym} algo orders: {len(algo)}")
        for o in algo:
            print(f"    type={o['type']} trigger={o.get('triggerPrice')} side={o.get('side')}")

print("\n[6] Done. Check @trading_v4 channel for:")
print("  - 'One-cycle test starting...' (pre-test)")
print("  - 'BOT KHOI DONG' (startup)")
print("  - 'MO LENH' entries (if any opportunities found)")
print("\nIf you only see pre-test + startup but NO entry notifications,")
print("the Telegram fix didn't work. Check bot_testnet_lv4.log for 'Telegram delivered' lines.")

# Cleanup
print("\n[7] Cleanup...")
for sym in {p["symbol"] for p in bot.client.position_risk()}:
    for o in bot.client.open_algo_orders(sym):
        bot.client.cancel_algo_order(sym, algo_id=o.get("algoId"))
    for p in bot.client.position_risk():
        if p["symbol"] == sym and p["amt"] != 0:
            side = "SELL" if p["amt"] > 0 else "BUY"
            bot.client.new_market_order(sym, side, abs(p["amt"]), reduce_only=True)
time.sleep(1)
print("  Done.")
