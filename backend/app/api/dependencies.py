from typing import cast

from fastapi import Request

from app.analyses.ports import RunnerControl
from app.cape.client import CapeClient
from app.samples.store import SampleStore


def get_cape(request: Request) -> CapeClient:
    return cast(CapeClient, request.app.state.cape)


def get_sample_store(request: Request) -> SampleStore:
    return cast(SampleStore, request.app.state.sample_store)


def get_runner(request: Request) -> RunnerControl:
    return cast(RunnerControl, request.app.state.runner)
