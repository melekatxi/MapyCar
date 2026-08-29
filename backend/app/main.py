from fastapi import FastAPI

from app.core.errors import register_error_handlers
from app.core.middleware import RequestIdMiddleware
from app.modules.identity.router import router as identity_router

app = FastAPI(title="Sofia API", version="0.1.0", root_path="")

app.add_middleware(RequestIdMiddleware)
register_error_handlers(app)

app.include_router(identity_router, prefix="/api/v1")


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
