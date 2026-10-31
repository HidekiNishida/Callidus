#!/usr/bin/env bash
# Arquivo: scripts/medir-multirequisito.sh
# Nome: medir-multirequisito.sh
# Propósito: medir com um modelo local real (qwen3-vl:8b por padrão) o cenário de complexidade média (multirequisito) antes e depois de uma correção ainda sem commit.
# Responsabilidade: script de medição — testes da correção, CI no worktree "depois" e rodadas alternadas de lab/avaliar.py nos dois lados, com resumo comparativo.
# Componentes: LADOS (antes, depois ou os dois), verificação do Ollama e do modelo, worktrees antes (HEAD) e depois (HEAD + arquivos da correção), testes, CI, laço de rodadas, resumo.
# Dependências: git, curl, ollama, .venv do projeto, lab/avaliar.py, scripts/ci.py, data/providers.yaml (provedor meu_ollama, só lido).
# Observações: não toca data/agent.db nem providers.yaml; o trabalho sem commit de outras sessões fica fora dos dois lados.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
MODEL="${MODEL:-qwen3-vl:8b}"
ROUNDS="${ROUNDS:-3}"
STEPS="${STEPS:-120}"
ONLY="${ONLY:-multirequisito}"
LADOS="${LADOS:-antes depois}"   # "depois" sozinho mede só a correção
PROVIDER="${PROVIDER:-meu_ollama}"
TAG="${TAG:-qwen3vl}"
OUTDIR="$ROOT/lab/out/$TAG"
WT="/tmp/callidus-antes-$TAG"
WT2="/tmp/callidus-depois-$TAG"
PY="$ROOT/.venv/bin/python"
# Arquivos da correção: só eles entram no lado "depois".
ARQUIVOS=(
  src/agent/orchestrator/requirements.py
  src/agent/orchestrator/plan_validation.py
  src/agent/tools/builtins.py
  src/agent/tools/diffing.py
  src/agent/remote/tools.py
  src/agent/providers/ollama_policy.py
  src/agent/providers/ollama.py
  src/agent/util/json_parse.py
  src/agent/context/budget.py
  src/agent/orchestrator/execution/model_operation.py
  src/agent/verification/runner.py
  tests/test_multirequisito_regressions.py
  tests/test_qwen3_ollama_policy.py
)
mkdir -p "$OUTDIR"
exec > >(tee -a "$OUTDIR/medicao.log") 2>&1

echo "== medição $MODEL ($ONLY) — $(date '+%Y-%m-%d %H:%M:%S') — rodadas=$ROUNDS"
curl -sf http://127.0.0.1:11434/api/version > "$OUTDIR/ollama-version.json" || { echo "Ollama não responde em 127.0.0.1:11434 — abra o Ollama e rode de novo."; exit 1; }
if ! ollama list | awk '{print $1}' | grep -qx "$MODEL"; then
  echo "baixando $MODEL ..."; ollama pull "$MODEL" || exit 1
fi
curl -s http://127.0.0.1:11434/api/show -d "{\"model\":\"$MODEL\"}" > "$OUTDIR/modelo-show.json"
"$PY" - "$OUTDIR/modelo-show.json" <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
print("   capacidades:", d.get("capabilities"), "| família:", (d.get("details") or {}).get("family"),
      "| parâmetros:", (d.get("details") or {}).get("parameter_size"), "| quant:", (d.get("details") or {}).get("quantization_level"))
PYEOF
{ sysctl -n hw.memsize; sysctl -n machdep.cpu.brand_string; sw_vers -productVersion; } > "$OUTDIR/maquina.txt" 2>/dev/null

# Worktrees limpos: "antes" = HEAD; "depois" = HEAD + os arquivos da correção.
for wt in "$WT" "$WT2"; do
  git worktree remove --force "$wt" >/dev/null 2>&1
  git worktree add --detach "$wt" HEAD >/dev/null || exit 1
  cp lab/avaliar.py "$wt/lab/"
done
for f in "${ARQUIVOS[@]}"; do cp "$f" "$WT2/$f"; done
( cd "$WT2" && git status --short )

