"""1. 거래소 비공개 API는 서버 내부 스케줄러만 호출하고, /api/gaps·/ws/gaps는 캐시만 반환한다."""
from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from conftest import sample_payload


def _count_exchange_calls(monkeypatch, m) -> dict:
    calls = {"compute": 0, "upbit_wallet": 0, "bithumb_wallet": 0, "withdraw": 0}

    async def compute():
        calls["compute"] += 1
        return sample_payload(int(time.time() * 1000))

    async def upbit_wallet(client):
        calls["upbit_wallet"] += 1
        return [], None

    async def bithumb_wallet(client):
        calls["bithumb_wallet"] += 1
        return [], None

    async def withdraw():
        calls["withdraw"] += 1

    monkeypatch.setattr(m, "_compute_gaps_payload", compute)
    monkeypatch.setattr(m, "_fetch_upbit_wallet_safe", upbit_wallet)
    monkeypatch.setattr(m, "_fetch_bithumb_wallet_safe", bithumb_wallet)
    monkeypatch.setattr(m, "_load_withdraw_limits", withdraw)
    return calls


def test_http_requests_never_call_exchanges(load_main, monkeypatch):
    m = load_main(RATE_LIMIT_PER_MIN=100000)
    calls = _count_exchange_calls(monkeypatch, m)
    m._LATEST_PAYLOAD = sample_payload(1)
    client = TestClient(m.app)
    for _ in range(50):
        r = client.get("/api/gaps")
        assert r.status_code == 200
        assert r.json()["updated_at_ms"] == 1
    assert calls == {"compute": 0, "upbit_wallet": 0, "bithumb_wallet": 0, "withdraw": 0}


def test_websocket_clients_never_call_exchanges(load_main, monkeypatch):
    m = load_main()
    calls = _count_exchange_calls(monkeypatch, m)
    m._LATEST_PAYLOAD = sample_payload(7)
    client = TestClient(m.app)
    for _ in range(3):
        with client.websocket_connect("/ws/gaps") as ws:
            assert ws.receive_json()["updated_at_ms"] == 7
    assert calls == {"compute": 0, "upbit_wallet": 0, "bithumb_wallet": 0, "withdraw": 0}


def test_gaps_is_503_until_first_payload(load_main):
    m = load_main()
    m._LATEST_PAYLOAD = None
    r = TestClient(m.app).get("/api/gaps")
    assert r.status_code == 503
    assert r.headers["retry-after"] == "5"


def test_wallet_scheduler_calls_private_api_once_per_run_and_hides_error_text(load_main, monkeypatch):
    m = load_main()
    calls = _count_exchange_calls(monkeypatch, m)

    async def upbit_fail(client):
        calls["upbit_wallet"] += 1
        return None, "Client error '401 Unauthorized' for url 'https://api.upbit.com/v1/status/wallet'"

    monkeypatch.setattr(m, "_fetch_upbit_wallet_safe", upbit_fail)
    asyncio.run(m._refresh_wallet_status())
    assert calls["upbit_wallet"] == 1 and calls["bithumb_wallet"] == 1
    assert m._WALLET_CACHE["up_err"] == "auth_error"  # 원문(URL) 대신 코드만
    assert m._WALLET_CACHE["bh_raw"] == [] and m._WALLET_CACHE["ts"] > 0


def _patch_public_market(monkeypatch, m):
    async def upbit_prices(client):
        return {"BTC": 100_000_000.0}

    async def bithumb_prices(client):
        return {"BTC": 100_100_000.0}

    async def ref(client):
        return {"BTC": 70_000.0}, {"BTC": "binance"}, {"binance": 1, "bybit": 0, "bitget": 0, "okx": 0, "gate": 0}

    async def snapshot(client):
        return {}, {}

    async def rate(client):
        return 1400.0

    async def forbidden(*args, **kwargs):
        raise AssertionError("페이로드 계산 중 비공개 API 호출")

    monkeypatch.setattr(m, "_fetch_upbit_krw_prices", upbit_prices)
    monkeypatch.setattr(m, "_fetch_bithumb_krw_prices", bithumb_prices)
    monkeypatch.setattr(m, "_fetch_reference_usdt_prices", ref)
    for name in ("binance", "bybit", "bitget", "okx", "gate"):
        monkeypatch.setattr(m, f"_{name}_price_snapshots", snapshot)
    monkeypatch.setattr(m, "_fetch_usdt_krw_rate", rate)
    monkeypatch.setattr(m, "_fetch_upbit_wallet_safe", forbidden)
    monkeypatch.setattr(m, "_fetch_bithumb_wallet_safe", forbidden)
    monkeypatch.setattr(m, "_load_withdraw_limits", forbidden)


