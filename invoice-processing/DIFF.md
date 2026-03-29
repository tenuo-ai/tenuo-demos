# What changes to add Tenuo

The complete diff between `baseline/` and `with-tenuo/`. Three files change. Everything else stays the same.

## 1. Invoice Processor (`agents/invoice_processor.py`)

One line changes — swap `AuthenticatedToolNode` for `TenuoToolNode`:

```diff
-def build_invoice_processor_graph() -> StateGraph:
-    tool_node = AuthenticatedToolNode(
-        INVOICE_PROCESSOR_TOOLS,
-        agent_id="invoice-processor",
-    )
+def build_invoice_processor_graph() -> StateGraph:
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
+def build_payment_executor_graph() -> StateGraph:
+    from auth.tenuo_tool_node import TenuoAuthenticatedToolNode
+    from auth.tenuo_local import build_tenuo_tool_node_local
+    inner = build_tenuo_tool_node_local(PAYMENT_EXECUTOR_TOOLS)
+    tool_node = TenuoAuthenticatedToolNode(inner, agent_id="payment-executor")
```

## 3. Graph (`agents/graph.py`)

Issue a warrant before running the pipeline:

```diff
+    from auth.tenuo_local import issue_local_warrant
+    warrant_b64 = issue_local_warrant()
+
     initial_state = {
-        "warrant": "",
+        "warrant": warrant_b64,
     }
```

## New files added

| File | What it does |
|------|-------------|
| `auth/tenuo_local.py` | Issues warrants locally. Pins `bank_account` and `bank_routing` as `Exact` constraints on `initiate_payment`. |
| `auth/tenuo_integration.py` | Connects to Tenuo Cloud for warrant issuance via triggers. |
| `auth/tenuo_tool_node.py` | Wraps `TenuoToolNode` with the 4-layer auth display so the dashboard shows all 5 layers. |

## What the warrant does

The warrant defines:

- **11 tools authorized** (everything except `update_vendor_bank`)
- **`initiate_payment` constrained**: `bank_account` must be `7291034851`, `bank_routing` must be `021000021`
- **All other tools**: unconstrained

When the injection poisons the vendor's bank account to `8847291034`, the Payment Executor calls `initiate_payment` with the poisoned value. The warrant catches it:

```
bank_account: expected '7291034851', got '8847291034' — DENIED
```
