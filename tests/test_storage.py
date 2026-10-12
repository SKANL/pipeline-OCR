"""Storage backends: local filesystem, S3 (moto) and a SeaweedFS roundtrip."""

from __future__ import annotations

import urllib.request
import uuid

import boto3
import pytest
from moto import mock_aws

from app.services.storage import LocalStorage, S3Storage, media_url

BUCKET = "biblioteca"


@pytest.fixture
def s3():
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
        yield S3Storage(endpoint_url=None, access_key_id="x", secret_access_key="x",
                        bucket=BUCKET, region="us-east-1")


def test_local_put_get_and_prefix_prune(tmp_path) -> None:
    storage = LocalStorage(tmp_path)
    for key in ("b/paginas/1.png", "b/paginas/2.png", "b/figuras/1-0.png", "b2/paginas/1.png"):
        storage.put(key, b"x", "image/png")
    storage.delete_prefix("b/", keep={"b/paginas/1.png"})
    assert storage.get("b/paginas/1.png") == b"x"
    assert not (tmp_path / "b/paginas/2.png").exists()
    assert not (tmp_path / "b/figuras/1-0.png").exists()
    assert (tmp_path / "b2/paginas/1.png").exists()  # another book is untouched


def test_local_save_returns_key_and_url_is_media_path(tmp_path) -> None:
    storage = LocalStorage(tmp_path)
    key = storage.save_page_image("b", 1, b"png")
    assert key == "b/paginas/1.png"
    assert storage.url(key) == "/media/b/paginas/1.png"


def test_s3_put_get_prune_and_path(s3) -> None:
    s3.put("b/paginas/1.png", b"one", "image/png")
    s3.put("b/figuras/1-0.png", b"fig", "image/png")
    s3.put("b2/x.png", b"other", "image/png")
    assert s3.get("b/paginas/1.png") == b"one"
    assert s3.path("b/paginas/1.png").read_bytes() == b"one"
    s3.delete_prefix("b/", keep={"b/paginas/1.png"})
    keys = {o["Key"] for o in s3.client.list_objects_v2(Bucket=BUCKET)["Contents"]}
    assert keys == {"b/paginas/1.png", "b2/x.png"}


def test_s3_url_public_base_or_presigned(s3) -> None:
    assert "X-Amz-Signature" in s3.url("b/paginas/1.png")
    s3.public_base_url = "https://cdn.example.org/"
    assert s3.url("b/paginas/1.png") == "https://cdn.example.org/b/paginas/1.png"


def test_s3_presign_put_signs_content_type(s3) -> None:
    url = s3.presign_put("uploads/a.pdf", "application/pdf")
    assert "X-Amz-Signature" in url and "uploads/a.pdf" in url


def test_media_url_accepts_keys_and_legacy_media_paths(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.services.storage.get_storage", lambda: LocalStorage(tmp_path))
    assert media_url("b/paginas/1.png") == "/media/b/paginas/1.png"
    assert media_url("/media/b/paginas/1.png") == "/media/b/paginas/1.png"
    assert media_url(None) is None


def _seaweed_up() -> bool:
    try:
        urllib.request.urlopen("http://localhost:9000", timeout=1)
    except urllib.error.HTTPError:
        return True
    except Exception:  # noqa: BLE001
        return False
    return True


@pytest.mark.skipif(not _seaweed_up(), reason="local S3 (SeaweedFS) not reachable on :9000")
def test_seaweedfs_roundtrip() -> None:
    storage = S3Storage(endpoint_url="http://localhost:9000", access_key_id="any",
                        secret_access_key="any", bucket=BUCKET, region="auto")
    try:
        storage.client.create_bucket(Bucket=BUCKET)
    except storage.client.exceptions.ClientError:
        pass  # already exists
    key = f"test-a1/{uuid.uuid4().hex}.txt"
    put = urllib.request.Request(storage.presign_put(key, "text/plain"), data=b"hola",
                                 method="PUT", headers={"Content-Type": "text/plain"})
    urllib.request.urlopen(put, timeout=5)
    with urllib.request.urlopen(storage.url(key), timeout=5) as response:
        assert response.read() == b"hola"
    storage.put(f"{key}.2", b"bytes", "text/plain")
    assert storage.get(f"{key}.2") == b"bytes"
    storage.delete_prefix("test-a1/")
    assert "Contents" not in storage.client.list_objects_v2(Bucket=BUCKET, Prefix="test-a1/")


def test_s3_delete_prefix_logs_per_key_errors(s3, monkeypatch, caplog) -> None:
    s3.put("b/paginas/1.png", b"one", "image/png")
    monkeypatch.setattr(s3.client, "delete_objects", lambda **kw: {
        "Errors": [{"Key": "b/paginas/1.png", "Code": "AccessDenied", "Message": "nope"}]})
    with caplog.at_level("ERROR"):
        s3.delete_prefix("b/")
    assert "b/paginas/1.png" in caplog.text and "AccessDenied" in caplog.text
