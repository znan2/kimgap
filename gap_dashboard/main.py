"""
업비트 vs 빗썸 KRW 마켓 실시간 가격 갭 API.
공개 시세 + (선택) API 키가 있으면 입출금 상태(/v1/status/wallet) 병합.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import websockets
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

UPBIT_MARKET = "https://api.upbit.com/v1/market/all"
UPBIT_TICKER = "https://api.upbit.com/v1/ticker"
UPBIT_WALLET = "https://api.upbit.com/v1/status/wallet"
BITHUMB_ALL_KRW = "https://api.bithumb.com/public/ticker/ALL_KRW"
BITHUMB_WALLET = "https://api.bithumb.com/v1/status/wallet"
BINANCE_TICKER = "https://api.binance.com/api/v3/ticker/price"
BINANCE_FAPI_TICKER = "https://fapi.binance.com/fapi/v1/ticker/price"
BINANCE_EXCHANGE_INFO = "https://api.binance.com/api/v3/exchangeInfo"
BINANCE_FAPI_EXCHANGE_INFO = "https://fapi.binance.com/fapi/v1/exchangeInfo"
BINANCE_SPOT_TICKER_WS = "wss://stream.binance.com:9443/ws/!ticker@arr"
BINANCE_FAPI_TICKER_WS = "wss://fstream.binance.com/ws/!ticker@arr"
BYBIT_INSTRUMENTS = "https://api.bybit.com/v5/market/instruments-info"
BYBIT_TICKERS = "https://api.bybit.com/v5/market/tickers"
BYBIT_SPOT_WS = "wss://stream.bybit.com/v5/public/spot"
BYBIT_LINEAR_WS = "wss://stream.bybit.com/v5/public/linear"
BITGET_SPOT_SYMBOLS = "https://api.bitget.com/api/v2/spot/public/symbols"
BITGET_USDT_FUTURES = "https://api.bitget.com/api/v2/mix/market/contracts"
BITGET_SPOT_TICKERS = "https://api.bitget.com/api/v2/spot/market/tickers"
BITGET_USDT_FUTURES_TICKERS = "https://api.bitget.com/api/v2/mix/market/tickers"
BITGET_WS = "wss://ws.bitget.com/v2/ws/public"
OKX_INSTRUMENTS = "https://www.okx.com/api/v5/public/instruments"
OKX_TICKERS = "https://www.okx.com/api/v5/market/tickers"
GATE_SPOT_PAIRS = "https://api.gateio.ws/api/v4/spot/currency_pairs"
GATE_USDT_CONTRACTS = "https://api.gateio.ws/api/v4/futures/usdt/contracts"
GATE_SPOT_TICKERS = "https://api.gateio.ws/api/v4/spot/tickers"
GATE_USDT_FUTURES_TICKERS = "https://api.gateio.ws/api/v4/futures/usdt/tickers"
GATE_WS = "wss://api.gateio.ws/ws/v4/"
UPBIT_WITHDRAW_CHANCE = "https://api.upbit.com/v1/withdraws/chance"
BITHUMB_WITHDRAW_CHANCE = "https://api.bithumb.com/v1/withdraws/chance"

# 업비트/빗썸 심볼 → 바이낸스 심볼 매핑 (서로 다른 경우만)
_SYMBOL_MAP: dict[str, str] = {
    "BTT": "BTTC",
    "LUNA2": "LUNA",
    "BORA": "BORA",
}
# 바이낸스 SPOT·USDT: uvicorn 기동 시 exchangeInfo 1회로 채움(프로세스 종료까지 유지)
_BINANCE_SPOT_USDT_BASES: frozenset[str] = frozenset()
_BINANCE_SPOT_USDT_SYMBOL_BY_BASE: dict[str, str] = {}
_BINANCE_SPOT_WS_PRICES: dict[str, float] = {}
# USDT-M 무기한 선물(FAPI): 기동 시 1회
_BINANCE_FUT_USDT_PERP_BASES: frozenset[str] = frozenset()
_BINANCE_FUT_USDT_PERP_SYMBOL_BY_BASE: dict[str, str] = {}
_BINANCE_FUT_WS_PRICES: dict[str, float] = {}
_BINANCE_PRICE_LOCK = asyncio.Lock()
_BINANCE_WS_TASKS: list[asyncio.Task[None]] = []
# Bybit v5: 기동 시 instruments-info (spot / linear 무기한)
_BYBIT_SPOT_USDT_BASES: frozenset[str] = frozenset()
_BYBIT_SPOT_USDT_SYMBOL_BY_BASE: dict[str, str] = {}
_BYBIT_SPOT_WS_PRICES: dict[str, float] = {}
_BYBIT_LINEAR_USDT_PERP_BASES: frozenset[str] = frozenset()
_BYBIT_LINEAR_USDT_PERP_SYMBOL_BY_BASE: dict[str, str] = {}
_BYBIT_LINEAR_WS_PRICES: dict[str, float] = {}
_BYBIT_PRICE_LOCK = asyncio.Lock()
_BYBIT_WS_TASKS: list[asyncio.Task[None]] = []
# Bitget
_BITGET_SPOT_USDT_BASES: frozenset[str] = frozenset()
_BITGET_SPOT_USDT_SYMBOL_BY_BASE: dict[str, str] = {}
_BITGET_SPOT_WS_PRICES: dict[str, float] = {}
_BITGET_USDT_PERP_BASES: frozenset[str] = frozenset()
_BITGET_USDT_PERP_SYMBOL_BY_BASE: dict[str, str] = {}
_BITGET_USDT_PERP_WS_PRICES: dict[str, float] = {}
_BITGET_PRICE_LOCK = asyncio.Lock()
_BITGET_WS_TASKS: list[asyncio.Task[None]] = []
# OKX
_OKX_SPOT_USDT_BASES: frozenset[str] = frozenset()
_OKX_SPOT_USDT_SYMBOL_BY_BASE: dict[str, str] = {}
_OKX_SWAP_USDT_BASES: frozenset[str] = frozenset()
_OKX_SWAP_USDT_SYMBOL_BY_BASE: dict[str, str] = {}
# Gate.io
_GATE_SPOT_USDT_BASES: frozenset[str] = frozenset()
_GATE_SPOT_USDT_SYMBOL_BY_BASE: dict[str, str] = {}
_GATE_SPOT_WS_PRICES: dict[str, float] = {}
_GATE_USDT_PERP_BASES: frozenset[str] = frozenset()
_GATE_USDT_PERP_SYMBOL_BY_BASE: dict[str, str] = {}
_GATE_USDT_PERP_WS_PRICES: dict[str, float] = {}
_GATE_PRICE_LOCK = asyncio.Lock()
_GATE_WS_TASKS: list[asyncio.Task[None]] = []

STATIC_DIR = Path(__file__).resolve().parent / "static"
_ROOT = Path(__file__).resolve().parent.parent

# WebSocket `/ws/gaps` 푸시 주기(초). 환경변수 `GAP_WS_INTERVAL_SEC`로 덮어쓸 수 있음.
_GAP_WS_INTERVAL_SEC = max(2.0, float(os.getenv("GAP_WS_INTERVAL_SEC", "5")))


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if (
                len(value) >= 2
                and ((value[0] == "'" and value[-1] == "'") or (value[0] == '"' and value[-1] == '"'))
            ):
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass


_load_env_file(Path.cwd() / ".env")
_load_env_file(_ROOT / ".env")
_load_env_file(Path(__file__).resolve().parent / ".env")

UPBIT_ACCESS_KEY = os.getenv("UPBIT_ACCESS_KEY", "")
UPBIT_SECRET_KEY = os.getenv("UPBIT_SECRET_KEY", "")
BITHUMB_ACCESS_KEY = os.getenv("BITHUMB_ACCESS_KEY", "")
BITHUMB_SECRET_KEY = os.getenv("BITHUMB_SECRET_KEY", "")

_LOG = logging.getLogger(__name__)


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    await _load_exchange_registries_at_startup()
    _start_binance_ws_tasks()
    _start_bybit_ws_tasks()
    _start_bitget_ws_tasks()
    _start_gate_ws_tasks()
    yield
    await _stop_binance_ws_tasks()
    await _stop_bybit_ws_tasks()
    await _stop_bitget_ws_tasks()
    await _stop_gate_ws_tasks()


app = FastAPI(title="Upbit–Bithumb gap dashboard", lifespan=_app_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _b64url_json(obj: dict[str, Any]) -> str:
    raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _jwt_hs256_encode(payload: dict[str, Any], secret: str) -> str:
    """PyJWT 없이 HS256 JWT 생성 (업비트/빗썸 인증용)."""
    header = {"alg": "HS256", "typ": "JWT"}
    h = _b64url_json(header)
    p = _b64url_json(payload)
    signing_input = f"{h}.{p}".encode("ascii")
    key = secret.encode("utf-8")
    sig = hmac.new(key, signing_input, hashlib.sha256).digest()
    s = base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")
    return f"{h}.{p}.{s}"


def _upbit_auth_header() -> dict[str, str]:
    payload = {"access_key": UPBIT_ACCESS_KEY, "nonce": str(uuid.uuid4())}
    token = _jwt_hs256_encode(payload, UPBIT_SECRET_KEY)
    return {"Authorization": f"Bearer {token}"}


def _bithumb_auth_header() -> dict[str, str]:
    payload = {
        "access_key": BITHUMB_ACCESS_KEY,
        "nonce": str(uuid.uuid4()),
        "timestamp": int(time.time() * 1000),
    }
    token = _jwt_hs256_encode(payload, BITHUMB_SECRET_KEY)
    return {"Authorization": f"Bearer {token}"}


def _upbit_auth_header_with_params(params: dict[str, str]) -> dict[str, str]:
    qs = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    qh = hashlib.sha512(qs.encode()).hexdigest()
    payload = {
        "access_key": UPBIT_ACCESS_KEY,
        "nonce": str(uuid.uuid4()),
        "query_hash": qh,
        "query_hash_alg": "SHA512",
    }
    return {"Authorization": f"Bearer {_jwt_hs256_encode(payload, UPBIT_SECRET_KEY)}"}


def _bithumb_auth_header_with_params(params: dict[str, str]) -> dict[str, str]:
    qs = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    qh = hashlib.sha512(qs.encode()).hexdigest()
    payload = {
        "access_key": BITHUMB_ACCESS_KEY,
        "nonce": str(uuid.uuid4()),
        "timestamp": int(time.time() * 1000),
        "query_hash": qh,
        "query_hash_alg": "SHA512",
    }
    return {"Authorization": f"Bearer {_jwt_hs256_encode(payload, BITHUMB_SECRET_KEY)}"}


def _deposit_withdraw_ok_from_wallet_state(wallet_state: str | None) -> tuple[bool, bool]:
    ws = str(wallet_state or "unknown").lower()
    deposit_ok = ws in ("working", "deposit_only")
    withdraw_ok = ws in ("working", "withdraw_only")
    return deposit_ok, withdraw_ok


def _boolish_ok(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "working", "active", "normal")
    if value is None:
        return default
    return default


def _parse_upbit_wallet_rows(raw: list[dict]) -> list[tuple[str, bool, bool]]:
    out: list[tuple[str, bool, bool]] = []
    for item in raw:
        cur = str(item.get("currency", "")).upper()
        if not cur:
            continue
        d, w = _deposit_withdraw_ok_from_wallet_state(item.get("wallet_state"))
        # 체인 동기화 중단 시 거래소는 입출금을 막는 경우가 많음 (wallet_state는 working일 수 있음)
        bs = str(item.get("block_state") or "normal").lower()
        if bs == "inactive":
            d, w = False, False
        out.append((cur, d, w))
    return out


def _parse_bithumb_wallet_rows(raw: list[dict]) -> list[tuple[str, bool, bool]]:
    out: list[tuple[str, bool, bool]] = []
    for item in raw:
        cur = str(
            item.get("currency") or item.get("coin_code") or item.get("asset_code") or ""
        ).upper()
        if not cur:
            continue
        ws = item.get("wallet_state")
        if ws is not None:
            d, w = _deposit_withdraw_ok_from_wallet_state(ws)
        else:
            d = _boolish_ok(item.get("deposit_status", item.get("deposit_state")), True)
            w = _boolish_ok(item.get("withdrawal_status", item.get("withdraw_state")), True)
        bs = str(item.get("block_status") or item.get("block_state") or "normal").lower()
        if bs == "inactive":
            d, w = False, False
        out.append((cur, d, w))
    return out


def _aggregate_pause_by_currency(
    rows: list[tuple[str, bool, bool]],
) -> dict[str, dict[str, bool]]:
    """
    코인별로 네트워크(행) 단위 입출금 가능 여부를 모은 뒤:
    - all_networks_full_pause: 모든 행에서 입금·출금 둘 다 불가
    - any_network_full_pause: 어떤 행이라도 입금·출금 둘 다 불가
    - any_network_restricted: 한 행이라도 양방향 동시 이용 불가
      (paused, deposit_only, withdraw_only, unsupported 등 → 입·출금 둘 다 True가 아님)
    """
    by_c: dict[str, list[tuple[bool, bool]]] = defaultdict(list)
    for cur, d_ok, w_ok in rows:
        by_c[cur].append((d_ok, w_ok))

    out: dict[str, dict[str, bool]] = {}
    for cur, lst in by_c.items():
        row_full_pause = [not d and not w for d, w in lst]
        row_restricted = [not (d and w) for d, w in lst]
        out[cur] = {
            "all_networks_full_pause": bool(lst) and all(row_full_pause),
            "any_network_full_pause": bool(lst) and any(row_full_pause),
            "any_network_restricted": bool(lst) and any(row_restricted),
            # 네트워크가 여러 개일 때: 하나라도 해당 방향이 열려 있으면 가능
            "deposit_available": bool(lst) and any(d for d, _w in lst),
            "withdraw_available": bool(lst) and any(w for _d, w in lst),
        }
    return out


def _upbit_network_row(item: dict[str, Any]) -> dict[str, Any]:
    net = str(item.get("net_type") or item.get("network") or "").strip() or "—"
    d, w = _deposit_withdraw_ok_from_wallet_state(item.get("wallet_state"))
    bs = str(item.get("block_state") or "normal").lower()
    if bs == "inactive":
        d, w = False, False
    return {
        "net_type": net,
        "deposit_available": d,
        "withdraw_available": w,
        "wallet_state": item.get("wallet_state"),
        "block_state": item.get("block_state"),
    }


def _bithumb_network_row(item: dict[str, Any]) -> dict[str, Any]:
    net = str(
        item.get("net_type")
        or item.get("network")
        or item.get("network_name")
        or ""
    ).strip() or "—"
    ws = item.get("wallet_state")
    if ws is not None:
        d, w = _deposit_withdraw_ok_from_wallet_state(ws)
    else:
        d = _boolish_ok(item.get("deposit_status", item.get("deposit_state")), True)
        w = _boolish_ok(item.get("withdrawal_status", item.get("withdraw_state")), True)
    bs = str(item.get("block_status") or item.get("block_state") or "normal").lower()
    if bs == "inactive":
        d, w = False, False
    return {
        "net_type": net,
        "deposit_available": d,
        "withdraw_available": w,
        "wallet_state": ws,
        "block_state": item.get("block_status") or item.get("block_state"),
    }


def _group_upbit_networks_by_currency(raw: list[dict]) -> dict[str, list[dict[str, Any]]]:
    by_c: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in raw:
        cur = str(item.get("currency", "")).upper()
        if not cur:
            continue
        by_c[cur].append(_upbit_network_row(item))
    return dict(by_c)


def _group_bithumb_networks_by_currency(raw: list[dict]) -> dict[str, list[dict[str, Any]]]:
    by_c: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in raw:
        cur = str(
            item.get("currency") or item.get("coin_code") or item.get("asset_code") or ""
        ).upper()
        if not cur:
            continue
        by_c[cur].append(_bithumb_network_row(item))
    return dict(by_c)


# ── Withdrawal-limit cache ──────────────────────────────────
_wl_cache: dict[str, dict[str, Any]] = {}
_wl_ts: float = 0
_wl_loading: bool = False
_wl_status: str = "idle"
_wl_progress: str = ""
_wl_task: asyncio.Task[None] | None = None
_wl_last_error: str = ""
_wl_stats: dict[str, int] = {
    "upbit_attempted": 0,
    "upbit_success": 0,
    "bithumb_attempted": 0,
    "bithumb_success": 0,
}


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


async def _load_withdraw_limits() -> None:
    global _wl_cache, _wl_ts, _wl_loading, _wl_status, _wl_progress, _wl_last_error, _wl_stats
    if _wl_loading:
        return
    _wl_loading = True
    _wl_status = "loading"
    _wl_progress = "시작"
    _wl_last_error = ""
    _wl_stats = {
        "upbit_attempted": 0,
        "upbit_success": 0,
        "bithumb_attempted": 0,
        "bithumb_success": 0,
    }
    result: dict[str, dict[str, Any]] = {}
    first_error: str | None = None

    try:
        async with httpx.AsyncClient(headers={"Accept": "application/json"}) as client:
            # ── Upbit ──
            if UPBIT_ACCESS_KEY and UPBIT_SECRET_KEY:
                _wl_progress = "업비트 지갑 목록 조회"
                try:
                    r = await client.get(
                        UPBIT_WALLET, headers=_upbit_auth_header(), timeout=20
                    )
                    r.raise_for_status()
                    up_wallet: list[dict] = r.json() if isinstance(r.json(), list) else []
                except Exception as e:
                    if first_error is None:
                        first_error = f"업비트 지갑 목록 조회 실패: {type(e).__name__}"
                    _LOG.warning("업비트 지갑 목록 조회 실패: %s", e)
                    up_wallet = []

                cur_net: dict[str, str] = {}
                for item in up_wallet:
                    cur = str(item.get("currency", "")).upper()
                    nt = str(item.get("net_type", ""))
                    if cur and nt and cur not in cur_net and cur != "KRW":
                        cur_net[cur] = nt

                total = len(cur_net)
                for idx, (cur, nt) in enumerate(cur_net.items()):
                    _wl_progress = f"업비트 {idx + 1}/{total} ({cur})"
                    params = {"currency": cur, "net_type": nt}
                    _wl_stats["upbit_attempted"] += 1
                    try:
                        headers = _upbit_auth_header_with_params(params)
                        r = await client.get(
                            UPBIT_WITHDRAW_CHANCE,
                            headers=headers,
                            params=params,
                            timeout=10,
                        )
                        if r.status_code == 403:
                            _wl_progress = "업비트 출금조회 권한 없음"
                            if first_error is None:
                                first_error = "업비트 출금조회 권한 없음(403)"
                            break
                        r.raise_for_status()
                        wl = r.json().get("withdraw_limit", {})
                        result.setdefault(cur, {})
                        result[cur]["upbit_daily"] = _safe_float(wl.get("daily"))
                        result[cur]["upbit_remaining_krw"] = _safe_float(
                            wl.get("remaining_daily_krw")
                        )
                        result[cur]["upbit_min"] = _safe_float(wl.get("minimum"))
                        _wl_stats["upbit_success"] += 1
                    except Exception as e:
                        if first_error is None:
                            first_error = f"업비트 {cur} 한도 조회 실패: {type(e).__name__}"
                    await asyncio.sleep(0.12)

            # ── Bithumb ──
            if BITHUMB_ACCESS_KEY and BITHUMB_SECRET_KEY:
                _wl_progress = "빗썸 지갑 목록 조회"
                try:
                    r = await client.get(
                        BITHUMB_WALLET, headers=_bithumb_auth_header(), timeout=20
                    )
                    r.raise_for_status()
                    bh_wallet: list[dict] = r.json() if isinstance(r.json(), list) else []
                except Exception as e:
                    if first_error is None:
                        first_error = f"빗썸 지갑 목록 조회 실패: {type(e).__name__}"
                    _LOG.warning("빗썸 지갑 목록 조회 실패: %s", e)
                    bh_wallet = []

                bh_cur_net: dict[str, str] = {}
                for item in bh_wallet:
                    cur = str(
                        item.get("currency") or item.get("coin_code") or ""
                    ).upper()
                    nt = str(item.get("net_type") or item.get("network") or "")
                    if cur and nt and cur not in bh_cur_net and cur != "KRW":
                        bh_cur_net[cur] = nt

                total = len(bh_cur_net)
                for idx, (cur, nt) in enumerate(bh_cur_net.items()):
                    _wl_progress = f"빗썸 {idx + 1}/{total} ({cur})"
                    params = {"currency": cur, "net_type": nt}
                    _wl_stats["bithumb_attempted"] += 1
                    try:
                        headers = _bithumb_auth_header_with_params(params)
                        r = await client.get(
                            BITHUMB_WITHDRAW_CHANCE,
                            headers=headers,
                            params=params,
                            timeout=10,
                        )
                        if r.status_code in (401, 403):
                            _wl_progress = "빗썸 출금조회 권한 없음"
                            if first_error is None:
                                first_error = f"빗썸 출금조회 권한 없음({r.status_code})"
                            break
                        r.raise_for_status()
                        wl = r.json().get("withdraw_limit", {})
                        result.setdefault(cur, {})
                        result[cur]["bithumb_daily"] = _safe_float(wl.get("daily"))
                        result[cur]["bithumb_min"] = _safe_float(wl.get("minimum"))
                        _wl_stats["bithumb_success"] += 1
                    except Exception as e:
                        if first_error is None:
                            first_error = f"빗썸 {cur} 한도 조회 실패: {type(e).__name__}"
                    await asyncio.sleep(0.22)

        _wl_cache = result
        _wl_ts = time.time()
        _wl_status = "done"
        if len(result) == 0 and first_error:
            _wl_last_error = first_error
            _wl_progress = f"완료 (0개) · {first_error}"
        else:
            _wl_progress = f"완료 ({len(result)}개)"
    except Exception as e:
        _wl_status = "error"
        _wl_last_error = f"{type(e).__name__}: {str(e)[:120]}"
        _wl_progress = _wl_last_error
        _LOG.warning("출금한도 로더 실패: %s", e)
    finally:
        _wl_loading = False


async def _fetch_upbit_krw_prices(client: httpx.AsyncClient) -> dict[str, float]:
    r = await client.get(UPBIT_MARKET, params={"isDetails": "false"}, timeout=30.0)
    r.raise_for_status()
    markets = [m["market"] for m in r.json() if str(m.get("market", "")).startswith("KRW-")]
    prices: dict[str, float] = {}
    chunk_size = 100
    for i in range(0, len(markets), chunk_size):
        chunk = markets[i : i + chunk_size]
        url = f"{UPBIT_TICKER}?markets={','.join(chunk)}"
        tr = await client.get(url, timeout=30.0)
        tr.raise_for_status()
        for row in tr.json():
            market = str(row.get("market", ""))
            if not market.startswith("KRW-"):
                continue
            sym = market[4:].upper()
            tp = row.get("trade_price")
            if tp is not None:
                prices[sym] = float(tp)
        await asyncio.sleep(0.05)
    return prices


async def _fetch_bithumb_krw_prices(client: httpx.AsyncClient) -> dict[str, float]:
    r = await client.get(BITHUMB_ALL_KRW, timeout=30.0)
    r.raise_for_status()
    body = r.json()
    if str(body.get("status")) != "0000":
        raise ValueError(f"bithumb status: {body.get('status')}")
    data = body.get("data") or {}
    out: dict[str, float] = {}
    for key, val in data.items():
        if key == "date" or not isinstance(val, dict):
            continue
        cp = val.get("closing_price")
        if cp is not None:
            out[str(key).upper()] = float(cp)
    return out


async def _fetch_usdt_krw_rate(client: httpx.AsyncClient) -> float | None:
    """업비트 KRW-USDT 체결가를 USDT/KRW 환율로 사용."""
    try:
        r = await client.get(UPBIT_TICKER, params={"markets": "KRW-USDT"}, timeout=10.0)
        r.raise_for_status()
        data = r.json()
        if data and isinstance(data, list) and data[0].get("trade_price"):
            return float(data[0]["trade_price"])
    except Exception:
        pass
    return None


async def _fetch_binance_usdt_prices(client: httpx.AsyncClient) -> dict[str, float]:
    """바이낸스 전체 ticker에서 USDT 페어만 가져온다 (1회 호출)."""
    try:
        r = await client.get(BINANCE_TICKER, timeout=15.0)
        r.raise_for_status()
        out: dict[str, float] = {}
        for item in r.json():
            sym = str(item.get("symbol", ""))
            if sym.endswith("USDT"):
                base = sym[:-4].upper()
                price = float(item.get("price", 0))
                if price > 0:
                    out[base] = price
        return out
    except Exception:
        return {}


async def _fetch_binance_futures_usdt_prices(client: httpx.AsyncClient) -> dict[str, float]:
    """바이낸스 USD-M ticker에서 USDT 무기한 선물 가격만 가져온다."""
    try:
        r = await client.get(BINANCE_FAPI_TICKER, timeout=15.0)
        r.raise_for_status()
        out: dict[str, float] = {}
        for item in r.json():
            sym = str(item.get("symbol", "")).upper()
            if not sym.endswith("USDT"):
                continue
            base = sym[:-4].upper()
            if _BINANCE_FUT_USDT_PERP_BASES and base not in _BINANCE_FUT_USDT_PERP_BASES:
                continue
            price = float(item.get("price", 0))
            if price > 0:
                out[base] = price
        return out
    except Exception:
        return {}


async def _binance_ws_ticker_loop(
    *,
    name: str,
    url: str,
    target: dict[str, float],
    allowed_bases_getter,
) -> None:
    """Binance all-ticker WebSocket을 메모리 가격 캐시로 유지한다."""
    while True:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                async for raw in ws:
                    try:
                        items = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(items, list):
                        continue
                    allowed = allowed_bases_getter()
                    updates: dict[str, float] = {}
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        sym = str(item.get("s") or "").upper()
                        if not sym.endswith("USDT"):
                            continue
                        base = sym[:-4]
                        if allowed and base not in allowed:
                            continue
                        price = _safe_float(item.get("c"))
                        if price and price > 0:
                            updates[base] = price
                    if updates:
                        async with _BINANCE_PRICE_LOCK:
                            target.update(updates)
        except asyncio.CancelledError:
            break
        except Exception as e:
            _LOG.warning("Binance %s WebSocket 재연결 대기: %s", name, e)
            try:
                await asyncio.sleep(3.0)
            except asyncio.CancelledError:
                break


def _start_binance_ws_tasks() -> None:
    global _BINANCE_WS_TASKS
    if _BINANCE_WS_TASKS:
        return
    _BINANCE_WS_TASKS = [
        asyncio.create_task(
            _binance_ws_ticker_loop(
                name="spot",
                url=BINANCE_SPOT_TICKER_WS,
                target=_BINANCE_SPOT_WS_PRICES,
                allowed_bases_getter=lambda: _BINANCE_SPOT_USDT_BASES,
            )
        ),
        asyncio.create_task(
            _binance_ws_ticker_loop(
                name="futures",
                url=BINANCE_FAPI_TICKER_WS,
                target=_BINANCE_FUT_WS_PRICES,
                allowed_bases_getter=lambda: _BINANCE_FUT_USDT_PERP_BASES,
            )
        ),
    ]


async def _stop_binance_ws_tasks() -> None:
    global _BINANCE_WS_TASKS
    tasks = _BINANCE_WS_TASKS
    _BINANCE_WS_TASKS = []
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass


async def _binance_price_snapshots(
    client: httpx.AsyncClient,
) -> tuple[dict[str, float], dict[str, float]]:
    """WebSocket 캐시를 우선 사용하고, 초기 수신 전에는 REST로 한 번 보강한다."""
    async with _BINANCE_PRICE_LOCK:
        spot = dict(_BINANCE_SPOT_WS_PRICES)
        futures = dict(_BINANCE_FUT_WS_PRICES)
    if not spot:
        spot = await _fetch_binance_usdt_prices(client)
    if not futures:
        futures = await _fetch_binance_futures_usdt_prices(client)
    return spot, futures


async def _fetch_bybit_linear_usdt_prices(client: httpx.AsyncClient) -> dict[str, float]:
    """Bybit linear tickers에서 USDT 무기한 가격(베이스→가격)."""
    out: dict[str, float] = {}
    try:
        r = await client.get(BYBIT_TICKERS, params={"category": "linear"}, timeout=45.0)
        r.raise_for_status()
        body = r.json()
        result = body.get("result") if isinstance(body, dict) else None
        items = result.get("list") if isinstance(result, dict) else None
        if not isinstance(items, list):
            return out
        for item in items:
            if not isinstance(item, dict):
                continue
            sym = str(item.get("symbol") or "").upper()
            if not sym.endswith("USDT"):
                continue
            base = sym[: -len("USDT")]
            if _BYBIT_LINEAR_USDT_PERP_BASES and base not in _BYBIT_LINEAR_USDT_PERP_BASES:
                continue
            try:
                price = float(item.get("lastPrice") or 0)
            except Exception:
                continue
            if price > 0 and base not in out:
                out[base] = price
    except Exception as e:
        _LOG.info("Bybit linear tickers 로드 실패: %s", e)
    return out


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[i : i + size] for i in range(0, len(values), size)]


async def _bybit_ws_ticker_loop(
    *,
    name: str,
    url: str,
    symbol_by_base_getter,
    target: dict[str, float],
) -> None:
    """Bybit v5 public ticker를 심볼별로 구독해 메모리 가격 캐시로 유지한다."""
    while True:
        try:
            symbol_by_base = symbol_by_base_getter()
            if not symbol_by_base:
                await asyncio.sleep(5.0)
                continue
            symbol_to_base = {sym: base for base, sym in symbol_by_base.items()}
            topics = [f"tickers.{sym}" for sym in sorted(symbol_to_base)]
            async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                for topic_chunk in _chunks(topics, 50):
                    await ws.send(
                        json.dumps(
                            {
                                "op": "subscribe",
                                "args": topic_chunk,
                            }
                        )
                    )
                    await asyncio.sleep(0.05)
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    data = msg.get("data") if isinstance(msg, dict) else None
                    if isinstance(data, list):
                        items = data
                    elif isinstance(data, dict):
                        items = [data]
                    else:
                        continue
                    updates: dict[str, float] = {}
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        sym = str(item.get("symbol") or "").upper()
                        base = symbol_to_base.get(sym)
                        if not base:
                            continue
                        price = _safe_float(item.get("lastPrice"))
                        if price and price > 0:
                            updates[base] = price
                    if updates:
                        async with _BYBIT_PRICE_LOCK:
                            target.update(updates)
        except asyncio.CancelledError:
            break
        except Exception as e:
            _LOG.warning("Bybit %s WebSocket 재연결 대기: %s", name, e)
            try:
                await asyncio.sleep(3.0)
            except asyncio.CancelledError:
                break


def _start_bybit_ws_tasks() -> None:
    global _BYBIT_WS_TASKS
    if _BYBIT_WS_TASKS:
        return
    _BYBIT_WS_TASKS = [
        asyncio.create_task(
            _bybit_ws_ticker_loop(
                name="spot",
                url=BYBIT_SPOT_WS,
                symbol_by_base_getter=lambda: _BYBIT_SPOT_USDT_SYMBOL_BY_BASE,
                target=_BYBIT_SPOT_WS_PRICES,
            )
        ),
        asyncio.create_task(
            _bybit_ws_ticker_loop(
                name="linear",
                url=BYBIT_LINEAR_WS,
                symbol_by_base_getter=lambda: _BYBIT_LINEAR_USDT_PERP_SYMBOL_BY_BASE,
                target=_BYBIT_LINEAR_WS_PRICES,
            )
        ),
    ]


async def _stop_bybit_ws_tasks() -> None:
    global _BYBIT_WS_TASKS
    tasks = _BYBIT_WS_TASKS
    _BYBIT_WS_TASKS = []
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass


async def _bybit_price_snapshots(
    client: httpx.AsyncClient,
) -> tuple[dict[str, float], dict[str, float]]:
    async with _BYBIT_PRICE_LOCK:
        spot = dict(_BYBIT_SPOT_WS_PRICES)
        linear = dict(_BYBIT_LINEAR_WS_PRICES)
    spot_min = max(100, int(len(_BYBIT_SPOT_USDT_SYMBOL_BY_BASE) * 0.8))
    linear_min = max(100, int(len(_BYBIT_LINEAR_USDT_PERP_SYMBOL_BY_BASE) * 0.8))
    if len(spot) < spot_min:
        rest_spot = await _fetch_bybit_usdt_spot_prices(client)
        if rest_spot:
            spot = {**rest_spot, **spot}
            async with _BYBIT_PRICE_LOCK:
                _BYBIT_SPOT_WS_PRICES.update(rest_spot)
    if len(linear) < linear_min:
        rest_linear = await _fetch_bybit_linear_usdt_prices(client)
        if rest_linear:
            linear = {**rest_linear, **linear}
            async with _BYBIT_PRICE_LOCK:
                _BYBIT_LINEAR_WS_PRICES.update(rest_linear)
    return spot, linear


async def _fetch_bybit_usdt_spot_prices(client: httpx.AsyncClient) -> dict[str, float]:
    """Bybit spot tickers에서 USDT 페어 가격(베이스→가격)."""
    out: dict[str, float] = {}
    try:
        r = await client.get(BYBIT_TICKERS, params={"category": "spot"}, timeout=45.0)
        r.raise_for_status()
        body = r.json()
        result = body.get("result") if isinstance(body, dict) else None
        items = result.get("list") if isinstance(result, dict) else None
        if not isinstance(items, list):
            return out
        for item in items:
            if not isinstance(item, dict):
                continue
            sym = str(item.get("symbol") or "").upper()
            if not sym.endswith("USDT"):
                continue
            base = sym[: -len("USDT")]
            if not base:
                continue
            try:
                price = float(item.get("lastPrice") or 0)
            except Exception:
                continue
            if price > 0 and base not in out:
                out[base] = price
    except Exception as e:
        _LOG.info("Bybit spot tickers 로드 실패(김프 fallback): %s", e)
    return out


async def _fetch_okx_usdt_spot_prices(client: httpx.AsyncClient) -> dict[str, float]:
    """OKX spot tickers에서 USDT 페어 가격(베이스→가격)."""
    out: dict[str, float] = {}
    try:
        r = await client.get(OKX_TICKERS, params={"instType": "SPOT"}, timeout=45.0)
        r.raise_for_status()
        body = r.json()
        items = body.get("data") if isinstance(body, dict) else None
        if not isinstance(items, list):
            return out
        for item in items:
            if not isinstance(item, dict):
                continue
            inst = str(item.get("instId") or "").upper()
            if not inst.endswith("-USDT"):
                continue
            base = inst.split("-", 1)[0]
            if not base:
                continue
            try:
                price = float(item.get("last") or 0)
            except Exception:
                continue
            if price > 0 and base not in out:
                out[base] = price
    except Exception as e:
        _LOG.info("OKX spot tickers 로드 실패(김프 fallback): %s", e)
    return out


async def _fetch_gate_usdt_spot_prices(client: httpx.AsyncClient) -> dict[str, float]:
    """Gate.io spot tickers에서 USDT 페어 가격(베이스→가격)."""
    out: dict[str, float] = {}
    try:
        r = await client.get(GATE_SPOT_TICKERS, timeout=45.0)
        r.raise_for_status()
        items = r.json()
        if not isinstance(items, list):
            return out
        for item in items:
            if not isinstance(item, dict):
                continue
            pair = str(item.get("currency_pair") or "").upper()
            if not pair.endswith("_USDT"):
                continue
            base = pair.split("_", 1)[0]
            if not base:
                continue
            try:
                price = float(item.get("last") or 0)
            except Exception:
                continue
            if price > 0 and base not in out:
                out[base] = price
    except Exception as e:
        _LOG.info("Gate spot tickers 로드 실패(김프 fallback): %s", e)
    return out


async def _fetch_bitget_usdt_spot_prices(client: httpx.AsyncClient) -> dict[str, float]:
    """Bitget spot tickers에서 USDT 페어 가격(베이스→가격)."""
    out: dict[str, float] = {}
    try:
        r = await client.get(BITGET_SPOT_TICKERS, timeout=45.0)
        r.raise_for_status()
        body = r.json()
        if str(body.get("code")) != "00000":
            raise ValueError(f"Bitget spot tickers: {body.get('msg')}")
        items = body.get("data") or []
        if not isinstance(items, list):
            return out
        for item in items:
            if not isinstance(item, dict):
                continue
            sym = str(item.get("symbol") or "").upper()
            if not sym.endswith("USDT"):
                continue
            base = sym[: -len("USDT")]
            if _BITGET_SPOT_USDT_BASES and base not in _BITGET_SPOT_USDT_BASES:
                continue
            price = _safe_float(item.get("lastPr") or item.get("close") or item.get("last"))
            if price and price > 0 and base not in out:
                out[base] = price
    except Exception as e:
        _LOG.info("Bitget spot tickers 로드 실패: %s", e)
    return out


async def _fetch_bitget_usdt_futures_prices(client: httpx.AsyncClient) -> dict[str, float]:
    """Bitget USDT-FUTURES tickers에서 무기한 선물 가격(베이스→가격)."""
    out: dict[str, float] = {}
    try:
        r = await client.get(
            BITGET_USDT_FUTURES_TICKERS,
            params={"productType": "USDT-FUTURES"},
            timeout=45.0,
        )
        r.raise_for_status()
        body = r.json()
        if str(body.get("code")) != "00000":
            raise ValueError(f"Bitget futures tickers: {body.get('msg')}")
        items = body.get("data") or []
        if not isinstance(items, list):
            return out
        for item in items:
            if not isinstance(item, dict):
                continue
            sym = str(item.get("symbol") or "").upper()
            if not sym.endswith("USDT"):
                continue
            base = sym[: -len("USDT")]
            if _BITGET_USDT_PERP_BASES and base not in _BITGET_USDT_PERP_BASES:
                continue
            price = _safe_float(item.get("lastPr") or item.get("last") or item.get("close"))
            if price and price > 0 and base not in out:
                out[base] = price
    except Exception as e:
        _LOG.info("Bitget futures tickers 로드 실패: %s", e)
    return out


async def _bitget_ws_ticker_loop(
    *,
    name: str,
    inst_type: str,
    symbol_by_base_getter,
    target: dict[str, float],
) -> None:
    """Bitget v2 public ticker WebSocket을 메모리 가격 캐시로 유지한다."""
    while True:
        try:
            symbol_by_base = symbol_by_base_getter()
            if not symbol_by_base:
                await asyncio.sleep(5.0)
                continue
            symbol_to_base = {sym: base for base, sym in symbol_by_base.items()}
            args = [
                {"instType": inst_type, "channel": "ticker", "instId": sym}
                for sym in sorted(symbol_to_base)
            ]
            async with websockets.connect(BITGET_WS, ping_interval=20, ping_timeout=20) as ws:
                for arg_chunk in _chunks(args, 50):
                    await ws.send(json.dumps({"op": "subscribe", "args": arg_chunk}))
                    await asyncio.sleep(0.05)
                async for raw in ws:
                    if raw == "pong":
                        continue
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    data = msg.get("data") if isinstance(msg, dict) else None
                    if not isinstance(data, list):
                        continue
                    updates: dict[str, float] = {}
                    for item in data:
                        if not isinstance(item, dict):
                            continue
                        sym = str(item.get("instId") or item.get("symbol") or "").upper()
                        base = symbol_to_base.get(sym)
                        if not base:
                            continue
                        price = _safe_float(item.get("lastPr") or item.get("last") or item.get("close"))
                        if price and price > 0:
                            updates[base] = price
                    if updates:
                        async with _BITGET_PRICE_LOCK:
                            target.update(updates)
        except asyncio.CancelledError:
            break
        except Exception as e:
            _LOG.warning("Bitget %s WebSocket 재연결 대기: %s", name, e)
            try:
                await asyncio.sleep(3.0)
            except asyncio.CancelledError:
                break


def _start_bitget_ws_tasks() -> None:
    global _BITGET_WS_TASKS
    if _BITGET_WS_TASKS:
        return
    _BITGET_WS_TASKS = [
        asyncio.create_task(
            _bitget_ws_ticker_loop(
                name="spot",
                inst_type="SPOT",
                symbol_by_base_getter=lambda: _BITGET_SPOT_USDT_SYMBOL_BY_BASE,
                target=_BITGET_SPOT_WS_PRICES,
            )
        ),
        asyncio.create_task(
            _bitget_ws_ticker_loop(
                name="futures",
                inst_type="USDT-FUTURES",
                symbol_by_base_getter=lambda: _BITGET_USDT_PERP_SYMBOL_BY_BASE,
                target=_BITGET_USDT_PERP_WS_PRICES,
            )
        ),
    ]


async def _stop_bitget_ws_tasks() -> None:
    global _BITGET_WS_TASKS
    tasks = _BITGET_WS_TASKS
    _BITGET_WS_TASKS = []
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass


async def _bitget_price_snapshots(
    client: httpx.AsyncClient,
) -> tuple[dict[str, float], dict[str, float]]:
    async with _BITGET_PRICE_LOCK:
        spot = dict(_BITGET_SPOT_WS_PRICES)
        futures = dict(_BITGET_USDT_PERP_WS_PRICES)
    spot_min = max(100, int(len(_BITGET_SPOT_USDT_SYMBOL_BY_BASE) * 0.8))
    futures_min = max(100, int(len(_BITGET_USDT_PERP_SYMBOL_BY_BASE) * 0.8))
    if len(spot) < spot_min:
        rest_spot = await _fetch_bitget_usdt_spot_prices(client)
        if rest_spot:
            spot = {**rest_spot, **spot}
            async with _BITGET_PRICE_LOCK:
                _BITGET_SPOT_WS_PRICES.update(rest_spot)
    if len(futures) < futures_min:
        rest_futures = await _fetch_bitget_usdt_futures_prices(client)
        if rest_futures:
            futures = {**rest_futures, **futures}
            async with _BITGET_PRICE_LOCK:
                _BITGET_USDT_PERP_WS_PRICES.update(rest_futures)
    return spot, futures


async def _fetch_gate_usdt_futures_prices(client: httpx.AsyncClient) -> dict[str, float]:
    """Gate.io USDT 무기한 선물 ticker에서 가격(베이스→가격)."""
    out: dict[str, float] = {}
    try:
        r = await client.get(GATE_USDT_FUTURES_TICKERS, timeout=45.0)
        r.raise_for_status()
        items = r.json()
        if not isinstance(items, list):
            return out
        for item in items:
            if not isinstance(item, dict):
                continue
            contract = str(item.get("contract") or "").upper()
            if not contract.endswith("_USDT"):
                continue
            base = contract[:-5]
            if _GATE_USDT_PERP_BASES and base not in _GATE_USDT_PERP_BASES:
                continue
            price = _safe_float(item.get("last"))
            if price and price > 0 and base not in out:
                out[base] = price
    except Exception as e:
        _LOG.info("Gate.io futures tickers 로드 실패: %s", e)
    return out


async def _gate_ws_ticker_loop(
    *,
    name: str,
    channel: str,
    symbol_by_base_getter,
    target: dict[str, float],
) -> None:
    """Gate.io public ticker WebSocket을 메모리 가격 캐시로 유지한다."""
    while True:
        try:
            symbol_by_base = symbol_by_base_getter()
            if not symbol_by_base:
                await asyncio.sleep(5.0)
                continue
            symbol_to_base = {sym: base for base, sym in symbol_by_base.items()}
            async with websockets.connect(GATE_WS, ping_interval=20, ping_timeout=20) as ws:
                for symbol_chunk in _chunks(sorted(symbol_to_base), 50):
                    await ws.send(
                        json.dumps(
                            {
                                "time": int(time.time()),
                                "channel": channel,
                                "event": "subscribe",
                                "payload": symbol_chunk,
                            }
                        )
                    )
                    await asyncio.sleep(0.05)
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(msg, dict) or msg.get("event") != "update":
                        continue
                    result = msg.get("result")
                    if not isinstance(result, dict):
                        continue
                    sym = str(
                        result.get("currency_pair") or result.get("contract") or ""
                    ).upper()
                    base = symbol_to_base.get(sym)
                    if not base:
                        continue
                    price = _safe_float(result.get("last"))
                    if price and price > 0:
                        async with _GATE_PRICE_LOCK:
                            target[base] = price
        except asyncio.CancelledError:
            break
        except Exception as e:
            _LOG.warning("Gate.io %s WebSocket 재연결 대기: %s", name, e)
            try:
                await asyncio.sleep(3.0)
            except asyncio.CancelledError:
                break


def _start_gate_ws_tasks() -> None:
    global _GATE_WS_TASKS
    if _GATE_WS_TASKS:
        return
    _GATE_WS_TASKS = [
        asyncio.create_task(
            _gate_ws_ticker_loop(
                name="spot",
                channel="spot.tickers",
                symbol_by_base_getter=lambda: _GATE_SPOT_USDT_SYMBOL_BY_BASE,
                target=_GATE_SPOT_WS_PRICES,
            )
        ),
        asyncio.create_task(
            _gate_ws_ticker_loop(
                name="futures",
                channel="futures.tickers",
                symbol_by_base_getter=lambda: _GATE_USDT_PERP_SYMBOL_BY_BASE,
                target=_GATE_USDT_PERP_WS_PRICES,
            )
        ),
    ]


async def _stop_gate_ws_tasks() -> None:
    global _GATE_WS_TASKS
    tasks = _GATE_WS_TASKS
    _GATE_WS_TASKS = []
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass


async def _gate_price_snapshots(
    client: httpx.AsyncClient,
) -> tuple[dict[str, float], dict[str, float]]:
    async with _GATE_PRICE_LOCK:
        spot = dict(_GATE_SPOT_WS_PRICES)
        futures = dict(_GATE_USDT_PERP_WS_PRICES)
    spot_min = max(100, int(len(_GATE_SPOT_USDT_SYMBOL_BY_BASE) * 0.8))
    futures_min = max(100, int(len(_GATE_USDT_PERP_SYMBOL_BY_BASE) * 0.8))
    if len(spot) < spot_min:
        rest_spot = await _fetch_gate_usdt_spot_prices(client)
        if rest_spot:
            spot = {**rest_spot, **spot}
            async with _GATE_PRICE_LOCK:
                _GATE_SPOT_WS_PRICES.update(rest_spot)
    if len(futures) < futures_min:
        rest_futures = await _fetch_gate_usdt_futures_prices(client)
        if rest_futures:
            futures = {**rest_futures, **futures}
            async with _GATE_PRICE_LOCK:
                _GATE_USDT_PERP_WS_PRICES.update(rest_futures)
    return spot, futures


async def _fetch_reference_usdt_prices(
    client: httpx.AsyncClient,
) -> tuple[dict[str, float], dict[str, str], dict[str, int]]:
    """
    김프 기준 USDT 가격을 바이낸스가 없을 때 다른 거래소로 fallback.
    우선순위: binance -> bybit -> bitget -> okx -> gate
    """
    bn_t = asyncio.create_task(_fetch_binance_usdt_prices(client))
    yb_t = asyncio.create_task(_fetch_bybit_usdt_spot_prices(client))
    bg_t = asyncio.create_task(_fetch_bitget_usdt_spot_prices(client))
    ox_t = asyncio.create_task(_fetch_okx_usdt_spot_prices(client))
    gt_t = asyncio.create_task(_fetch_gate_usdt_spot_prices(client))
    bn, yb, bg, ox, gt = await asyncio.gather(bn_t, yb_t, bg_t, ox_t, gt_t)

    prices: dict[str, float] = {}
    sources: dict[str, str] = {}
    stats: dict[str, int] = {"binance": 0, "bybit": 0, "bitget": 0, "okx": 0, "gate": 0}

    for base, p in bn.items():
        prices[base] = p
        sources[base] = "binance"
        stats["binance"] += 1

    for name, mp in (("bybit", yb), ("bitget", bg), ("okx", ox), ("gate", gt)):
        for base, p in mp.items():
            if base in prices:
                continue
            prices[base] = p
            sources[base] = name
            stats[name] += 1

    return prices, sources, stats


async def _load_binance_spot_registry(client: httpx.AsyncClient) -> None:
    """
    SPOT 마켓에서 quote=USDT·TRADING(및 permissions에 SPOT 있으면)인 심볼만 반영.
    baseAsset(예: BTC)이 업비트/빗썸의 KRW-BTC `BTC`와 동일하게 매칭된다.
    기동 시 `_load_exchange_registries_at_startup`에서만 병렬 호출된다.
    """
    global _BINANCE_SPOT_USDT_BASES, _BINANCE_SPOT_USDT_SYMBOL_BY_BASE
    bases: set[str] = set()
    by_base: dict[str, str] = {}
    try:
        r = await client.get(BINANCE_EXCHANGE_INFO, timeout=45.0)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        _LOG.warning(
            "Binance exchangeInfo 로드 실패 — 김프는 티커 기준으로만 판별합니다: %s",
            e,
        )
        _BINANCE_SPOT_USDT_BASES = frozenset()
        _BINANCE_SPOT_USDT_SYMBOL_BY_BASE = {}
        return

    for s in data.get("symbols") or []:
        if str(s.get("status") or "") != "TRADING":
            continue
        if str(s.get("quoteAsset") or "") != "USDT":
            continue
        perms = s.get("permissions")
        if isinstance(perms, list) and perms and "SPOT" not in perms:
            continue
        base = str(s.get("baseAsset") or "").upper()
        sym = str(s.get("symbol") or "").upper()
        if not base or not sym:
            continue
        bases.add(base)
        if base not in by_base:
            by_base[base] = sym

    _BINANCE_SPOT_USDT_BASES = frozenset(bases)
    _BINANCE_SPOT_USDT_SYMBOL_BY_BASE = by_base
    _LOG.info("Binance SPOT·USDT 레지스트리 로드: %d개 베이스 자산", len(bases))


async def _load_binance_futures_usdt_perp_registry(client: httpx.AsyncClient) -> None:
    """
    USDⓈ-M 무기한(Perpetual) + quote USDT + TRADING.
    baseAsset은 SPOT과 동일하게 국내 KRW 티커와 매칭된다.
    """
    global _BINANCE_FUT_USDT_PERP_BASES, _BINANCE_FUT_USDT_PERP_SYMBOL_BY_BASE
    bases: set[str] = set()
    by_base: dict[str, str] = {}
    try:
        r = await client.get(BINANCE_FAPI_EXCHANGE_INFO, timeout=45.0)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        _LOG.warning("Binance FAPI exchangeInfo 로드 실패: %s", e)
        _BINANCE_FUT_USDT_PERP_BASES = frozenset()
        _BINANCE_FUT_USDT_PERP_SYMBOL_BY_BASE = {}
        return

    for s in data.get("symbols") or []:
        if str(s.get("status") or "") != "TRADING":
            continue
        if str(s.get("contractType") or "") != "PERPETUAL":
            continue
        if str(s.get("quoteAsset") or "") != "USDT":
            continue
        base = str(s.get("baseAsset") or "").upper()
        sym = str(s.get("symbol") or "").upper()
        if not base or not sym:
            continue
        bases.add(base)
        if base not in by_base:
            by_base[base] = sym

    _BINANCE_FUT_USDT_PERP_BASES = frozenset(bases)
    _BINANCE_FUT_USDT_PERP_SYMBOL_BY_BASE = by_base
    _LOG.info("Binance FAPI USDT 무기한 레지스트리 로드: %d개 베이스 자산", len(bases))


async def _bybit_fetch_instruments_all(
    client: httpx.AsyncClient, category: str
) -> list[dict[str, Any]]:
    """v5 instruments-info는 category=linear 등에서 cursor 페이지네이션된다."""
    out: list[dict[str, Any]] = []
    cursor = ""
    while True:
        params: dict[str, str] = {"category": category, "limit": "1000"}
        if cursor:
            params["cursor"] = cursor
        r = await client.get(BYBIT_INSTRUMENTS, params=params, timeout=60.0)
        r.raise_for_status()
        body = r.json()
        if int(body.get("retCode", -1)) != 0:
            raise ValueError(f"Bybit {category}: {body.get('retMsg')}")
        result = body.get("result") or {}
        out.extend(result.get("list") or [])
        cursor = str(result.get("nextPageCursor") or "").strip()
        if not cursor:
            break
    return out


async def _load_bybit_spot_registry(client: httpx.AsyncClient) -> None:
    global _BYBIT_SPOT_USDT_BASES, _BYBIT_SPOT_USDT_SYMBOL_BY_BASE
    bases: set[str] = set()
    by_base: dict[str, str] = {}
    try:
        items = await _bybit_fetch_instruments_all(client, "spot")
    except Exception as e:
        _LOG.warning("Bybit SPOT instruments 로드 실패: %s", e)
        _BYBIT_SPOT_USDT_BASES = frozenset()
        _BYBIT_SPOT_USDT_SYMBOL_BY_BASE = {}
        return

    for s in items:
        if str(s.get("status") or "") != "Trading":
            continue
        if str(s.get("quoteCoin") or "") != "USDT":
            continue
        base = str(s.get("baseCoin") or "").upper()
        sym = str(s.get("symbol") or "").upper()
        if not base or not sym:
            continue
        bases.add(base)
        if base not in by_base:
            by_base[base] = sym

    _BYBIT_SPOT_USDT_BASES = frozenset(bases)
    _BYBIT_SPOT_USDT_SYMBOL_BY_BASE = by_base
    _LOG.info("Bybit SPOT·USDT 레지스트리 로드: %d개 베이스 자산", len(bases))


async def _load_bybit_linear_perp_registry(client: httpx.AsyncClient) -> None:
    """USDT 결제 Linear 무기한(LinearPerpetual)."""
    global _BYBIT_LINEAR_USDT_PERP_BASES, _BYBIT_LINEAR_USDT_PERP_SYMBOL_BY_BASE
    bases: set[str] = set()
    by_base: dict[str, str] = {}
    try:
        items = await _bybit_fetch_instruments_all(client, "linear")
    except Exception as e:
        _LOG.warning("Bybit Linear instruments 로드 실패: %s", e)
        _BYBIT_LINEAR_USDT_PERP_BASES = frozenset()
        _BYBIT_LINEAR_USDT_PERP_SYMBOL_BY_BASE = {}
        return

    for s in items:
        if str(s.get("status") or "") != "Trading":
            continue
        if str(s.get("contractType") or "") != "LinearPerpetual":
            continue
        if str(s.get("quoteCoin") or "") != "USDT":
            continue
        base = str(s.get("baseCoin") or "").upper()
        sym = str(s.get("symbol") or "").upper()
        if not base or not sym:
            continue
        bases.add(base)
        if base not in by_base:
            by_base[base] = sym

    _BYBIT_LINEAR_USDT_PERP_BASES = frozenset(bases)
    _BYBIT_LINEAR_USDT_PERP_SYMBOL_BY_BASE = by_base
    _LOG.info("Bybit Linear USDT 무기한 레지스트리 로드: %d개 베이스 자산", len(bases))


async def _load_bitget_spot_registry(client: httpx.AsyncClient) -> None:
    global _BITGET_SPOT_USDT_BASES, _BITGET_SPOT_USDT_SYMBOL_BY_BASE
    bases: set[str] = set()
    by_base: dict[str, str] = {}
    try:
        r = await client.get(BITGET_SPOT_SYMBOLS, timeout=45.0)
        r.raise_for_status()
        body = r.json()
        if str(body.get("code")) != "00000":
            raise ValueError(f"Bitget spot: {body.get('msg')}")
        items = body.get("data") or []
    except Exception as e:
        _LOG.warning("Bitget SPOT symbols 로드 실패: %s", e)
        _BITGET_SPOT_USDT_BASES = frozenset()
        _BITGET_SPOT_USDT_SYMBOL_BY_BASE = {}
        return

    for s in items:
        if str(s.get("status") or "") != "online":
            continue
        if str(s.get("quoteCoin") or "") != "USDT":
            continue
        base = str(s.get("baseCoin") or "").upper()
        sym = str(s.get("symbol") or "").upper()
        if not base or not sym:
            continue
        bases.add(base)
        if base not in by_base:
            by_base[base] = sym

    _BITGET_SPOT_USDT_BASES = frozenset(bases)
    _BITGET_SPOT_USDT_SYMBOL_BY_BASE = by_base
    _LOG.info("Bitget SPOT·USDT 레지스트리 로드: %d개 베이스 자산", len(bases))


async def _load_bitget_usdt_perp_registry(client: httpx.AsyncClient) -> None:
    global _BITGET_USDT_PERP_BASES, _BITGET_USDT_PERP_SYMBOL_BY_BASE
    bases: set[str] = set()
    by_base: dict[str, str] = {}
    try:
        r = await client.get(BITGET_USDT_FUTURES, params={"productType": "USDT-FUTURES"}, timeout=45.0)
        r.raise_for_status()
        body = r.json()
        if str(body.get("code")) != "00000":
            raise ValueError(f"Bitget futures: {body.get('msg')}")
        items = body.get("data") or []
    except Exception as e:
        _LOG.warning("Bitget USDT 선물 로드 실패: %s", e)
        _BITGET_USDT_PERP_BASES = frozenset()
        _BITGET_USDT_PERP_SYMBOL_BY_BASE = {}
        return

    for s in items:
        if str(s.get("symbolStatus") or "") != "normal":
            continue
        if str(s.get("quoteCoin") or "") != "USDT":
            continue
        if str(s.get("symbolType") or "").lower() != "perpetual":
            continue
        base = str(s.get("baseCoin") or "").upper()
        sym = str(s.get("symbol") or "").upper()
        if not base or not sym:
            continue
        bases.add(base)
        if base not in by_base:
            by_base[base] = sym

    _BITGET_USDT_PERP_BASES = frozenset(bases)
    _BITGET_USDT_PERP_SYMBOL_BY_BASE = by_base
    _LOG.info("Bitget USDT 무기한 레지스트리 로드: %d개 베이스 자산", len(bases))


async def _load_okx_spot_registry(client: httpx.AsyncClient) -> None:
    global _OKX_SPOT_USDT_BASES, _OKX_SPOT_USDT_SYMBOL_BY_BASE
    bases: set[str] = set()
    by_base: dict[str, str] = {}
    try:
        r = await client.get(OKX_INSTRUMENTS, params={"instType": "SPOT"}, timeout=45.0)
        r.raise_for_status()
        body = r.json()
        if str(body.get("code")) != "0":
            raise ValueError(f"OKX spot: {body.get('msg')}")
        items = body.get("data") or []
    except Exception as e:
        _LOG.warning("OKX SPOT instruments 로드 실패: %s", e)
        _OKX_SPOT_USDT_BASES = frozenset()
        _OKX_SPOT_USDT_SYMBOL_BY_BASE = {}
        return

    for s in items:
        if str(s.get("state") or "") != "live":
            continue
        if str(s.get("quoteCcy") or "") != "USDT":
            continue
        base = str(s.get("baseCcy") or "").upper()
        sym = str(s.get("instId") or "").upper()
        if not base or not sym:
            continue
        bases.add(base)
        if base not in by_base:
            by_base[base] = sym

    _OKX_SPOT_USDT_BASES = frozenset(bases)
    _OKX_SPOT_USDT_SYMBOL_BY_BASE = by_base
    _LOG.info("OKX SPOT·USDT 레지스트리 로드: %d개 베이스 자산", len(bases))


async def _load_okx_swap_usdt_registry(client: httpx.AsyncClient) -> None:
    global _OKX_SWAP_USDT_BASES, _OKX_SWAP_USDT_SYMBOL_BY_BASE
    bases: set[str] = set()
    by_base: dict[str, str] = {}
    try:
        r = await client.get(OKX_INSTRUMENTS, params={"instType": "SWAP"}, timeout=45.0)
        r.raise_for_status()
        body = r.json()
        if str(body.get("code")) != "0":
            raise ValueError(f"OKX swap: {body.get('msg')}")
        items = body.get("data") or []
    except Exception as e:
        _LOG.warning("OKX SWAP instruments 로드 실패: %s", e)
        _OKX_SWAP_USDT_BASES = frozenset()
        _OKX_SWAP_USDT_SYMBOL_BY_BASE = {}
        return

    for s in items:
        if str(s.get("state") or "") != "live":
            continue
        if str(s.get("instType") or "") != "SWAP":
            continue
        if str(s.get("settleCcy") or "") != "USDT":
            continue
        if str(s.get("ctType") or "") != "linear":
            continue
        base = str(s.get("ctValCcy") or "").upper()
        sym = str(s.get("instId") or "").upper()
        if not base or not sym:
            continue
        bases.add(base)
        if base not in by_base:
            by_base[base] = sym

    _OKX_SWAP_USDT_BASES = frozenset(bases)
    _OKX_SWAP_USDT_SYMBOL_BY_BASE = by_base
    _LOG.info("OKX SWAP·USDT 레지스트리 로드: %d개 베이스 자산", len(bases))


async def _load_gate_spot_registry(client: httpx.AsyncClient) -> None:
    global _GATE_SPOT_USDT_BASES, _GATE_SPOT_USDT_SYMBOL_BY_BASE
    bases: set[str] = set()
    by_base: dict[str, str] = {}
    try:
        r = await client.get(GATE_SPOT_PAIRS, timeout=45.0)
        r.raise_for_status()
        items = r.json()
    except Exception as e:
        _LOG.warning("Gate.io SPOT pairs 로드 실패: %s", e)
        _GATE_SPOT_USDT_BASES = frozenset()
        _GATE_SPOT_USDT_SYMBOL_BY_BASE = {}
        return

    for s in items:
        if str(s.get("trade_status") or "") != "tradable":
            continue
        if str(s.get("quote") or "") != "USDT":
            continue
        base = str(s.get("base") or "").upper()
        sym = str(s.get("id") or "").upper()
        if not base or not sym:
            continue
        bases.add(base)
        if base not in by_base:
            by_base[base] = sym

    _GATE_SPOT_USDT_BASES = frozenset(bases)
    _GATE_SPOT_USDT_SYMBOL_BY_BASE = by_base
    _LOG.info("Gate.io SPOT·USDT 레지스트리 로드: %d개 베이스 자산", len(bases))


async def _load_gate_usdt_perp_registry(client: httpx.AsyncClient) -> None:
    global _GATE_USDT_PERP_BASES, _GATE_USDT_PERP_SYMBOL_BY_BASE
    bases: set[str] = set()
    by_base: dict[str, str] = {}
    try:
        r = await client.get(GATE_USDT_CONTRACTS, timeout=45.0)
        r.raise_for_status()
        items = r.json()
    except Exception as e:
        _LOG.warning("Gate.io USDT 선물 contracts 로드 실패: %s", e)
        _GATE_USDT_PERP_BASES = frozenset()
        _GATE_USDT_PERP_SYMBOL_BY_BASE = {}
        return

    for s in items:
        if str(s.get("status") or "") != "trading":
            continue
        name = str(s.get("name") or "").upper()
        if not name.endswith("_USDT"):
            continue
        base = name[:-5]
        if not base:
            continue
        bases.add(base)
        if base not in by_base:
            by_base[base] = name

    _GATE_USDT_PERP_BASES = frozenset(bases)
    _GATE_USDT_PERP_SYMBOL_BY_BASE = by_base
    _LOG.info("Gate.io USDT 무기한 레지스트리 로드: %d개 베이스 자산", len(bases))


async def _load_exchange_registries_at_startup() -> None:
    """
    프로세스 기동 시 1회만: 거래소별 공개 레지스트리를 같은 httpx 클라이언트로 병렬 로드.
    shutdown 전까지 재호출하지 않는다.
    """
    headers = {"Accept": "application/json"}
    async with httpx.AsyncClient(headers=headers) as http:
        loaders = (
            _load_binance_spot_registry(http),
            _load_binance_futures_usdt_perp_registry(http),
            _load_bybit_spot_registry(http),
            _load_bybit_linear_perp_registry(http),
            _load_bitget_spot_registry(http),
            _load_bitget_usdt_perp_registry(http),
            _load_okx_spot_registry(http),
            _load_okx_swap_usdt_registry(http),
            _load_gate_spot_registry(http),
            _load_gate_usdt_perp_registry(http),
        )
        results = await asyncio.gather(*loaders, return_exceptions=True)
    for res in results:
        if isinstance(res, BaseException):
            _LOG.error("거래소 레지스트리 로더 예외", exc_info=res)


def _binance_spot_has_usdt(base: str) -> bool:
    """레지스트리가 비었으면(기동 실패 등) 스팟 여부로 김프를 막지 않는다."""
    if not _BINANCE_SPOT_USDT_BASES:
        return True
    return base in _BINANCE_SPOT_USDT_BASES


def _any_spot_has_usdt(base: str) -> bool:
    """
    어떤 거래소든 SPOT·USDT로 거래 가능한 베이스인지 판별.
    레지스트리가 전부 비어 있으면(기동 실패 등) 스팟 여부로 김프를 막지 않는다.
    """
    loaded = any(
        (
            bool(_BINANCE_SPOT_USDT_BASES),
            bool(_BYBIT_SPOT_USDT_BASES),
            bool(_OKX_SPOT_USDT_BASES),
            bool(_GATE_SPOT_USDT_BASES),
            bool(_BITGET_SPOT_USDT_BASES),
        )
    )
    if not loaded:
        return True
    return (
        base in _BINANCE_SPOT_USDT_BASES
        or base in _BYBIT_SPOT_USDT_BASES
        or base in _OKX_SPOT_USDT_BASES
        or base in _GATE_SPOT_USDT_BASES
        or base in _BITGET_SPOT_USDT_BASES
    )


def _calc_kimchi_premium(
    krw_price: float,
    ref_prices: dict[str, float],
    usdt_krw: float,
    symbol: str,
) -> float | None:
    """김프(%) = (국내_KRW / (USDT_기준가격 × USDT_KRW) - 1) × 100"""
    if usdt_krw <= 0 or krw_price <= 0:
        return None
    bn_sym = _SYMBOL_MAP.get(symbol, symbol)
    if not _any_spot_has_usdt(bn_sym):
        return None
    ref_price = ref_prices.get(bn_sym)
    if ref_price is None or ref_price <= 0:
        return None
    fair_krw = ref_price * usdt_krw
    return round((krw_price / fair_krw - 1) * 100, 4)


def _domestic_usdt_price(krw_price: float | None, usdt_krw: float | None) -> float | None:
    if krw_price is None or usdt_krw is None or krw_price <= 0 or usdt_krw <= 0:
        return None
    return round(krw_price / usdt_krw, 8)


def _pct_vs_reference(domestic_usdt: float | None, reference_usdt: float | None) -> float | None:
    if domestic_usdt is None or reference_usdt is None or domestic_usdt <= 0 or reference_usdt <= 0:
        return None
    return round((domestic_usdt / reference_usdt - 1) * 100, 4)


def _max_abs_gap(*values: float | None) -> float | None:
    nums = [abs(v) for v in values if isinstance(v, (int, float))]
    return round(max(nums), 4) if nums else None


def _build_exchange_comparison_rows(
    upbit: dict[str, float],
    bithumb: dict[str, float],
    reference_prices: dict[str, float],
    usdt_krw: float | None,
    *,
    exchange: str,
    exchange_label: str,
    market: str,
    symbol_key: str,
    symbol_by_base: dict[str, str],
) -> list[dict[str, Any]]:
    """업비트·빗썸 KRW 가격을 업비트 KRW-USDT 기준으로 USDT화해 해외거래소와 비교."""
    if not usdt_krw or usdt_krw <= 0:
        return []
    rows: list[dict[str, Any]] = []
    symbols = sorted(set(upbit) | set(bithumb))
    for sym in symbols:
        bn_base = _SYMBOL_MAP.get(sym, sym)
        reference_price = reference_prices.get(bn_base)
        if reference_price is None or reference_price <= 0:
            continue
        exchange_symbol = symbol_by_base.get(bn_base, f"{bn_base}USDT")
        upbit_usdt = _domestic_usdt_price(upbit.get(sym), usdt_krw)
        bithumb_usdt = _domestic_usdt_price(bithumb.get(sym), usdt_krw)
        upbit_gap = _pct_vs_reference(upbit_usdt, reference_price)
        bithumb_gap = _pct_vs_reference(bithumb_usdt, reference_price)
        row: dict[str, Any] = {
            "symbol": sym,
            "mapped_symbol": bn_base,
            "exchange": exchange,
            "exchange_label": exchange_label,
            "market": market,
            "exchange_symbol": exchange_symbol,
            "reference_usdt": reference_price,
            "binance_usdt": reference_price,
            "upbit": upbit.get(sym),
            "bithumb": bithumb.get(sym),
            "upbit_usdt": upbit_usdt,
            "bithumb_usdt": bithumb_usdt,
            "upbit_gap_pct": upbit_gap,
            "bithumb_gap_pct": bithumb_gap,
            "max_abs_gap_pct": _max_abs_gap(upbit_gap, bithumb_gap),
            symbol_key: exchange_symbol,
        }
        rows.append(row)
    rows.sort(key=lambda x: x.get("max_abs_gap_pct") or -1, reverse=True)
    return rows


async def _fetch_upbit_wallet_safe(client: httpx.AsyncClient) -> tuple[list[dict] | None, str | None]:
    if not UPBIT_ACCESS_KEY or not UPBIT_SECRET_KEY:
        return None, None
    try:
        r = await client.get(UPBIT_WALLET, headers=_upbit_auth_header(), timeout=20.0)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else [], None
    except Exception as e:
        return None, str(e)


async def _fetch_bithumb_wallet_safe(client: httpx.AsyncClient) -> tuple[list[dict] | None, str | None]:
    if not BITHUMB_ACCESS_KEY or not BITHUMB_SECRET_KEY:
        return None, None
    try:
        r = await client.get(BITHUMB_WALLET, headers=_bithumb_auth_header(), timeout=20.0)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else [], None
    except Exception as e:
        return None, str(e)


def _merge_gaps(
    upbit: dict[str, float],
    bithumb: dict[str, float],
    up_wallet: dict[str, dict[str, bool]] | None,
    bh_wallet: dict[str, dict[str, bool]] | None,
    ref_prices: dict[str, float] | None = None,
    ref_sources: dict[str, str] | None = None,
    usdt_krw: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    common = sorted(set(upbit) & set(bithumb))
    rows: list[dict[str, Any]] = []
    for sym in common:
        pu, pb = upbit[sym], bithumb[sym]
        if pu <= 0 or pb <= 0:
            continue
        lo, hi = (pu, pb) if pu <= pb else (pb, pu)
        gap_pct = (hi - lo) / lo * 100.0
        cheaper = "upbit" if pu < pb else "bithumb" if pb < pu else "tie"
        row: dict[str, Any] = {
            "symbol": sym,
            "upbit": pu,
            "bithumb": pb,
            "gap_pct": round(gap_pct, 4),
            "cheaper_on": cheaper,
        }
        bn_base = _SYMBOL_MAP.get(sym, sym)
        if _BINANCE_SPOT_USDT_BASES and bn_base in _BINANCE_SPOT_USDT_BASES:
            spot_sym = _BINANCE_SPOT_USDT_SYMBOL_BY_BASE.get(bn_base)
            if spot_sym:
                row["binance_spot_symbol"] = spot_sym
        if _BINANCE_FUT_USDT_PERP_BASES and bn_base in _BINANCE_FUT_USDT_PERP_BASES:
            fut_sym = _BINANCE_FUT_USDT_PERP_SYMBOL_BY_BASE.get(bn_base)
            if fut_sym:
                row["binance_futures_symbol"] = fut_sym
        if _BYBIT_SPOT_USDT_BASES and bn_base in _BYBIT_SPOT_USDT_BASES:
            yb_sp = _BYBIT_SPOT_USDT_SYMBOL_BY_BASE.get(bn_base)
            if yb_sp:
                row["bybit_spot_symbol"] = yb_sp
        if _BYBIT_LINEAR_USDT_PERP_BASES and bn_base in _BYBIT_LINEAR_USDT_PERP_BASES:
            yb_ln = _BYBIT_LINEAR_USDT_PERP_SYMBOL_BY_BASE.get(bn_base)
            if yb_ln:
                row["bybit_futures_symbol"] = yb_ln
        if _BITGET_SPOT_USDT_BASES and bn_base in _BITGET_SPOT_USDT_BASES:
            bg_sp = _BITGET_SPOT_USDT_SYMBOL_BY_BASE.get(bn_base)
            if bg_sp:
                row["bitget_spot_symbol"] = bg_sp
        if _BITGET_USDT_PERP_BASES and bn_base in _BITGET_USDT_PERP_BASES:
            bg_ft = _BITGET_USDT_PERP_SYMBOL_BY_BASE.get(bn_base)
            if bg_ft:
                row["bitget_futures_symbol"] = bg_ft
        if _OKX_SPOT_USDT_BASES and bn_base in _OKX_SPOT_USDT_BASES:
            ox_sp = _OKX_SPOT_USDT_SYMBOL_BY_BASE.get(bn_base)
            if ox_sp:
                row["okx_spot_symbol"] = ox_sp
        if _OKX_SWAP_USDT_BASES and bn_base in _OKX_SWAP_USDT_BASES:
            ox_sw = _OKX_SWAP_USDT_SYMBOL_BY_BASE.get(bn_base)
            if ox_sw:
                row["okx_futures_symbol"] = ox_sw
        if _GATE_SPOT_USDT_BASES and bn_base in _GATE_SPOT_USDT_BASES:
            gt_sp = _GATE_SPOT_USDT_SYMBOL_BY_BASE.get(bn_base)
            if gt_sp:
                row["gate_spot_symbol"] = gt_sp
        if _GATE_USDT_PERP_BASES and bn_base in _GATE_USDT_PERP_BASES:
            gt_ft = _GATE_USDT_PERP_SYMBOL_BY_BASE.get(bn_base)
            if gt_ft:
                row["gate_futures_symbol"] = gt_ft

        if ref_prices and usdt_krw and usdt_krw > 0:
            kp_u = _calc_kimchi_premium(pu, ref_prices, usdt_krw, sym)
            kp_b = _calc_kimchi_premium(pb, ref_prices, usdt_krw, sym)
            row["kp_upbit"] = kp_u
            row["kp_bithumb"] = kp_b
            row["ref_usdt"] = ref_prices.get(bn_base)
            if ref_sources:
                row["ref_usdt_source"] = ref_sources.get(bn_base)
        if up_wallet and sym in up_wallet:
            u = up_wallet[sym]
            row["upbit_wallet"] = {
                "deposit_available": u["deposit_available"],
                "withdraw_available": u["withdraw_available"],
                "all_networks_full_pause": u["all_networks_full_pause"],
                "any_network_full_pause": u["any_network_full_pause"],
                "any_network_restricted": u["any_network_restricted"],
            }
        if bh_wallet and sym in bh_wallet:
            b = bh_wallet[sym]
            row["bithumb_wallet"] = {
                "deposit_available": b["deposit_available"],
                "withdraw_available": b["withdraw_available"],
                "all_networks_full_pause": b["all_networks_full_pause"],
                "any_network_full_pause": b["any_network_full_pause"],
                "any_network_restricted": b["any_network_restricted"],
            }
        rows.append(row)
    rows.sort(key=lambda x: x["gap_pct"], reverse=True)
    meta = {
        "pairs_compared": len(rows),
        "upbit_only": len(set(upbit) - set(bithumb)),
        "bithumb_only": len(set(bithumb) - set(upbit)),
    }
    return rows, meta


async def _compute_gaps_payload() -> dict[str, Any]:
    """업스트림 조회 후 `/api/gaps`·WebSocket과 동일한 JSON 페이로드 생성. httpx.HTTPError·ValueError는 그대로 전파."""
    t0 = time.time()
    up_wallet_map: dict[str, dict[str, bool]] | None = None
    bh_wallet_map: dict[str, dict[str, bool]] | None = None
    up_net_by_sym: dict[str, list[dict[str, Any]]] = {}
    bh_net_by_sym: dict[str, list[dict[str, Any]]] = {}
    up_wallet_loaded = False
    bh_wallet_loaded = False
    wallet_meta: dict[str, Any] = {
        "upbit_configured": bool(UPBIT_ACCESS_KEY and UPBIT_SECRET_KEY),
        "bithumb_configured": bool(BITHUMB_ACCESS_KEY and BITHUMB_SECRET_KEY),
        "upbit_error": None,
        "bithumb_error": None,
    }

    usdt_krw: float | None = None
    binance_prices: dict[str, float] = {}
    binance_spot_prices: dict[str, float] = {}
    binance_futures_prices: dict[str, float] = {}
    bybit_spot_prices: dict[str, float] = {}
    bybit_linear_prices: dict[str, float] = {}
    bitget_spot_prices: dict[str, float] = {}
    bitget_futures_prices: dict[str, float] = {}
    gate_spot_prices: dict[str, float] = {}
    gate_futures_prices: dict[str, float] = {}
    ref_prices: dict[str, float] = {}
    ref_sources: dict[str, str] = {}
    ref_stats: dict[str, int] = {}

    async with httpx.AsyncClient(headers={"Accept": "application/json"}) as client:
        up_p = asyncio.create_task(_fetch_upbit_krw_prices(client))
        bh_p = asyncio.create_task(_fetch_bithumb_krw_prices(client))
        up_w = asyncio.create_task(_fetch_upbit_wallet_safe(client))
        bh_w = asyncio.create_task(_fetch_bithumb_wallet_safe(client))
        ref_p = asyncio.create_task(_fetch_reference_usdt_prices(client))
        binance_p = asyncio.create_task(_binance_price_snapshots(client))
        bybit_p = asyncio.create_task(_bybit_price_snapshots(client))
        bitget_p = asyncio.create_task(_bitget_price_snapshots(client))
        gate_p = asyncio.create_task(_gate_price_snapshots(client))
        usdt_task = asyncio.create_task(_fetch_usdt_krw_rate(client))
        (
            upbit,
            bithumb,
            (up_raw, up_err),
            (bh_raw, bh_err),
            (ref_prices, ref_sources, ref_stats),
            (binance_spot_prices, binance_futures_prices),
            (bybit_spot_prices, bybit_linear_prices),
            (bitget_spot_prices, bitget_futures_prices),
            (gate_spot_prices, gate_futures_prices),
            usdt_krw,
        ) = await asyncio.gather(
            up_p,
            bh_p,
            up_w,
            bh_w,
            ref_p,
            binance_p,
            bybit_p,
            bitget_p,
            gate_p,
            usdt_task,
        )

        # 기존 메타 호환: ref_sources를 이용해 "바이낸스에서 채워진 심볼 수"만 별도로 계산
        if ref_sources:
            binance_prices = {k: v for k, v in ref_prices.items() if ref_sources.get(k) == "binance"}
        else:
            binance_prices = {}

        if up_err:
            wallet_meta["upbit_error"] = up_err
        if bh_err:
            wallet_meta["bithumb_error"] = bh_err

        if up_raw is not None:
            up_wallet_loaded = True
            up_wallet_map = _aggregate_pause_by_currency(_parse_upbit_wallet_rows(up_raw))
            up_net_by_sym = _group_upbit_networks_by_currency(up_raw)
        if bh_raw is not None:
            bh_wallet_loaded = True
            bh_wallet_map = _aggregate_pause_by_currency(_parse_bithumb_wallet_rows(bh_raw))
            bh_net_by_sym = _group_bithumb_networks_by_currency(bh_raw)

        configured = wallet_meta["upbit_configured"] or wallet_meta["bithumb_configured"]
        if up_wallet_map is None and bh_wallet_map is None:
            wallet_meta["mode"] = "off" if not configured else "failed"
        elif wallet_meta["upbit_error"] or wallet_meta["bithumb_error"]:
            wallet_meta["mode"] = "partial"
        else:
            wallet_meta["mode"] = "on"

    rows, meta = _merge_gaps(
        upbit, bithumb, up_wallet_map, bh_wallet_map, ref_prices, ref_sources, usdt_krw
    )
    binance_spot_rows = _build_exchange_comparison_rows(
        upbit,
        bithumb,
        binance_spot_prices,
        usdt_krw,
        exchange="binance",
        exchange_label="Binance",
        market="spot",
        symbol_key="binance_spot_symbol",
        symbol_by_base=_BINANCE_SPOT_USDT_SYMBOL_BY_BASE,
    )
    binance_futures_rows = _build_exchange_comparison_rows(
        upbit,
        bithumb,
        binance_futures_prices,
        usdt_krw,
        exchange="binance",
        exchange_label="Binance",
        market="futures",
        symbol_key="binance_futures_symbol",
        symbol_by_base=_BINANCE_FUT_USDT_PERP_SYMBOL_BY_BASE,
    )
    bybit_spot_rows = _build_exchange_comparison_rows(
        upbit,
        bithumb,
        bybit_spot_prices,
        usdt_krw,
        exchange="bybit",
        exchange_label="Bybit",
        market="spot",
        symbol_key="bybit_spot_symbol",
        symbol_by_base=_BYBIT_SPOT_USDT_SYMBOL_BY_BASE,
    )
    bybit_futures_rows = _build_exchange_comparison_rows(
        upbit,
        bithumb,
        bybit_linear_prices,
        usdt_krw,
        exchange="bybit",
        exchange_label="Bybit",
        market="futures",
        symbol_key="bybit_futures_symbol",
        symbol_by_base=_BYBIT_LINEAR_USDT_PERP_SYMBOL_BY_BASE,
    )
    bitget_spot_rows = _build_exchange_comparison_rows(
        upbit,
        bithumb,
        bitget_spot_prices,
        usdt_krw,
        exchange="bitget",
        exchange_label="Bitget",
        market="spot",
        symbol_key="bitget_spot_symbol",
        symbol_by_base=_BITGET_SPOT_USDT_SYMBOL_BY_BASE,
    )
    bitget_futures_rows = _build_exchange_comparison_rows(
        upbit,
        bithumb,
        bitget_futures_prices,
        usdt_krw,
        exchange="bitget",
        exchange_label="Bitget",
        market="futures",
        symbol_key="bitget_futures_symbol",
        symbol_by_base=_BITGET_USDT_PERP_SYMBOL_BY_BASE,
    )
    gate_spot_rows = _build_exchange_comparison_rows(
        upbit,
        bithumb,
        gate_spot_prices,
        usdt_krw,
        exchange="gate",
        exchange_label="Gate.io",
        market="spot",
        symbol_key="gate_spot_symbol",
        symbol_by_base=_GATE_SPOT_USDT_SYMBOL_BY_BASE,
    )
    gate_futures_rows = _build_exchange_comparison_rows(
        upbit,
        bithumb,
        gate_futures_prices,
        usdt_krw,
        exchange="gate",
        exchange_label="Gate.io",
        market="futures",
        symbol_key="gate_futures_symbol",
        symbol_by_base=_GATE_USDT_PERP_SYMBOL_BY_BASE,
    )
    spot_comparison_rows = sorted(
        [*binance_spot_rows, *bybit_spot_rows, *bitget_spot_rows, *gate_spot_rows],
        key=lambda x: x.get("max_abs_gap_pct") or -1,
        reverse=True,
    )
    futures_comparison_rows = sorted(
        [*binance_futures_rows, *bybit_futures_rows, *bitget_futures_rows, *gate_futures_rows],
        key=lambda x: x.get("max_abs_gap_pct") or -1,
        reverse=True,
    )

    global _wl_task
    if not _wl_cache and not _wl_loading and _wl_status == "idle":
        _wl_task = asyncio.create_task(_load_withdraw_limits())

    for row in rows:
        sym = row["symbol"]
        wl = _wl_cache.get(sym)
        if wl:
            row["withdraw_limits"] = wl
        if up_wallet_loaded:
            row["upbit_networks"] = up_net_by_sym.get(sym, [])
        if bh_wallet_loaded:
            row["bithumb_networks"] = bh_net_by_sym.get(sym, [])

    def _exchange_fully_dead(w: dict[str, Any] | None) -> bool:
        if not w:
            return False
        return not w.get("deposit_available", False) and not w.get("withdraw_available", False)

    def _exchange_dw_limited(w: dict[str, Any] | None) -> bool:
        if not w:
            return False
        return not w.get("deposit_available", True) or not w.get("withdraw_available", True)

    fully_blocked = [
        r
        for r in rows
        if _exchange_fully_dead(r.get("upbit_wallet")) or _exchange_fully_dead(r.get("bithumb_wallet"))
    ]
    any_pause = [
        r
        for r in rows
        if (
            r.get("upbit_wallet", {}).get("any_network_full_pause")
            or r.get("bithumb_wallet", {}).get("any_network_full_pause")
        )
    ]
    restricted = [
        r
        for r in rows
        if _exchange_dw_limited(r.get("upbit_wallet")) or _exchange_dw_limited(r.get("bithumb_wallet"))
    ]

    meta["wallet"] = wallet_meta
    meta["usdt_krw"] = usdt_krw
    meta["binance_symbols"] = len(binance_prices) if binance_prices else 0
    meta["binance_spot_price_symbols"] = len(binance_spot_prices)
    meta["binance_futures_price_symbols"] = len(binance_futures_prices)
    meta["binance_spot_compared"] = len(binance_spot_rows)
    meta["binance_futures_compared"] = len(binance_futures_rows)
    meta["bybit_spot_price_symbols"] = len(bybit_spot_prices)
    meta["bybit_futures_price_symbols"] = len(bybit_linear_prices)
    meta["bybit_spot_compared"] = len(bybit_spot_rows)
    meta["bybit_futures_compared"] = len(bybit_futures_rows)
    meta["bitget_spot_price_symbols"] = len(bitget_spot_prices)
    meta["bitget_futures_price_symbols"] = len(bitget_futures_prices)
    meta["bitget_spot_compared"] = len(bitget_spot_rows)
    meta["bitget_futures_compared"] = len(bitget_futures_rows)
    meta["gate_spot_price_symbols"] = len(gate_spot_prices)
    meta["gate_futures_price_symbols"] = len(gate_futures_prices)
    meta["gate_spot_compared"] = len(gate_spot_rows)
    meta["gate_futures_compared"] = len(gate_futures_rows)
    meta["spot_compared"] = len(spot_comparison_rows)
    meta["futures_compared"] = len(futures_comparison_rows)
    meta["ref_usdt_symbols"] = len(ref_prices) if ref_prices else 0
    meta["ref_usdt_stats"] = ref_stats
    meta["binance_spot_registry"] = {
        "loaded": bool(_BINANCE_SPOT_USDT_BASES),
        "usdt_spot_bases": len(_BINANCE_SPOT_USDT_BASES),
    }
    meta["binance_futures_registry"] = {
        "loaded": bool(_BINANCE_FUT_USDT_PERP_BASES),
        "usdt_perp_bases": len(_BINANCE_FUT_USDT_PERP_BASES),
    }
    meta["bybit_spot_registry"] = {
        "loaded": bool(_BYBIT_SPOT_USDT_BASES),
        "usdt_spot_bases": len(_BYBIT_SPOT_USDT_BASES),
    }
    meta["bybit_linear_registry"] = {
        "loaded": bool(_BYBIT_LINEAR_USDT_PERP_BASES),
        "usdt_perp_bases": len(_BYBIT_LINEAR_USDT_PERP_BASES),
    }
    meta["bitget_spot_registry"] = {
        "loaded": bool(_BITGET_SPOT_USDT_BASES),
        "usdt_spot_bases": len(_BITGET_SPOT_USDT_BASES),
    }
    meta["bitget_futures_registry"] = {
        "loaded": bool(_BITGET_USDT_PERP_BASES),
        "usdt_perp_bases": len(_BITGET_USDT_PERP_BASES),
    }
    meta["okx_spot_registry"] = {
        "loaded": bool(_OKX_SPOT_USDT_BASES),
        "usdt_spot_bases": len(_OKX_SPOT_USDT_BASES),
    }
    meta["okx_futures_registry"] = {
        "loaded": bool(_OKX_SWAP_USDT_BASES),
        "usdt_perp_bases": len(_OKX_SWAP_USDT_BASES),
    }
    meta["gate_spot_registry"] = {
        "loaded": bool(_GATE_SPOT_USDT_BASES),
        "usdt_spot_bases": len(_GATE_SPOT_USDT_BASES),
    }
    meta["gate_futures_registry"] = {
        "loaded": bool(_GATE_USDT_PERP_BASES),
        "usdt_perp_bases": len(_GATE_USDT_PERP_BASES),
    }
    kp_available = sum(1 for r in rows if r.get("kp_upbit") is not None)
    meta["kp_available"] = kp_available
    meta["wl_status"] = _wl_status
    meta["wl_progress"] = _wl_progress
    meta["wl_count"] = len(_wl_cache)
    meta["wl_ts"] = int(_wl_ts * 1000) if _wl_ts else None
    return {
        "updated_at_ms": int(time.time() * 1000),
        "latency_ms": round((time.time() - t0) * 1000, 2),
        "meta": meta,
        "gaps": rows,
        "spot_comparisons": spot_comparison_rows,
        "futures_comparisons": futures_comparison_rows,
        "binance_spot_comparisons": binance_spot_rows,
        "binance_futures_comparisons": binance_futures_rows,
        "bybit_spot_comparisons": bybit_spot_rows,
        "bybit_futures_comparisons": bybit_futures_rows,
        "bitget_spot_comparisons": bitget_spot_rows,
        "bitget_futures_comparisons": bitget_futures_rows,
        "gate_spot_comparisons": gate_spot_rows,
        "gate_futures_comparisons": gate_futures_rows,
        "wallet_fully_blocked": fully_blocked,
        "wallet_any_network_full_pause": any_pause,
        "wallet_restricted": restricted,
    }


@app.get("/api/gaps")
async def get_gaps() -> dict[str, Any]:
    try:
        return await _compute_gaps_payload()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"upstream http error: {e}") from e
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.websocket("/ws/gaps")
async def websocket_gaps(websocket: WebSocket) -> None:
    """
    연결 후 `_GAP_WS_INTERVAL_SEC`마다 `/api/gaps`와 동일한 JSON을 푸시.
    업스트림 오류 시 `type: error` 객체를 한 번 보내고 주기는 유지.
    """
    await websocket.accept()
    try:
        while True:
            try:
                payload = await _compute_gaps_payload()
                await websocket.send_json(payload)
            except (WebSocketDisconnect, RuntimeError):
                break
            except (httpx.HTTPError, ValueError) as e:
                try:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "detail": str(e),
                            "updated_at_ms": int(time.time() * 1000),
                        }
                    )
                except (WebSocketDisconnect, RuntimeError):
                    break
            try:
                await asyncio.sleep(_GAP_WS_INTERVAL_SEC)
            except asyncio.CancelledError:
                break
    except WebSocketDisconnect:
        pass


@app.post("/api/refresh-limits")
async def refresh_limits() -> dict[str, Any]:
    global _wl_task
    if _wl_loading:
        return {"status": _wl_status, "progress": _wl_progress, "msg": "이미 로딩 중"}
    _wl_task = asyncio.create_task(_load_withdraw_limits())
    return {"status": "started", "msg": "백그라운드 조회 시작"}


@app.get("/api/limits-status")
async def limits_status() -> dict[str, Any]:
    return {
        "status": _wl_status,
        "progress": _wl_progress,
        "cached_count": len(_wl_cache),
        "cached_at_ms": int(_wl_ts * 1000) if _wl_ts else None,
        "loading": _wl_loading,
        "last_error": _wl_last_error,
        "stats": _wl_stats,
    }


@app.get("/")
async def index() -> FileResponse:
    index_path = STATIC_DIR / "index.html"
    if not index_path.is_file():
        raise HTTPException(status_code=404, detail="index.html missing")
    return FileResponse(index_path)


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
