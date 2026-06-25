"""Telegram notification module — ASYNC, fire-and-forget.

Design goal: notifications are AUXILIARY and must NEVER slow down or block the
trading loop. All sends go through a bounded background queue processed by a
daemon worker thread. The trading thread only does an O(1) non-blocking enqueue.

If Telegram is slow/unreachable (common on some networks), messages are sent
best-effort by the worker with a short timeout; the trading loop is unaffected.
If the queue fills up, the oldest message is dropped (never blocks the producer).

Setup:
  1. Chat with @BotFather -> /newbot -> get BOT_TOKEN
  2. Create Telegram channels, add bot as admin to each
  3. Set env vars (or live/.env):
     TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
     TELEGRAM_CHAT_LV4=@trading_v4   (and _LV5, _LV6, etc.)
"""
import os
import time
import queue
import logging
import threading
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

log = logging.getLogger("telegram")

# Lazy-loaded config
_BOT_TOKEN = None
_CHAT_IDS = {}
_loaded = False

# Background delivery
_QUEUE = queue.Queue(maxsize=500)   # bounded; producer never blocks
_worker = None
_worker_lock = threading.Lock()
_session = requests.Session()
# SSL: ON for live (real money security), OFF for testnet (compat)
_session_verify = False  # set in _load_config based on MODE
_SEND_TIMEOUT = 8                    # seconds per HTTP call (worker thread only)


def _load_config():
    global _BOT_TOKEN, _CHAT_IDS, _loaded, _session_verify
    if _loaded:
        return
    # Importing config triggers .env auto-loading into os.environ
    from . import config  # noqa: F401
    _BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    _CHAT_IDS = {
        "lv1": os.environ.get("TELEGRAM_CHAT_LV1", ""),
        "lv2": os.environ.get("TELEGRAM_CHAT_LV2", ""),
        "lv3": os.environ.get("TELEGRAM_CHAT_LV3", ""),
        "lv4": os.environ.get("TELEGRAM_CHAT_LV4", ""),
        "lv5": os.environ.get("TELEGRAM_CHAT_LV5", ""),
        "lv6": os.environ.get("TELEGRAM_CHAT_LV6", ""),
        "lv6plus": os.environ.get("TELEGRAM_CHAT_LV4", ""),  # borrow lv4 channel
    }
    # SSL verification: ON for live (real money), OFF for testnet
    _session_verify = config.MODE == "live"
    _session.verify = _session_verify
    if not _session_verify:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    _loaded = True


def _ensure_worker():
    """Start the background delivery thread once, on first use."""
    global _worker
    if _worker is not None and _worker.is_alive():
        return
    with _worker_lock:
        if _worker is not None and _worker.is_alive():
            return
        _worker = threading.Thread(target=_worker_loop, name="tg-worker", daemon=True)
        _worker.start()


def _worker_loop():
    while True:
        try:
            chat_id, text, parse_mode = _QUEUE.get()
        except Exception:
            continue
        try:
            _deliver(chat_id, text, parse_mode)
        except Exception as e:
            log.debug(f"Telegram deliver error (ignored): {e}")
        finally:
            try:
                _QUEUE.task_done()
            except Exception:
                pass


def _deliver(chat_id, text, parse_mode):
    """Actual HTTP send — runs ONLY in the worker thread."""
    url = f"https://api.telegram.org/bot{_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode,
               "disable_web_page_preview": True}
    try:
        r = _session.post(url, json=payload, timeout=_SEND_TIMEOUT, verify=_session_verify)
        if r.status_code != 200:
            log.warning(f"Telegram send failed: {r.status_code} {r.text[:200]}")
        else:
            log.info(f"Telegram delivered to {chat_id} ({len(text)} chars)")
    except Exception as e:
        log.warning(f"Telegram network error: {e}")


def is_enabled():
    """True if bot token + chat_id for current strategy are configured."""
    _load_config()
    from . import config
    return bool(_BOT_TOKEN and _CHAT_IDS.get(config.STRATEGY_LEVEL))


def send(message, level=None, parse_mode="HTML"):
    """Enqueue a message for async delivery. NON-BLOCKING, returns immediately.

    Returns True if queued, False if not configured or queue full (dropped).
    The trading loop must never depend on the return value for correctness.
    """
    _load_config()
    if level is None:
        from . import config
        level = config.STRATEGY_LEVEL
    chat_id = _CHAT_IDS.get(level, "")
    if not _BOT_TOKEN or not chat_id:
        return False  # not configured -> silently skip, no network, no block

    _ensure_worker()
    try:
        _QUEUE.put_nowait((chat_id, message, parse_mode))
        return True
    except queue.Full:
        # Drop oldest, enqueue newest — never block the trading thread
        try:
            _QUEUE.get_nowait(); _QUEUE.task_done()
            _QUEUE.put_nowait((chat_id, message, parse_mode))
        except Exception:
            pass
        log.debug("Telegram queue full, dropped a message")
        return False


