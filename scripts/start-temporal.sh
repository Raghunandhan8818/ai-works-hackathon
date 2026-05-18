#!/usr/bin/env bash
set -euo pipefail
temporal server start-dev --db-filename "${TMPDIR:-/tmp}/ripple-temporal.db"
