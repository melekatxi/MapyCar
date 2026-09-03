"""Genera un .xls BIFF8 mínimo (OLE2) para pruebas. Datos ficticios; no usa xlwt."""

from __future__ import annotations

import struct

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
FREESECT = 0xFFFFFFFF
ENDOFCHAIN = 0xFFFFFFFE
FATSECT = 0xFFFFFFFD
NOSTREAM = 0xFFFFFFFF
SECTOR_SIZE = 512
MINI_STREAM_CUTOFF = 4096


def _record(rec_type: int, data: bytes) -> bytes:
    return struct.pack("<HH", rec_type, len(data)) + data


def _bof(dt: int) -> bytes:
    return _record(0x0809, struct.pack("<HHHHII", 0x0600, dt, 0x0C65, 0x07CC, 0x41, 0x0206))


def _eof() -> bytes:
    return _record(0x000A, b"")


def _short_string(text: str) -> bytes:
    encoded = text.encode("latin-1")
    return bytes([len(encoded), 0x00]) + encoded


def _sst_string(text: str) -> bytes:
    encoded = text.encode("latin-1")
    return struct.pack("<HB", len(text), 0x00) + encoded


def _workbook_stream(rows: list[list[str]]) -> bytes:
    strings: list[str] = []
    indexes: dict[str, int] = {}

    def intern(text: str) -> int:
        if text not in indexes:
            indexes[text] = len(strings)
            strings.append(text)
        return indexes[text]

    for row in rows:
        for cell in row:
            intern(cell)

    ncols = max((len(row) for row in rows), default=0)
    sheet = bytearray()
    sheet.extend(_bof(0x0010))
    sheet.extend(_record(0x0200, struct.pack("<IIHHH", 0, len(rows), 0, ncols, 0)))
    for rowx, row in enumerate(rows):
        for colx, value in enumerate(row):
            sheet.extend(_record(0x00FD, struct.pack("<HHHI", rowx, colx, 0x000F, intern(value))))
    sheet.extend(_eof())

    prefix = b"".join(
        (
            _bof(0x0005),
            _record(0x0042, struct.pack("<H", 1200)),
            _record(
                0x003D, struct.pack("<HHHHHHHHH", 0, 0, 0x1D1C, 0x1C84, 0x0038, 0, 0, 1, 0x0258)
            ),
        )
    )
    sst = _record(
        0x00FC,
        struct.pack("<II", len(strings), len(strings)) + b"".join(_sst_string(s) for s in strings),
    )
    boundsheet_len = 4 + 2 + 2 + len("Sheet1")  # lbPlyPos + hs + dt + short string
    globals_eof = _eof()
    sheet_offset = len(prefix) + 4 + boundsheet_len + len(sst) + len(globals_eof)
    boundsheet = _record(0x0085, struct.pack("<IBB", sheet_offset, 0, 0) + _short_string("Sheet1"))
    return prefix + boundsheet + sst + globals_eof + bytes(sheet)


def _directory_entry(*, name: str, entry_type: int, child: int, start: int, size: int) -> bytes:
    encoded = (name + "\x00").encode("utf-16-le").ljust(64, b"\x00")[:64]
    name_len = min(len(name) * 2 + 2, 64)
    return b"".join(
        (
            encoded,
            struct.pack("<H", name_len),
            bytes([entry_type, 1]),
            struct.pack("<III", NOSTREAM, NOSTREAM, child),
            b"\x00" * 16,
            struct.pack("<I", 0),
            struct.pack("<QQ", 0, 0),
            struct.pack("<I", start),
            struct.pack("<Q", size),
        )
    )


def _ole_container(stream: bytes) -> bytes:
    # El corte de mini-stream es 4096: si el tamaño declarado es menor, xlrd lee SSCS.
    padded = stream.ljust(
        max(MINI_STREAM_CUTOFF, ((len(stream) + SECTOR_SIZE - 1) // SECTOR_SIZE) * SECTOR_SIZE),
        b"\x00",
    )
    n_stream_sectors = len(padded) // SECTOR_SIZE
    fat = [FREESECT] * (SECTOR_SIZE // 4)
    fat[0] = FATSECT
    fat[1] = ENDOFCHAIN
    for index in range(n_stream_sectors):
        sector = 2 + index
        fat[sector] = ENDOFCHAIN if index == n_stream_sectors - 1 else sector + 1
    fat_bytes = struct.pack(f"<{len(fat)}I", *fat)

    directory = (
        _directory_entry(name="Root Entry", entry_type=5, child=1, start=ENDOFCHAIN, size=0)
        + _directory_entry(name="Workbook", entry_type=2, child=NOSTREAM, start=2, size=len(padded))
        + b"\x00" * 256
    )

    header = bytearray(SECTOR_SIZE)
    header[0:8] = OLE_MAGIC
    struct.pack_into("<HHHHH", header, 24, 0x003E, 0x0003, 0xFFFE, 9, 6)
    struct.pack_into(
        "<IIIIIIII", header, 44, 1, 1, 0, MINI_STREAM_CUTOFF, ENDOFCHAIN, 0, ENDOFCHAIN, 0
    )
    struct.pack_into("<I", header, 76, 0)
    for slot in range(1, 109):
        struct.pack_into("<I", header, 76 + 4 * slot, FREESECT)

    return bytes(header) + fat_bytes + directory + padded


def build_xls(rows: list[list[str]]) -> bytes:
    """Devuelve bytes de un .xls BIFF8 con la primera fila como cabecera."""
    return _ole_container(_workbook_stream(rows))