echo "-- testes da correção (worktree depois)"
( cd "$WT2" && "$PY" -c "import sys; sys.path.insert(0,'src'); import agent; print('   código:', agent.__file__)" )
if ! ( cd "$WT2" && "$PY" -m pytest -q -p no:cacheprovider tests/test_multirequisito_regressions.py tests/test_requirements.py \
      tests/test_plan_contract.py tests/test_dev_tools.py tests/test_tool_contracts.py tests/test_global_acceptance.py \
      tests/test_qwen3_ollama_policy.py tests/test_ollama_provider.py ); then
  echo "!! testes da correção falharam — medição interrompida"; exit 1
fi
echo "-- CI completo (worktree depois)"
( cd "$WT2" && PATH="$ROOT/.venv/bin:$PATH" "$PY" scripts/ci.py ) > "$OUTDIR/ci-depois.log" 2>&1
echo "   CI saiu com $? — detalhes em lab/out/$TAG/ci-depois.log"; tail -25 "$OUTDIR/ci-depois.log"

export PROVIDERS_CONFIG_PATH="$ROOT/data/providers.yaml"
rodar() {  # $1 = antes|depois  $2 = rodada
  local lado="$1" r="$2" dir="$WT2" work="/tmp/callidus-aval-$TAG-$1"
  [ "$lado" = antes ] && dir="$WT"
  echo "-- rodada $r · $lado · $(date '+%H:%M:%S')"
  ( cd "$dir" && AVALIACAO_WORKDIR="$work" "$PY" lab/avaliar.py --label "$TAG-$lado-r$r" --model "$MODEL" \
      --provider "$PROVIDER" --max-steps "$STEPS" --only "$ONLY" ) | grep -v '^ "\|^{\|^}'
  cp "$dir/lab/out/avaliacao-$TAG-$lado-r$r.json" "$OUTDIR/" 2>/dev/null
  mkdir -p "$OUTDIR/$lado-r$r" && cp "$work"/*.db "$OUTDIR/$lado-r$r/" 2>/dev/null
  curl -s http://127.0.0.1:11434/api/ps > "$OUTDIR/$lado-r$r/ollama-ps.json"
}
# Aquecimento: a primeira carga do modelo não entra na conta de nenhum lado.
curl -s http://127.0.0.1:11434/api/generate -d "{\"model\":\"$MODEL\",\"prompt\":\"ok\",\"stream\":false,\"think\":false}" >/dev/null
for r in $(seq 1 "$ROUNDS"); do
  # Ordem alternada: nenhum lado sempre pega o modelo já aquecido.
  if [ $((r % 2)) -eq 1 ]; then ordem="antes depois"; else ordem="depois antes"; fi
  for lado in $ordem; do case " $LADOS " in *" $lado "*) rodar "$lado" "$r";; esac; done
done

"$PY" - "$OUTDIR" "$TAG" <<'PYEOF'
import json, sys, glob, statistics as st
out, tag = sys.argv[1], sys.argv[2]
for lado in ("antes", "depois"):
    rs = [json.load(open(f))["cenarios"][0] for f in sorted(glob.glob(f"{out}/avaliacao-{tag}-{lado}-r*.json"))]
    if not rs:
        continue
    n = len(rs)
    def med(k): return round(st.median(r[k] for r in rs), 1)
    print(f"{lado:6} n={n} aceite={sum(r['aceite_ok'] for r in rs)}/{n} completos={sum(r['run_status']=='completed' for r in rs)}/{n} "
          f"falsas={sum(r.get('conclusao_falsa', False) for r in rs)} prematuras={sum(r['conclusao_prematura'] for r in rs)} "
          f"| mediana: {med('segundos')}s model_calls={med('model_calls')} tool_calls={med('tool_calls')} tarefas={med('tarefas')} "
          f"tokens_out={med('tokens_completion')}")
PYEOF
git worktree remove --force "$WT" >/dev/null 2>&1
git worktree remove --force "$WT2" >/dev/null 2>&1
echo "== fim $(date '+%Y-%m-%d %H:%M:%S') — resultados em lab/out/$TAG/"
