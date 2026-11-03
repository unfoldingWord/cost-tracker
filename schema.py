#!/usr/bin/env python3
"""Database schema for the cost tracker.

Holds the table definition and a helper to create it if missing. Imported
and called by ingest_aws_costs.py at startup, so the schema lives in one
place, separate from the ingest logic.
"""

DDL = """
CREATE TABLE IF NOT EXISTS cost_daily (
  day        DATE          NOT NULL,
  provider   VARCHAR(32)   NOT NULL DEFAULT 'aws',
  service    VARCHAR(128)  NOT NULL,
  cost_type  VARCHAR(32)   NOT NULL,
  amount_usd DECIMAL(16,6) NOT NULL,
  is_final   TINYINT(1)    NOT NULL DEFAULT 0,
  updated_at TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP
                                     ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (day, provider, service, cost_type)
)
"""


def ensure_table(conn):
    """Create the cost_daily table if it does not already exist."""
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()