def flush(timeout=5):
    """Best-effort wait for queued messages to be delivered (used on shutdown)."""
    end = time.time() + timeout
    while not _QUEUE.empty() and time.time() < end:
        time.sleep(0.1)


# ============================================================
# Formatted notifications (all non-blocking via send())
# ============================================================
def _fmt_money(x):
    return f"${x:,.2f}"


def notify_entry(symbol, direction, qty, price, lev, sl_pct, tp_pct, score,
                 margin=None, notional=None, sl_price=None, tp_price=None, entry_time=None):
    """Full entry notification: coin, direction, qty, price, leverage, margin,
    notional (volume), SL/TP price+%, score, time."""
    emoji = "🟢" if direction == "LONG" else "🔴"
    when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(
        (entry_time / 1000) if entry_time else time.time()))
    rr = (tp_pct / sl_pct) if sl_pct else 0
    lines = [
        f"{emoji} <b>MỞ LỆNH</b> — {symbol}",
        f"├ Hướng: <b>{direction}</b>  |  Đòn bẩy: <b>{lev}x</b>",
        f"├ Giá vào: <b>{price:.6g}</b>",
        f"├ Khối lượng: <b>{qty}</b>" + (f"  (~{_fmt_money(notional)})" if notional else ""),
    ]
    if margin is not None:
        lines.append(f"├ Ký quỹ: <b>{_fmt_money(margin)}</b>")
    if sl_price is not None:
        lines.append(f"├ SL: <b>{sl_price:.6g}</b> ({sl_pct:.2f}%)")
    else:
        lines.append(f"├ SL: {sl_pct:.2f}%")
    if tp_price is not None:
        lines.append(f"├ TP: <b>{tp_price:.6g}</b> ({tp_pct:.2f}%)")
    else:
        lines.append(f"├ TP: {tp_pct:.2f}%")
    lines.append(f"├ RR: <b>{rr:.1f}</b>  |  Score: <b>{score}/10</b>")
    lines.append(f"└ Thời gian: {when}")
    return send("\n".join(lines))


