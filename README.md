# greptimedb

A lightweight Python SDK for the [GreptimeDB](https://greptime.com/) HTTP SQL API (`/v1/sql`).

## Features

- Execute SQL queries, DDL (`CREATE TABLE`), and DML (`INSERT`) via GreptimeDB's HTTP SQL API
- Structured response models (`SQLResponse`, `QueryResult`, `ColumnSchema`) with `.to_dicts()`, `.fetchone()`, `.fetchall()`
- Convenient `insert()` helper with automatic SQL literal escaping
- HTTP Basic Authentication support
- Built-in `show_tables()`, `show_databases()`, and `health()` helpers
- Full type annotations (`py.typed`)

## Installation

```bash
pip install greptimedb
```

Or with `uv`:

```bash
uv add greptimedb
```

## Quick Start

```python
from datetime import datetime, timezone
from greptimedb import Client

with Client(
    host="http://localhost:4000",
    database="public",
    username="greptime_user",  # optional
    password="greptime_pwd",   # optional
) as client:
    # Check server health
    assert client.health()

    # Create a table
    client.execute(
        """
        CREATE TABLE IF NOT EXISTS system_metrics (
            host STRING,
            cpu DOUBLE,
            ts TIMESTAMP TIME INDEX,
            PRIMARY KEY (host)
        )
        """
    )

    # Insert rows
    affected = client.insert(
        "system_metrics",
        [
            {"host": "host1", "cpu": 0.42, "ts": datetime.now(timezone.utc)},
            {"host": "host2", "cpu": 0.78, "ts": datetime.now(timezone.utc)},
        ],
    )
    print(f"Inserted {affected} rows")

    # Query rows
    rows = client.query_dicts("SELECT host, cpu, ts FROM system_metrics LIMIT 10")
    for row in rows:
        print(row)
```

## Development & Publishing (with `uv`)

```bash
# Install dependencies and run tests
uv sync
uv run pytest

# Lint & format check
uv run ruff check .

# Build sdist and wheel into dist/
uv build

# Publish to TestPyPI (recommended first)
uv publish --publish-url https://test.pypi.org/legacy/ --token <TESTPYPI_TOKEN>

# Publish to PyPI
uv publish --token <PYPI_TOKEN>
```

## License

MIT
