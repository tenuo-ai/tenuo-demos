#!/usr/bin/env bash
set -euo pipefail

# Tenuo Enterprise Demo — Local Runner
# Usage: ./scripts/run-demo.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEMO_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Tenuo AP Automation Demo ==="
echo ""

# Check dependencies
command -v docker >/dev/null 2>&1 || { echo "Error: docker required"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "Error: python3 required"; exit 1; }

# Start infrastructure
echo "Starting infrastructure (postgres, spicedb, opa)..."
cd "$DEMO_DIR"
docker compose up -d postgres spicedb opa

# Wait for postgres
echo "Waiting for PostgreSQL..."
for i in $(seq 1 30); do
    if docker compose exec -T postgres pg_isready -U demo -d tenuo_demo >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

# Seed database
echo "Seeding database..."
python3 -m db.seed

# Start vendor portal
echo "Starting vendor portal..."
python3 -m uvicorn vendor_portal.server:app --host 0.0.0.0 --port 8082 &
PORTAL_PID=$!

# Start demo server
echo "Starting demo server..."
python3 -m uvicorn server.app:app --host 0.0.0.0 --port 8080 &
SERVER_PID=$!

echo ""
echo "=== Demo Ready ==="
echo "  Dashboard server: http://localhost:8080"
echo "  Vendor portal:    http://localhost:8082"
echo "  Dashboard UI:     cd dashboard && npm run dev (port 3000)"
echo ""
echo "Press Ctrl+C to stop."

trap "kill $PORTAL_PID $SERVER_PID 2>/dev/null; docker compose down" EXIT
wait
