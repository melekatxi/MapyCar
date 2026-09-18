"""Render de exportación: PDF/PNG esquemáticos y URL de navegación (solo coords).

Ref: 3.BE.13, RF-22. No descarga teselas OSM (política de uso). El enlace no lleva
nombre, dirección ni referencia de paciente.
"""

from __future__ import annotations

import struct
import zlib
from itertools import pairwise
from typing import Any

Point = tuple[float, float]


def navigation_url(points: list[Point]) -> str:
    """Google Maps directions solo con lat,lon (RF-22). Sin nombres ni direcciones."""
    if not points:
        raise ValueError("sin puntos para el enlace de navegación")
    path = "/".join(f"{lat:.5f},{lon:.5f}" for lat, lon in points)
    return f"https://www.google.com/maps/dir/{path}"


def render_pdf(points: list[Point], *, title: str = "Ruta Sofia") -> bytes:
    lines = [title, "Paradas (lat, lon). Sin datos de paciente.", ""]
    for index, (lat, lon) in enumerate(points, start=1):
        lines.append(f"{index}. {lat:.5f},{lon:.5f}")
    lines.append("")
    lines.append("(c) OpenStreetMap contributors")
    text = "\n".join(lines)
    # PDF mínimo 1.4: una página de texto. Latin-1 para el subset de ASCII.
    stream = "BT /F1 12 Tf 50 780 Td 14 TL (" + text.replace("\\", "\\\\").replace("(", "\\(").replace(
        ")", "\\)"
    ).replace("\n", ") Tj T* (") + ") Tj ET"
    stream_bytes = stream.encode("latin-1", errors="replace")
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        (
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n"
        ),
        b"4 0 obj << /Length "
        + str(len(stream_bytes)).encode()
        + b" >> stream\n"
        + stream_bytes
        + b"\nendstream endobj\n",
        b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
    ]
    header = b"%PDF-1.4\n"
    offsets = [0]
    body = b""
    cursor = len(header)
    for obj in objects:
        offsets.append(cursor)
        body += obj
        cursor += len(obj)
    xref_pos = len(header) + len(body)
    xref = b"xref\n0 6\n0000000000 65535 f \n"
    for off in offsets[1:]:
        xref += f"{off:010d} 00000 n \n".encode()
    trailer = (
        b"trailer << /Size 6 /Root 1 0 R >>\nstartxref\n"
        + str(xref_pos).encode()
        + b"\n%%EOF\n"
    )
    return header + body + xref + trailer


def render_png(points: list[Point], *, size: int = 320) -> bytes:
    """Esquema de paradas (puntos azules) sin teselas. Atribución OSM en tests de magia PNG."""
    rgb = bytearray(b"\xff" * (size * size * 3))

    def set_pixel(x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < size and 0 <= y < size:
            idx = (y * size + x) * 3
            rgb[idx : idx + 3] = bytes(color)

    def dot(x: int, y: int, radius: int, color: tuple[int, int, int]) -> None:
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx * dx + dy * dy <= radius * radius:
                    set_pixel(x + dx, y + dy, color)

    if points:
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        min_lat, max_lat = min(lats), max(lats)
        min_lon, max_lon = min(lons), max(lons)
        span_lat = max(max_lat - min_lat, 1e-5)
        span_lon = max(max_lon - min_lon, 1e-5)
        margin = 24
        usable = size - 2 * margin
        coords: list[tuple[int, int]] = []
        for lat, lon in points:
            x = margin + int((lon - min_lon) / span_lon * usable)
            y = margin + int((max_lat - lat) / span_lat * usable)
            coords.append((x, y))
            dot(x, y, 5, (21, 101, 192))
        for (x1, y1), (x2, y2) in pairwise(coords):
            steps = max(abs(x2 - x1), abs(y2 - y1), 1)
            for i in range(steps + 1):
                set_pixel(
                    x1 + (x2 - x1) * i // steps,
                    y1 + (y2 - y1) * i // steps,
                    (13, 71, 161),
                )
    return _png_bytes(size, size, bytes(rgb))


def tour_points(snapshot: dict[str, Any]) -> list[Point]:
    points: list[Point] = []
    origin = snapshot.get("origin") or {}
    dest = snapshot.get("destination") or {}
    if "lat" in origin and "lon" in origin:
        points.append((float(origin["lat"]), float(origin["lon"])))
    for item in snapshot.get("order") or []:
        if item.get("lat") is None or item.get("lon") is None:
            continue
        points.append((float(item["lat"]), float(item["lon"])))
    if "lat" in dest and "lon" in dest:
        dest_pt = (float(dest["lat"]), float(dest["lon"]))
        if not points or points[-1] != dest_pt:
            points.append(dest_pt)
    return points


def _png_bytes(width: int, height: int, rgb: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    raw = b""
    row = width * 3
    for y in range(height):
        raw += b"\x00" + rgb[y * row : (y + 1) * row]
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(
        b"IEND", b""
    )
