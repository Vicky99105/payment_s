#!/usr/bin/env bash
# Copies the server-side secrets from the local .env into the Vercel project's production environment.
# Run from the repo root after `npx vercel link`. Values are piped via stdin and never echoed.
set -euo pipefail

cd "$(dirname "$0")/.."
set -a
# shellcheck disable=SC1091
. ./.env
set +a

put() {
  local name="$1" value="$2"
  npx --yes vercel env rm "$name" production --yes >/dev/null 2>&1 || true
  printf '%s' "$value" | npx --yes vercel env add "$name" production >/dev/null
  echo "set $name"
}

put ENV production
put DATABASE_URL "$DATABASE_URL"
put WEBHOOK_SIGNING_SECRET "$WEBHOOK_SIGNING_SECRET"
put API_KEYS "$API_KEYS"
put SETTLEMENT_FAULT_INJECTION "${SETTLEMENT_FAULT_INJECTION:-false}"

echo "done. Redeploy for the values to take effect: npx vercel deploy --prod"
