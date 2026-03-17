"""Quick test to verify API connectivity and run one scan cycle."""

import json
from config import load_config
from exchange import BinanceFuturesClient
from strategy import TradingStrategy

def main():
    trading_config, api_config, log_config = load_config()

    print("=" * 60)
    print(f"Environment: {'TESTNET' if api_config.TESTNET else 'MAINNET'}")
    print(f"Base URL: {api_config.base_url}")
    print(f"API Key: {api_config.API_KEY[:12]}...")
    print("=" * 60)

    client = BinanceFuturesClient(api_config)

    # 1. Test balance
    print("\n--- Account Balance ---")
    try:
        balance = client.get_balance()
        for b in balance:
            bal = float(b.get("balance", 0))
            if bal > 0:
                print(f"  {b['asset']}: {bal:.4f} (available: {float(b.get('availableBalance', 0)):.4f})")
    except Exception as e:
        print(f"  ERROR: {e}")
        return

    # 2. Test market scan
    print("\n--- Market Scan (Top 10 by Volume) ---")
    try:
        tickers = client.get_24hr_tickers()
        usdt_tickers = [t for t in tickers if t["symbol"].endswith("USDT")]
        usdt_tickers.sort(key=lambda t: float(t.get("quoteVolume", 0)), reverse=True)
        top10 = usdt_tickers[:10]

        for i, t in enumerate(top10, 1):
            symbol = t["symbol"]
            vol = float(t.get("quoteVolume", 0))
            change = float(t.get("priceChangePercent", 0))
            price = float(t.get("lastPrice", 0))
            print(f"  {i}. {symbol:12s} | Price: {price:>12.4f} | 24h Vol: {vol:>18,.0f} USDT | 24h Change: {change:>+7.2f}%")

        # Find best candidate
        strategy = TradingStrategy(client, trading_config)
        result = strategy.scan_and_select()
        if result:
            symbol, direction = result
            print(f"\n  >> Selected: {symbol} ({direction})")

            # Get daily levels
            levels = strategy.get_daily_levels(symbol)
            if levels:
                triggers = strategy.compute_entry_triggers(levels, direction)
                print(f"\n--- Entry Plan for {symbol} ({direction}) ---")
                print(f"  Current price:   {levels['current_price']:.6f}")
                print(f"  Prev daily low:  {levels['prev_low']:.6f}")
                print(f"  Prev daily high: {levels['prev_high']:.6f}")
                print(f"  Daily range:     {levels['daily_range']:.6f}")
                print(f"  Entry 1: $10  @ MARKET (immediate)")
                print(f"  Entry 2: $20  @ {triggers[1]:.6f}")
                print(f"  Entry 3: $40  @ {triggers[2]:.6f}")
                print(f"  Take profit: 30% of total invested")
        else:
            print("\n  >> No suitable candidate found this cycle")

    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 60)
    print("Connection test complete!")


if __name__ == "__main__":
    main()
