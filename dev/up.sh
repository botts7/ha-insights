#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

mkdir -p config

# Pick up HA_PORT from .env if present, else default to 8125.
HA_PORT="${HA_PORT:-8125}"
if [ -f .env ]; then
  HA_PORT=$(grep -E '^HA_PORT=' .env | tail -n1 | cut -d= -f2- | tr -d '"' || echo "$HA_PORT")
  HA_PORT="${HA_PORT:-8125}"
fi

docker compose up -d

echo "Waiting for HA to come online on port $HA_PORT..."
for i in $(seq 1 60); do
  if curl -sf "http://localhost:$HA_PORT/manifest.json" >/dev/null 2>&1; then
    echo "HA reachable at http://localhost:$HA_PORT"
    echo ""
    echo "First-run setup:"
    echo "  1. Open http://localhost:$HA_PORT in a browser"
    echo "  2. Complete onboarding (create admin user)"
    echo "  3. Profile -> Long-Lived Access Tokens -> create one"
    echo "  4. Save the token to dev/token.txt"
    echo "  5. Run: python probe.py"
    exit 0
  fi
  sleep 2
done

echo "HA did not come online within 120 seconds. Check 'docker compose logs'." >&2
exit 1
