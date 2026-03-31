# What changes to add Tenuo

The complete diff between `baseline/` and `with-tenuo/`. Three agent files change, three new auth files are added, and two existing auth files get minor updates (`pipeline.py`, `tool_node.py`) to pass a shared request ID so the dashboard can group auth decisions by tool call.

## 1. Invoice Processor (`agents/invoice_processor.py`)

The key change — swap `AuthenticatedToolNode` for `TenuoToolNode`. The `use_tenuo` parameter lets `graph.py` build either version from the same function signature:

```diff
-def build_invoice_processor_graph() -> StateGraph:
-    tool_node = AuthenticatedToolNode(
-        INVOICE_PROCESSOR_TOOLS,
-        agent_id="invoice-processor",
-    )
+def build_invoice_processor_graph(use_tenuo: bool = False) -> StateGraph:
+    from auth.tenuo_tool_node import TenuoAuthenticatedToolNode
+    from auth.tenuo_local import build_tenuo_tool_node_local
+    inner = build_tenuo_tool_node_local(INVOICE_PROCESSOR_TOOLS)
+    tool_node = TenuoAuthenticatedToolNode(inner, agent_id="invoice-processor")
```

## 2. Payment Executor (`agents/payment_executor.py`)

Same change:

```diff
-def build_payment_executor_graph() -> StateGraph:
-    tool_node = AuthenticatedToolNode(
-        PAYMENT_EXECUTOR_TOOLS,
-        agent_id="payment-executor",
-    )
+def build_payment_executor_graph(use_tenuo: bool = False) -> StateGraph:
+    from auth.tenuo_tool_node import TenuoAuthenticatedToolNode
+    from auth.tenuo_local import build_tenuo_tool_node_local
+    inner = build_tenuo_tool_node_local(PAYMENT_EXECUTOR_TOOLS)
+    tool_node = TenuoAuthenticatedToolNode(inner, agent_id="payment-executor")
```

## 3. Graph (`agents/graph.py`)

Issue a root warrant before running the pipeline. As the Finance Controller
delegates to each subgraph, the warrant is attenuated — narrowing the tool set
and pinning payment arguments per-invoice:

```diff
+    if auth_stack == "tenuo" and os.environ.get("TENUO_MODE", "local") == "local":
+        from auth.tenuo_local import issue_root_warrant
+        warrant_b64 = issue_root_warrant()
+
     initial_state = {
-        "warrant": "",
+        "warrant": warrant_b64,
     }
```

Attenuation happens at each delegation boundary in the same file:

```diff
+    # Invoice Processor gets 5 tools; update_vendor_bank is excluded
+    processor_warrant = await attenuate_for_invoice_processor(
+        root_warrant, invoice_id, vendor_id,
+    )
+
+    # Payment Executor gets bank_account and bank_routing pinned from vendor master
+    payment_warrant = await attenuate_for_payment_executor(
+        root_warrant, invoice_id, vendor_id,
+    )
```

## 4. Policy code (`auth/tenuo_local.py`)

This is the file you'd write in your own app — it defines what each agent is
allowed to do and under what constraints. Three functions matter:

**Issue a root warrant** (all tools, no constraints — the Finance Controller
holds this and narrows it before delegating):

```python
root = Warrant.issue(
    keypair=issuer_key,
    capabilities={
        "read_invoice": {},
        "initiate_payment": {},
        "update_vendor_bank": {},
        # ... 9 more tools
    },
    ttl_seconds=1800,
    holder=controller_key.public_key,
)
```

**Attenuate for the Invoice Processor** (remove `update_vendor_bank` entirely):

```python
child = root.attenuate(
    {
        "read_invoice": {},
        "read_po": {},
        "lookup_vendor": {},
        "verify_vendor": {},
        "approve_invoice": {},
        # NO update_vendor_bank — structurally unavailable to this agent
    },
    signing_key=controller_key,
    holder=processor_key.public_key,
    ttl_seconds=600,
)
```

**Attenuate for the Payment Executor** (pin `bank_account` and `bank_routing`
to the values read from the vendor master *before* the injection can corrupt them):

```python
child = root.attenuate(
    {
        "initiate_payment": {
            "bank_account": Exact(bank_account),   # pinned from vendor master
            "bank_routing": Exact(bank_routing),   # pinned from vendor master
            "vendor_id":    Exact(vendor_id),
            "amount":       Wildcard(),
            "invoice_id":   Wildcard(),
        },
        "approve_payment": {},
        "get_fx_rate": {},
    },
    signing_key=controller_key,
    holder=payment_key.public_key,
    ttl_seconds=300,
)
```

When the injection fires and `initiate_payment` is called with account
`8847291034`, the warrant rejects it:

```
bank_account: expected '7291034851', got '8847291034' — DENIED
```

The other two new files (`auth/tenuo_integration.py` and `auth/tenuo_tool_node.py`)
are demo plumbing — connecting to Tenuo Cloud and wiring the dashboard display.
You would not write these in a typical integration.
