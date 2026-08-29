"""UUIDv7 (RFC 9562): PK con orden temporal sin revelar conteos. Ref: diseño sección 6.1."""
from __future__ import annotations

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    unix_ms = int(time.time() * 1000)
    rand = os.urandom(10)
    time_bytes = unix_ms.to_bytes(6, "big")
    raw = bytearray(time_bytes + rand)
    raw[6] = (raw[6] & 0x0F) | 0x70  # versión 7
    raw[8] = (raw[8] & 0x3F) | 0x80  # variante RFC 4122
    return uuid.UUID(bytes=bytes(raw))
