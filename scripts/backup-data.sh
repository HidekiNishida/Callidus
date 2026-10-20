#!/usr/bin/env bash
# Arquivo: scripts/backup-data.sh
# Nome: backup-data.sh
# Propósito: gerar um backup datetado do diretório de dados do Callidus.
# Responsabilidade: camada de script — empacota a pasta de dados em um arquivo comprimido na pasta de backups.
# Componentes: resolução do diretório de dados, criação da pasta de destino e geração do arquivo tar.gz.
# Dependências: tar, date e as ferramentas padrão do shell.
# Observações: não altera os dados de origem; quando a pasta de dados não existe, o script termina com erro.
#
# backup timestamped do diretório data/
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
