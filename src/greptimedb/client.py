"""HTTP SQL client for GreptimeDB."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

import httpx

from .exceptions import (
    GreptimeDBConnectionError,
    GreptimeDBError,
    GreptimeDBHTTPError,
    GreptimeDBQueryError,
)
from .models import ColumnSchema, QueryResult, SQLResponse


def _normalize_base_url(host: str) -> str:
    url = host.strip()
    if not url:
        raise ValueError("host must not be empty")
    if "://" not in url:
        url = f"http://{url}"
    return url.rstrip("/")


def _quote_identifier(identifier: str) -> str:
    if not identifier or not identifier.strip():
        raise ValueError("SQL identifier must not be empty")
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


def _format_sql_value(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError(f"Unsupported float value for SQL literal: {value!r}")
        return repr(value)
    if isinstance(value, datetime):
        return f"'{value.isoformat()}'"
    if isinstance(value, date):
        return f"'{value.isoformat()}'"
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    raise TypeError(f"Unsupported value type for SQL literal: {type(value).__name__}")


def _parse_sql_response(payload: dict[str, Any]) -> SQLResponse:
    execution_time_ms = payload.get("execution_time_ms")
    output = payload.get("output") or []
    results: list[QueryResult] = []

    for item in output:
        if not isinstance(item, dict):
            continue
        if "records" in item and isinstance(item["records"], dict):
            records = item["records"]
            schema = records.get("schema") or {}
            raw_cols = schema.get("column_schemas") or []
            columns = [
                ColumnSchema(
                    name=str(col.get("name", "")),
                    data_type=str(col.get("data_type", "")),
                )
                for col in raw_cols
                if isinstance(col, dict)
            ]
            rows = records.get("rows") or []
            results.append(
                QueryResult(
                    columns=columns,
                    rows=rows,
                    execution_time_ms=execution_time_ms,
                )
            )
        elif "affectedrows" in item:
            results.append(
                QueryResult(
                    affected_rows=int(item["affectedrows"]),
                    execution_time_ms=execution_time_ms,
                )
            )

    return SQLResponse(
        results=results,
        execution_time_ms=execution_time_ms,
        raw=payload,
    )


class Client:
    """Synchronous HTTP SQL client for GreptimeDB.

    Example:
        >>> with Client(host="http://localhost:4000", database="public") as client:
        ...     result = client.query("SELECT 1 AS val")
        ...     print(result.to_dicts())
    """

    def __init__(
        self,
        host: str = "http://localhost:4000",
        database: str = "public",
        *,
        username: str | None = None,
        password: str | None = None,
        timeout: float = 30.0,
        headers: Mapping[str, str] | None = None,
        verify: bool = True,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = _normalize_base_url(host)
        self.database = database

        auth: httpx.Auth | None = None
        if username is not None or password is not None:
            auth = httpx.BasicAuth(username or "", password or "")

        if http_client is not None:
            self._client = http_client
            self._owns_client = False
        else:
            self._client = httpx.Client(
                base_url=self.base_url,
                auth=auth,
                timeout=timeout,
                headers=dict(headers) if headers else None,
                verify=verify,
            )
            self._owns_client = True

    def close(self) -> None:
        """Close the underlying HTTP client if owned by this instance."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Client:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def execute(
        self,
        sql: str,
        *,
        database: str | None = None,
        format: str | None = None,
    ) -> SQLResponse:
        """Execute one or more SQL statements via ``POST /v1/sql``.

        Args:
            sql: The SQL statement(s) to execute.
            database: Target database name. Defaults to ``self.database``.
            format: Optional GreptimeDB output format parameter (defaults to ``greptimedb_v1``).

        Returns:
            Parsed :class:`SQLResponse`.

        Raises:
            GreptimeDBConnectionError: On network or timeout errors.
            GreptimeDBQueryError: When GreptimeDB returns a structured API error.
            GreptimeDBHTTPError: On unexpected non-2xx HTTP responses.
        """
        if not sql or not sql.strip():
            raise ValueError("sql must not be empty")

        params: dict[str, str] = {"db": database or self.database}
        if format is not None:
            params["format"] = format

        url = f"{self.base_url}/v1/sql"
        try:
            response = self._client.post(
                url,
                params=params,
                data={"sql": sql},
            )
        except httpx.HTTPError as exc:
            raise GreptimeDBConnectionError(f"Failed to connect to GreptimeDB: {exc}") from exc

        payload: dict[str, Any] | None = None
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                payload = parsed
        except ValueError:
            payload = None

        if payload is not None and "error" in payload:
            raise GreptimeDBQueryError(
                message=str(payload["error"]),
                code=payload.get("code"),
                execution_time_ms=payload.get("execution_time_ms"),
                status_code=response.status_code,
            )

        if response.is_error:
            raise GreptimeDBHTTPError(
                status_code=response.status_code,
                message=response.reason_phrase or "Request failed",
                body=response.text,
            )

        if payload is None:
            raise GreptimeDBError(
                f"Expected JSON object from GreptimeDB, got: {response.text[:200]!r}"
            )

        return _parse_sql_response(payload)

    def query(self, sql: str, *, database: str | None = None) -> QueryResult:
        """Execute a SQL statement and return the first :class:`QueryResult`."""
        resp = self.execute(sql, database=database)
        if resp.first is not None:
            return resp.first
        return QueryResult(execution_time_ms=resp.execution_time_ms)

    def query_dicts(self, sql: str, *, database: str | None = None) -> list[dict[str, Any]]:
        """Execute a SQL query and return rows as a list of dictionaries."""
        return self.query(sql, database=database).to_dicts()

    def insert(
        self,
        table: str,
        rows: Sequence[Mapping[str, Any]],
        *,
        database: str | None = None,
    ) -> int:
        """Insert rows into a table using a SQL ``INSERT INTO`` statement.

        Args:
            table: Target table name.
            rows: Non-empty sequence of row mappings (column name -> value).
            database: Target database name. Defaults to ``self.database``.

        Returns:
            Number of affected rows reported by GreptimeDB.
        """
        if not rows:
            return 0

        columns: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    columns.append(key)

        if not columns:
            raise ValueError("rows must contain at least one column")

        quoted_table = _quote_identifier(table)
        quoted_cols = ", ".join(_quote_identifier(col) for col in columns)

        value_tuples: list[str] = []
        for row in rows:
            values = ", ".join(_format_sql_value(row.get(col)) for col in columns)
            value_tuples.append(f"({values})")

        sql = f"INSERT INTO {quoted_table} ({quoted_cols}) VALUES {', '.join(value_tuples)}"
        resp = self.execute(sql, database=database)
        return resp.affected_rows or 0

    def show_tables(self, *, database: str | None = None) -> list[str]:
        """Return the list of table names in the target database."""
        result = self.query("SHOW TABLES", database=database)
        return [str(row[0]) for row in result.rows if row]

    def show_databases(self) -> list[str]:
        """Return the list of database names."""
        result = self.query("SHOW DATABASES")
        return [str(row[0]) for row in result.rows if row]

    def health(self) -> bool:
        """Check whether the GreptimeDB HTTP server is healthy (``GET /health``)."""
        url = f"{self.base_url}/health"
        try:
            response = self._client.get(url)
        except httpx.HTTPError as exc:
            raise GreptimeDBConnectionError(f"Failed to check GreptimeDB health: {exc}") from exc
        return response.status_code == 200
