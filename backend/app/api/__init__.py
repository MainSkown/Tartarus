from fastapi import APIRouter

from app.api import (
    analyses,
    annotations,
    events,
    export,
    guests,
    iocs,
    jobs,
    query,
    rules,
    search,
    settings,
    system,
    views_events,
    views_findings,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(system.router)
api_router.include_router(settings.router)
api_router.include_router(guests.router)
api_router.include_router(analyses.router)
api_router.include_router(views_events.router)
api_router.include_router(views_findings.router)
api_router.include_router(events.router)
api_router.include_router(query.router)
api_router.include_router(rules.router)
api_router.include_router(rules.analysis_router)
api_router.include_router(export.router)
api_router.include_router(annotations.router)
api_router.include_router(jobs.router)
api_router.include_router(search.router)
api_router.include_router(iocs.router)
