"""El arranque crea índices y no falla si Mongo no está accesible."""

from __future__ import annotations

from fastapi.testclient import TestClient

import app.main as main


def test_startup_calls_ensure_indexes(monkeypatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(main, "ensure_indexes", lambda: calls.append(1) or [])
    with TestClient(main.app):
        pass
    assert calls == [1]


def test_startup_survives_mongo_down(monkeypatch) -> None:
    def boom() -> list[str]:
        raise RuntimeError("mongo caído")

    monkeypatch.setattr(main, "ensure_indexes", boom)
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200
