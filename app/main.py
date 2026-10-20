import os
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from dotenv import load_dotenv


load_dotenv()

if not os.environ.get("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = os.environ.get("DEEPSEEK_API_KEY", "")

from app.routes.research_tasks import router as research_tasks_router
from app.services.task_service import ServiceError


app = FastAPI(
    title="DS Reporter API",
    version="1.0.0",
    description="REST API for asynchronous research report generation.",
)

app.include_router(research_tasks_router)


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    retryable: bool,
    details: list[dict] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or [],
                "request_id": str(uuid.uuid4()),
                "retryable": retryable,
            }
        },
    )


@app.exception_handler(ServiceError)
async def service_error_handler(_: Request, exc: ServiceError) -> JSONResponse:
    return _error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        retryable=exc.retryable,
        details=exc.details,
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    _: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    details = [
        {
            "field": ".".join(str(part) for part in error.get("loc", [])[1:]),
            "reason": error.get("msg", "invalid value"),
        }
        for error in exc.errors()
    ]
    return _error_response(
        status_code=422,
        code="VALIDATION_ERROR",
        message="Request validation failed.",
        retryable=False,
        details=details,
    )
