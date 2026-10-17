#!/usr/bin/env bash
# scripts/backup-data.sh — backup timestamped do diretório data/
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="${AGENT_DATA_DIR:-$ROOT/data}"
DEST="$ROOT/backups"
TS="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$DEST"
ARCHIVE="$DEST/agent-data-$TS.tar.gz"
if [[ -d "$DATA" ]]; then
  tar -czf "$ARCHIVE" -C "$(dirname "$DATA")" "$(basename "$DATA")"
  echo "Backup criado: $ARCHIVE"
else
  echo "Nada a copiar: $DATA não existe"
  exit 1
fi
