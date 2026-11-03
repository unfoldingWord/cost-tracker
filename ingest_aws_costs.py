#!/usr/bin/env python3
"""Pull AWS Cost Explorer daily costs into MySQL/MariaDB.

Two modes:
  --backfill   One-time: pull ~13 months of history (CE's max window).
  (default)    Daily: re-pull a recent window and upsert, so AWS's
               restatements of recent days overwrite the stored values.

Restatement is handled by upsert: the primary key is
(day, provider, service, cost_type); re-running overwrites amounts in place.
A day is marked is_final=1 once its month has settled (see --settle-days);
until then it stays is_final=0 (an estimate that may still change).

Config via environment variables:
  DB_HOST, DB_PORT (3306), DB_USER, DB_PASSWORD, DB_NAME
  AWS credentials: standard boto3 resolution (env vars, profile, or IAM role).
IAM needs ce:GetCostAndUsage (Resource: *). Cost Explorer lives only in
us-east-1, so the CE client is pinned there regardless of your default region.
"""

import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import boto3
import pymysql

from schema import ensure_table

# CE metric name -> the cost_type value we store.
COST_TYPES = {
    "UnblendedCost": "unblended",
    "NetUnblendedCost": "net_unblended",
    # Add "AmortizedCost": "amortized" here if you use RIs/Savings Plans.
    # It comes back in the same API call at no extra request cost.
}

UPSERT = """
INSERT INTO cost_daily (day, provider, service, cost_type, amount_usd, is_final)
VALUES (%s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
  amount_usd = VALUES(amount_usd),
  is_final   = VALUES(is_final)
"""


# --- date / settle helpers (all UTC, matching how CE buckets days) ---

def first_of_next_month(d: date) -> date:
    return date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)


def months_ago_first(d: date, n: int) -> date:
    """First day of the month n months before d."""
    y, m = d.year, d.month - n
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def is_final(day: date, today: date, settle_days: int) -> bool:
    """A day is final once its month has closed and settled."""
    return today >= first_of_next_month(day) + timedelta(days=settle_days)


# --- Cost Explorer ---

def fetch_costs(ce, start: date, end: date):
    """Yield (day, service, cost_type, Decimal amount) rows.

    start inclusive, end exclusive. Follows NextPageToken to the last page.
    """
    kwargs = {
        "TimePeriod": {"Start": start.isoformat(), "End": end.isoformat()},
        "Granularity": "DAILY",
        "Metrics": list(COST_TYPES),
        "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
    }
    while True:
        resp = ce.get_cost_and_usage(**kwargs)
        for bucket in resp["ResultsByTime"]:
            day = date.fromisoformat(bucket["TimePeriod"]["Start"])
            for group in bucket["Groups"]:
                service = group["Keys"][0]
                for ce_metric, cost_type in COST_TYPES.items():
                    amount = Decimal(group["Metrics"][ce_metric]["Amount"])
                    yield day, service, cost_type, amount
        token = resp.get("NextPageToken")
        if not token:
            break
        kwargs["NextPageToken"] = token


# --- DB ---

def connect():
    return pymysql.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 3306)),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
        autocommit=False,
    )


def upsert(conn, rows):
    """rows: iterable of (day, service, cost_type, amount, is_final_bool)."""
    params = [
        (day.isoformat(), "aws", service, cost_type, str(amount), int(final))
        for day, service, cost_type, amount, final in rows
    ]
    if not params:
        return 0
    with conn.cursor() as cur:
        cur.executemany(UPSERT, params)
    conn.commit()
    return len(params)


# --- main ---

def run(backfill: bool, days: int, settle_days: int):
    today = datetime.now(timezone.utc).date()
    if backfill:
        start = months_ago_first(today, 12)  # ~13 months incl. current month
    else:
        start = today - timedelta(days=days)
    end = today  # exclusive -> last complete day is yesterday

    ce = boto3.client("ce", region_name="us-east-1")
    conn = connect()
    try:
        ensure_table(conn)

        rows = (
            (day, service, cost_type, amount, is_final(day, today, settle_days))
            for day, service, cost_type, amount in fetch_costs(ce, start, end)
        )
        n = upsert(conn, rows)
    finally:
        conn.close()

    mode = "backfill" if backfill else "daily"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{ts} {mode}: upserted {n} rows for {start} .. {end} (exclusive)")


def main():
    p = argparse.ArgumentParser(description="Ingest AWS Cost Explorer daily costs into MySQL/MariaDB.")
    p.add_argument("--backfill", action="store_true",
                   help="One-time pull of ~13 months of history.")
    p.add_argument("--days", type=int, default=60,
                   help="Daily mode: how many recent days to re-pull (default 60).")
    p.add_argument("--settle-days", type=int, default=7,
                   help="Days after month end before a month is marked final (default 7).")
    args = p.parse_args()
    try:
        run(args.backfill, args.days, args.settle_days)
    except KeyError as e:
        sys.exit(f"Missing required env var: {e}")


if __name__ == "__main__":
    main()
