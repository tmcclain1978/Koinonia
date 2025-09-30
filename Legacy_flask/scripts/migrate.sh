#!/usr/bin/env bash
set -euo pipefail
# Run DB migrations (Alembic) at any time:
alembic upgrade head
