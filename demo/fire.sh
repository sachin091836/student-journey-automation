#!/usr/bin/env bash
# Fire test events at the Student Journey workflow.
#   ./demo/fire.sh optin | optin-ghl | enroll | replay | unmapped | break zoom | heal | state | reset
# N8N_WEBHOOK defaults to the production URL; use http://localhost:5678/webhook-test while
# the workflow is open in the editor and you've clicked "Test workflow".
set -euo pipefail
cd "$(dirname "$0")"
HOOK="${N8N_WEBHOOK:-http://localhost:5678/webhook}/student-journey"
SECRET="${JOURNEY_SECRET:-demo-secret}"
MOCK="${MOCK_URL:-http://localhost:4010}"
post() { curl -sS -X POST "$HOOK/$1" -H "X-Journey-Secret: $SECRET" -H 'Content-Type: application/json' --data @"payloads/$2"; echo; }
case "${1:-}" in
  optin)     post optin optin-wordpress.json ;;
  optin-ghl) post optin optin-ghl.json ;;
  enroll)    post enrollment purchase-woocommerce.json ;;
  unmapped)  post enrollment purchase-unmapped-product.json ;;
  replay)    post replay recording-riverside.json ;;
  break)     curl -sS -X POST "$MOCK/__fail/${2:?service: ghl|klaviyo|zoom|wp}"; echo ;;
  heal)      curl -sS -X POST "$MOCK/__heal"; echo ;;
  state)     curl -sS "$MOCK/__state" | python3 -m json.tool ;;
  reset)     curl -sS -X POST "$MOCK/__reset"; echo ;;
  *) sed -n '2,5p' "$0"; exit 1 ;;
esac