def test_compute_payload_reads_wallet_cache_instead_of_private_api(load_main, monkeypatch):
    m = load_main()
    _patch_public_market(monkeypatch, m)
    monkeypatch.setattr(m, "UPBIT_ACCESS_KEY", "k")
    monkeypatch.setattr(m, "UPBIT_SECRET_KEY", "s")
    monkeypatch.setattr(m, "BITHUMB_ACCESS_KEY", "k")
    monkeypatch.setattr(m, "BITHUMB_SECRET_KEY", "s")
    m._WALLET_CACHE.update(
        {
            "up_raw": [{"currency": "BTC", "net_type": "BTC", "wallet_state": "working", "block_state": "normal"}],
            "up_err": None,
            "bh_raw": None,
            "bh_err": "auth_error",
            "ts": time.time(),
        }
    )
    payload = asyncio.run(m._compute_gaps_payload())
    wallet = payload["meta"]["wallet"]
    assert wallet["mode"] == "partial"
    assert wallet["bithumb_error"] == "auth_error"
    btc = next(r for r in payload["gaps"] if r["symbol"] == "BTC")
    assert btc["upbit_networks"][0]["net_type"] == "BTC"
    assert btc["upbit_wallet"]["withdraw_available"] is True


def test_lifespan_runs_schedulers_and_stops_them(load_main, monkeypatch):
    m = load_main()
    calls = _count_exchange_calls(monkeypatch, m)

    async def noop():
        return None

    monkeypatch.setattr(m, "_load_exchange_registries_at_startup", noop)
    for name in ("binance", "bybit", "bitget", "okx", "gate"):
        monkeypatch.setattr(m, f"_start_{name}_ws_tasks", lambda: None)
        monkeypatch.setattr(m, f"_stop_{name}_ws_tasks", noop)

    with TestClient(m.app) as client:
        deadline = time.time() + 5
        while client.get("/api/gaps").status_code != 200:
            assert time.time() < deadline, "첫 페이로드가 만들어지지 않음"
            time.sleep(0.05)
        tasks = list(m._BACKGROUND_TASKS)
        assert len(tasks) == 3 and not any(t.done() for t in tasks)
    assert m._BACKGROUND_TASKS == []
    assert all(t.done() for t in tasks)
    # 기동 시 지갑 1회 + 출금 정보 1회 + 페이로드 계산(스케줄러만)
    assert calls["upbit_wallet"] == 1 and calls["bithumb_wallet"] == 1
    assert calls["withdraw"] == 1
    assert calls["compute"] >= 1


@pytest.mark.parametrize("path", ["/api/gaps"])
def test_public_payload_has_no_withdrawal_amounts(load_main, monkeypatch, path):
    """3. 공개 응답에는 출금 한도 금액이 없고 출금 가능 여부(불리언)만 있다."""
    m = load_main()
    _patch_public_market(monkeypatch, m)
    m._wl_cache = {"BTC": {"upbit_can_withdraw": True, "bithumb_can_withdraw": False}}
    payload = asyncio.run(m._compute_gaps_payload())
    m._LATEST_PAYLOAD = payload
    body = TestClient(m.app).get(path).json()
    btc = next(r for r in body["gaps"] if r["symbol"] == "BTC")
    assert btc["withdraw_status"] == {"upbit_can_withdraw": True, "bithumb_can_withdraw": False}
    assert "withdraw_limits" not in btc
    text = str(body)
    for banned in ("daily", "remaining", "minimum", "_min", "wl_progress"):
        assert banned not in text


def test_withdraw_chance_parser_keeps_only_boolean():
    import gap_dashboard.main as m

    body = {
        "withdraw_limit": {
            "currency": "BTC",
            "minimum": "0.0008",
            "daily": "10",
            "remaining_daily_krw": "500000000",
            "can_withdraw": True,
        },
        "account": {"balance": "1.23"},
    }
    assert m._parse_can_withdraw(body) is True
    assert m._parse_can_withdraw({"withdraw_limit": {"can_withdraw": "false"}}) is False
    assert m._parse_can_withdraw({"withdraw_limit": {}}) is None
    assert m._parse_can_withdraw(None) is None
