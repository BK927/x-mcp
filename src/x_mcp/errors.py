"""Sanitized errors; upstream payloads and credentials never become messages."""

from typing import Any


class XError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.retry_after = retry_after

    def payload(self) -> dict[str, Any]:
        error: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.retry_after is not None:
            error["retry_after_seconds"] = self.retry_after
        return {"error": error}


def invalid(message: str) -> XError:
    return XError("INVALID_ARGUMENT", message)
