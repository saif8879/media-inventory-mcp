from __future__ import annotations

from typing import Any, Generic, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginationMeta(BaseModel):
    offset: int = 0
    limit: int = 20
    total: int = 0


class ErrorPayload(BaseModel):
    code: str
    message: str
    details: Any | None = None


class StandardResponse(BaseModel, Generic[T]):
    success: bool
    data: T | None = None
    pagination: PaginationMeta | None = None
    error: ErrorPayload | None = None

    @classmethod
    def success_response(
        cls,
        data: T,
        pagination: PaginationMeta | None = None,
    ) -> StandardResponse[T]:
        return cls(success=True, data=data, pagination=pagination, error=None)

    @classmethod
    def error_response(
        cls,
        code: str,
        message: str,
        details: Any | None = None,
    ) -> StandardResponse[None]:
        return cls(
            success=False,
            data=None,
            pagination=None,
            error=ErrorPayload(code=code, message=message, details=details),
        )
