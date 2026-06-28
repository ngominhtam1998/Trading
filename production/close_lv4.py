"""Close all positions and cancel all orders for lv4 testnet account only."""
import os, sys, requests, time, hmac, hashlib, urllib3
urllib3.disable_warnings()

BASE = "https://testnet.binancefuture.com"

def get_keys():
    k = os.environ.get("BINANCE_TESTNET_KEY_LV4", "")
    s = os.environ.get("BINANCE_TESTNET_SECRET_LV4", "")
    if not k or not s:
        print("MISSING lv4 keys"); sys.exit(1)
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
    return requests.request(method, url, headers=headers, verify=False, timeout=15)

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

key, secret = get_keys()
print("=== LV4 ===")
r = signed_request(key, secret, "GET", "/fapi/v1/openOrders")
if r.status_code == 200:
    orders = r.json()
    symbols = set(o["symbol"] for o in orders)
    for sym in symbols:
        r = signed_request(key, secret, "DELETE", "/fapi/v1/allOpenOrders", {"symbol": sym})
        print(f"  Cancel orders {sym}: {r.status_code}")

r = signed_request(key, secret, "GET", "/fapi/v2/positionRisk")
if r.status_code != 200:
    print(f"ERROR positions: {r.text[:200]}")
    sys.exit(1)
positions = [p for p in r.json() if float(p.get("positionAmt", 0)) != 0]
if not positions:
    print("No open positions")
else:
    for p in positions:
        symbol = p["symbol"]
        amt = float(p["positionAmt"])
        side = "SELL" if amt > 0 else "BUY"
        qty = abs(amt)
        r = signed_request(key, secret, "POST", "/fapi/v1/order", {
            "symbol": symbol, "side": side, "type": "MARKET",
            "quantity": qty, "reduceOnly": "true",
        })
        print(f"  Close {symbol} qty={qty}: {r.status_code} {r.text[:200]}")
        time.sleep(0.5)
print("Done")
