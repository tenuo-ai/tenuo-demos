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


def _kubectl(argv: list[str]) -> int:
    p = world.paths()
    cluster = world.load_cluster(p)
    ns = cluster["namespace"]

    if argv[:1] == ["get"]:
        what = argv[1] if len(argv) > 1 else ""
        if what.startswith("pod"):
            print(f"{'NAME':32} {'READY':6} {'STATUS':10} {'RESTARTS':9} AGE")
            for pod in cluster["pods"]:
                print(f"{pod['name']:32} {pod['ready']:6} {pod['status']:10} {pod['restarts']:<9} {pod['age']}")
            return 0
        if what.startswith("deploy"):
            print(f"{'NAME':12} {'READY':8} {'UP-TO-DATE':11} IMAGE")
            for name, d in cluster["deployments"].items():
                print(f"{name:12} {str(d['ready'])+'/'+str(d['replicas']):8} {d['replicas']:<11} {d['image']}")
            return 0
        if what.startswith("event"):
            print(f"{'LAST SEEN':10} {'TYPE':9} {'REASON':18} {'OBJECT':34} MESSAGE")
            for e in cluster["events"]:
                print(f"{e['age']:10} {e['type']:9} {e['reason']:18} {e['object']:34} {e['message']}")
            return 0
        if what == "secret":
            # Reachable only in --unguarded mode; the warrant denies this.
            name = argv[2] if len(argv) > 2 else ""
            data = cluster.get("secrets", {}).get(name)
            if data is None:
                print(f"Error from server (NotFound): secrets {name!r} not found", file=sys.stderr)
                return 1
            print(json.dumps({"kind": "Secret", "metadata": {"name": name, "namespace": ns}, "data": data}, indent=2))
            return 0
        print(f"error: unknown resource {what!r}", file=sys.stderr)
        return 1

    if argv[:1] == ["logs"] and len(argv) > 1 and argv[1].startswith("deploy/"):
        deployment = argv[1].split("/", 1)[1]
        log_file = _logs_path(p, deployment)
        if not log_file.exists():
            print(f"Error from server (NotFound): deployments.apps {deployment!r} not found", file=sys.stderr)
            return 1
        sys.stdout.write(log_file.read_text())
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
