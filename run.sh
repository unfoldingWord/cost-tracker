#!/usr/bin/env bash
# Wrapper for cron: loads .env and runs the ingest script from the repo dir,
# wherever the repo happens to live. Any args are passed through
# (e.g. run.sh --backfill).
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"

set -a
. ./.env
set +a

exec ./venv/bin/python ingest_aws_costs.py "$@"
