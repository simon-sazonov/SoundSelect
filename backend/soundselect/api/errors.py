"""Errors the API sends: always ``{"detail": {"code": ..., "message": ...}}``.

The message is written for the player and can be shown as it is; the code is for the front
end to tell cases apart. Requests the API can't parse at all (a missing field, a wrong type)
get FastAPI's usual 422 answer.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..core.song import Model
from ..render.pdf import PdfUnavailable
from ..service import BadRequest, NotFound


class ErrorDetail(Model):
    code: str
    message: str


class ErrorResponse(Model):
    detail: ErrorDetail


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"detail": {"code": code, "message": message}}, status_code=status)


def add_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(BadRequest)
    async def _bad_request(request: Request, exc: BadRequest) -> JSONResponse:
        return error_response(400, "bad_request", str(exc))

    @app.exception_handler(NotFound)
    async def _not_found(request: Request, exc: NotFound) -> JSONResponse:
        return error_response(404, "not_found", str(exc))

    @app.exception_handler(PdfUnavailable)
    async def _no_pdf(request: Request, exc: PdfUnavailable) -> JSONResponse:
        return error_response(503, "pdf_unavailable", str(exc))


ERRORS = {
    400: {"model": ErrorResponse, "description": "The request can't be used; see the message."},
    404: {"model": ErrorResponse, "description": "Not found."},
}
