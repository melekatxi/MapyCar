import base64
import os

from app.core.crypto import EnvKeyProvider, FieldCipher, KeyProvider, ObjectCipher


class _StaticKeyProvider(KeyProvider):
    def __init__(self, active: str, keys: dict[str, bytes]) -> None:
        self._active = active
        self._keys = keys

    def active_key_id(self) -> str:
        return self._active

    def get_key(self, key_id: str) -> bytes:
        return self._keys[key_id]


def test_encrypt_decrypt_roundtrip_with_active_key() -> None:
    provider = _StaticKeyProvider("k1", {"k1": os.urandom(32)})
    cipher = FieldCipher(provider)

    token = cipher.encrypt("Calle Mayor 1, Bilbao")

    assert cipher.decrypt(token) == "Calle Mayor 1, Bilbao"
    assert "Calle Mayor" not in token


def test_rotating_active_key_does_not_break_previous_ciphertexts() -> None:
    keys = {"k1": os.urandom(32), "k2": os.urandom(32)}
    provider = _StaticKeyProvider("k1", keys)
    cipher = FieldCipher(provider)
    old_token = cipher.encrypt("dirección antigua")

    provider._active = "k2"  # simula rotación de clave activa
    new_token = cipher.encrypt("dirección nueva")

    assert cipher.decrypt(old_token) == "dirección antigua"
    assert cipher.decrypt(new_token) == "dirección nueva"


def test_object_cipher_roundtrip_and_framing_matches_field_cipher() -> None:
    provider = _StaticKeyProvider("k1", {"k1": os.urandom(32)})
    objects = ObjectCipher(provider)
    fields = FieldCipher(provider)
    plaintext = b"Calle Mayor 1, Bilbao"

    token = objects.encrypt(plaintext)

    assert objects.decrypt(token) == plaintext
    assert b"Calle Mayor" not in token
    assert fields.decrypt(base64.b64encode(token).decode()) == plaintext.decode()


def test_object_cipher_rotation_does_not_break_previous_payloads() -> None:
    keys = {"k1": os.urandom(32), "k2": os.urandom(32)}
    provider = _StaticKeyProvider("k1", keys)
    cipher = ObjectCipher(provider)
    old = cipher.encrypt(b"csv antiguo")

    provider._active = "k2"
    new = cipher.encrypt(b"csv nuevo")

    assert cipher.decrypt(old) == b"csv antiguo"
    assert cipher.decrypt(new) == b"csv nuevo"


def test_env_key_provider_reads_keys_from_settings(monkeypatch) -> None:
    key_b64 = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("SOFIA_FIELD_ENCRYPTION_ACTIVE_KEY_ID", "k1")
    monkeypatch.setenv("SOFIA_FIELD_ENCRYPTION_KEYS", f"k1:{key_b64}")
    from app.core.config import get_settings

    get_settings.cache_clear()
    provider = EnvKeyProvider()
    assert provider.active_key_id() == "k1"
    assert len(provider.get_key("k1")) == 32
