# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a real-time cryptocurrency arbitrage monitoring dashboard that tracks price gaps ("김치 프리미엄") between Korean exchanges (Upbit, Bithumb) and international exchanges (Binance, Bybit, Bitget, OKX, Gate.io). The application provides:

- Real-time price gap calculations between Upbit and Bithumb (domestic comparison)
- USDT-converted price comparisons with international exchanges (spot and futures)
- Deposit/withdrawal availability tracking for each coin and network
- Daily withdrawal limit monitoring
- WebSocket-based real-time updates

## Development Commands

### Running the Application

```bash
# Install dependencies
pip install -r requirements.txt

# Run the FastAPI server (development)
uvicorn gap_dashboard.main:app --reload

# Run with specific host/port
uvicorn gap_dashboard.main:app --host 0.0.0.0 --port 8000
```

### Environment Configuration

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Required for full functionality:
- `UPBIT_ACCESS_KEY` and `UPBIT_SECRET_KEY` - For withdrawal limits and deposit/withdrawal status
- `BITHUMB_ACCESS_KEY` and `BITHUMB_SECRET_KEY` - Same as above
- `GAP_WS_INTERVAL_SEC` - WebSocket push interval (default: 5 seconds)

The application works without API keys but will not show deposit/withdrawal status or withdrawal limits.

## Architecture

### Core Components

**`gap_dashboard/main.py`** (single-file FastAPI application, ~2400 lines)

The entire backend is in one file organized as follows:

1. **Exchange Symbol Registries** (lines 60-107): Global frozensets and dicts that map Korean exchange symbols to international exchange symbols. Populated once at startup via `_load_exchange_registries_at_startup()`.

2. **WebSocket Price Feeds** (multiple tasks): Background asyncio tasks connect to Binance, Bybit, Bitget, and Gate.io WebSocket streams to maintain real-time USDT prices. These run continuously and update global price dictionaries protected by locks.

3. **Authentication Helpers** (lines 172-227): JWT HS256 token generation for Upbit/Bithumb API authentication (implemented without PyJWT dependency).

4. **Wallet Status Processing** (lines 230-372): Functions to parse deposit/withdrawal availability from exchange wallet APIs, aggregate by currency, and handle network-level details.

5. **Withdrawal Limits Cache** (lines 374-600): Background task system (`_load_withdraw_limits()`) that queries withdrawal limits for each coin from both exchanges. This is rate-limited and runs on-demand via `/api/refresh-limits` endpoint.

6. **Kimchi Premium Calculation** (around line 1700+): Functions to calculate percentage differences between Korean exchange KRW prices (converted to USDT using Upbit's KRW-USDT rate) and international exchange USDT prices.

7. **Gap Computation Engine** (`_compute_gaps_payload()` around line 1982): The main orchestration function that:
   - Fetches current prices from Upbit and Bithumb public APIs
   - Fetches wallet status if API keys are configured
   - Reads real-time USDT prices from WebSocket-maintained dictionaries
   - Computes domestic gaps (Upbit vs Bithumb in KRW)
   - Computes international comparisons (Korean exchanges vs Binance/Bybit/Bitget/Gate.io in USDT)
   - Identifies restricted/blocked coins based on deposit/withdrawal availability
   - Merges withdrawal limit data from cache

8. **API Endpoints**:
   - `GET /api/gaps` (line 2310): HTTP endpoint returning current snapshot
   - `WebSocket /ws/gaps` (line 2320): Streams periodic updates to clients
   - `POST /api/refresh-limits` (line 2353): Triggers background withdrawal limit refresh
   - `GET /api/limits-status` (line 2362): Returns withdrawal limit loading status
   - `GET /` (line 2375): Serves `static/index.html`

**`gap_dashboard/static/index.html`** (single-page application, ~1600 lines)

Pure vanilla JavaScript (no framework), includes:
- WebSocket client with auto-reconnect
- Three tabs: domestic (Upbit × Bithumb), spot comparison, futures comparison
- Real-time table rendering with search/filter/sort
- Modal popups showing coin-specific details (withdrawal limits, network status, international exchange listings)
- Color-coded rows based on deposit/withdrawal availability

### Data Flow

1. **Startup**: `_app_lifespan()` loads symbol registries from all exchanges and spawns WebSocket listener tasks
2. **Background**: WebSocket tasks continuously update `_BINANCE_SPOT_WS_PRICES`, `_BYBIT_LINEAR_WS_PRICES`, etc.
3. **On Request/Timer**: `_compute_gaps_payload()` is called, which fetches fresh Upbit/Bithumb prices, reads cached international prices, and computes all gaps
4. **Client Update**: Result is sent via WebSocket to browser clients every `_GAP_WS_INTERVAL_SEC` seconds

### Key Design Patterns

- **Symbol Mapping**: Korean exchanges use different tickers (e.g., "BTT" vs "BTTC"). `_SYMBOL_MAP` dict handles these mappings.
- **Network Aggregation**: Each coin can have multiple networks (ERC20, TRC20, etc.). The wallet status aggregator checks if "any network is available" for deposit/withdrawal.
- **Lazy Loading**: Withdrawal limits are loaded on-demand (first WebSocket connection or manual refresh) because they require API calls for every coin with rate limiting.
- **Error Resilience**: All exchange API calls use try/except with fallbacks. Missing data is marked as `null` or omitted rather than crashing.

## Important Coding Conventions

### WebSocket Price Updates

When modifying international exchange integrations, remember:
- All price updates must acquire the corresponding lock (`_BINANCE_PRICE_LOCK`, `_BYBIT_PRICE_LOCK`, etc.)
- WebSocket reconnection logic is in each `_binance_spot_ws_loop()`, `_bybit_linear_ws_loop()`, etc.
- Symbol registries are read-only after startup

### Adding New Exchanges

To add a new international exchange:
1. Add global frozensets for bases and symbol mappings (e.g., `_NEWEX_SPOT_USDT_BASES`)
2. Create HTTP fetcher in `_load_exchange_registries_at_startup()` to populate the registry
3. Add WebSocket listener task (e.g., `_newex_spot_ws_loop()`) and global price dict
4. Update `_build_exchange_comparison_rows()` or `_merge_gaps()` to include new exchange symbols
5. Update frontend (`index.html`) to display new exchange data in modal

### API Authentication

Both Upbit and Bithumb require JWT tokens with:
- `access_key`, `nonce` (UUID), and optionally `query_hash` (SHA512 of query params)
- Use `_upbit_auth_header()` or `_upbit_auth_header_with_params()` helpers
- Bithumb additionally requires `timestamp` in payload

### Kimchi Premium Formula

```
김프 % = ((국내 KRW 가격 / 업비트 USDT 환율) - 해외 USDT 가격) / 해외 USDT 가격 × 100
```

Positive = premium (Korean price higher), Negative = reverse premium

## Common Modifications

### Changing WebSocket Update Frequency

Set `GAP_WS_INTERVAL_SEC` in `.env` (minimum 2 seconds enforced)

### Adjusting Rate Limits

Withdrawal limit fetching has `await asyncio.sleep(0.12)` between requests (lines ~470, ~530). Adjust if exchanges complain about rate limiting.

### Filtering Coins

The main table supports client-side filtering (search box, "입출금 이슈만" toggle). Server-side filtering can be added in `_merge_gaps()` before sorting.

## Deployment Notes

- The application is stateless except for in-memory caches (symbol registries, WebSocket prices, withdrawal limits)
- No database required
- WebSocket connections from international exchanges run continuously; ensure stable network
- API keys are optional but recommended for full feature set
- Check `deploy/` directory for systemd service examples (currently empty based on git status)
