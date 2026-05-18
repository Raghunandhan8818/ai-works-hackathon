#!/usr/bin/env bash
set -euo pipefail

docker exec -i rib-postgres psql -U ripple -d rib -c "
TRUNCATE TABLE
  disagreements,
  consumer_beliefs,
  semantic_profiles,
  history_signals,
  field_usages,
  symbols,
  fields,
  indexed_files,
  services
RESTART IDENTITY CASCADE;
"

echo "RIB database flushed."
