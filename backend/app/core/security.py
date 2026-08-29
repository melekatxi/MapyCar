"""Hashing de contraseñas (Argon2id) y firma simple de tokens de sesión."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import get_settings

_hasher = PasswordHasher()

TOKEN_TTL_SECONDS = 3600


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except VerifyMismatchError:
        return False


def _secret() -> bytes:
    return get_settings().database_url.encode()  # placeholder: en prod, secreto dedicado vía KMS


def sign_session_token(*, user_id: str) -> str:
    payload = {"sub": user_id, "exp": int(time.time()) + TOKEN_TTL_SECONDS}
    payload_bytes = json.dumps(payload).encode()
    signature = hmac.new(_secret(), payload_bytes, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload_bytes).decode() + "." + base64.urlsafe_b64encode(signature).decode()


def verify_session_token(token: str) -> str | None:
    try:
        payload_b64, sig_b64 = token.split(".")
        payload_bytes = base64.urlsafe_b64decode(payload_b64.encode())
        signature = base64.urlsafe_b64decode(sig_b64.encode())
    except (ValueError, binascii.Error):
        return None
    expected = hmac.new(_secret(), payload_bytes, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        return None
    payload = json.loads(payload_bytes)
    if payload["exp"] < time.time():
        return None
    return payload["sub"]
