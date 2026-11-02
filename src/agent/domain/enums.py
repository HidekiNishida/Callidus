"""
Arquivo: src/agent/domain/enums.py
Nome: enums.py
Propósito: definir os enums de domínio do Callidus (tarefa, run, tentativa e memória).
Responsabilidade: camada de domínio — vocabulário de estados compartilhado por toda a aplicação.
Componentes: TaskStatus, TaskKind, MemoryKind, RunStatus, AttemptKind.
Dependências: enum (stdlib).
Observações: são `StrEnum`; o valor gravado no banco e o exibido na API são o mesmo texto.
"""
from enum import StrEnum


class TaskStatus(StrEnum):
    """Ciclo de vida de uma tarefa: do planejamento à verificação e ao desfecho final."""

    PENDING = "PENDING"
    PLANNING = "PLANNING"
    READY = "READY"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    RETRY_PENDING = "RETRY_PENDING"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TaskKind(StrEnum):
    """Papel da tarefa na decomposição: objetivo do usuário, subsistema ou operação concreta."""

    OBJECTIVE = "objective"
    SUBSYSTEM = "subsystem"
    OPERATION = "operation"


class MemoryKind(StrEnum):
    """Natureza do registro de memória: canônico, de execução, contextual, evidência ou procedimento."""

    CANONICAL = "canonical"
    EXECUTION = "execution"
    CONTEXTUAL = "contextual"
    EVIDENCE = "evidence"
    PROCEDURE = "procedure"
    # Níveis da memória operacional da tarefa: resumo, detalhe recuperável e artefato.
    OPERATIONAL = "operational"
    TASK_DETAIL = "task_detail"
    ARTIFACT = "artifact"


class RunStatus(StrEnum):
    """Estado do run: ativo, pausado para retomada ou encerrado de forma definitiva."""

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AttemptKind(StrEnum):
    """Natureza do registro de tentativa: chamada de modelo, de ferramenta ou de verificação."""

    MODEL = "model"
    TOOL = "tool"
    VERIFICATION = "verification"


class InferenceType(StrEnum):
    """Taxonomia da finalidade da inferência, atribuída pelo orquestrador conforme a operação."""

    PLANNING = "planning"
    TASK_DECOMPOSITION = "task_decomposition"
    EXECUTION = "execution"
    TOOL_SELECTION = "tool_selection"
    TOOL_RESULT_ANALYSIS = "tool_result_analysis"
    VERIFICATION = "verification"
    ERROR_CORRECTION = "error_correction"
    RECOVERY = "recovery"
    RESEARCH = "research"
    MEMORY_RETRIEVAL = "memory_retrieval"
    CONTEXT_SUMMARIZATION = "context_summarization"
    FINAL_RESPONSE = "final_response"
    DIAGNOSTIC = "diagnostic"
    CALIBRATION = "calibration"
    OTHER = "other"


class ContextComponentCategory(StrEnum):
    """Categoria independente que identifica os componentes que formam o prompt do modelo."""

    SYSTEM_INSTRUCTIONS = "system_instructions"
    AGENT_INSTRUCTIONS = "agent_instructions"
    TASK_INSTRUCTIONS = "task_instructions"
    CONVERSATION_HISTORY = "conversation_history"
    PARENT_AGENT_CONTEXT = "parent_agent_context"
    CHILD_AGENT_CONTEXT = "child_agent_context"
    SHORT_TERM_MEMORY = "short_term_memory"
    LONG_TERM_MEMORY = "long_term_memory"
    KNOWLEDGE_RETRIEVAL = "knowledge_retrieval"
    TOOL_DEFINITIONS = "tool_definitions"
    TOOL_CALLS = "tool_calls"
    TOOL_RESULTS = "tool_results"
    FILES_AND_DOCUMENTS = "files_and_documents"
    CODE_CONTEXT = "code_context"
    RESEARCH_RESULTS = "research_results"
    COMPACTION_SUMMARIES = "compaction_summaries"
    OUTPUT_FORMAT_AND_SCHEMAS = "output_format_and_schemas"
    PROVIDER_METADATA = "provider_metadata"
    OTHER = "other"
