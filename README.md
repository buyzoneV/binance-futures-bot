# Binance Futures Averaging Bot

A multi-step averaging entry trading bot for Binance USDT-M Futures. It scans the market for high-volume assets with strong recent price movement, enters with a staged scaling strategy based on daily support/resistance levels, and exits at a 30% profit target.

## Strategy Overview

### Asset Selection
1. Scans all USDT-M Futures pairs
2. Identifies the **top 10 by 24h trading volume**
3. Selects the asset with the **largest price movement** in the last 24 hours
4. Supports LONG (buy the dip), SHORT (sell the rip), or BOTH directions

### Entry Structure
| Entry | Amount | Trigger |
|-------|--------|---------|
| 1st   | $10    | Market order (immediate) |
| 2nd   | $20    | Previous daily low (LONG) / high (SHORT) |
| 3rd   | $40    | Below previous daily low (LONG) / above previous daily high (SHORT) |

**Maximum position size: $70**

### Exit Strategy
- Monitors total unrealized PnL across all entries
- Closes the entire position when profit reaches **30% of total invested capital**
- Example: $70 invested → exits at $21 profit

## Setup

### 1. Clone the repository
```bash
git clone https://github.com/YOUR_USERNAME/binance-futures-bot.git
cd binance-futures-bot
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure environment
```bash
cp .env.example .env
# Edit .env with your API credentials
```

### 4. Get Binance API Keys

**For Testnet (recommended first):**
1. Go to [Binance Futures Testnet](https://testnet.binancefuture.com/)
2. Log in with your Binance account
3. Generate API keys from the API management page

**For Live Trading:**
1. Go to [Binance API Management](https://www.binance.com/en/my/settings/api-management)
2. Create a new API key
3. Enable **Futures** permissions
4. Restrict by IP for security

### 5. Run the bot
```bash
python bot.py
```

## Configuration

All settings are in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `BINANCE_API_KEY` | — | Your Binance API key |
| `BINANCE_API_SECRET` | — | Your Binance API secret |
| `BINANCE_TESTNET` | `true` | Use testnet (`true`) or live (`false`) |
| `ENTRY_1_AMOUNT` | `10` | First entry amount in USD |
| `ENTRY_2_AMOUNT` | `20` | Second entry amount in USD |
| `ENTRY_3_AMOUNT` | `40` | Third entry amount in USD |
| `LEVERAGE` | `1` | Leverage multiplier |
| `DIRECTION` | `BOTH` | `LONG`, `SHORT`, or `BOTH` |
| `SCAN_INTERVAL_SECONDS` | `60` | Polling interval in seconds |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

## Architecture

```
binance-futures-bot/
├── bot.py          # Main loop & orchestration
├── strategy.py     # Trading strategy logic (selection, entries, exits)
├── exchange.py     # Binance Futures API client
├── config.py       # Configuration management
├── requirements.txt
├── .env.example
└── README.md
```

### Flow

```
┌──────────────┐     ┌───────────────┐     ┌──────────────┐
│  Scan Market │────▶│ Select Asset  │────▶│ Setup Trade  │
│  (24h data)  │     │ (volume+drop) │     │ (levels)     │
└──────────────┘     └───────────────┘     └──────┬───────┘
                                                   │
                                                   ▼
┌──────────────┐     ┌───────────────┐     ┌──────────────┐
│ Close at 30% │◀────│ Monitor PnL   │◀────│ Entry 1: $10 │
│   profit     │     │ + check lvls  │     │ (market)     │
└──────────────┘     └───────┬───────┘     └──────────────┘
                             │
                     ┌───────┴───────┐
                     │ Entry 2: $20  │  ← at prev daily low/high
                     │ Entry 3: $40  │  ← below/above daily range
                     └───────────────┘
```

## Risk Warning

⚠️ **This bot trades with real money when BINANCE_TESTNET=false.** Always test thoroughly on testnet first. Cryptocurrency futures trading carries significant risk. Use at your own discretion.

## License

MIT
