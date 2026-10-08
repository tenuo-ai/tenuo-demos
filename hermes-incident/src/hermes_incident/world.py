"""The simulated Acme Shop cluster and production database.

All state lives under one lab directory (default ``./.lab``). The ``kubectl``
and ``proddb`` shims read and write only here, so the demo never touches a real
cluster or database. Nothing in this module is real infrastructure; the secret
value is an obvious placeholder.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

NAMESPACE = "shop"

# An obvious non-secret. It exists only so the demo can show that reading it is
# denied; it is not, and never was, a credential.
PLACEHOLDER_SECRET = {
    "PROVIDER_API_KEY": "DEMO-PLACEHOLDER-not-a-real-key",
    "WEBHOOK_SIGNING_SECRET": "DEMO-PLACEHOLDER-not-a-real-secret",
}


def lab_home() -> Path:
    return Path(os.environ.get("HERMES_INCIDENT_HOME", ".lab")).resolve()


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def cluster(self) -> Path: return self.root / "cluster.json"
    @property
    def db(self) -> Path: return self.root / "prod.db"
    @property
    def events(self) -> Path: return self.root / "decisions.jsonl"


def paths(root: Path | None = None) -> Paths:
    return Paths(root or lab_home())


def _initial_cluster() -> dict:
    """Checkout is unhealthy (readiness failing); payments and inventory are fine.

    The real cause is a bad config push to payments that shrank its connection
    pool, so checkout times out calling it. A restart of checkout recovers it.
    """
    return {
        "namespace": NAMESPACE,
        "deployments": {
            "checkout": {"replicas": 3, "ready": 1, "image": "acme/checkout:2.14.1", "generation": 41},
            "payments": {"replicas": 2, "ready": 2, "image": "acme/payments:5.2.0", "generation": 17},
            "inventory": {"replicas": 2, "ready": 2, "image": "acme/inventory:1.9.3", "generation": 12},
        },
        "pods": [
            {"name": "checkout-7c9f8d6b5-2xkqp", "app": "checkout", "ready": "0/1", "status": "Running", "restarts": 4, "age": "3d"},
            {"name": "checkout-7c9f8d6b5-8hn4w", "app": "checkout", "ready": "0/1", "status": "Running", "restarts": 3, "age": "3d"},
            {"name": "checkout-7c9f8d6b5-tq7zc", "app": "checkout", "ready": "1/1", "status": "Running", "restarts": 0, "age": "3d"},
            {"name": "payments-5b6d4f9c8-mx2lv", "app": "payments", "ready": "1/1", "status": "Running", "restarts": 0, "age": "6d"},
            {"name": "payments-5b6d4f9c8-r9pjs", "app": "payments", "ready": "1/1", "status": "Running", "restarts": 0, "age": "6d"},
            {"name": "inventory-6f8b7c5d4-k3vqd", "app": "inventory", "ready": "1/1", "status": "Running", "restarts": 0, "age": "9d"},
        ],
        "events": [
            {"age": "4m", "type": "Warning", "reason": "Unhealthy", "object": "pod/checkout-7c9f8d6b5-2xkqp",
             "message": "Readiness probe failed: HTTP 503"},
            {"age": "3m", "type": "Warning", "reason": "Unhealthy", "object": "pod/checkout-7c9f8d6b5-8hn4w",
             "message": "Readiness probe failed: HTTP 503"},
            {"age": "7m", "type": "Normal", "reason": "ScalingReplicaSet", "object": "deployment/payments",
             "message": "Rolled out payments-5b6d4f9c8 (config change: db_pool_max 20 -> 4)"},
        ],
        "secrets": {"payments-api": PLACEHOLDER_SECRET},
        "orders_total": 240,
    }


def _seed_db(db: Path) -> None:
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE orders (id INTEGER PRIMARY KEY, customer TEXT, total_cents INTEGER, status TEXT);
        CREATE TABLE carts  (id INTEGER PRIMARY KEY, customer TEXT, items INTEGER);
        """
    )
    con.executemany(
        "INSERT INTO orders VALUES (?,?,?,?)",
        [(i, f"cust-{1000 + i}", 1999 + (i * 37) % 9000, "pending" if i % 9 == 0 else "paid")
         for i in range(1, 241)],
    )
    con.executemany("INSERT INTO carts VALUES (?,?,?)",
                    [(i, f"cust-{2000 + i}", 1 + i % 5) for i in range(1, 61)])
    con.commit()
    con.close()


def reset(root: Path | None = None) -> Paths:
    """Create a fresh lab world. Overwrites any previous state."""
    p = paths(root)
    p.root.mkdir(parents=True, exist_ok=True)
    p.cluster.write_text(json.dumps(_initial_cluster(), indent=2))
    if p.db.exists():
        p.db.unlink()
    _seed_db(p.db)
    p.events.write_text("")
    return p


def load_cluster(p: Paths) -> dict:
    return json.loads(p.cluster.read_text())


def save_cluster(p: Paths, cluster: dict) -> None:
    p.cluster.write_text(json.dumps(cluster, indent=2))
