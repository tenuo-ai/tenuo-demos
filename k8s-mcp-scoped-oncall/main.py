"""An on-call agent on the Kubernetes MCP server: non-destructive mode vs a task warrant.

The incident commander may restart and scale (up to 10) any deployment in
staging or production. It hands the on-call agent one task: restart
checkout in staging, and scale it to at most 5.

The agent then also tries what a confused or prompt-injected agent would.
The server's own ALLOW_ONLY_NON_DESTRUCTIVE_TOOLS mode lets most of it
through, because scaling to zero, applying manifests and switching clusters
aren't "destructive" tools. With the Tenuo check, only the task reaches
kubectl.

kubectl is a fake that records what it was asked to run. Run ./setup.sh first.
"""

import asyncio
import base64
import os
import tempfile
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from tenuo import Exact, OneOf, Range, SigningKey, Warrant, encode_warrant_stack

HERE = Path(__file__).parent
SERVER = HERE / "server/dist/index.js"

org_key = SigningKey.generate()  # the server trusts only this key
commander_key = SigningKey.generate()
oncall_key = SigningKey.generate()

DEPLOYMENT = {"resourceType": Exact("deployment")}

commander_warrant = (
    Warrant.mint_builder()
    .capability(
        "kubectl_rollout",
        {"subCommand": Exact("restart"), **DEPLOYMENT, "name": OneOf(["checkout", "payments", "search"]), "namespace": OneOf(["staging", "production"])},
    )
    .capability(
        "kubectl_scale",
        {**DEPLOYMENT, "name": OneOf(["checkout", "payments", "search"]), "namespace": OneOf(["staging", "production"]), "replicas": Range(max=10)},
    )
    .holder(commander_key.public_key)
    .ttl(3600)
    .mint(org_key)
)


def oncall_warrant_for(name: str, namespace: str, max_replicas: int) -> Warrant:
    """One deployment, one namespace, a replica ceiling. Tenuo rejects anything wider than the parent."""
    return (
        commander_warrant.grant_builder()
        .capability("kubectl_rollout", {"subCommand": Exact("restart"), **DEPLOYMENT, "name": Exact(name), "namespace": Exact(namespace)})
        .capability("kubectl_scale", {**DEPLOYMENT, "name": Exact(name), "namespace": Exact(namespace), "replicas": Range(max=max_replicas)})
        .holder(oncall_key.public_key)
        .ttl(900)
        .grant(commander_key)
    )


def tenuo_meta(chain: list[Warrant], key: SigningKey, tool: str, args: dict) -> dict:
    proof = chain[-1].sign(key, tool, args, int(time.time()))
    warrant = chain[0].to_base64() if len(chain) == 1 else encode_warrant_stack(chain)
    return {"tenuo": {"warrant": warrant, "signature": base64.b64encode(bytes(proof)).decode()}}


D = {"resourceType": "deployment"}
CLUSTER_ADMIN_BINDING = """apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata: {name: agent-admin}
roleRef: {apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: cluster-admin}
subjects: [{kind: ServiceAccount, name: default, namespace: staging}]
"""

AGENT_CALLS = [
    ("restart checkout/staging", "kubectl_rollout", {"subCommand": "restart", **D, "name": "checkout", "namespace": "staging"}),
    ("scale checkout/staging 3", "kubectl_scale", {**D, "name": "checkout", "namespace": "staging", "replicas": 3}),
    ("scale checkout/production 0", "kubectl_scale", {**D, "name": "checkout", "namespace": "production", "replicas": 0}),
    ("scale checkout/staging 50", "kubectl_scale", {**D, "name": "checkout", "namespace": "staging", "replicas": 50}),
    ("restart payments/staging", "kubectl_rollout", {"subCommand": "restart", **D, "name": "payments", "namespace": "staging"}),
    ("scale on another cluster", "kubectl_scale", {**D, "name": "checkout", "namespace": "staging", "replicas": 3, "context": "prod-cluster"}),
    ("scale, namespace omitted", "kubectl_scale", {**D, "name": "checkout", "replicas": 3}),
    ("apply cluster-admin binding", "kubectl_apply", {"manifest": CLUSTER_ADMIN_BINDING}),
]


def _kubeconfig() -> str:
    path = Path(tempfile.mkstemp(suffix=".yaml")[1])
    path.write_text(
        "apiVersion: v1\nkind: Config\n"
        "clusters: [{name: c, cluster: {server: 'https://127.0.0.1:1'}}]\n"
        "contexts: [{name: c, context: {cluster: c, user: u}}]\ncurrent-context: c\n"
        "users: [{name: u, user: {token: x}}]\n"
    )
    return str(path)


async def run(with_tenuo: bool, calls=AGENT_CALLS, chain=None, key=None, attach=True):
    """Run calls against the server; returns (label, kubectl_ran, is_error, text) and the kubectl log."""
    chain = chain or [commander_warrant, oncall_warrant_for("checkout", "staging", 5)]
    key = key or oncall_key
    log = Path(tempfile.mkstemp()[1])
    env = {
        "PATH": f"{HERE / 'fakebin'}:{os.environ['PATH']}",
        "HOME": os.environ.get("HOME", "/tmp"),
        "KUBECTL_LOG": str(log),
        "KUBECONFIG": _kubeconfig(),
        "ALLOW_ONLY_NON_DESTRUCTIVE_TOOLS": "true",
    }
    if with_tenuo:
        env["TENUO_TRUSTED_ROOT"] = bytes(org_key.public_key.to_bytes()).hex()
    results = []
    params = StdioServerParameters(command="node", args=[str(SERVER)], env=env)
    async with stdio_client(params, errlog=open(os.devnull, "w")) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for label, tool, args in calls:
                before = len(log.read_text().splitlines())
                meta = tenuo_meta(chain, key, tool, args) if attach else None
                res = await session.call_tool(tool, args, meta=meta)
                ran = len(log.read_text().splitlines()) > before
                text = "".join(getattr(b, "text", "") for b in res.content)
                results.append((label, ran, res.isError, text))
    return results, log.read_text().splitlines()


def report(title: str, results) -> None:
    print(f"\n{title}")
    for label, ran, _, text in results:
        if ran:
            print(f"  {label:30} kubectl ran")
        else:
            reason = text.split('"message":"', 1)[-1].split('"', 1)[0][:70]
            print(f"  {label:30} REFUSED  {reason}")


def main() -> None:
    results, _ = asyncio.run(run(with_tenuo=False))
    report("ALLOW_ONLY_NON_DESTRUCTIVE_TOOLS=true:", results)
    results, log = asyncio.run(run(with_tenuo=True))
    report("ALLOW_ONLY_NON_DESTRUCTIVE_TOOLS=true + Tenuo (on-call warrant: checkout in staging, <= 5 replicas):", results)
    print("\nkubectl was asked to run:")
    for line in log:
        print(f"  kubectl {line}")


if __name__ == "__main__":
    main()
