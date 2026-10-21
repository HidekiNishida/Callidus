"""
Arquivo: src/agent/skills/authoring/service.py
Nome: service.py
Propósito: criar skills a partir de pedidos, propor melhorias e testar skills antes de usá-las.
Responsabilidade: camada de aplicação — fluxo de autoria, do rascunho à skill aprovada.
Componentes: SkillAuthoringService, Proposal.
Dependências: agent.skills.authoring.layout, agent.skills.authoring.store, agent.skills.authoring.validator.
Observações: uma resposta do modelo nunca vira conhecimento permanente sem passar por validação e teste.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

from agent.skills.authoring.layout import (
    SkillLayout,
    default_manifest,
    now_iso,
    render_manifest,
    render_skill_md,
)
from agent.skills.authoring.store import SkillStore
from agent.skills.authoring.validator import validate_name, validate_skill

#: Estados possíveis de uma proposta de melhoria.
PROPOSAL_STATES = ("proposed", "accepted", "rejected", "implemented")


@dataclass
class Proposal:
    """Uma proposta de melhoria de skill, vinda de uma execução real.

    Atributos:
        id: identificador da proposta.
        skill: nome da skill que a proposta afeta.
        title: resumo curto da proposta.
        rationale: evidência que motivou a proposta.
        changes: alterações propostas, em texto.
        state: estado da proposta.
        created_at: instante de criação.
        evidence: referências de execuções que dão suporte à proposta.
    """

    id: str
    skill: str
    title: str
    rationale: str
    changes: str = ""
    state: str = "proposed"
    created_at: str = field(default_factory=now_iso)
    evidence: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Representação serializável da proposta.

        Returns:
            Um dicionário com os campos da proposta.
        """
        return {
            "id": self.id,
            "skill": self.skill,
            "title": self.title,
            "rationale": self.rationale,
            "changes": self.changes,
            "state": self.state,
            "created_at": self.created_at,
            "evidence": self.evidence,
        }