def notify_exit(symbol, direction, reason, pnl=None, pnl_pct=None,
                entry_price=None, exit_price=None, qty=None,
                hold_seconds=None, margin=None):
    """Full exit notification: reason, PnL $ and %, entry/exit price, qty,
    hold time, ROI on margin."""
    win = (pnl is None) or (pnl >= 0)
    emoji = "✅" if win else "❌"
    lines = [f"{emoji} <b>ĐÓNG LỆNH</b> — {symbol}",
             f"├ Hướng: <b>{direction}</b>  |  Lý do: <b>{reason}</b>"]
    if entry_price is not None and exit_price is not None:
        lines.append(f"├ Vào: <b>{entry_price:.6g}</b> → Ra: <b>{exit_price:.6g}</b>")
    if qty is not None:
        lines.append(f"├ Khối lượng: <b>{qty}</b>")
    if pnl is not None:
        roi = (pnl / margin * 100) if margin else None
        pnl_line = f"├ PnL: <b>{'+' if pnl >= 0 else ''}{_fmt_money(pnl)}</b>"
        if pnl_pct is not None:
            pnl_line += f"  (<b>{pnl_pct:+.2f}%</b> giá)"
        lines.append(pnl_line)
        if roi is not None:
            lines.append(f"├ ROI ký quỹ: <b>{roi:+.1f}%</b>")
    if hold_seconds is not None:
        h = int(hold_seconds // 3600); m = int((hold_seconds % 3600) // 60)
        lines.append(f"├ Giữ lệnh: <b>{h}h {m}m</b>")
    when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    lines.append(f"└ Thời gian: {when}")
    return send("\n".join(lines))


def notify_sl_move(symbol, new_sl, kind):
    emoji = "📍" if kind == "breakeven" else "📈"
    label = "Hòa vốn (BE)" if kind == "breakeven" else "Dời theo (Trail)"
    msg = (f"{emoji} <b>DỜI SL</b> — {symbol}\n"
           f"├ SL mới: <b>{new_sl:.6g}</b>\n"
           f"└ Loại: {label}")
    return send(msg)


def notify_orphan_adopted(symbol, direction, qty, entry, lev, sl_price, tp_price, sl_pct):
    """Notification when bot adopts an orphan position (found on exchange, not in DB).
    Happens when bot restarts with fresh DB or after crash."""
    emoji = "🟢" if direction == "LONG" else "🔴"
    when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    notional = qty * entry
    tp_pct = sl_pct * 3.5
    msg = (f"{emoji} <b>ADOPT ORPHAN</b> — {symbol}\n"
           f"├ Hướng: <b>{direction}</b>  |  Đòn bẩy: <b>{lev}x</b>\n"
           f"├ Giá vào: <b>{entry:.6g}</b>\n"
           f"├ Khối lượng: <b>{qty}</b>  (~{_fmt_money(notional)})\n"
           f"├ SL: <b>{sl_price:.6g}</b> ({sl_pct:.2f}%)\n"
           f"├ TP: <b>{tp_price:.6g}</b> ({tp_pct:.2f}%)\n"
           f"└ Tìm thấy khi khởi động — {when}")
    return send(msg)


def notify_error(symbol, error_msg):
    msg = (f"⚠️ <b>LỖI</b> — {symbol}\n"
           f"└ {error_msg}")
    return send(msg)


def notify_daily_halt(equity, start_equity):
    dd_pct = (start_equity - equity) / start_equity * 100 if start_equity > 0 else 0
    msg = (f"🛑 <b>DỪNG TRONG NGÀY</b> (chạm giới hạn lỗ)\n"
           f"├ Vốn: <b>{_fmt_money(equity)}</b>\n"
           f"├ Đầu ngày: {_fmt_money(start_equity)}\n"
           f"├ Sụt: <b>{dd_pct:.1f}%</b>\n"
           f"└ Tạm dừng mở lệnh đến ngày mai")
    return send(msg)


def notify_startup(level, mode, equity):
    when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    msg = (f"🚀 <b>BOT KHỞI ĐỘNG</b>\n"
           f"├ Chiến lược: <b>{level.upper()}</b>\n"
           f"├ Chế độ: <b>{mode}</b>\n"
           f"├ Vốn: <b>{_fmt_money(equity)}</b>\n"
           f"└ {when}")
    return send(msg)


def notify_shutdown(level, reason="manual"):
    msg = (f"🛑 <b>BOT DỪNG</b>\n"
           f"├ Chiến lược: <b>{level.upper()}</b>\n"
           f"└ Lý do: {reason}")
    ok = send(msg)
    flush(3)  # give worker a moment to deliver the final message
    return ok


def notify_cooldown(symbol, consec_sls, cooldown_bars):
    """Notification when a symbol enters cooldown after consecutive SLs."""
    mins = cooldown_bars * 15  # 15m bars
    msg = (f"⏸️ <b>COOLDOWN</b> — {symbol}\n"
           f"├ SL liên tiếp: <b>{consec_sls}</b>\n"
           f"├ Bỏ qua entry <b>{mins} phút</b>\n"
           f"└ Tránh vào lại cùng coin khi đang thua")
    return send(msg)


def notify_liq_warning(symbol, direction, mark_price, liq_price, distance_pct, leverage):
    """Warning when price is approaching liquidation price."""
    msg = (f"🚨 <b>CẢNH BÁO LIQUIDATION</b> — {symbol}\n"
           f"├ Hướng: <b>{direction}</b>  |  Đòn bẩy: <b>{leverage}x</b>\n"
           f"├ Giá hiện tại: <b>{mark_price:.6g}</b>\n"
           f"├ Giá liquidation: <b>{liq_price:.6g}</b>\n"
           f"├ Cách liq: <b>{distance_pct:.1f}%</b>\n"
           f"└ SL có thể không kịp trigger!")
    return send(msg)


def notify_funding_warning(total_funding, equity, threshold_pct):
    """Warning when daily funding cost exceeds threshold."""
    pct = total_funding / equity * 100 if equity > 0 else 0
    msg = (f"💸 <b>CẢNH BÁO FUNDING</b>\n"
           f"├ Funding hôm nay: <b>{_fmt_money(total_funding)}</b>\n"
           f"├ Equity: <b>{_fmt_money(equity)}</b>\n"
           f"├ Tỷ lệ: <b>{pct:.1f}%</b> (ngưỡng {threshold_pct}%)\n"
           f"└ Funding đang ăn mòn lợi nhuận")
    return send(msg)
