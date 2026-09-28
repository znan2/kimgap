"""4. API 문서는 기본으로 꺼져 있다. 5. CORS는 설정한 출처만, GET만 허용한다."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import sample_payload

DOC_PATHS = ["/docs", "/redoc", "/openapi.json"]


@pytest.mark.parametrize("path", DOC_PATHS)
def test_api_docs_disabled_by_default(load_main, path):
    m = load_main()
    assert TestClient(m.app).get(path).status_code == 404


@pytest.mark.parametrize("path", DOC_PATHS)
def test_api_docs_enabled_only_by_env(load_main, path):
    m = load_main(ENABLE_API_DOCS="1")
    assert TestClient(m.app).get(path).status_code == 200


def test_no_cors_headers_when_not_configured(load_main):
    m = load_main()
    m._LATEST_PAYLOAD = sample_payload()
    client = TestClient(m.app)
    r = client.get("/api/gaps", headers={"Origin": "https://evil.example"})
    assert r.status_code == 200
    assert "access-control-allow-origin" not in r.headers
    pre = client.options(
        "/api/gaps",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in pre.headers


def test_cors_allows_only_configured_origin_and_get(load_main):
    m = load_main(CORS_ALLOW_ORIGINS="https://kimgap.com, https://demo.kimgap.com/")
    m._LATEST_PAYLOAD = sample_payload()
    client = TestClient(m.app)

    ok = client.get("/api/gaps", headers={"Origin": "https://kimgap.com"})
    assert ok.headers["access-control-allow-origin"] == "https://kimgap.com"
    trailing = client.get("/api/gaps", headers={"Origin": "https://demo.kimgap.com"})
    assert trailing.headers["access-control-allow-origin"] == "https://demo.kimgap.com"

    evil = client.get("/api/gaps", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in evil.headers

    pre_get = client.options(
        "/api/gaps", headers={"Origin": "https://kimgap.com", "Access-Control-Request-Method": "GET"}
    )
    assert pre_get.status_code == 200
    assert pre_get.headers["access-control-allow-methods"] == "GET"

    pre_post = client.options(
        "/api/refresh-limits", headers={"Origin": "https://kimgap.com", "Access-Control-Request-Method": "POST"}
    )
    assert pre_post.status_code == 400
