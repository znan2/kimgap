"""테스트 공통 설정.

- 실제 API 키가 든 .env를 읽지 않는다 (KIMGAP_SKIP_DOTENV=1).
- 거래소로 나가는 모든 네트워크 호출(httpx 비동기 요청, websockets.connect)을 막는다. 호출되면 테스트가 실패한다.
- `load_main(**env)`로 환경변수를 바꿔 앱 모듈을 새로 로드한다 (설정은 import 시점에 읽힌다).
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["KIMGAP_SKIP_DOTENV"] = "1"

CONFIG_ENV = [
    "ENABLE_API_DOCS",
    "CORS_ALLOW_ORIGINS",
    "ADMIN_TOKEN",
    "ADMIN_REFRESH_COOLDOWN_SEC",
    "RATE_LIMIT_PER_MIN",
    "WS_MAX_CONNECTIONS",
    "WS_MAX_PER_IP",
    "WALLET_STATUS_INTERVAL_SEC",
    "WITHDRAW_INFO_INTERVAL_SEC",
    "GAP_WS_INTERVAL_SEC",
    "UPBIT_ACCESS_KEY",
    "UPBIT_SECRET_KEY",
    "BITHUMB_ACCESS_KEY",
    "BITHUMB_SECRET_KEY",
]
for _k in CONFIG_ENV:
    os.environ.pop(_k, None)

import httpx  # noqa: E402
import websockets  # noqa: E402


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    async def blocked_send(self, request, *args, **kwargs):
        raise AssertionError(f"테스트 중 네트워크 호출 차단: {request.method} {request.url}")

    def blocked_ws(*args, **kwargs):
        raise AssertionError("테스트 중 거래소 WebSocket 연결 차단")

    monkeypatch.setattr(httpx.AsyncClient, "send", blocked_send)
    monkeypatch.setattr(websockets, "connect", blocked_ws)


@pytest.fixture
def load_main(monkeypatch):
    def _load(**env):
        for k in CONFIG_ENV:
            monkeypatch.delenv(k, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, str(v))
        import gap_dashboard.main as m

        return importlib.reload(m)

    return _load


def sample_payload(ts: int = 1) -> dict:
    return {
        "updated_at_ms": ts,
        "meta": {"wallet": {"mode": "on"}},
        "gaps": [{"symbol": "BTC", "gap_pct": 0.1}],
    }
