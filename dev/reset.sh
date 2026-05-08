#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
docker compose down -v 2>/dev/null || true
rm -rf config token.txt
echo "State wiped. Run ./up.sh to start fresh."
