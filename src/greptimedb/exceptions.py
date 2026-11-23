"""Exception classes for the GreptimeDB Python SDK."""

from __future__ import annotations


class GreptimeDBError(Exception):
    """Base exception for all GreptimeDB SDK errors."""


class GreptimeDBConnectionError(GreptimeDBError):
    """Raised when a network or connection error occurs while talking to GreptimeDB."""


class GreptimeDBHTTPError(GreptimeDBError):
    """Raised when GreptimeDB returns an unexpected non-2xx HTTP response."""

    def __init__(self, status_code: int, message: str, body: str | None = None) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"HTTP {status_code}: {message}")


class GreptimeDBQueryError(GreptimeDBError):
    """Raised when GreptimeDB returns a structured SQL/API error."""

    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        execution_time_ms: int | None = None,
        status_code: int | None = None,
    ) -> None:
        self.message = message
        self.code = code
        self.execution_time_ms = execution_time_ms
        self.status_code = status_code

        parts = []
        if code is not None:
            parts.append(f"[{code}]")
        parts.append(message)
        super().__init__(" ".join(parts))
