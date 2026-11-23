"""Unit tests for the GreptimeDB HTTP SQL SDK."""

from __future__ import annotations

import base64
from datetime import date, datetime, timezone
from urllib.parse import parse_qs

import httpx
import pytest

from greptimedb import (
    Client,
    ColumnSchema,
    GreptimeDBConnectionError,
    GreptimeDBError,
    GreptimeDBHTTPError,
    GreptimeDBQueryError,
)


def _make_client(handler, **kwargs) -> Client:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, trust_env=False)
    return Client(http_client=http_client, **kwargs)


def test_url_normalization() -> None:
    c1 = Client(host="localhost:4000")
    assert c1.base_url == "http://localhost:4000"
    c1.close()

    c2 = Client(host="https://cloud.greptime.com/")
    assert c2.base_url == "https://cloud.greptime.com"
    c2.close()

    with pytest.raises(ValueError):
        Client(host="   ")


def test_select_query_and_dict_conversion() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["db"] = request.url.params.get("db")
        captured["body"] = parse_qs(request.content.decode())
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "records": {
                            "schema": {
                                "column_schemas": [
                                    {"name": "host", "data_type": "String"},
                                    {"name": "ts", "data_type": "TimestampMillisecond"},
                                    {"name": "cpu", "data_type": "Float64"},
                                ]
                            },
                            "rows": [
                                ["127.0.0.1", 1667446797450, 0.1],
                                ["127.0.0.2", 1667446798450, 0.25],
                            ],
                        }
                    }
                ],
                "execution_time_ms": 15,
            },
        )

    client = _make_client(handler, host="http://localhost:4000", database="metrics")
    result = client.query("SELECT host, ts, cpu FROM system_metrics")

    assert captured["method"] == "POST"
    assert captured["path"] == "/v1/sql"
    assert captured["db"] == "metrics"
    assert captured["body"] == {"sql": ["SELECT host, ts, cpu FROM system_metrics"]}

    assert result.execution_time_ms == 15
    assert result.columns == [
        ColumnSchema(name="host", data_type="String"),
        ColumnSchema(name="ts", data_type="TimestampMillisecond"),
        ColumnSchema(name="cpu", data_type="Float64"),
    ]
    assert result.column_names == ["host", "ts", "cpu"]
    assert len(result) == 2
    assert list(result) == [
        ["127.0.0.1", 1667446797450, 0.1],
        ["127.0.0.2", 1667446798450, 0.25],
    ]
    assert result.fetchone() == {"host": "127.0.0.1", "ts": 1667446797450, "cpu": 0.1}
    assert result.fetchall() == [
        {"host": "127.0.0.1", "ts": 1667446797450, "cpu": 0.1},
        {"host": "127.0.0.2", "ts": 1667446798450, "cpu": 0.25},
    ]


def test_basic_auth_header() -> None:
    seen_auth: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("Authorization", ""))
        return httpx.Response(200, json={"output": [{"affectedrows": 0}], "execution_time_ms": 1})

    transport = httpx.MockTransport(handler)
    with Client(
        host="http://localhost:4000",
        username="greptime_user",
        password="greptime_pwd",
    ) as client:
        client._client._transport = transport
        client._client._mounts = {}
        resp = client.execute("CREATE TABLE t (ts TIMESTAMP TIME INDEX)")
        assert resp.affected_rows == 0

    expected = base64.b64encode(b"greptime_user:greptime_pwd").decode()
    assert seen_auth == [f"Basic {expected}"]


def test_insert_helper_escapes_values() -> None:
    captured_sql: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        captured_sql.append(form["sql"][0])
        return httpx.Response(200, json={"output": [{"affectedrows": 2}], "execution_time_ms": 4})

    client = _make_client(handler)
    ts = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    affected = client.insert(
        "events",
        [
            {"host": "srv'1", "cpu": 0.5, "ok": True, "ts": ts, "day": date(2026, 1, 2)},
            {"host": "srv2", "cpu": None, "ok": False, "ts": ts, "note": "hi"},
        ],
    )

    assert affected == 2
    assert len(captured_sql) == 1
    assert captured_sql[0] == (
        'INSERT INTO "events" ("host", "cpu", "ok", "ts", "day", "note") VALUES '
        "('srv''1', 0.5, TRUE, '2026-01-02T03:04:05+00:00', '2026-01-02', NULL), "
        "('srv2', NULL, FALSE, '2026-01-02T03:04:05+00:00', NULL, 'hi')"
    )


def test_insert_empty_rows_noop() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Should not make an HTTP request for empty rows")

    client = _make_client(handler)
    assert client.insert("events", []) == 0


def test_show_tables_and_databases() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        sql = parse_qs(request.content.decode())["sql"][0]
        if sql == "SHOW TABLES":
            return httpx.Response(
                200,
                json={
                    "output": [
                        {
                            "records": {
                                "schema": {
                                    "column_schemas": [{"name": "Tables", "data_type": "String"}]
                                },
                                "rows": [["metrics"], ["logs"]],
                            }
                        }
                    ],
                    "execution_time_ms": 2,
                },
            )
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "records": {
                            "schema": {
                                "column_schemas": [{"name": "Schemas", "data_type": "String"}]
                            },
                            "rows": [["public"], ["information_schema"]],
                        }
                    }
                ],
                "execution_time_ms": 2,
            },
        )

    client = _make_client(handler)
    assert client.show_tables() == ["metrics", "logs"]
    assert client.show_databases() == ["public", "information_schema"]


def test_health_check() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/health"
        return httpx.Response(200, json={})

    client = _make_client(handler)
    assert client.health() is True


def test_structured_query_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "code": 2000,
                "error": "Invalid SQL syntax near 'SELEC'",
                "execution_time_ms": 1,
            },
        )

    client = _make_client(handler)
    with pytest.raises(GreptimeDBQueryError) as exc_info:
        client.execute("SELEC 1")

    err = exc_info.value
    assert err.code == 2000
    assert err.status_code == 400
    assert err.execution_time_ms == 1
    assert "Invalid SQL syntax" in str(err)


def test_http_error_without_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="Bad Gateway")

    client = _make_client(handler)
    with pytest.raises(GreptimeDBHTTPError) as exc_info:
        client.execute("SELECT 1")

    assert exc_info.value.status_code == 502
    assert exc_info.value.body == "Bad Gateway"


def test_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    client = _make_client(handler)
    with pytest.raises(GreptimeDBConnectionError):
        client.execute("SELECT 1")


def test_invalid_non_json_200_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="plain text")

    client = _make_client(handler)
    with pytest.raises(GreptimeDBError):
        client.execute("SELECT 1")
