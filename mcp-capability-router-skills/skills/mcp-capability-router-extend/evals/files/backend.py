"""Evaluation fixture: persist this JSON document without losing typed fields."""

CAPABILITY_TABLE = """
CREATE TABLE capabilities (
    capability_id TEXT PRIMARY KEY,
    server_id TEXT NOT NULL,
    capability_type TEXT NOT NULL,
    document JSONB NOT NULL
)
"""
