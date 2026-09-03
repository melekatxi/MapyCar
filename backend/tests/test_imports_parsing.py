"""Parseo de ficheros de importación: firma real, CSV `;`/`,`, XLSX y XLS. Ref: RF-01, RF-04, RNF-09."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable

import pytest
from openpyxl import Workbook

from app.core.errors import DomainError
from app.modules.imports import parsing
from tests.xls_fixture import build_xls

CSV_SEMICOLON = (
    b"id_paciente;nombre_referencia;direccion;codigo_postal;municipio;provincia\n"
    b"PAC-001;Paciente 001;Calle Mayor 1;48001;Bilbao;Bizkaia\n"
)

CSV_COMMA = (
    b"id_paciente,nombre_referencia,direccion,codigo_postal,municipio,provincia\n"
    b"PAC-002,Paciente 002,Calle Mayor 2,48001,Bilbao,Bizkaia\n"
)


HEADERS = [
    "id_paciente",
    "nombre_referencia",
    "direccion",
    "codigo_postal",
    "municipio",
    "provincia",
]


def _xlsx_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(HEADERS)
    sheet.append(["PAC-003", "Paciente 003", "Calle Mayor 3", "48001", "Bilbao", "Bizkaia"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _xls_bytes() -> bytes:
    return build_xls(
        [
            HEADERS,
            ["PAC-004", "Paciente 004", "Calle Mayor 4", "48001", "Bilbao", "Bizkaia"],
        ]
    )


def _xlsx_with_macros() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/vbaProject.bin", b"not-a-real-macro")
        archive.writestr("[Content_Types].xml", b"<Types/>")
    return buffer.getvalue()


def test_parses_csv_with_semicolon_delimiter() -> None:
    rows = parsing.parse_rows(filename="dataset.csv", content=CSV_SEMICOLON)

    assert rows == [
        {
            "id_paciente": "PAC-001",
            "nombre_referencia": "Paciente 001",
            "direccion": "Calle Mayor 1",
            "codigo_postal": "48001",
            "municipio": "Bilbao",
            "provincia": "Bizkaia",
        }
    ]


def test_parses_csv_with_comma_delimiter() -> None:
    rows = parsing.parse_rows(filename="dataset.csv", content=CSV_COMMA)

    assert rows[0]["id_paciente"] == "PAC-002"
    assert rows[0]["direccion"] == "Calle Mayor 2"


def test_parses_xlsx() -> None:
    rows = parsing.parse_rows(filename="dataset.xlsx", content=_xlsx_bytes())

    assert rows[0]["id_paciente"] == "PAC-003"
    assert rows[0]["municipio"] == "Bilbao"


def test_parses_xls() -> None:
    rows = parsing.parse_rows(filename="dataset.xls", content=_xls_bytes())

    assert rows[0]["id_paciente"] == "PAC-004"
    assert rows[0]["direccion"] == "Calle Mayor 4"
    assert rows[0]["codigo_postal"] == "48001"


@pytest.mark.parametrize(
    ("filename", "content_factory", "expected_id"),
    [
        ("dataset.csv", lambda: CSV_SEMICOLON, "PAC-001"),
        ("dataset.csv", lambda: CSV_COMMA, "PAC-002"),
        ("dataset.xlsx", _xlsx_bytes, "PAC-003"),
        ("dataset.xls", _xls_bytes, "PAC-004"),
    ],
)
def test_four_import_formats_map_canonical_columns(
    filename: str, content_factory: Callable[[], bytes], expected_id: str
) -> None:
    rows = parsing.parse_rows(filename=filename, content=content_factory())

    assert rows[0]["id_paciente"] == expected_id
    assert rows[0]["municipio"] == "Bilbao"
    assert rows[0]["provincia"] == "Bizkaia"


def test_detects_xls_format() -> None:
    assert parsing.detect_format(filename="dataset.xls", content=_xls_bytes()) == "xls"


def test_rejects_xlsx_with_fake_signature() -> None:
    with pytest.raises(DomainError) as exc_info:
        parsing.parse_rows(filename="dataset.xlsx", content=b"esto no es un zip xlsx real")

    assert exc_info.value.status_code == 415
    assert exc_info.value.code == "INVALID_FILE_SIGNATURE"


def test_rejects_unsupported_extension() -> None:
    with pytest.raises(DomainError) as exc_info:
        parsing.parse_rows(filename="dataset.pdf", content=b"%PDF-1.4")

    assert exc_info.value.status_code == 415
    assert exc_info.value.code == "UNSUPPORTED_FORMAT"


def test_rejects_xls_with_fake_signature() -> None:
    with pytest.raises(DomainError) as exc_info:
        parsing.parse_rows(filename="dataset.xls", content=b"esto no es un ole xls real")

    assert exc_info.value.status_code == 415
    assert exc_info.value.code == "INVALID_FILE_SIGNATURE"


def test_rejects_ole_file_that_is_not_a_workbook() -> None:
    # Firma OLE2 válida (p. ej. .doc) pero sin stream Workbook.
    ole_but_not_excel = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64
    with pytest.raises(DomainError) as exc_info:
        parsing.parse_rows(filename="dataset.xls", content=ole_but_not_excel)

    assert exc_info.value.status_code == 415
    assert exc_info.value.code == "INVALID_FILE_SIGNATURE"


def test_rejects_xlsx_with_macros() -> None:
    with pytest.raises(DomainError) as exc_info:
        parsing.parse_rows(filename="dataset.xlsx", content=_xlsx_with_macros())

    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "MACROS_NOT_ALLOWED"


def test_rejects_xls_with_macros() -> None:
    content = parsing.XLS_MAGIC + b"\x00" * 16 + "_VBA_PROJECT".encode("utf-16-le")
    with pytest.raises(DomainError) as exc_info:
        parsing.parse_rows(filename="dataset.xls", content=content)

    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "MACROS_NOT_ALLOWED"


def test_rejects_too_many_rows() -> None:
    header = "id_paciente;nombre_referencia;direccion;codigo_postal;municipio;provincia\n"
    body = "\n".join(f"PAC-{i};P {i};Calle {i};48001;Bilbao;Bizkaia" for i in range(501))
    content = (header + body).encode("utf-8")

    with pytest.raises(DomainError) as exc_info:
        parsing.parse_rows(filename="dataset.csv", content=content)

    assert exc_info.value.code == "IMPORT_TOO_MANY_ROWS"
