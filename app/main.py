from fastapi import FastAPI

from app.routers import health, teams


def create_app() -> FastAPI:
    app = FastAPI(title="segmentation-api", version="0.1.0")

    app.include_router(health.router)
    app.include_router(teams.router)

    return app


app = create_app()
