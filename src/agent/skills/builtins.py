"""
Arquivo: src/agent/skills/builtins.py
Nome: builtins.py
Propósito: definir o catálogo de Skills profissionais nativas do Agente.
Responsabilidade: camada de domínio — competências padrão disponíveis mesmo sem catálogo em disco.
Componentes: get_builtin_skills.
Dependências: agent.skills.models.
Observações: as skills embutidas garantem operação offline; o catálogo em disco tem precedência sobre elas.
"""
from __future__ import annotations

from agent.skills.models import SkillSpec


def get_builtin_skills() -> list[SkillSpec]:
    """Retorna as Skills profissionais essenciais nativas do agente.

    Returns:
        A lista de skills embutidas, prontas para o registro.
    """
    return [
        SkillSpec(
            id="software_engineering",
            name="Engenharia de Software e Implementação Modular",
            description="Construção de código robusto, modular, tipado e sustentável seguindo padrões de projeto e preservando compatibilidade.",
            activation_criteria=[
                "Tarefas que envolvem criação ou alteração de código-fonte, módulos, classes ou funções",
                "Implementação de novas funcionalidades ou extensão de subsistemas existentes",
            ],
            prohibited_criteria=[
                "Não usar para simples consultas de documentação ou leituras sem alteração",
            ],
            required_tools=["file_read", "file_write", "file_edit", "shell_exec"],
            procedures=[
                "Inspecione a arquitetura existente e os módulos consumidores antes de qualquer alteração",
                "Preserve rigorosamente contratos de API existentes e compatibilidade retroativa",
                "Implemente alterações atômicas com tipagem estática (Type hints) e tratamento de erros defensivo",
                "Não introduza dependências externas sem justificação técnica explícita",
                "Garanta que novos componentes possuam pontos claros de teste e verificação",
            ],
            validation_rules=[
                "Código não introduz erros de sintaxe ou de importação",
                "Funcionalidade possui testes correspondentes que comprovam seu comportamento",
                "Módulos existentes continuam funcionando sem regressão",
            ],
            risk_factors=[
                "Quebra de compatibilidade em APIs públicas ou serviços consumidores",
                "Efeitos colaterais em estado persistente ou concorrência",
            ],
            keywords=[
                "implementar", "criar", "desenvolver", "funcionalidade", "feature",
                "módulo", "código", "backend", "api", "classe", "função", "service",
            ],
            applies_to_kinds=["MODEL_OPERATION", "SUBSYSTEM", "OBJECTIVE"],
        ),
        SkillSpec(
            id="debugging_root_cause",
            name="Depuração Sistemática e Análise de Causa Raiz",
            description="Diagnóstico metodológico de falhas, formulação de hipóteses, isolamento da causa fundamental e correção cirúrgica sem mascarar sintomas.",
            activation_criteria=[
                "Tarefas de correção de bugs, falhas em testes, exceções ou comportamentos anômalos",
                "Diagnóstico de problemas reproduzíveis no ambiente ou na execução",
            ],
            prohibited_criteria=[
                "Nunca altere testes ou especificações silenciosamente apenas para forçar passagem",
                "Não aplique correções por tentativa e erro sem evidência da causa",
            ],
            required_tools=["file_read", "grep_search", "pytest_run", "shell_exec", "file_edit"],
            procedures=[
                "Reproduza a falha com o teste específico ou comando mínimo reproduzível",
                "Colete evidências concretas: stack trace, linhas exatas, valores de variáveis e estado do banco",
                "Formule hipóteses claras sobre o mecanismo da falha antes de editar qualquer código",
                "Isole a causa fundamental diferenciando causa raiz de sintoma superficial",
                "Implemente a correção cirúrgica no local exato do defeito",
                "Reexecute a suíte de testes para confirmar que a falha foi resolvida e nenhuma regressão ocorreu",
            ],
            validation_rules=[
                "O teste que anteriormente falhava passa com sucesso",
                "Nenhum teste pré-existente foi quebrado pela correção",
                "A causa raiz foi comprovadamente eliminada",
            ],
            risk_factors=[
                "Mascarar o defeito com tratamento genérico (ex: catch-all silencioso)",
                "Introduzir regressões em outros fluxos que dependiam do comportamento anterior",
            ],
            keywords=[
                "bug", "erro", "falha", "corrigir", "diagnosticar", "investigar",
                "quebrou", "crash", "exception", "traceback", "fix", "reparar", "consertar",
            ],
            applies_to_kinds=["MODEL_OPERATION", "VERIFICATION", "SUBSYSTEM"],
        ),
        SkillSpec(
            id="testing_quality_assurance",
            name="Garantia de Qualidade e Testes Independentes",
            description="Elaboração e execução de verificações determinísticas, casos de borda, testes de regressão e validação independente de critérios de aceitação.",
            activation_criteria=[
                "Tarefas de validação, criação de testes, verificação de critérios de aceite ou homologação",
                "Subtarefas de verificação em planos de execução",
            ],
            prohibited_criteria=[
                "Não considerar conclusão baseando-se apenas em afirmação do modelo sem execução do teste",
            ],
            required_tools=["pytest_run", "shell_exec", "file_read", "file_write"],
            procedures=[
                "Mapeie os critérios de aceitação formais e requisitos da tarefa",
                "Escreva testes determinísticos cobrindo o caminho principal e casos de borda (limites, nulos, erros)",
                "Execute os testes em subprocesso real e capture stdout, stderr e código de retorno",
                "Armazene evidências estruturadas com fingerprint dos artefatos avaliados",
            ],
            validation_rules=[
                "Todos os testes relevantes passam com código de saída 0",
                "Os critérios de aceitação foram explicitamente validados",
            ],
            risk_factors=[
                "Testes frágeis que dependem de ordem de execução ou estado global",
                "Asserções vazias ou insuficientes que dão falso positivo",
            ],
            keywords=[
                "teste", "testes", "pytest", "validar", "verificar", "qualidade",
                "qa", "cobertura", "critérios", "aceite", "evidência", "homologação",
            ],
            applies_to_kinds=["VERIFICATION", "MODEL_OPERATION", "OBJECTIVE"],
        ),
        SkillSpec(
            id="refactoring_clean_code",
            name="Refatoração e Código Limpo",
            description="Melhoria da estrutura interna, legibilidade e manutenibilidade do código sem alterar seu comportamento observável externo.",
            activation_criteria=[
                "Tarefas de limpeza de código, simplificação, redução de débito técnico ou desacoplamento",
            ],
            prohibited_criteria=[
                "Não refatore sem uma rede de testes automatizados prévia e funcional",
                "Não misture refatoração estrutural com mudanças de comportamento ou novas regras de negócio",
            ],
            required_tools=["file_read", "file_edit", "pytest_run", "grep_search"],
            procedures=[
                "Confirme que todos os testes existentes passam antes de tocar no código",
                "Identifique duplicações, complexidade ciclomática excessiva e acoplamento desnecessário",
                "Aplique passos incrementais e atômicos (extrair método, simplificar condicionais, renomear)",
                "Reexecute os testes após cada pequeno passo para garantir equivalência comportamental",
            ],
            validation_rules=[
                "Todos os testes continuam passando exatamente com o mesmo comportamento externo",
                "Métricas de clareza e manutenibilidade melhoraram comprovadamente",
            ],
            risk_factors=[
                "Alteração inadvertida de comportamentos sutis ou casos especiais",
            ],
            keywords=[
                "refatorar", "refatoração", "clean code", "simplificar", "reestruturar",
                "débito técnico", "limpar código", "otimizar estrutura", "desacoplar",
            ],
            applies_to_kinds=["MODEL_OPERATION", "SUBSYSTEM"],
        ),
        SkillSpec(
            id="system_architecture",
            name="Arquitetura de Sistemas e Decomposição",
            description="Definição de fronteiras entre módulos, fluxo de dados, separação de responsabilidades e contratos de interface consistentes.",
            activation_criteria=[
                "Tarefas complexas de planejamento, desenho de subsistemas, arquitetura ou decomposição de grandes pedidos",
            ],
            prohibited_criteria=[
                "Não introduza camadas ou padrões de projeto desnecessários sem benefício claro",
            ],
            required_tools=["file_read", "file_list", "grep_search"],
            procedures=[
                "Mapeie as entidades de domínio, persistência e interfaces existentes",
                "Isole o estado e garanta dependências direcionadas sem ciclos",
                "Defina contratos explícitos (schemas, interfaces, enums) para comunicação entre camadas",
                "Divida o objetivo em subtarefas com contexto mínimo suficiente e dependências explícitas",
            ],
            validation_rules=[
                "Grafo de dependências acíclico e coeso",
                "Contratos formais definidos antes da implementação dos consumidores",
            ],
            risk_factors=[
                "Sobre-engenharia com abstrações vazias ou excesso de indireção",
            ],
            keywords=[
                "arquitetura", "decompor", "módulos", "estrutura", "design",
                "fronteiras", "contratos", "subsistemas", "planejamento", "camadas",
            ],
            applies_to_kinds=["OBJECTIVE", "SUBSYSTEM", "PLANNING"],
        ),
        SkillSpec(
            id="technical_writing",
            name="Documentação Técnica e Comunicação Estruturada",
            description="Elaboração de documentação hierárquica clara, diagramas, resumos de arquitetura e sincronização rigorosa com o código real.",
            activation_criteria=[
                "Tarefas de documentação, atualização de READMEs, resumos técnicos (Resume.md) ou guias",
            ],
            prohibited_criteria=[
                "Não documente comportamentos não implementados como se estivessem funcionais",
            ],
            required_tools=["file_read", "file_write", "file_edit", "shell_exec"],
            procedures=[
                "Identifique o público-alvo (engenheiros, operadores, agentes de IA)",
                "Estruture a informação com propósito, quando/onde roda, entradas e saídas explícitas",
                "Crie links relativos navegáveis para arquivos e símbolos de código",
                "Mantenha documentação e código 100% sincronizados",
            ],
            validation_rules=[
                "Todos os links internos e referências a arquivos são válidos",
                "Resumos de inventário passam nas checagens determinísticas do projeto",
            ],
            risk_factors=[
                "Documentação obsoleta ou divergente da implementação real",
            ],
            keywords=[
                "documentar", "documentação", "docs", "readme", "resume",
                "guia", "manual", "explicar", "diagrama", "especificação",
            ],
            applies_to_kinds=["MODEL_OPERATION", "CLOSING", "OBJECTIVE"],
        ),
    ]
