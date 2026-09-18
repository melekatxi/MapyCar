"""Token de enlace externo (≥256 bit) y sesión efímera de canje. Ref: 4.BE.7."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time

from app.core.config import get_settings

TOKEN_BYTES = 32
SESSION_TTL_SECONDS = 3600
COOKIE_NAME = "sofia_public_share"


def _secret() -> bytes:
    return get_settings().database_url.encode()


def generate_share_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_share_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def sign_public_share_session(*, grant_id: str, organization_id: str, ttl: int) -> str:
    payload = {
        "gid": grant_id,
        "org": organization_id,
        "exp": int(time.time()) + max(1, min(ttl, SESSION_TTL_SECONDS)),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(_secret(), payload_bytes, hashlib.sha256).digest()
    return (
        base64.urlsafe_b64encode(payload_bytes).decode()
        + "."
        + base64.urlsafe_b64encode(signature).decode()
    )


def verify_public_share_session(token: str) -> tuple[str, str] | None:
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
    if payload.get("exp", 0) < time.time():
        return None
    grant_id = payload.get("gid")
    org_id = payload.get("org")
    if not grant_id or not org_id:
        return None
    return str(grant_id), str(org_id)
