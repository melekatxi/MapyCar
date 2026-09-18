from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.middleware import RequestIdMiddleware
from app.modules.geocoding.router import router as geocoding_router
from app.modules.history.router import router as history_router
from app.modules.identity.router import router as identity_router
from app.modules.imports.router import patients_router
from app.modules.imports.router import router as imports_router
from app.modules.jobs.router import router as jobs_router
from app.modules.planning.router import router as planning_router
from app.modules.routing.router import router as routing_router
from app.modules.sharing.router import router as sharing_router
from app.modules.zoning.router import router as zoning_router

app = FastAPI(title="Sofia API", version="0.1.0", root_path="")

app.add_middleware(RequestIdMiddleware)
if get_settings().environment == "development":
    # Solo en desarrollo: permite al SPA de Vite (puerto distinto) llamar al API local.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
register_error_handlers(app)

app.include_router(identity_router, prefix="/api/v1")
app.include_router(imports_router, prefix="/api/v1")
app.include_router(patients_router, prefix="/api/v1")
app.include_router(geocoding_router, prefix="/api/v1")
app.include_router(zoning_router, prefix="/api/v1")
app.include_router(planning_router, prefix="/api/v1")
app.include_router(routing_router, prefix="/api/v1")
app.include_router(sharing_router, prefix="/api/v1")
app.include_router(history_router, prefix="/api/v1")
app.include_router(jobs_router, prefix="/api/v1")


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
