from fastapi import FastAPI

from app.routers import health


def create_app() -> FastAPI:
    """Factory to build FastAPI instances."""

    app = FastAPI(title="segmentation-api", version="0.1.0")

    app.include_router(health.router)

    return app


app = create_app()
