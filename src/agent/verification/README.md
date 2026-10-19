# Verificação (`verification/`) — Checks Determinísticos Independentes

Verificação proporcional ao risco: quem executa **não** aprova o próprio resultado. Evidência persistida e reavaliada na retomada.

## Módulos

| Arquivo | Exporta | Propósito |
|---------|---------|-----------|
| [`runner.py`](runner.py) | `run_verification`, `VerificationResult`, `VerificationResult(verifier, passed, summary, detail)` | **Runner principal** — executa spec de verificação e retorna resultado estruturado |
| [`recovery.py`](recovery.py) | `diagnose_verification_failure`, `plan_recovery`, `recovery_signature`, `RecoveryDiagnosis` | **Ciclo de recuperação** — classifica a causa da reprovação e decide diagnóstico → correção → re-verificação |
| [`fingerprint.py`](fingerprint.py) | `snapshot(root, spec, tool_args)` | **Impressão digital** — SHA256 dos arquivos avaliados; detecta evidência desatualizada na retomada |

## Verificadores Suportados (`runner.py`)

| Tipo (`spec.type`) | Verificador | Quando Usa | Critério |
|-------------------|-------------|------------|----------|
| `pytest` | `run_pytest` tool | Projetos Python com testes | `exit_code == 0` + testes coletados |
| `script` / `run_script` | `run_script` tool | Script Python custom | `exit_code == 0` |
| `command` / `run_command` | `run_command` tool | Comando shell arbitrário | `exit_code == 0` |
| `file_contains` | Leitura direta (`_read_whole`) | Escrita de arquivo (edit/write) | `needle in content` (+ `syntax: true` → `ast.parse`/JSON) |
| `syntax` | `ast.parse` / `json.loads` | Validação sintática standalone | Sem `SyntaxError` / `ValueError` |
| `file_exists` | Leitura direta (`_read_whole`) | Artefato que precisa existir | Arquivo existe e tem ao menos `min_bytes` bytes |
| `static_analysis` / `ast_check` | `ast.parse` por arquivo | Lint estático sem depender de ferramenta externa | Nenhum erro sintático no caminho (ou nos `.py` recursivos) |
| `acceptance_manual` | — | Critério subjetivo humano | `passed=None` (inconclusivo → `BLOCKED`) |
| `stages` | — | Etapas anteriores concluídas | `passed=True` (atalho) |

## Fluxo de Verificação (`_finalize_verification` no runner.py)

```python
async def _finalize_verification(run, project, task, work_root, implicit_spec=None):
    spec = task.metadata.get("verification") or implicit_spec or task.metadata.get("implicit_verification")
    if not spec:
        # Sem verificação declarada → completa sem evidência (apenas leitura/operação sem risco)
        update_status(task, COMPLETED)
        return {"action": "completed_without_verification"}

    vresult = await run_verification(project_root=work_root, spec=spec, tool_args=meta.get("tool_args"))
    
    # Evidência persistida
    evidence = EvidenceModel(
        task_id=task.id,
        attempt_id=attempt.id,
        verifier=vresult.verifier,
        passed=vresult.passed,
        summary=vresult.summary,
        detail_json={..., "criteria": criteria_of(task), "artifacts": fingerprint.snapshot(...)}
    )
    
    # Classificação de falha
    failure = classify_verification(vresult.passed, vresult.summary, output)
    
    if vresult.passed is True:
        update_status(task, COMPLETED)
        consolidate_parent(parent)
        return {"action": "verified_ok"}
    elif blocked:  # passed=None + categoria CONFIGURATION/EXTERNAL
        update_status(task, BLOCKED, reason="verificação bloqueada: ...")
        return {"action": "verify_blocked", "failure": noted}
    elif vresult.passed is False:
        # Loop detection: mesma verificação falhou 2x → BLOCKED
        if repeated_output_detected(task.id, fingerprint):
            update_status(task, BLOCKED, reason="a mesma verificação falhou de novo")
            return {"action": "blocked_loop"}
        update_status(task, RETRY_PENDING)
        return {"action": "verify_failed", "failure": noted}
    else:  # inconclusivo
        update_status(task, BLOCKED, reason="verificação inconclusiva")
        return {"action": "verify_inconclusive"}
```

## Ciclo de Recuperação (`recovery.py`)

