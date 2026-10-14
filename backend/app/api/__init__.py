from fastapi import APIRouter

from app.api import (
    analyses,
    events,
    export,
    query,
    rules,
    settings,
    system,
    views_events,
    views_findings,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(system.router)
api_router.include_router(settings.router)
api_router.include_router(analyses.router)
api_router.include_router(views_events.router)
api_router.include_router(views_findings.router)
api_router.include_router(events.router)
api_router.include_router(query.router)
api_router.include_router(rules.router)
api_router.include_router(rules.analysis_router)
api_router.include_router(export.router)
