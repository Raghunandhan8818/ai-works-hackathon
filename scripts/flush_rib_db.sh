#!/usr/bin/env bash
set -euo pipefail

SQL="
TRUNCATE TABLE
  disagreements,
  consumer_beliefs,
  semantic_profiles,
  history_signals,
  field_usages,
  symbols,
  fields,
  indexed_files,
  services,
  business_contexts,
  code_classes,
  code_methods,
  drift_events,
  test_evidences
RESTART IDENTITY CASCADE;
"

# Try direct psql first (works if postgres is running locally or via docker port-forward)
if PGPASSWORD=ripple psql -h localhost -U ripple -d rib -c "$SQL" 2>/dev/null; then
  echo "RIB database flushed (direct psql)."
  exit 0
fi

# Fallback: docker exec (container named rib-postgres)
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "rib-postgres"; then
  docker exec -i rib-postgres psql -U ripple -d rib -c "$SQL"
  echo "RIB database flushed (docker exec)."
  exit 0
fi

# Fallback: API endpoint
if curl -sf -X POST http://localhost:8000/api/flush | grep -q flushed; then
  echo "RIB database flushed (API endpoint)."
  exit 0
fi

echo "ERROR: could not connect to Ripple database. Try:" >&2
echo "  curl -X POST http://localhost:8000/api/flush" >&2
exit 1
