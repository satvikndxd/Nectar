"""FastAPI application factory."""

from fastapi import FastAPI

from niglas_api.routes import events, health


def create_app() -> FastAPI:
    app = FastAPI(
        title="Niglas API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.include_router(health.router)
    app.include_router(events.router)
    return app


app = create_app()
