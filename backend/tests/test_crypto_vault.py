"""Prueba de integración contra un Vault real (KMS autoalojado). Ref: 0.DATA.4."""
from __future__ import annotations

import os
from collections.abc import Iterator

import hvac
import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

from app.core.crypto import FieldCipher
from app.core.crypto_vault import VaultKeyProvider, write_keys

ROOT_TOKEN = "sofia-test-root-token"


@pytest.fixture(scope="module")
def vault_client() -> Iterator[hvac.Client]:
    container = (
        DockerContainer("hashicorp/vault:1.17")
        .with_env("VAULT_DEV_ROOT_TOKEN_ID", ROOT_TOKEN)
        .with_env("VAULT_DEV_LISTEN_ADDRESS", "0.0.0.0:8200")
        .with_exposed_ports(8200)
        .with_kwargs(cap_add=["IPC_LOCK"])
    )
    with container:
        wait_for_logs(container, "Vault server started")
        host = container.get_container_host_ip()
        port = container.get_exposed_port(8200)
        client = hvac.Client(url=f"http://{host}:{port}", token=ROOT_TOKEN)
        yield client


def test_vault_backed_cipher_encrypts_and_decrypts(vault_client: hvac.Client) -> None:
    write_keys(vault_client, active_key_id="k1", keys={"k1": os.urandom(32)})
    provider = VaultKeyProvider(vault_client)
    cipher = FieldCipher(provider)

    token = cipher.encrypt("Calle Mayor 1, Bilbao")

    assert cipher.decrypt(token) == "Calle Mayor 1, Bilbao"


def test_vault_key_rotation_keeps_previous_values_readable(vault_client: hvac.Client) -> None:
    key_k1 = os.urandom(32)
    write_keys(vault_client, active_key_id="k1", keys={"k1": key_k1})
    provider = VaultKeyProvider(vault_client)
    cipher = FieldCipher(provider)
    old_token = cipher.encrypt("dirección con clave k1")

    key_k2 = os.urandom(32)
    write_keys(vault_client, active_key_id="k2", keys={"k1": key_k1, "k2": key_k2})
    new_token = cipher.encrypt("dirección con clave k2")

    assert cipher.decrypt(old_token) == "dirección con clave k1"
    assert cipher.decrypt(new_token) == "dirección con clave k2"
