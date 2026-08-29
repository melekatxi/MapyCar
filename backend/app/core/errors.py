"""Modelo de error estándar y manejadores de excepción. Ref: diseño sección 8.1."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

ERROR_BASE_TYPE = "https://sofia.example/errors"

_TITLES: dict[int, str] = {
    400: "Solicitud incorrecta",
    401: "No autenticado",
    403: "No autorizado",
    404: "Recurso no encontrado",
    409: "Conflicto",
    413: "Fichero demasiado grande",
    415: "Formato no soportado",
    422: "Datos no válidos",
    429: "Demasiadas solicitudes",
    500: "Error interno",
    503: "Dependencia no disponible",
    504: "Tiempo de espera agotado",
}


def build_error_body(
    *,
    status: int,
    request: Request,
    code: str,
    detail: str,
    errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    request_id = getattr(request.state, "request_id", None)
    return {
        "type": f"{ERROR_BASE_TYPE}/{code.lower().replace('_', '-')}",
        "title": _TITLES.get(status, "Error"),
        "status": status,
        "code": code,
        "detail": detail,
        "instance": str(request.url.path),
        "request_id": request_id,
        "errors": errors or [],
    }


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = getattr(exc, "code", None) or f"HTTP_{exc.status_code}"
        body = build_error_body(
            status=exc.status_code, request=request, code=code, detail=str(exc.detail)
        )
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [
            {"field": ".".join(str(p) for p in e["loc"]), "code": e["type"], "message": e["msg"]}
            for e in exc.errors()
        ]
        body = build_error_body(
            status=422,
            request=request,
            code="VALIDATION_ERROR",
            detail="Hay campos que requieren corrección",
            errors=errors,
        )
        return JSONResponse(status_code=422, content=body)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        body = build_error_body(
            status=500, request=request, code="INTERNAL_ERROR", detail="Error interno inesperado"
        )
        return JSONResponse(status_code=500, content=body)


class DomainError(HTTPException):
    """Excepción de dominio con código estable para el body de error."""

    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.code = code
