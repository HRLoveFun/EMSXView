#!/bin/bash
# P4-OpenAPI: Extract OpenAPI spec from running backend and generate TypeScript types.
#
# Prerequisites:
#   1. Backend must be running on http://localhost:3000
#   2. npm install --save-dev openapi-typescript (in frontend/)
#
# Usage:
#   bash scripts/generate-openapi-types.sh
#
# This script replaces the hand-written TypeScript interfaces with
# auto-generated types sourced directly from the FastAPI Pydantic schemas,
# eliminating the risk of frontend/backend type drift.

set -euo pipefail

BACKEND_URL="${BACKEND_URL:-http://localhost:3000}"
OUTPUT_DIR="frontend/src/shared/api-types"
OPENAPI_JSON="$OUTPUT_DIR/openapi.json"
TYPES_FILE="$OUTPUT_DIR/schema.d.ts"

echo "==> Fetching OpenAPI spec from $BACKEND_URL/openapi.json ..."
mkdir -p "$OUTPUT_DIR"
curl -sSf "$BACKEND_URL/openapi.json" -o "$OPENAPI_JSON"
echo "    Saved to $OPENAPI_JSON"

echo "==> Generating TypeScript types from OpenAPI spec ..."
cd frontend
npx openapi-typescript "../$OPENAPI_JSON" -o "../$TYPES_FILE"
echo "    Generated $TYPES_FILE"

echo ""
echo "Done! Import types via:"
echo "  import type { paths, components } from '@shared/api-types/schema';"
echo ""
echo "Verify against hand-written contracts:"
echo "  See docs/schema-contract.md for the canonical type mapping."
