#!/usr/bin/env bash
# Arquivo: scripts/medir-qwen3.sh
# Nome: medir-qwen3.sh
# Propósito: medir com o modelo real (qwen3:8b no Ollama local) o Callidus antes e depois de um commit.
# Responsabilidade: script de medição — roda lab/avaliar.py em rodadas alternadas (antes e depois em worktrees limpos de dois commits) e guarda resumos, bancos isolados e dados do servidor.
# Componentes: verificação do Ollama e do modelo, worktree do commit base, função rodar (uma rodada de um lado), laço de rodadas alternadas.
# Dependências: git, curl, ollama, .venv do projeto, lab/avaliar.py, data/providers.yaml (provedor meu_ollama).
# Observações: não toca data/agent.db nem providers.yaml; os bancos de avaliação ficam em /tmp e são copiados para lab/out/qwen3/.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
MODEL="${MODEL:-qwen3:8b}"
ROUNDS="${ROUNDS:-3}"
ANTES="${ANTES:-d180d09}"
STEPS="${STEPS:-120}"
PROVIDER="${PROVIDER:-meu_ollama}"
OUTDIR="$ROOT/lab/out/qwen3"
WT="/tmp/callidus-antes"
WT2="/tmp/callidus-depois"
DEPOIS="${DEPOIS:-$(git rev-parse --short HEAD)}"
PY="$ROOT/.venv/bin/python"
mkdir -p "$OUTDIR"
exec > >(tee -a "$OUTDIR/medicao.log") 2>&1

echo "== medição $MODEL — $(date '+%Y-%m-%d %H:%M:%S') — antes=$ANTES depois=$DEPOIS rodadas=$ROUNDS"
curl -sf http://127.0.0.1:11434/api/version > "$OUTDIR/ollama-version.json" || { echo "Ollama não responde em 127.0.0.1:11434 — abra o Ollama e rode de novo."; exit 1; }
if ! ollama list | awk '{print $1}' | grep -qx "$MODEL"; then
  echo "baixando $MODEL ..."; ollama pull "$MODEL" || exit 1
fi
curl -s http://127.0.0.1:11434/api/show -d "{\"model\":\"$MODEL\"}" > "$OUTDIR/modelo-show.json"
{ sysctl -n hw.memsize; sysctl -n machdep.cpu.brand_string; sw_vers -productVersion; } > "$OUTDIR/maquina.txt" 2>/dev/null
env | grep '^OLLAMA_' > "$OUTDIR/ollama-env.txt" 2>/dev/null
launchctl getenv OLLAMA_CONTEXT_LENGTH >> "$OUTDIR/ollama-env.txt" 2>/dev/null

# Os dois lados rodam em worktrees limpos: trabalho sem commit na árvore não contamina a medição.
for par in "$WT:$ANTES" "$WT2:$DEPOIS"; do
  git worktree remove --force "${par%%:*}" >/dev/null 2>&1
  git worktree add --detach "${par%%:*}" "${par##*:}" >/dev/null || exit 1
  cp lab/avaliar.py "${par%%:*}/lab/"
done
export PROVIDERS_CONFIG_PATH="$ROOT/data/providers.yaml"

rodar() {  # $1 = antes|depois  $2 = rodada
  local lado="$1" r="$2" dir="$WT2" work="/tmp/callidus-aval-$1"
  [ "$lado" = antes ] && dir="$WT"
  echo "-- rodada $r · $lado · $(date '+%H:%M:%S')"
  ( cd "$dir" && "$PY" -c "import sys; sys.path.insert(0, 'src'); import agent; print('   código:', agent.__file__)" )
  ( cd "$dir" && AVALIACAO_WORKDIR="$work" "$PY" lab/avaliar.py --label "qwen3-$lado-r$r" --model "$MODEL" --provider "$PROVIDER" --max-steps "$STEPS" )
  cp "$dir/lab/out/avaliacao-qwen3-$lado-r$r.json" "$OUTDIR/" 2>/dev/null
  mkdir -p "$OUTDIR/$lado-r$r" && cp "$work"/*.db "$OUTDIR/$lado-r$r/" 2>/dev/null
  curl -s http://127.0.0.1:11434/api/ps > "$OUTDIR/$lado-r$r/ollama-ps.json"
}

for r in $(seq 1 "$ROUNDS"); do
  # Ordem alternada: nenhum lado sempre pega o modelo já aquecido.
  if [ $((r % 2)) -eq 1 ]; then rodar antes "$r"; rodar depois "$r"; else rodar depois "$r"; rodar antes "$r"; fi
done

git worktree remove --force "$WT" >/dev/null 2>&1
git worktree remove --force "$WT2" >/dev/null 2>&1
echo "== fim $(date '+%Y-%m-%d %H:%M:%S') — resultados em lab/out/qwen3/"
