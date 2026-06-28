"""Emergency close all positions and cancel all orders for all 3 testnet accounts.
Run on VPS: cd /opt/trading/production && python close_all_positions.py
"""
import os, sys, requests, time, hmac, hashlib, urllib3
urllib3.disable_warnings()

BASE = "https://testnet.binancefuture.com"

def get_keys(lv):
    k = os.environ.get(f"BINANCE_TESTNET_KEY_{lv.upper()}", "")
    s = os.environ.get(f"BINANCE_TESTNET_SECRET_{lv.upper()}", "")
    if not k or not s:
        print(f"MISSING keys for {lv}")
        return None, None
    return k, s

def signed_request(key, secret, method, path, params=None):
    params = params or {}
    params["timestamp"] = int(time.time() * 1000) + 1000
    params["recvWindow"] = 5000
    qs = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    sig = hmac.new(secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
    qs += f"&signature={sig}"
    url = f"{BASE}{path}?{qs}"
    headers = {"X-MBX-APIKEY": key}
    r = requests.request(method, url, headers=headers, verify=False, timeout=15)
    return r

def close_account(lv):
    key, secret = get_keys(lv)
    if not key:
        return
    print(f"\n=== {lv.upper()} ===")
    
    # 1. Cancel all open orders per symbol
    r = signed_request(key, secret, "GET", "/fapi/v1/openOrders")
    if r.status_code == 200:
        orders = r.json()
        symbols = set(o["symbol"] for o in orders)
        for sym in symbols:
            r = signed_request(key, secret, "DELETE", "/fapi/v1/allOpenOrders", {"symbol": sym})
            print(f"  Cancel orders {sym}: {r.status_code}")
    else:
        print(f"  ERROR listing orders: {r.text[:200]}")
    
    # 2. Get positions
    r = signed_request(key, secret, "GET", "/fapi/v2/positionRisk")
    if r.status_code != 200:
        print(f"  ERROR getting positions: {r.text[:200]}")
        return
    positions = [p for p in r.json() if float(p.get("positionAmt", 0)) != 0]
    if not positions:
        print(f"  No open positions")
        return
    
    print(f"  Found {len(positions)} open positions")
    for p in positions:
        symbol = p["symbol"]
        amt = float(p["positionAmt"])
        side = "SELL" if amt > 0 else "BUY"
        qty = abs(amt)
        print(f"  Closing {symbol} qty={qty} ({side})")
        r = signed_request(key, secret, "POST", "/fapi/v1/order", {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": qty,
            "reduceOnly": "true",
        })
        print(f"    -> {r.status_code} {r.text[:200]}")
        time.sleep(0.5)

if __name__ == "__main__":
    # Load .env from live/.env
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "live", ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip(); v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    
    for lv in ["lv4", "lv5", "lv6"]:
        close_account(lv)
    print("\nDone.")
