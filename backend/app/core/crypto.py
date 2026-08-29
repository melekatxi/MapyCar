"""Cifrado de campo AES-256-GCM con claves versionadas (envelope encryption).

En producción las claves se obtienen de un KMS/Vault autoalojado (ver ADR-09 y 0.DATA.4);
`EnvKeyProvider` es la implementación de desarrollo que lee claves desde configuración.
Rotar la clave activa no debe romper el descifrado de valores cifrados con claves anteriores.
"""
from __future__ import annotations

import base64
import os
from abc import ABC, abstractmethod

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

_NONCE_SIZE = 12


class KeyProvider(ABC):
    @abstractmethod
    def active_key_id(self) -> str: ...

    @abstractmethod
    def get_key(self, key_id: str) -> bytes: ...


class EnvKeyProvider(KeyProvider):
    """Lee `k1:base64,k2:base64` de configuración. Sustituir por VaultKeyProvider en producción."""

    def __init__(self) -> None:
        settings = get_settings()
        self._active_key_id = settings.field_encryption_active_key_id
        self._keys: dict[str, bytes] = {}
        for entry in filter(None, settings.field_encryption_keys.split(",")):
            key_id, _, value = entry.partition(":")
            self._keys[key_id] = base64.b64decode(value)

    def active_key_id(self) -> str:
        return self._active_key_id

    def get_key(self, key_id: str) -> bytes:
        return self._keys[key_id]


class FieldCipher:
    def __init__(self, key_provider: KeyProvider) -> None:
        self._key_provider = key_provider

    def encrypt(self, plaintext: str) -> str:
        key_id = self._key_provider.active_key_id()
        key = self._key_provider.get_key(key_id)
        nonce = os.urandom(_NONCE_SIZE)
        ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode(), None)
        payload = key_id.encode() + b":" + nonce + ciphertext
        return base64.b64encode(payload).decode()

    def decrypt(self, token: str) -> str:
        raw = base64.b64decode(token.encode())
        key_id_bytes, rest = raw.split(b":", 1)
        key_id = key_id_bytes.decode()
        nonce, ciphertext = rest[:_NONCE_SIZE], rest[_NONCE_SIZE:]
        key = self._key_provider.get_key(key_id)
        return AESGCM(key).decrypt(nonce, ciphertext, None).decode()
