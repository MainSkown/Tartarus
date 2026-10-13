from fastapi import APIRouter

from app.api import analyses, settings, system

api_router = APIRouter(prefix="/api")
api_router.include_router(system.router)
api_router.include_router(settings.router)
api_router.include_router(analyses.router)
