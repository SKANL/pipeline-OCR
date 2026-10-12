"""Rate limiting (token bucket per client) and `/ingest` allowed-root confinement."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import ratelimit
from app.config import get_settings
from app.main import app

client = TestClient(app)


@pytest.fixture
def env(monkeypatch):
    def set_(**values):
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()
        ratelimit.reset()

    yield set_
    get_settings.cache_clear()
    ratelimit.reset()


def test_bucket_refills_over_time() -> None:
    bucket = ratelimit.TokenBucket()
    assert [bucket.take("k", 2, 60, now=0.0) for _ in range(3)] == [0.0, 0.0, pytest.approx(30.0)]
    assert bucket.take("k", 2, 60, now=30.0) == 0.0  # one token back after 30 s
    assert bucket.take("other", 2, 60, now=30.0) == 0.0  # separate client


def test_write_endpoints_return_429_with_retry_after(env) -> None:
    env(RATE_LIMIT_WRITE_PER_MIN="2")
    codes = [client.post("/api/v1/uploads", json={"archivos": []}).status_code for _ in range(3)]
    assert codes == [422, 422, 429]
    blocked = client.post("/api/v1/uploads", json={"archivos": []})
    assert int(blocked.headers["Retry-After"]) >= 1


def test_search_has_its_own_budget(env) -> None:
    env(RATE_LIMIT_SEARCH_PER_MIN="1")
    assert client.get("/api/v1/search", params={"q": ""}).status_code == 422
    assert client.get("/api/v1/search", params={"q": ""}).status_code == 429


def test_forwarded_for_only_trusted_when_enabled(env) -> None:
    env(RATE_LIMIT_WRITE_PER_MIN="1")
    spoof = [client.post("/api/v1/uploads", json={"archivos": []}, headers={"X-Forwarded-For": f"9.9.9.{i}"})
             for i in range(2)]
    assert [r.status_code for r in spoof] == [422, 429]  # header ignored: same client

    env(RATE_LIMIT_WRITE_PER_MIN="1", TRUST_PROXY_HEADERS="true")
    # The proxy appends the real peer on the right; the left-most entries are client-controlled.
    rotated = [client.post("/api/v1/uploads", json={"archivos": []}, headers={"X-Forwarded-For": f"9.9.9.{i}, 10.0.0.1"})
               for i in range(2)]
    assert [r.status_code for r in rotated] == [422, 429]
    other = client.post("/api/v1/uploads", json={"archivos": []}, headers={"X-Forwarded-For": "9.9.9.0, 10.0.0.2"})
    assert other.status_code == 422


def test_ingest_disabled_without_allowed_roots(env) -> None:
    env(INGEST_ALLOWED_ROOTS="")
    response = client.post("/api/v1/ingest", json={"root": str(Path.cwd())})
    assert response.status_code == 403


def test_ingest_rejects_paths_outside_allowed_roots(env, tmp_path) -> None:
    allowed = tmp_path / "corpus"
    (allowed / "libro").mkdir(parents=True)
    outside = tmp_path / "fuera"
    outside.mkdir()
    env(INGEST_ALLOWED_ROOTS=str(allowed))
    assert client.post("/api/v1/ingest", json={"root": str(outside)}).status_code == 403
    assert client.post("/api/v1/ingest", json={"root": str(allowed / ".." / "fuera")}).status_code == 403
    assert client.post("/api/v1/ingest", json={"root": str(allowed / "no-existe")}).status_code == 400


def test_ingest_rejects_symlink_escaping_root(env, tmp_path) -> None:
    allowed = tmp_path / "corpus"
    allowed.mkdir()
    outside = tmp_path / "fuera"
    outside.mkdir()
    link = allowed / "atajo"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not permitted on this system")
    env(INGEST_ALLOWED_ROOTS=str(allowed))
    assert client.post("/api/v1/ingest", json={"root": str(link)}).status_code == 403


def test_ops_key_ingests_within_allowed_root(env, tmp_path) -> None:
    (tmp_path / "libro").mkdir()
    (tmp_path / "libro" / "paginas").mkdir()
    (tmp_path / "libro" / "paginas" / "1.txt").write_text("hola", encoding="utf-8")
    env(INGEST_ALLOWED_ROOTS=str(tmp_path), API_KEY="ops-key")
    assert client.post("/api/v1/ingest", json={"root": str(tmp_path)}).status_code == 401
    response = client.post("/api/v1/ingest", json={"root": str(tmp_path / "otra")}, headers={"X-API-Key": "ops-key"})
    assert response.status_code == 400  # past auth and confinement; missing dir