class SkillAuthoringService:
    """Fluxo de autoria de skills sobre um repositório de skills.

    O serviço mantém a separação entre as fases: **criar** gera um rascunho, **validar**
    confere o contrato, **testar** roda os testes da skill, **aprovar** habilita o uso e
    **rejeitar** encerra a proposta. Cada fase é um passo explícito e auditável.

    Atributos:
        store: repositório onde as skills vivem.
    """

    def __init__(self, store: SkillStore) -> None:
        """Cria o serviço.

        Args:
            store: repositório de skills.
        """
        self.store = store
        self._proposals_dir = store.root / ".proposals"
        self._proposals_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ criação

    def create_draft(
        self,
        name: str,
        description: str,
        *,
        activation: list[str] | None = None,
        prohibited: list[str] | None = None,
        tools: list[str] | None = None,
        procedures: list[str] | None = None,
        validation: list[str] | None = None,
        risks: list[str] | None = None,
        prerequisites: list[str] | None = None,
        requires_binaries: list[str] | None = None,
        version: str = "1.0.0",
    ) -> dict[str, Any]:
        """Cria uma skill em estado de rascunho.

        A skill criada **não** é ativada: ela precisa passar por validação e teste.

        Args:
            name: nome da skill (minúsculas, hífens e sublinhados).
            description: descrição objetiva da competência.
            activation: critérios de utilização.
            prohibited: situações proibidas.
            tools: ferramentas permitidas.
            procedures: passos a seguir.
            validation: critérios de conclusão.
            risks: riscos a controlar.
            prerequisites: pré-requisitos de ambiente.
            requires_binaries: executáveis necessários.
            version: versão inicial.

        Returns:
            Um dicionário com o resultado e a skill criada.
        """
        name_error = validate_name(name)
        if name_error:
            return {"success": False, "error": name_error}
        if not description or not description.strip():
            return {"success": False, "error": "a descrição é obrigatória"}
        if self.store.path_of(name).exists():
            return {"success": False, "error": f"a skill '{name}' já existe"}
        layout = SkillLayout.of(self.store.path_of(name)).ensure()
        layout.skill_md.write_text(
            render_skill_md(
                name,
                description,
                version=version,
                activation=activation,
                prohibited=prohibited,
                tools=tools,
                procedures=procedures,
                validation=validation,
                risks=risks,
                prerequisites=prerequisites,
            ),
            encoding="utf-8",
        )
        manifest = default_manifest(
            name,
            version=version,
            description=description,
            origin="agent",
            state="draft",
            permissions=[],
            requires_tools=list(tools or []),
            requires_binaries=list(requires_binaries or []),
        )
        manifest["history"] = [
            {
                "version": version,
                "at": now_iso(),
                "action": "create",
                "digest": "",
                "note": "rascunho criado pelo agente",
            }
        ]
        layout.manifest.write_text(render_manifest(manifest), encoding="utf-8")
        return {"success": True, "skill": (self.store.get(name).as_dict() if self.store.get(name) else {})}

    # ------------------------------------------------------------ validação

    def validate(self, name: str) -> dict[str, Any]:
        """Valida uma skill e avança o estado quando ela passa.

        Args:
            name: nome da skill.

        Returns:
            Um dicionário com o resultado da validação.
        """
        result = validate_skill(self.store.path_of(name))
        if result.valid:
            manifest = self.store.read_manifest(name)
            if manifest.get("state") == "draft":
                self.store.set_state(name, "validated", note="contrato conferido")
        return {"success": True, **result.as_dict()}

    # ------------------------------------------------------------ testes

    def test(self, name: str, *, timeout: float = 120.0) -> dict[str, Any]:
        """Executa os testes da skill, quando ela tem pasta `tests`.

        Os testes rodam em subprocesso, com o interpretador do Callidus e a pasta da
        skill como diretório de trabalho. Uma skill sem testes é considerada testada
        apenas no contrato — o resultado diz isso explicitamente.

        Args:
            name: nome da skill.
            timeout: tempo limite da execução.

        Returns:
            Um dicionário com o resultado do teste.
        """
        installed = self.store.get(name)
        if installed is None:
            return {"success": False, "error": f"skill não instalada: {name}"}
        layout = SkillLayout.of(self.store.path_of(name))
        if not layout.tests.is_dir() or not any(layout.tests.glob("test_*.py")):
            return {
                "success": True,
                "status": "not_applicable",
                "reason": "a skill não tem testes em tests/test_*.py",
                "skill": installed.as_dict(),
            }
        command = [sys.executable, "-m", "pytest", str(layout.tests), "-q"]
        try:
            completed = subprocess.run(
                command,
                cwd=str(layout.root),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"success": False, "status": "timeout", "error": f"tempo limite excedido ({timeout:.0f}s)"}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"success": False, "status": "error", "error": f"falha ao rodar os testes: {exc}"}
        output = (completed.stdout or "") + (completed.stderr or "")
        return {
            "success": completed.returncode == 0,
            "status": "passed" if completed.returncode == 0 else "failed",
            "exit_code": completed.returncode,
            "output": output[:8000],
            "skill": installed.as_dict(),
        }

    # ------------------------------------------------------------ propostas

    def propose(
        self,
        skill: str,
        title: str,
        rationale: str,
        *,
        changes: str = "",
        evidence: list[str] | None = None,
    ) -> dict[str, Any]:
        """Registra uma proposta de melhoria vinda de uma execução.

        A proposta não altera a skill: ela fica registrada até ser aceita.

        Args:
            skill: nome da skill afetada.
            title: resumo da proposta.
            rationale: evidência que motivou a proposta.
            changes: alterações propostas, em texto.
            evidence: referências de execuções que dão suporte à proposta.

        Returns:
            Um dicionário com a proposta registrada.
        """
        if not title or not title.strip():
            return {"success": False, "error": "a proposta precisa de um título"}
        if not rationale or not rationale.strip():
            return {"success": False, "error": "a proposta precisa de uma justificativa com evidência"}
        identifier = f"{skill}-{len(self.list_proposals()) + 1}"
        proposal = Proposal(
            id=identifier,
            skill=skill,
            title=title,
            rationale=rationale,
            changes=changes,
            evidence=list(evidence or []),
        )
        path = self._proposals_dir / f"{identifier}.json"
        path.write_text(json.dumps(proposal.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"success": True, "proposal": proposal.as_dict()}

    def list_proposals(self, *, skill: str | None = None) -> list[dict[str, Any]]:
        """Lista as propostas registradas.

        Args:
            skill: filtra pelas propostas de uma skill específica.

        Returns:
            A lista de propostas.
        """
        found: list[dict[str, Any]] = []
        for path in sorted(self._proposals_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            if skill and data.get("skill") != skill:
                continue
            found.append(data)
        return found

    def resolve_proposal(self, proposal_id: str, *, accept: bool, note: str = "") -> dict[str, Any]:
        """Aceita ou rejeita uma proposta.

        Aceitar não aplica a alteração automaticamente: a skill entra em `validated`
        quando passa no contrato, e a edição do conteúdo continua sendo um passo
        explícito.

        Args:
            proposal_id: identificador da proposta.
            accept: quando `True`, a proposta é aceita.
            note: observação registrada.

        Returns:
            Um dicionário com o resultado.
        """
        path = self._proposals_dir / f"{proposal_id}.json"
        if not path.is_file():
            return {"success": False, "error": f"proposta desconhecida: {proposal_id}"}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {"success": False, "error": f"proposta ilegível: {exc}"}
        data["state"] = "accepted" if accept else "rejected"
        data["resolved_at"] = now_iso()
        data["note"] = note
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"success": True, "proposal": data}
