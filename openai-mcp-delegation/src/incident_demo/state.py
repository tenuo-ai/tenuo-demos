"""Small stateful operations backend used by the MCP server."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class DeploymentState:
    service: str
    environment: str
    deployment: str
    previous_deployment: str
    p95_latency_ms: int
    error_rate: float
    rollbacks_executed: int


class OperationsState:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS services (
                    service TEXT PRIMARY KEY,
                    environment TEXT NOT NULL,
                    deployment TEXT NOT NULL,
                    previous_deployment TEXT NOT NULL,
                    p95_latency_ms INTEGER NOT NULL,
                    error_rate REAL NOT NULL,
                    rollbacks_executed INTEGER NOT NULL
                )
                """
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO services VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ("checkout", "production", "8c1e", "79af", 1840, 0.071, 0),
                    ("payments", "production", "4d2a", "31bc", 240, 0.003, 0),
                ],
            )

    def snapshot(self, service: str) -> DeploymentState:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM services WHERE service = ?", (service,)
            ).fetchone()
        if row is None:
            raise ValueError(f"unknown service: {service}")
        return DeploymentState(**dict(row))

    def as_dict(self, service: str) -> dict[str, object]:
        return asdict(self.snapshot(service))

    def rollback(self, service: str, deployment: str) -> DeploymentState:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE services
                SET deployment = previous_deployment,
                    previous_deployment = ?,
                    p95_latency_ms = 310,
                    error_rate = 0.004,
                    rollbacks_executed = rollbacks_executed + 1
                WHERE service = ? AND deployment = ?
                """,
                (deployment, service, deployment),
            )
            if cursor.rowcount == 0:
                row = connection.execute(
                    "SELECT deployment FROM services WHERE service = ?", (service,)
                ).fetchone()
                if row is None:
                    raise ValueError(f"unknown service: {service}")
                raise ValueError(
                    f"deployment {deployment} is not active for {service}; "
                    f"active={row['deployment']}"
                )
        return self.snapshot(service)
