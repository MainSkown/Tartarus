from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.errors import error_response
from app.guest.errors import (
    GuestControlBadResponse,
    GuestControlError,
    GuestControlRejected,
    GuestControlUnreachable,
)

UNREACHABLE_MESSAGE = "The guest control service is not reachable"
UNINTELLIGIBLE_MESSAGE = "The guest control service sent an answer the backend cannot read"
NOT_ACCEPTED_MESSAGE = "The guest control service did not accept the request"
# (status, error code) the API answers with for the service's refusals whose words are passed on;
# for any other refusal those words are the service's internals.
PASSED_ON: dict[int, tuple[int, str]] = {
    HTTPStatus.NOT_FOUND: (HTTPStatus.NOT_FOUND, "not_found"),
    HTTPStatus.CONFLICT: (HTTPStatus.CONFLICT, "conflict"),
    HTTPStatus.UNPROCESSABLE_ENTITY: (HTTPStatus.UNPROCESSABLE_ENTITY, "validation_error"),
    HTTPStatus.BAD_REQUEST: (HTTPStatus.UNPROCESSABLE_ENTITY, "validation_error"),
}


def install_guest_control_error_handler(app: FastAPI) -> None:
    @app.exception_handler(GuestControlError)
    async def handle_guest_control_error(_: Request, exc: GuestControlError) -> JSONResponse:
        return guest_control_error_response(exc)


def guest_control_error_response(error: GuestControlError) -> JSONResponse:
    if isinstance(error, GuestControlRejected):
        return _rejection_response(error)
    return error_response(HTTPStatus.BAD_GATEWAY, "bad_gateway", _bad_gateway_message(error))


def _bad_gateway_message(error: GuestControlError) -> str:
    if isinstance(error, GuestControlUnreachable):
        return UNREACHABLE_MESSAGE
    if isinstance(error, GuestControlBadResponse):
        return UNINTELLIGIBLE_MESSAGE
    return NOT_ACCEPTED_MESSAGE


def _rejection_response(error: GuestControlRejected) -> JSONResponse:
    passed_on = PASSED_ON.get(error.status)
    if passed_on is None:
        return error_response(HTTPStatus.BAD_GATEWAY, "bad_gateway", NOT_ACCEPTED_MESSAGE)
    status, code = passed_on
    details = {"fields": _fields_of(error)} if status == HTTPStatus.UNPROCESSABLE_ENTITY else None
    return error_response(status, code, error.message, details)


def _fields_of(error: GuestControlRejected) -> list[dict[str, object]]:
    return [
        {"location": ["body", field], "message": problem, "type": "rejected"}
        for field, problem in error.fields.items()
    ]
