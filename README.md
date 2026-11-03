# aws_cost

Pull daily AWS cost data from Cost Explorer into a MySQL/MariaDB table for display in Grafana.

One script, no ORM. Restated costs are handled by upsert, so re-running is always safe.

## What it does

- Calls AWS Cost Explorer (`ce:GetCostAndUsage`), grouped by service, for the
  `unblended` and `net_unblended` cost types.
- Upserts into a table `cost_daily`, keyed on `(day, provider, service, cost_type)`.
  Re-pulling a day overwrites it in place — no duplicates.
- Marks a month `is_final = 1` once it is `--settle-days` past month end (default 7);
  recent, still-changing days stay `is_final = 0` (estimate).

> Cost Explorer lives in `us-east-1`; the client is pinned there regardless of your
> default region. Each API request costs ~$0.01.

## Requirements

- Python 3.10+ (boto3 dropped Python 3.9 support on 2026-04-29). If the
  default `python3` is older, install a newer interpreter and build the venv
  with it, e.g. `python3.12 -m venv venv`.
- A reachable MySQL/MariaDB database (e.g. RDS)
- AWS credentials with permission `ce:GetCostAndUsage` (via env, shared profile, or an instance role)

## Setup

```bash
# from the repo root
python3 -m venv venv          # use a 3.10+ interpreter, e.g. python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` with the database connection (git-ignored — never commit it):

```bash
DB_HOST=your-db-host
DB_PORT=3306          # optional, defaults to 3306
DB_NAME=your_db
DB_USER=your_user
DB_PASSWORD=your_password
```

AWS credentials are **not** read from `.env`. Use one of:

- an AWS profile: `export AWS_PROFILE=your-profile`, or
- env vars (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`), or
- an instance/task role (nothing to set).

## Usage

The script reads the DB settings from the environment. Load `.env` into the shell first:

```bash
source venv/bin/activate
set -a; source .env; set +a
```

Then:

```bash
# One-time: pull ~13 months of history (Cost Explorer's max window)
python ingest_aws_costs.py --backfill

# Ongoing: re-pull and upsert recent days (default: last 60)
python ingest_aws_costs.py
```

Options:

| Flag | Default | Meaning |
|------|---------|---------|
| `--backfill` | off | One-time pull of ~13 months of history. |
| `--days N` | 60 | Daily mode: how many recent days to re-pull. |
| `--settle-days N` | 7 | Days after month end before a month is marked final. |

## Scheduling (cron)

Cron does not load `.env` or activate the venv. Use the `run.sh` wrapper, which
locates the repo from its own path, loads `.env`, and runs the venv's Python:

```cron
17 6 * * *  /absolute/path/to/cost-tracker/run.sh >> /absolute/path/to/cost-tracker/ingest.log 2>&1
```

Only the path in the cron line itself is absolute (cron requires it); everything
inside `run.sh` is relative to the repo, so you can move the repo without editing
the script. Any arguments pass through, e.g. `run.sh --days 90`.

## Grafana

Point a Grafana **MySQL** data source at the same database. Example daily-by-service panel:

```sql
SELECT day AS time, service AS metric, SUM(amount_usd) AS value
FROM cost_daily
WHERE provider='aws' AND cost_type='$cost_type' AND $__timeFilter(day)
GROUP BY day, service
ORDER BY day;
```

For category panels (e.g. top services), set the query's **Format as → Table**, since
those queries have no time column.
