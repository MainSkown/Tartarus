from fastapi import APIRouter

from app.api import system

api_router = APIRouter(prefix="/api")
api_router.include_router(system.router)
