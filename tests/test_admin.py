"""2. POST /api/refresh-limits 는 관리자 토큰 헤더와 쿨다운 없이는 호출할 수 없다."""
from __future__ import annotations

from fastapi.testclient import TestClient


def _count_loader(monkeypatch, m) -> dict:
    calls = {"withdraw": 0}

    async def withdraw():
        calls["withdraw"] += 1

    monkeypatch.setattr(m, "_load_withdraw_limits", withdraw)
    return calls


def test_admin_endpoints_are_404_without_admin_token_config(load_main, monkeypatch):
    m = load_main()
    calls = _count_loader(monkeypatch, m)
    client = TestClient(m.app)
    assert client.post("/api/refresh-limits").status_code == 404
    assert client.post("/api/refresh-limits", headers={"X-Admin-Token": "anything"}).status_code == 404
    assert client.get("/api/limits-status").status_code == 404
    assert client.get("/api/refresh-limits").status_code == 404  # 405가 아님: 경로 존재 자체가 드러나지 않음
    assert calls["withdraw"] == 0


def test_refresh_requires_valid_token_and_honors_cooldown(load_main, monkeypatch):
    m = load_main(ADMIN_TOKEN="s3cret-token", ADMIN_REFRESH_COOLDOWN_SEC=600)
    calls = _count_loader(monkeypatch, m)
    client = TestClient(m.app)

    assert client.post("/api/refresh-limits").status_code == 401
    assert client.post("/api/refresh-limits", headers={"X-Admin-Token": "wrong"}).status_code == 403
    assert calls["withdraw"] == 0

    ok = client.post("/api/refresh-limits", headers={"X-Admin-Token": "s3cret-token"})
    assert ok.status_code == 202
    assert ok.json() == {"status": "started"}
    assert calls["withdraw"] == 1

    again = client.post("/api/refresh-limits", headers={"X-Admin-Token": "s3cret-token"})
    assert again.status_code == 429
    assert 0 < int(again.headers["retry-after"]) <= 600
    assert calls["withdraw"] == 1


def test_refresh_rejects_get_and_limits_status_requires_token(load_main):
    m = load_main(ADMIN_TOKEN="s3cret-token")
    client = TestClient(m.app)
    assert client.get("/api/refresh-limits").status_code == 405
    assert client.get("/api/limits-status").status_code == 401
    r = client.get("/api/limits-status", headers={"X-Admin-Token": "s3cret-token"})
    assert r.status_code == 200
    assert set(r.json()) == {"status", "progress", "cached_count", "cached_at_ms", "loading", "last_error", "stats"}


def test_minimum_cooldown_is_enforced(load_main):
    m = load_main(ADMIN_TOKEN="t", ADMIN_REFRESH_COOLDOWN_SEC=1)
    assert m._ADMIN_REFRESH_COOLDOWN_SEC == 60
