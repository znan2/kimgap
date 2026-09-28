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

2. **WebSocket Price Feeds** (multiple tasks): Background asyncio tasks connect to Binance, Bybit, Bitget, OKX, and Gate.io WebSocket streams (public, no API keys) to maintain real-time USDT prices. OKX uses string `"ping"`/`"pong"` keepalive and reconnects if no reply arrives. These run continuously and update global price dictionaries protected by locks.

3. **Authentication Helpers** (lines 172-227): JWT HS256 token generation for Upbit/Bithumb API authentication (implemented without PyJWT dependency).

4. **Wallet Status Processing** (lines 230-372): Functions to parse deposit/withdrawal availability from exchange wallet APIs, aggregate by currency, and handle network-level details.

5. **Withdrawal Info Cache**: `_load_withdraw_limits()` queries `/v1/withdraws/chance` for each coin and keeps **only `can_withdraw` booleans** (no limit/remaining/minimum amounts). It runs from the internal scheduler (`_withdraw_info_loop`, `WITHDRAW_INFO_INTERVAL_SEC`) or the admin-only `POST /api/refresh-limits`.

6. **Kimchi Premium Calculation** (around line 1700+): Functions to calculate percentage differences between Korean exchange KRW prices (converted to USDT using Upbit's KRW-USDT rate) and international exchange USDT prices.

7. **Gap Computation Engine** (`_compute_gaps_payload()`): Called **only by the internal scheduler** (`_payload_refresh_loop`), never per request. It:
   - Fetches current prices from Upbit and Bithumb public APIs
   - Reads wallet status from `_WALLET_CACHE` (filled by `_wallet_status_loop`; private APIs are never called here)
   - Reads real-time USDT prices from WebSocket-maintained dictionaries
   - Computes domestic gaps (Upbit vs Bithumb in KRW)
   - Computes international comparisons (Korean exchanges vs Binance/Bybit/Bitget/OKX/Gate.io in USDT)
   - Identifies restricted/blocked coins based on deposit/withdrawal availability
   - Merges `withdraw_status` (`upbit_can_withdraw` / `bithumb_can_withdraw`) from the withdrawal info cache

8. **API Endpoints** (public ones return the cached payload only; exchange call count is independent of request count):
   - `GET /api/gaps`: latest cached payload (`503` until the first one is ready)
   - `WebSocket /ws/gaps`: pushes the cached payload when it changes; limited by `WS_MAX_CONNECTIONS` / `WS_MAX_PER_IP`
   - `POST /api/refresh-limits`: admin only (`X-Admin-Token` = `ADMIN_TOKEN`, cooldown `ADMIN_REFRESH_COOLDOWN_SEC`); 404 when `ADMIN_TOKEN` is unset
   - `GET /api/limits-status`: admin only, same token rule
   - `GET /`: Serves `static/index.html`
   - `/docs`, `/redoc`, `/openapi.json` are disabled unless `ENABLE_API_DOCS=1`; CORS (GET only) only for `CORS_ALLOW_ORIGINS`; per-IP rate limit `RATE_LIMIT_PER_MIN` (except `/static/*`); gzip for responses ≥ 1KB

**`gap_dashboard/static/index.html`** (single-page application, ~1600 lines)

Pure vanilla JavaScript (no framework), includes:
- WebSocket client with auto-reconnect
- Three tabs: domestic (Upbit × Bithumb), spot comparison, futures comparison
- Real-time table rendering with search/filter/sort
- Modal popups showing coin-specific details (withdrawal availability, network status, international exchange listings)
- Color-coded rows based on deposit/withdrawal availability

### Data Flow

1. **Startup**: `_app_lifespan()` loads symbol registries from all exchanges, spawns WebSocket listener tasks, and starts the internal schedulers (`_start_background_schedulers`)
2. **Background**: WebSocket tasks continuously update `_BINANCE_SPOT_WS_PRICES`, `_BYBIT_LINEAR_WS_PRICES`, etc.; `_wallet_status_loop` refreshes `_WALLET_CACHE`; `_withdraw_info_loop` refreshes the withdrawal info cache
3. **Timer**: `_payload_refresh_loop` calls `_compute_gaps_payload()` every `_GAP_WS_INTERVAL_SEC` seconds and stores `_LATEST_PAYLOAD`
4. **Client Update**: `/api/gaps` and `/ws/gaps` serve `_LATEST_PAYLOAD` (no exchange calls per request)

### Key Design Patterns

- **Symbol Mapping**: Korean exchanges use different tickers (e.g., "BTT" vs "BTTC"). `_SYMBOL_MAP` dict handles these mappings.
- **Network Aggregation**: Each coin can have multiple networks (ERC20, TRC20, etc.). The wallet status aggregator checks if "any network is available" for deposit/withdrawal.
- **Scheduler-only exchange access**: Private APIs (wallet status, withdraw chance) run only in internal schedulers, never per request. Public responses expose error codes (`auth_error`, `rate_limited`, `upstream_error`), not raw upstream messages.
- **Tests**: `python -m pytest` (see `requirements-dev.txt`). Tests set `KIMGAP_SKIP_DOTENV=1` and block all outbound network calls.
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
4. Call `_build_exchange_comparison_rows()` for spot/futures (pass `symbol_format` if the exchange's symbol style differs from `BTCUSDT`, e.g. OKX spot `{base}-USDT` / swap `{base}-USDT-SWAP`, Gate.io `{base}_USDT`) and update `_merge_gaps()` to include new exchange symbols
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
