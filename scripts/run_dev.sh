#!/usr/bin/env bash
set -euo pipefail
export FLASK_DEBUG=${FLASK_DEBUG:-1}
export FLASK_APP=${FLASK_APP:-server.py}
python3 -m flask run --port=${PORT:-5000} --host=0.0.0.0
