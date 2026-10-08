"""The ``kubectl`` and ``proddb`` command shims.

These are the real executables the agent's terminal tool runs. They read and
write the simulated world (:mod:`hermes_incident.world`) only. A warrant gates
which command strings ever reach them; in ``--unguarded`` mode nothing gates
them and a destructive command really changes the simulated state, which is how
the demo shows the difference.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from hermes_incident import world


def _logs_path(p: world.Paths, deployment: str) -> Path:
    return p.root / "logs" / f"{deployment}.log"


# kubectl resource aliases → canonical cluster key.
_ALIAS = {
    "pod": "pods", "pods": "pods", "po": "pods",
    "deployment": "deployments", "deployments": "deployments", "deploy": "deployments",
    "replicaset": "pods", "replicasets": "pods", "rs": "pods",
    "service": "services", "services": "services", "svc": "services",
    "endpoint": "endpoints", "endpoints": "endpoints", "ep": "endpoints",
    "event": "events", "events": "events", "ev": "events",
    "configmap": "configmaps", "configmaps": "configmaps", "cm": "configmaps",
    "secret": "secrets", "secrets": "secrets",
}


def _get_or_describe(verb: str, rest: list[str], cluster: dict, ns: str) -> int:
    """Handle `kubectl get|describe <resource> [name] [flags]` for read-only types."""
    if not rest:
        print("error: no resource specified", file=sys.stderr)
        return 1
    kind = _ALIAS.get(rest[0])
    if kind is None:
        print(f"error: the server doesn't have a resource type {rest[0]!r}", file=sys.stderr)
        return 1
    # An optional name is the next bare (non-flag) token.
    name = rest[1] if len(rest) > 1 and not rest[1].startswith("-") else None

    if kind == "pods":
        rows = [p for p in cluster["pods"] if name is None or p["name"] == name]
        print(f"{'NAME':32} {'READY':6} {'STATUS':10} {'RESTARTS':9} AGE")
        for p in rows:
            print(f"{p['name']:32} {p['ready']:6} {p['status']:10} {p['restarts']:<9} {p['age']}")
        return 0
    if kind == "deployments":
        items = cluster["deployments"].items()
        print(f"{'NAME':12} {'READY':8} {'UP-TO-DATE':11} IMAGE")
        for n, d in items:
            if name and n != name:
                continue
            print(f"{n:12} {str(d['ready'])+'/'+str(d['replicas']):8} {d['replicas']:<11} {d['image']}")
        return 0
    if kind == "services":
        print(f"{'NAME':12} {'TYPE':11} {'CLUSTER-IP':14} {'PORT(S)':12} SELECTOR")
        for n, s in cluster.get("services", {}).items():
            if name and n != name:
                continue
            print(f"{n:12} {s['type']:11} {s['cluster_ip']:14} {s['ports']:12} {s['selector']}")
        return 0
    if kind == "endpoints":
        print(f"{'NAME':12} ENDPOINTS")
        for n, e in cluster.get("endpoints", {}).items():
            if name and n != name:
                continue
            print(f"{n:12} {e}")
        return 0
    if kind == "events":
        print(f"{'LAST SEEN':10} {'TYPE':9} {'REASON':18} {'OBJECT':34} MESSAGE")
        for e in cluster["events"]:
            print(f"{e['age']:10} {e['type']:9} {e['reason']:18} {e['object']:34} {e['message']}")
        return 0
    if kind == "configmaps":
        cms = cluster.get("configmaps", {})
        if name:
            data = cms.get(name)
            if data is None:
                print(f"Error from server (NotFound): configmaps {name!r} not found", file=sys.stderr)
                return 1
            print(json.dumps({"kind": "ConfigMap", "metadata": {"name": name, "namespace": ns}, "data": data}, indent=2))
            return 0
        print(f"{'NAME':20} DATA")
        for n, data in cms.items():
            print(f"{n:20} {len(data)}")
        return 0
    if kind == "secrets":
        # Reachable only in --unguarded mode; the warrant denies this.
        data = cluster.get("secrets", {}).get(name) if name else None
        if data is None:
            print(f"Error from server (NotFound): secrets {name!r} not found", file=sys.stderr)
            return 1
        print(json.dumps({"kind": "Secret", "metadata": {"name": name, "namespace": ns}, "data": data}, indent=2))
        return 0
    print(f"error: unsupported resource {kind!r}", file=sys.stderr)
    return 1


def _kubectl(argv: list[str]) -> int:
    p = world.paths()
    cluster = world.load_cluster(p)
    ns = cluster["namespace"]

    if argv[:1] in (["get"], ["describe"]):
        return _get_or_describe(argv[0], argv[1:], cluster, ns)

    if argv[:1] == ["logs"] and len(argv) > 1 and argv[1].startswith("deploy/"):
        deployment = argv[1].split("/", 1)[1]
        log_file = _logs_path(p, deployment)
        if not log_file.exists():
            print(f"Error from server (NotFound): deployments.apps {deployment!r} not found", file=sys.stderr)
            return 1
        sys.stdout.write(log_file.read_text())
        return 0

    if argv[:2] == ["rollout", "status"] and len(argv) > 2 and argv[2].startswith("deploy/"):
        name = argv[2].split("/", 1)[1]
        d = cluster["deployments"].get(name)
        if d is None:
            print(f"Error from server (NotFound): deployments.apps {name!r} not found", file=sys.stderr)
            return 1
        if d["ready"] >= d["replicas"]:
            print(f'deployment "{name}" successfully rolled out')
        else:
            print(f'Waiting for deployment "{name}" rollout: {d["ready"]} of {d["replicas"]} updated replicas are available...')
        return 0

    if argv[:2] == ["rollout", "restart"] and len(argv) > 2 and argv[2].startswith("deploy/"):
        deployment = argv[2].split("/", 1)[1]
        d = cluster["deployments"].get(deployment)
        if d is None:
            print(f"Error from server (NotFound): deployments.apps {deployment!r} not found", file=sys.stderr)
            return 1
        d["ready"] = d["replicas"]
        d["generation"] += 1
        for pod in cluster["pods"]:
            if pod["app"] == deployment:
                pod["ready"] = "1/1"
                pod["restarts"] += 1
        if deployment == "checkout":
            cluster["events"].insert(0, {"age": "0s", "type": "Normal", "reason": "ScalingReplicaSet",
                                         "object": f"deployment/{deployment}", "message": "restarted; readiness recovering"})
        world.save_cluster(p, cluster)
        print(f'deployment.apps/{deployment} restarted')
        return 0

    print(f"error: unrecognized kubectl command: {' '.join(argv)}", file=sys.stderr)
    return 1


def _proddb(argv: list[str]) -> int:
    p = world.paths()
    con = sqlite3.connect(p.db)
    try:
        if argv[:1] == ["select"] and len(argv) >= 2:
            table = argv[1]
            limit = 20
            if "--limit" in argv:
                try:
                    limit = int(argv[argv.index("--limit") + 1])
                except (ValueError, IndexError):
                    pass
            try:
                rows = con.execute(f"SELECT * FROM {table} LIMIT ?", (limit,)).fetchall()
            except sqlite3.Error as exc:
                print(f"proddb: {exc}", file=sys.stderr)
                return 1
            for row in rows:
                print("  ".join(str(c) for c in row))
            print(f"({len(rows)} rows)")
            return 0
        if argv[:1] == ["exec"] and len(argv) >= 2:
            # Reachable only in --unguarded mode; the warrant allows select only.
            sql = argv[1]
            cur = con.execute(sql)
            con.commit()
            print(f"OK ({cur.rowcount} rows affected)")
            return 0
        print(f"proddb: unrecognized command: {' '.join(argv)}", file=sys.stderr)
        return 1
    finally:
        con.close()


def kubectl() -> int:
    return _kubectl(sys.argv[1:])


def proddb() -> int:
    return _proddb(sys.argv[1:])
