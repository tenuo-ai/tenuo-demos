-- Tenuo Enterprise Demo: AP Automation Schema

CREATE TABLE employees (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    email           TEXT NOT NULL,
    department      TEXT NOT NULL,
    role            TEXT NOT NULL,
    approval_limit  NUMERIC(12,2),
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE vendors (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    tax_id          TEXT,
    bank_name       TEXT NOT NULL,
    bank_account    TEXT NOT NULL,
    bank_routing    TEXT NOT NULL,
    verified        BOOLEAN DEFAULT false,
    verified_at     TIMESTAMPTZ,
    risk_score      TEXT DEFAULT 'low',
    country         TEXT DEFAULT 'US',
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE vendor_bank_changes (
    id              SERIAL PRIMARY KEY,
    vendor_id       TEXT REFERENCES vendors(id),
    old_account     TEXT,
    new_account     TEXT,
    old_routing     TEXT,
    new_routing     TEXT,
    changed_by      TEXT NOT NULL,
    reason          TEXT,
    authorized      BOOLEAN DEFAULT false,
    auth_method     TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE purchase_orders (
    id              TEXT PRIMARY KEY,
    vendor_id       TEXT REFERENCES vendors(id),
    department      TEXT NOT NULL,
    description     TEXT NOT NULL,
    amount          NUMERIC(12,2) NOT NULL,
    currency        TEXT DEFAULT 'USD',
    status          TEXT DEFAULT 'open',
    approved_by     TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE invoices (
    id              TEXT PRIMARY KEY,
    vendor_id       TEXT REFERENCES vendors(id),
    po_id           TEXT REFERENCES purchase_orders(id),
    department      TEXT NOT NULL,
    amount          NUMERIC(12,2) NOT NULL,
    currency        TEXT DEFAULT 'USD',
    description     TEXT NOT NULL,
    notes           TEXT,
    status          TEXT DEFAULT 'pending',
    due_date        DATE,
    submitted_at    TIMESTAMPTZ DEFAULT now(),
    processed_at    TIMESTAMPTZ,
    processed_by    TEXT
);

CREATE TABLE payments (
    id              TEXT PRIMARY KEY,
    invoice_id      TEXT REFERENCES invoices(id),
    vendor_id       TEXT REFERENCES vendors(id),
    amount          NUMERIC(12,2) NOT NULL,
    currency        TEXT DEFAULT 'USD',
    bank_account    TEXT NOT NULL,
    bank_routing    TEXT NOT NULL,
    fx_rate         NUMERIC(10,6),
    status          TEXT DEFAULT 'pending',
    approved_by     TEXT,
    executed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE auth_decisions (
    id              SERIAL PRIMARY KEY,
    request_id      TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    tool_name       TEXT NOT NULL,
    tool_args       JSONB,
    layer           TEXT NOT NULL,
    decision        TEXT NOT NULL,
    reason          TEXT,
    latency_us      INTEGER,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE agent_logs (
    id              SERIAL PRIMARY KEY,
    run_id          TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    event_type      TEXT NOT NULL,       -- 'thinking', 'tool_call', 'tool_result', 'delegation', 'status'
    content         TEXT,                -- LLM reasoning text, tool result, status message
    tool_name       TEXT,                -- For tool_call/tool_result events
    tool_args       JSONB,               -- For tool_call events
    metadata        JSONB,               -- Extra context (invoice_id, vendor_id, etc.)
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- Indexes for dashboard queries
CREATE INDEX idx_agent_logs_run_id ON agent_logs(run_id);
CREATE INDEX idx_agent_logs_created_at ON agent_logs(created_at);
CREATE INDEX idx_auth_decisions_request_id ON auth_decisions(request_id);
CREATE INDEX idx_auth_decisions_created_at ON auth_decisions(created_at DESC);
CREATE INDEX idx_payments_created_at ON payments(created_at DESC);
CREATE INDEX idx_vendor_bank_changes_vendor ON vendor_bank_changes(vendor_id);
CREATE INDEX idx_invoices_status ON invoices(status);
