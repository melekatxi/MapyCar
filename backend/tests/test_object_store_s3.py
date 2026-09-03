"""Contrato del ObjectStore S3 cifrado. El fake InMemory sigue en tests e2e via override."""
from __future__ import annotations

import base64
import os

import boto3
import pytest
from moto import mock_aws

from app.adapters.object_store.fake import InMemoryObjectStore
from app.adapters.object_store.s3 import S3ObjectStore
from app.core.config import get_settings
from app.core.crypto import KeyProvider, ObjectCipher
from app.modules.imports.deps import get_object_store

PLAINTEXT = b"id_paciente;nombre\nPAC-001;Calle Mayor 1, Bilbao\n"
OBJECT_KEY = "imports/org-id/batch-id/pacientes.csv"


class _StaticKeyProvider(KeyProvider):
    def __init__(self, active: str, keys: dict[str, bytes]) -> None:
        self._active = active
        self._keys = keys

    def active_key_id(self) -> str:
        return self._active

    def get_key(self, key_id: str) -> bytes:
        return self._keys[key_id]


def _cipher() -> ObjectCipher:
    return ObjectCipher(_StaticKeyProvider("k1", {"k1": os.urandom(32)}))


def _store(cipher: ObjectCipher, *, bucket: str = "sofia") -> S3ObjectStore:
    client = boto3.client(
        "s3",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    return S3ObjectStore(
        bucket=bucket,
        cipher=cipher,
        endpoint_url="http://s3.amazonaws.com",
        access_key="test",
        secret_key="test",
        region="us-east-1",
        client=client,
    )


def _raw_s3_body(*, bucket: str, key: str) -> bytes:
    client = boto3.client(
        "s3",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    return client.get_object(Bucket=bucket, Key=key)["Body"].read()


@mock_aws
def test_put_get_roundtrip_survives_new_store_instance() -> None:
    cipher = _cipher()
    first = _store(cipher)
    first.put(key=OBJECT_KEY, content=PLAINTEXT, content_type="text/csv")

    restarted = _store(cipher)
    assert restarted is not first
    assert restarted.get(key=OBJECT_KEY) == PLAINTEXT


@mock_aws
def test_payload_at_rest_is_not_plaintext() -> None:
    cipher = _cipher()
    _store(cipher).put(key=OBJECT_KEY, content=PLAINTEXT, content_type="text/csv")

    raw = _raw_s3_body(bucket="sofia", key=OBJECT_KEY)
    assert raw != PLAINTEXT
    assert b"Calle Mayor" not in raw
    assert b"PAC-001" not in raw
    assert cipher.decrypt(raw) == PLAINTEXT


@mock_aws
def test_object_keys_remain_listable() -> None:
    _store(_cipher()).put(key=OBJECT_KEY, content=PLAINTEXT, content_type="text/csv")
    client = boto3.client(
        "s3",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    listed = client.list_objects_v2(Bucket="sofia")
    keys = [item["Key"] for item in listed.get("Contents", [])]
    assert OBJECT_KEY in keys


def test_get_object_store_uses_inmemory_when_endpoint_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOFIA_S3_ENDPOINT_URL", raising=False)
    monkeypatch.setenv("SOFIA_S3_ENDPOINT_URL", "")
    get_settings.cache_clear()
    get_object_store.cache_clear()
    try:
        assert isinstance(get_object_store(), InMemoryObjectStore)
    finally:
        get_object_store.cache_clear()
        get_settings.cache_clear()


def test_get_object_store_uses_s3_when_endpoint_set(monkeypatch: pytest.MonkeyPatch) -> None:
    key_b64 = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("MOTO_S3_CUSTOM_ENDPOINTS", "http://minio:9000")
    monkeypatch.setenv("SOFIA_S3_ENDPOINT_URL", "http://minio:9000")
    monkeypatch.setenv("SOFIA_S3_ACCESS_KEY", "test")
    monkeypatch.setenv("SOFIA_S3_SECRET_KEY", "test")
    monkeypatch.setenv("SOFIA_S3_BUCKET", "sofia-wired")
    monkeypatch.setenv("SOFIA_S3_REGION", "us-east-1")
    monkeypatch.setenv("SOFIA_FIELD_ENCRYPTION_ACTIVE_KEY_ID", "k1")
    monkeypatch.setenv("SOFIA_FIELD_ENCRYPTION_KEYS", f"k1:{key_b64}")
    get_settings.cache_clear()
    get_object_store.cache_clear()
    try:
        with mock_aws():
            store = get_object_store()
            assert isinstance(store, S3ObjectStore)
            store.put(key=OBJECT_KEY, content=PLAINTEXT, content_type="text/csv")
            assert store.get(key=OBJECT_KEY) == PLAINTEXT
            raw = _raw_s3_body(bucket="sofia-wired", key=OBJECT_KEY)
            assert b"Calle Mayor" not in raw
    finally:
        get_object_store.cache_clear()
        get_settings.cache_clear()
