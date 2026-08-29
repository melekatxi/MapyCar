"""KeyProvider respaldado por HashiCorp Vault (KMS autoalojado). Ref: ADR-09, 0.DATA.4."""
from __future__ import annotations

import base64

import hvac

from app.core.crypto import KeyProvider

_DEFAULT_MOUNT_POINT = "secret"
_DEFAULT_PATH = "field-encryption"


def write_keys(
    client: hvac.Client,
    *,
    active_key_id: str,
    keys: dict[str, bytes],
    mount_point: str = _DEFAULT_MOUNT_POINT,
    path: str = _DEFAULT_PATH,
) -> None:
    """Escribe (o rota) el conjunto de claves activo en Vault (KV v2)."""
    client.secrets.kv.v2.create_or_update_secret(
        path=path,
        mount_point=mount_point,
        secret={
            "active_key_id": active_key_id,
            "keys": {key_id: base64.b64encode(value).decode() for key_id, value in keys.items()},
        },
    )


class VaultKeyProvider(KeyProvider):
    def __init__(
        self,
        client: hvac.Client,
        *,
        mount_point: str = _DEFAULT_MOUNT_POINT,
        path: str = _DEFAULT_PATH,
    ) -> None:
        self._client = client
        self._mount_point = mount_point
        self._path = path

    def _read(self) -> dict:
        response = self._client.secrets.kv.v2.read_secret_version(
            path=self._path, mount_point=self._mount_point, raise_on_deleted_version=True
        )
        return response["data"]["data"]

    def active_key_id(self) -> str:
        return self._read()["active_key_id"]

    def get_key(self, key_id: str) -> bytes:
        data = self._read()
        return base64.b64decode(data["keys"][key_id])
