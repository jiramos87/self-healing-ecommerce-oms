-- Initial schema for self-healing OMS: orders, incidents, counters.

CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_number TEXT NOT NULL,
    store TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('created', 'on_hold')),
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (store, order_number)
);

CREATE TABLE IF NOT EXISTS incidents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    class TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN (
            'received',
            'diagnosing',
            'issue_opened',
            'pr_opened',
            'issue_only',
            'duplicate',
            'expected_behavior',
            'diagnosis_failed'
        )
    ),
    fingerprint TEXT NOT NULL UNIQUE,
    summary TEXT,
    error_body JSONB,
    payload JSONB,
    recurrence_count INTEGER NOT NULL DEFAULT 1,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    duplicate_of UUID REFERENCES incidents (id),
    issue_url TEXT,
    pr_url TEXT,
    trace JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE IF NOT EXISTS counters (
    key TEXT NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (key, window_start)
);

CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_incidents_created_at ON incidents (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents (status);
