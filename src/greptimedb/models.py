"""Data models for GreptimeDB HTTP SQL API responses."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ColumnSchema:
    """Metadata describing a single column in a query result."""

    name: str
    data_type: str


@dataclass
class QueryResult:
    """Result of a single SQL statement execution."""

    columns: list[ColumnSchema] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    affected_rows: int | None = None
    execution_time_ms: int | None = None

    @property
    def column_names(self) -> list[str]:
        """Return the ordered list of column names."""
        return [col.name for col in self.columns]

    def iter_dicts(self) -> Iterator[dict[str, Any]]:
        """Yield each row as a dictionary mapping column name to value."""
        names = self.column_names
        for row in self.rows:
            yield dict(zip(names, row))

    def to_dicts(self) -> list[dict[str, Any]]:
        """Return all rows as a list of dictionaries."""
        return list(self.iter_dicts())

    def fetchone(self) -> dict[str, Any] | None:
        """Return the first row as a dictionary, or None if there are no rows."""
        if not self.rows:
            return None
        return dict(zip(self.column_names, self.rows[0]))

    def fetchall(self) -> list[dict[str, Any]]:
        """Return all rows as a list of dictionaries."""
        return self.to_dicts()

    def __len__(self) -> int:
        return len(self.rows)

    def __iter__(self) -> Iterator[list[Any]]:
        return iter(self.rows)


@dataclass
class SQLResponse:
    """Top-level response from GreptimeDB's ``/v1/sql`` endpoint."""

    results: list[QueryResult] = field(default_factory=list)
    execution_time_ms: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def first(self) -> QueryResult | None:
        """Return the first statement result, or None if output is empty."""
        return self.results[0] if self.results else None

    @property
    def columns(self) -> list[ColumnSchema]:
        """Return columns from the first result."""
        return self.first.columns if self.first is not None else []

    @property
    def rows(self) -> list[list[Any]]:
        """Return rows from the first result."""
        return self.first.rows if self.first is not None else []

    @property
    def affected_rows(self) -> int | None:
        """Return affected rows from the first result."""
        return self.first.affected_rows if self.first is not None else None

    def to_dicts(self) -> list[dict[str, Any]]:
        """Return rows from the first result as a list of dictionaries."""
        return self.first.to_dicts() if self.first is not None else []
