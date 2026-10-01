#!/usr/bin/env bash
# Wake the scale-to-zero backend before sharing the demo link (costs ~$0.06 of Modal credit for 30 min warm).
#   API=https://<workspace>--quotedesk-web.modal.run ./scripts/warmup.sh
set -euo pipefail
API="${API:-${1:-http://localhost:8000}}"
echo "waking $API ..."
for i in $(seq 1 30); do
  if curl -fsS --max-time 60 "$API/api/health" > /tmp/qd_health.json 2>/dev/null; then break; fi
  echo "  not up yet ($i), retrying in 5s"; sleep 5
done
cat /tmp/qd_health.json; echo
echo "running one sample so the model is hot ..."
curl -fsS --max-time 180 -X POST "$API/api/quotes/process?stream=false" \
  -H 'Content-Type: application/json' -d '{"sample_id":"clean-multi"}' \
  | python -c "import json,sys; q=json.load(sys.stdin); print('quote', q['id'], q['status'], 'path', q['flags']['path'])"
echo "warm. The container stays up while in use and ~5 min after the last request (scaledown_window=300)."
