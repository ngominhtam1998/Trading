"""Test DECISION_EVERY_BARS enforcement (mock, no real API needed).

Run: python -m live.test_decision_bars  (from D:/Tam/trading/production)
"""
import os
import time

os.environ.setdefault("BOT_MODE", "dry")
os.environ.setdefault("BOT_STRATEGY", "opus")

from live import config
from live.bot import Bot

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def make_bot():
    bot = Bot.__new__(Bot)
    bot.last_decision_bar = None
    return bot


print("=== DECISION_EVERY_BARS TEST ===")
print(f"Strategy={config.STRATEGY_LEVEL}, DECISION_EVERY_BARS={config.DECISION_EVERY_BARS}")

bot = make_bot()
bar0 = bot._bar_index()
check("first call is decision bar", bot._is_decision_bar() is True,
      f"last_decision_bar={bot.last_decision_bar}")
check("last_decision_bar updated to current bar", bot.last_decision_bar == bar0,
      f"expected {bar0}, got {bot.last_decision_bar}")

# Same bar -> not decision
bot.last_decision_bar = bar0
# _bar_index() might have advanced by 1 bar during test execution; recalculate
bar_now = bot._bar_index()
if bar_now == bar0:
    check("same bar is not decision", bot._is_decision_bar() is False)
else:
    check("same bar is not decision", True, "skipped (bar advanced)")

# Less than DECISION_EVERY_BARS difference -> not decision
bot.last_decision_bar = bar_now - (config.DECISION_EVERY_BARS - 1)
check(f"< {config.DECISION_EVERY_BARS} bars later is not decision",
      bot._is_decision_bar() is False,
      f"last={bot.last_decision_bar}, current={bar_now}")

# Exactly DECISION_EVERY_BARS difference -> decision
bot.last_decision_bar = bar_now - config.DECISION_EVERY_BARS
check(f">= {config.DECISION_EVERY_BARS} bars later is decision",
      bot._is_decision_bar() is True,
      f"last={bot.last_decision_bar}, current={bar_now}")
check("last_decision_bar updated", bot.last_decision_bar == bar_now,
      f"expected {bar_now}, got {bot.last_decision_bar}")

print(f"\nRESULT: {PASS} passed, {FAIL} failed")
