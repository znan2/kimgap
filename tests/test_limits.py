"""6. 요청 속도 제한과 WebSocket 동시 연결 상한.

참고: accept 전에 닫는 거부의 close 코드(1008/1013)는 TestClient에서 보이는 값이다. 실제 uvicorn에서는 HTTP 403으로 보인다.
"""
from __future__ import annotations

import asyncio
import contextlib

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from conftest import sample_payload


def test_http_rate_limit_returns_429_with_retry_after(load_main):
    m = load_main(RATE_LIMIT_PER_MIN=5)
    m._LATEST_PAYLOAD = sample_payload()
    client = TestClient(m.app)
    codes = [client.get("/api/gaps").status_code for _ in range(5)]
    assert codes == [200] * 5
    blocked = client.get("/api/gaps")
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1
    # 정적 파일은 제한하지 않는다 (페이지 로드마다 여러 개 요청되므로)
    assert client.get("/static/mock-data.js").status_code == 200


def test_rate_limited_response_keeps_cors_headers(load_main):
    m = load_main(RATE_LIMIT_PER_MIN=1, CORS_ALLOW_ORIGINS="https://kimgap.com")
    m._LATEST_PAYLOAD = sample_payload()
    client = TestClient(m.app)
    headers = {"Origin": "https://kimgap.com"}
    assert client.get("/api/gaps", headers=headers).status_code == 200
    blocked = client.get("/api/gaps", headers=headers)
    assert blocked.status_code == 429
    assert blocked.headers["access-control-allow-origin"] == "https://kimgap.com"


def test_websocket_connects_are_rate_limited(load_main):
    m = load_main(RATE_LIMIT_PER_MIN=2, WS_MAX_PER_IP=10)
    m._LATEST_PAYLOAD = sample_payload()
    client = TestClient(m.app)
    for _ in range(2):  # 연결 → 페이로드 수신 → 끊기를 반복해도
        with client.websocket_connect("/ws/gaps") as ws:
            ws.receive_json()
    with pytest.raises(WebSocketDisconnect) as exc:  # 분당 한도를 넘으면 거부
        with client.websocket_connect("/ws/gaps") as ws:
            ws.receive_json()
    assert exc.value.code == 1008
    assert m._WS_SLOTS.total == 0


def test_websocket_slot_released_on_disconnect_without_new_payload(load_main):
    """uvicorn은 끊긴 연결의 핸들러를 취소하지 않는다. 페이로드가 바뀌지 않아도 끊김을 감지해 슬롯을 반납해야 한다."""
    m = load_main()
    m._LATEST_PAYLOAD = None  # 워밍업(또는 거래소 장애로 갱신 없음)

    class FakeWebSocket:
        headers: dict = {}
        client = type("Client", (), {"host": "203.0.113.7"})()

        def __init__(self):
            self.inbox: asyncio.Queue = asyncio.Queue()

        async def accept(self):
            pass

        async def close(self, code=1000):
            pass

        async def send_json(self, data):
            pass

        async def receive(self):
            return await self.inbox.get()

    async def run():
        ws = FakeWebSocket()
        handler = asyncio.create_task(m.websocket_gaps(ws))
        await asyncio.sleep(0.05)
        assert m._WS_SLOTS.total == 1
        await ws.inbox.put({"type": "websocket.disconnect", "code": 1001})
        await asyncio.wait_for(handler, timeout=2)  # 취소 없이 스스로 끝나야 한다
        assert m._WS_SLOTS.total == 0

    asyncio.run(run())


def test_large_payload_is_gzip_compressed(load_main):
    m = load_main()
    big = {"updated_at_ms": 1, "gaps": [{"symbol": f"C{i}", "gap_pct": 0.1} for i in range(2000)]}
    m._LATEST_PAYLOAD = big
    r = TestClient(m.app).get("/api/gaps", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers["content-encoding"] == "gzip"
    assert len(r.json()["gaps"]) == 2000


def test_rate_limiter_is_per_key_and_refills():
    import gap_dashboard.main as m

    now = [1000.0]
    limiter = m._RateLimiter(2, clock=lambda: now[0])
    assert limiter.check("a") == 0 and limiter.check("a") == 0
    assert limiter.check("a") > 0  # a는 소진
    assert limiter.check("b") == 0  # 다른 IP는 영향 없음
    now[0] += 30  # 분당 2개 → 30초에 1개 회복
    assert limiter.check("a") == 0


def test_rate_limiter_memory_is_bounded():
    import gap_dashboard.main as m

    now = [0.0]
    limiter = m._RateLimiter(60, clock=lambda: now[0], max_keys=100)
    for i in range(100):
        limiter.check(f"ip{i}")
    now[0] += 120  # 모두 가득 찬 상태가 될 만큼 지남
    limiter.check("new")
    assert len(limiter._buckets) <= 101 and "new" in limiter._buckets


def _open(client, n, **kw):
    stack = contextlib.ExitStack()
    sockets = [stack.enter_context(client.websocket_connect("/ws/gaps", **kw)) for _ in range(n)]
    for s in sockets:
        s.receive_json()
    return stack


def test_websocket_per_ip_limit(load_main):
    m = load_main(WS_MAX_PER_IP=2, WS_MAX_CONNECTIONS=50)
    m._LATEST_PAYLOAD = sample_payload()
    client = TestClient(m.app)
    with _open(client, 2):
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/ws/gaps") as ws:
                ws.receive_json()
        assert exc.value.code == 1013
        assert m._WS_SLOTS.total == 2
    # 닫힌 연결의 슬롯은 반납된다
    with _open(client, 2):
        assert m._WS_SLOTS.total == 2
    assert m._WS_SLOTS.total == 0


def test_websocket_global_limit(load_main):
    m = load_main(WS_MAX_PER_IP=10, WS_MAX_CONNECTIONS=1)
    m._LATEST_PAYLOAD = sample_payload()
    client = TestClient(m.app)
    with _open(client, 1):
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/ws/gaps") as ws:
                ws.receive_json()
        assert exc.value.code == 1013


def test_websocket_origin_restricted_when_cors_origins_configured(load_main):
    m = load_main(CORS_ALLOW_ORIGINS="https://kimgap.com")
    m._LATEST_PAYLOAD = sample_payload()
    client = TestClient(m.app)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/gaps", headers={"Origin": "https://evil.example"}) as ws:
            ws.receive_json()
    assert exc.value.code == 1008
    with client.websocket_connect("/ws/gaps", headers={"Origin": "https://kimgap.com"}) as ws:
        assert ws.receive_json()["updated_at_ms"] == 1
    with client.websocket_connect("/ws/gaps") as ws:  # Origin 없는 비브라우저 클라이언트
        assert ws.receive_json()["updated_at_ms"] == 1
    assert m._WS_SLOTS.total == 0