Verificação reprovada não encerra a tarefa: o agente **diagnostica**, **corrige** e **re-verifica**.

| Causa detectada | Ação | Automática | Orientação ao modelo |
|-----------------|------|-----------|----------------------|
| `syntax_error` | `fix_syntax` | sim | corrigir a sintaxe do arquivo indicado antes de qualquer outra mudança |
| `test_failure` | `fix_tests` | sim | corrigir a causa no código de produção — nunca alterar o teste |
| `missing_artifact` | `regenerate_artifact` | sim | gerar o artefato esperado antes de reexecutar |
| `timeout` | `retry` | sim | reduzir o escopo do passo e executar de novo |
| `missing_dependency` | `install_dependency` | não | verificar se o módulo existe no ambiente |
| `environment` | `manual_review` | não | é condição do ambiente, não defeito do código |
| `unknown` | `manual_review` | não | repetir a verificação com mais contexto |

```python
diagnosis = diagnose_verification_failure(verifier=..., summary=..., detail=..., spec=...)
plan = plan_recovery(diagnosis, attempt_count=recoveries, max_recoveries=settings.verification_max_recoveries)
# plan["retry"] == True  → nova tentativa com `recovery_guidance` no prompt
# plan["action"] == "block" → tarefa bloqueada com diagnóstico (sem laço infinito)
```

A assinatura da falha (`recovery_signature`) ignora números, paths e hashes — a mesma causa não vira laço diferente. O limite é `verification_max_recoveries` (2 por padrão).

## Verificação Implícita (Escrita de Arquivo)

Quando o modelo faz `model_operation` (edit_file/write_file), o orquestrador cria verificação implícita:

```python
implicit = {
    "type": "file_contains",
    "path": payload["path"],
    "contains": written[:200],
    "implicit": True,
    "syntax": True  # valida ast.parse / json.loads
}
```

## Fingerprint (`fingerprint.py`)

```python
def snapshot(root: str, spec: dict, tool_args: dict) -> dict:
    """SHA256 dos arquivos que a verificação avaliou."""
    if spec.get("type") == "file_contains":
        path = resolve_under_root(root, spec["path"])
        return {spec["path"]: sha256(path.read_bytes()).hexdigest()}
    if spec.get("type") in {"pytest", "script", "command"}:
        # Arquivos alterados pela tool_args (path, cwd, etc.)
        ...
    return {}
```

**Na retomada**: `reopen_verification_gaps` compara fingerprint salvo vs atual → se mudou, evidência vira `desatualizada` e tarefa reabre para verificar de novo.

## Estados de Evidência (`detail_json.state`)

| Estado | `passed` | Efeito na Task |
|--------|----------|----------------|
| `aprovado` | `true` | → `COMPLETED` |
| `reprovado` | `false` | → `RETRY_PENDING` (corrigir implementação) |
| `bloqueado` | `null` | → `BLOCKED` (verificação não rodou: exec faltando, aprovação) |
| `inconclusivo` | `null` | → `BLOCKED` (nunca conta como sucesso) |
| `desatualizado` | mantém | Deixa de valer; tarefa reabre para verificar de novo |

## Verificação Proporcional ao Risco

| Risco | Verificador | Exemplo |
|-------|-------------|---------|
| Baixo (leitura) | Nenhuma (completed_without_verification) | `read_file`, `list_dir`, `search_grep` |
| Médio (escrita) | `file_contains` + `syntax` | `edit_file`, `write_file` (implícita) |
| Alto (comportamento) | `pytest` / `script` / `command` | Testes unitários, integração, build |
| Global (integração) | Etapa `Verificação global` | Todos os requisitos obrigatórios `satisfied` |

## Testes

```bash
# Verificação independente
pytest tests/test_independent_verification.py -v

# Verificação proporcional
pytest tests/test_proportional_verification.py -v

# Global verify + requisitos
pytest tests/test_global_verify.py tests/test_global_acceptance.py -v

# Fingerprint + retomada
pytest tests/test_resume_integrity.py -v
```

---

**Voltar:** [src/agent/README.md](../README.md) · **Raiz:** [README.md](../../../README.md) · **Requisitos/Verificação:** [docs/architecture/requisitos-verificacao-progresso.md](../../../docs/architecture/requisitos-verificacao-progresso.md)