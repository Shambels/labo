#!/usr/bin/env bash
# docker compose for NVIDIA auto-ontology (cloned in $AO_DIR, default ~/src/auto-ontology) with our overrides.
#   ontology/ao.sh build auto-ontology
#   ontology/ao.sh up -d postgres auto-ontology ingestion-service auto-ontology-frontend
set -euo pipefail
AO_DIR="${AO_DIR:-$HOME/src/auto-ontology}"
HERE="$(cd "$(dirname "$0")" && pwd)"
exec docker compose -f "$AO_DIR/docker-compose.yml" -f "$HERE/auto-ontology.override.yaml" \
  --env-file "$AO_DIR/.env" "$@"
