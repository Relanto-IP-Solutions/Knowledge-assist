#!/usr/bin/env bash
# Knowledge-Assist Database Setup - run from project root
# Usage: ./setup.sh
#
# Prerequisites: gcloud CLI, uv (or pip)
# The script will prompt for GCP project, password, etc. if not in configs/.env

set -e
cd "$(dirname "$0")"

echo "=== Knowledge-Assist Database Setup ==="
echo ""

if command -v uv &>/dev/null; then
    uv run python -m scripts.setup_database "$@"
else
    echo "uv not found. Install: https://docs.astral.sh/uv/"
    echo "Or run: pip install -e . && python -m scripts.setup_database"
    exit 1
fi
