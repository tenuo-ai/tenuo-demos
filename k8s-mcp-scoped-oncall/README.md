# Task-scoped authority for an on-call agent on the Kubernetes MCP server

The incident commander may restart and scale any of three deployments in
staging or production. It hands the on-call agent one task: restart
`checkout` in staging, and scale it to at most 5 replicas.

[mcp-server-kubernetes](https://github.com/Flux159/mcp-server-kubernetes)
already has `ALLOW_ONLY_NON_DESTRUCTIVE_TOOLS`, which removes the delete
tools. It doesn't know about the task, so an agent that's confused or
prompt-injected can still scale production to zero, bind itself
cluster-admin, or point a call at another cluster.

## Run it

Needs [uv](https://docs.astral.sh/uv/), Node and git.

```bash
./setup.sh      # clones mcp-server-kubernetes v4.1.9, adds the check, builds it
uv run main.py
```

```text
ALLOW_ONLY_NON_DESTRUCTIVE_TOOLS=true:
  restart checkout/staging       kubectl ran
  scale checkout/staging 3       kubectl ran
  scale checkout/production 0    kubectl ran
  scale checkout/staging 50      kubectl ran
  restart payments/staging       kubectl ran
  scale on another cluster       kubectl ran
  scale, namespace omitted       kubectl ran
  apply cluster-admin binding    kubectl ran

ALLOW_ONLY_NON_DESTRUCTIVE_TOOLS=true + Tenuo (on-call warrant: checkout in staging, <= 5 replicas):
  restart checkout/staging       kubectl ran
  scale checkout/staging 3       kubectl ran
  scale checkout/production 0    REFUSED  constraint not satisfied: namespace
  scale checkout/staging 50      REFUSED  constraint not satisfied: replicas
  restart payments/staging       REFUSED  constraint not satisfied: name
  scale on another cluster       REFUSED  constraint not satisfied: context - unknown field not allowed
  scale, namespace omitted       REFUSED  constraint not satisfied: namespace - missing required argument
  apply cluster-admin binding    REFUSED  warrant does not authorize tool 'kubectl_apply'

kubectl was asked to run:
  kubectl rollout restart deployment/checkout -n staging
  kubectl scale deployment checkout --replicas=3 --namespace=staging
```

The server is the real release. `fakebin/kubectl` stands in for kubectl and
records what the server asked it to run, so nothing touches a cluster.

## What changes in the server

`index.ts.patch` is 9 lines in the `tools/call` handler, right after the
existing `isToolAllowed` check, plus `tenuo-authz.ts`. When
`TENUO_TRUSTED_ROOT` is set, every call must carry a warrant chain in
`_meta.tenuo` that leads back to that key and a signature from the warrant's
holder; the server verifies it with `@tenuo/core` before running kubectl.
Unset, nothing changes.

The check is per argument and closed-world: `namespace`, `name` and
`replicas` must fit the warrant, a missing `namespace` doesn't fall through
to `default`, and an argument the warrant doesn't name (`context`) is
refused. The on-call warrant is derived from the commander's, so it can only
be narrower, and the on-call agent can't pass on more than it got.

## Where the warrant comes from

The agent's side holds a key and attaches `_meta.tenuo`; `tenuo_meta()` in
`main.py` shows it. Here the warrants are minted in Python and verified by the
TypeScript server, which is the same wire format any Tenuo client uses.
Callers without a warrant are refused when the check is on, so it's for
servers serving agents you run.

## Tests

```bash
uv run pytest
```

- non-destructive mode alone lets every call through (the baseline)
- with Tenuo, kubectl sees exactly the two task commands, and each refusal names the argument that failed
- no warrant, an untrusted root, a stolen warrant without its key, and a child warrant without its parent never reach kubectl
- the commander can't delegate outside its scope; the on-call agent can't re-delegate wider

Tested with mcp-server-kubernetes v4.1.9, `@tenuo/core` 0.3.2-beta.0, tenuo 0.3.2 and mcp 1.30.
