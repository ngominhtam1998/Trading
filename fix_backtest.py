import glob
files = glob.glob('production/strategy_aggressive*.py')
for fn in files:
    with open(fn, 'r', encoding='utf-8') as f:
        text = f.read()
    text = text.replace('url = "https://api.binance.com/api/v3/klines"', 'url = "https://fapi.binance.com/fapi/v1/klines"')
    text = text.replace('FEE_PCT = 0.01', 'FEE_PCT = 0.02')
    with open(fn, 'w', encoding='utf-8') as f:
        f.write(text)
    print(f"Updated {fn}")
