#!/usr/bin/env bash
# Smoke E2E: tarefa mínima via API com meu_ollama + gpt-oss:20b (não altera providers.yaml).
set -euo pipefail
BASE="${CALLIDUS_URL:-http://127.0.0.1:8765}"
PROJECT_ID="${1:-}"
if [[ -z "$PROJECT_ID" ]]; then
  PROJECT_ID="$(curl -s -m 15 "$BASE/projects" | python3 -c "import sys,json; ps=json.load(sys.stdin); print(ps[0]['id'] if ps else '')")"
fi
[[ -n "$PROJECT_ID" ]] || { echo "sem projeto"; exit 2; }

CONV="$(curl -s -m 15 -X POST "$BASE/projects/$PROJECT_ID/conversations" \
  -H 'Content-Type: application/json' \
  -d '{"title":"audit ollama gpt-oss"}')"
CONV_ID="$(python3 -c "import json,sys; print(json.load(sys.stdin)['id'])" <<<"$CONV")"

TASK="$(curl -s -m 15 -X POST "$BASE/projects/$PROJECT_ID/tasks" \
  -H 'Content-Type: application/json' \
  -d "{\"title\":\"audit ollama\",\"objective\":\"Responda apenas com a palavra OK, sem ferramentas.\",\"kind\":\"objective\",\"conversation_id\":\"$CONV_ID\"}")"
TASK_ID="$(python3 -c "import json,sys; print(json.load(sys.stdin)['id'])" <<<"$TASK")"

RUN="$(curl -s -m 15 -X POST "$BASE/projects/$PROJECT_ID/runs" \
  -H 'Content-Type: application/json' \
  -d "{\"root_task_id\":\"$TASK_ID\",\"config\":{\"provider\":\"meu_ollama\",\"model_id\":\"gpt-oss:20b\",\"approve_risky_tools\":true}}")"
RUN_ID="$(python3 -c "import json,sys; print(json.load(sys.stdin)['id'])" <<<"$RUN")"

curl -s -m 10 -X POST "$BASE/runs/$RUN_ID/autonomous/enable" -H 'Content-Type: application/json' >/dev/null
echo "run=$RUN_ID task=$TASK_ID conv=$CONV_ID"

curl -s -m 900 -X POST "$BASE/runs/$RUN_ID/execute?max_steps=40" -H 'Content-Type: application/json' || true

for i in $(seq 1 30); do
  STATUS="$(curl -s -m 10 "$BASE/runs/$RUN_ID" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',''))")"
  echo "status=$STATUS"
  case "$STATUS" in COMPLETED|FAILED|CANCELLED|PAUSED) break ;; esac
  sleep 2
done

curl -s -m 60 "$BASE/runs/$RUN_ID/observe" | python3 -c "
import json, sys
d = json.load(sys.stdin)
events = d.get('events') or []
we = [e for e in events if e.get('type') == 'work.explained']
print('events', len(events), 'work.explained', len(we))
print('run_status', (d.get('run') or {}).get('status'))
"
