"""
Arquivo: tests/test_skills_authoring.py
Nome: test_skills_authoring.py
Propósito: verificar o ciclo de vida das skills autorais: criação, validação, teste, ativação, versão e rollback.
Responsabilidade: camada de testes — comportamento do repositório de skills e do serviço de autoria.
Componentes: SkillStore, SkillAuthoringService, validação, manifesto e catálogo em formato de pasta.
Dependências: agent.skills.authoring, agent.skills.catalog.loader, pytest.
Observações: os testes usam um repositório de skills temporário e nunca executam scripts externos.
"""
import json
from pathlib import Path

import pytest

from agent.skills.authoring import SkillAuthoringService, SkillStore, render_skill_md
from agent.skills.authoring.validator import validate_name, validate_skill
from agent.skills.catalog.loader import load_catalog
from agent.skills.discovery import SkillRegistry


@pytest.fixture()
def service(tmp_path) -> SkillAuthoringService:
    """Serviço de autoria sobre um repositório temporário.

    Args:
        tmp_path: pasta temporária do teste.

    Returns:
        O serviço pronto para uso.
    """
    return SkillAuthoringService(SkillStore(tmp_path / "skills"))


def test_nome_invalido_e_recusado():
    """Nomes fora do padrão são recusados com a explicação do formato."""
    assert validate_name("ok-name_1.2") is None
    assert validate_name("") is not None
    assert validate_name("Nome Com Espaço") is not None
    assert validate_name("../escape") is not None


def test_criacao_gera_skill_md_e_manifesto(service):
    """A criação escreve o contrato e o manifesto, e a skill nasce como rascunho."""
    out = service.create_draft(
        "revisar-diff",
        "Revisa um diff antes de commitá-lo",
        procedures=["Leia o diff", "Aponte riscos"],
        validation=["Riscos listados"],
    )
    assert out["success"] is True
    layout = service.store.path_of("revisar-diff")
    assert (layout / "SKILL.md").is_file()
    assert (layout / "manifest.json").is_file()
    manifest = service.store.read_manifest("revisar-diff")
    assert manifest["state"] == "draft"
    assert manifest["origin"] == "agent"
    assert manifest["history"][0]["action"] == "create"


def test_criacao_exige_nome_e_descricao(service):
    """Uma skill sem nome válido ou sem descrição não é criada."""
    assert service.create_draft("Nome Ruim", "descricao")["success"] is False
    assert service.create_draft("ok-name", "  ")["success"] is False


def test_validacao_aprova_uma_skill_bem_formada(service):
    """Uma skill com contrato completo passa na validação e avança de estado."""
    service.create_draft(
        "skill-valida",
        "Faz algo verificável",
        activation=["Quando o pedido bater"],
        procedures=["Passo 1"],
        validation=["O teste passou"],
    )
    result = service.validate("skill-valida")
    assert result["valid"] is True
    assert result["errors"] == []
    assert service.store.read_manifest("skill-valida")["state"] == "validated"


def test_validacao_reprova_arquivo_ausente(tmp_path):
    """Uma pasta sem SKILL.md é inválida."""
    folder = tmp_path / "sem-arquivo"
    folder.mkdir()
    result = validate_skill(folder)
    assert result.valid is False
    assert any("SKILL.md" in item for item in result.errors)


def test_validacao_reprova_arquivo_referenciado_inexistente(service):
    """Um arquivo listado no manifesto que não existe reprova a skill."""
    service.create_draft("skill-quebrada", "Faz algo")
    manifest = service.store.read_manifest("skill-quebrada")
    manifest["scripts"] = ["scripts/ausente.py"]
    service.store._write_manifest("skill-quebrada", manifest)  # noqa: SLF001 - teste do próprio pacote
    result = service.validate("skill-quebrada")
    assert result["valid"] is False
    assert any("ausente.py" in item for item in result["errors"])


def test_ativacao_exige_validacao(service):
    """Uma skill inválida não é ativada, e o erro traz a validação."""
    service.create_draft("skill-invalida", "x")
    manifest = service.store.read_manifest("skill-invalida")
    manifest["scripts"] = ["scripts/ausente.py"]
    service.store._write_manifest("skill-invalida", manifest)  # noqa: SLF001 - teste do próprio pacote
    out = service.store.activate("skill-invalida")
    assert out["success"] is False
    assert out["validation"]["errors"]


def test_ativacao_e_desativacao_mudam_o_estado(service):
    """Ativar aprova a skill; desativar a torna desabilitada sem apagar o conteúdo."""
    service.create_draft("skill-ciclo", "Faz algo", procedures=["Passo"])
    assert service.store.activate("skill-ciclo")["success"] is True
    assert service.store.get("skill-ciclo").state == "approved"
    assert service.store.deactivate("skill-ciclo")["success"] is True
    assert service.store.get("skill-ciclo").enabled is False
    assert (service.store.path_of("skill-ciclo") / "SKILL.md").is_file()


def test_atualizacao_guarda_a_versao_anterior(service, tmp_path):
    """A atualização arquiva a versão anterior e registra o histórico."""
    service.create_draft("skill-versao", "Primeira versão", procedures=["Passo 1"])
    service.store.activate("skill-versao")
    updated = tmp_path / "nova"
    updated.mkdir()
    (updated / "SKILL.md").write_text(
        render_skill_md("skill-versao", "Segunda versão", procedures=["Passo 2"]), encoding="utf-8"
    )
    out = service.store.update("skill-versao", updated, version="2.0.0")
    assert out["success"] is True
    assert Path(out["backup"]).is_dir()
    assert service.store.get("skill-versao").version == "2.0.0"
    assert any(item["action"] == "update" for item in service.store.read_manifest("skill-versao")["history"])


def test_rollback_restaura_a_versao_anterior(service, tmp_path):
    """O rollback devolve o conteúdo da versão arquivada."""
    service.create_draft("skill-rollback", "Primeira versão", procedures=["Passo 1"])
    service.store.activate("skill-rollback")
    first = (service.store.path_of("skill-rollback") / "SKILL.md").read_text(encoding="utf-8")
    updated = tmp_path / "nova"
    updated.mkdir()
    (updated / "SKILL.md").write_text(
        render_skill_md("skill-rollback", "Segunda versão", procedures=["Passo 2"]), encoding="utf-8"
    )
    service.store.update("skill-rollback", updated, version="2.0.0")
    assert service.store.rollback("skill-rollback")["success"] is True
    assert (service.store.path_of("skill-rollback") / "SKILL.md").read_text(encoding="utf-8") == first


def test_remocao_exige_confirmacao_e_guarda_copia(service):
    """A remoção é irreversível: ela exige confirmação e deixa uma cópia arquivada."""
    service.create_draft("skill-removivel", "Faz algo", procedures=["Passo"])
    refused = service.store.remove("skill-removivel")
    assert refused["success"] is False
    assert refused["confirm_required"] is True
    removed = service.store.remove("skill-removivel", confirm=True)
    assert removed["success"] is True
    assert Path(removed["backup"]).is_dir()
    assert service.store.get("skill-removivel") is None


def test_instalacao_copia_sem_executar_e_registra_proveniencia(service, tmp_path):
    """A instalação copia o conteúdo, registra a origem e não executa nada."""
    origin = tmp_path / "origem"
    (origin / "scripts").mkdir(parents=True)
    (origin / "SKILL.md").write_text(
        render_skill_md("skill-importada", "Vinda de fora", procedures=["Passo"]), encoding="utf-8"
    )
    (origin / "scripts" / "marca.txt").write_text("não deve rodar", encoding="utf-8")
    out = service.store.install(origin, origin="import", state="draft")
    assert out["success"] is True
    installed = service.store.get("skill-importada")
    assert installed.manifest["origin"] == "import"
    assert installed.manifest["history"][0]["action"] == "install"
    assert (service.store.path_of("skill-importada") / "scripts" / "marca.txt").is_file()


def test_instalacao_nao_sobrescreve_sem_forca(service, tmp_path):
    """Uma skill já instalada só é substituída com `force`."""
    origin = tmp_path / "origem"
    origin.mkdir()
    (origin / "SKILL.md").write_text(render_skill_md("skill-x", "x"), encoding="utf-8")
    assert service.store.install(origin)["success"] is True
    assert service.store.install(origin)["success"] is False
    assert service.store.install(origin, force=True)["success"] is True


def test_proposta_exige_justificativa_com_evidencia(service):
    """Uma proposta sem justificativa não é registrada."""
    service.create_draft("skill-proposta", "Faz algo", procedures=["Passo"])
    assert service.propose("skill-proposta", "Título", "")["success"] is False
    out = service.propose(
        "skill-proposta",
        "Incluir passo de revisão",
        "Em três execuções o agente esqueceu de revisar o diff",
        evidence=["run-1", "run-2"],
    )
    assert out["success"] is True
    assert out["proposal"]["state"] == "proposed"
    assert len(service.list_proposals(skill="skill-proposta")) == 1
    resolved = service.resolve_proposal(out["proposal"]["id"], accept=True, note="boa ideia")
    assert resolved["proposal"]["state"] == "accepted"


def test_teste_de_skill_sem_testes_e_declarado_como_nao_aplicavel(service):
    """Uma skill sem pasta de testes tem o status explícito, não um sucesso falso."""
    service.create_draft("skill-sem-teste", "Faz algo", procedures=["Passo"])
    result = service.test("skill-sem-teste")
    assert result["success"] is True
    assert result["status"] == "not_applicable"


def test_teste_de_skill_com_testes_roda_em_subprocesso(service):
    """Os testes da skill rodam em subprocesso e o resultado é objetivo."""
    service.create_draft("skill-com-teste", "Faz algo", procedures=["Passo"])
    tests = service.store.path_of("skill-com-teste") / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    (tests / "test_skill.py").write_text(
        "def test_exemplo():\n    assert True\n", encoding="utf-8"
    )
    result = service.test("skill-com-teste")
    assert result["status"] == "passed"
    assert result["exit_code"] == 0


def test_catalogo_carrega_skill_em_formato_de_pasta(tmp_path):
    """O catálogo reconhece a pasta de skill e lê o manifesto dela."""
    folder = tmp_path / "skills" / "minha-skill"
    (folder / "scripts").mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        render_skill_md("minha-skill", "Competência nova", procedures=["Passo"]), encoding="utf-8"
    )
    (folder / "manifest.json").write_text(
        json.dumps({"id": "minha-skill", "version": "1.2.0", "state": "approved", "origin": "agent"}),
        encoding="utf-8",
    )
    (folder / "scripts" / "util.py").write_text("print('oi')\n", encoding="utf-8")
    skills = load_catalog(tmp_path / "skills")
    assert len(skills) == 1
    assert skills[0].id == "minha-skill"
    assert skills[0].version == "1.2.0"
    assert skills[0].state == "approved"
    assert skills[0].scripts == ["scripts/util.py"]


def test_registro_carrega_a_skill_do_projeto(tmp_path):
    """O registro de skills lê a pasta de skills do projeto."""
    folder = tmp_path / "skills" / "do-projeto"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        render_skill_md("do-projeto", "Competência do projeto", procedures=["Passo"]), encoding="utf-8"
    )
    registry = SkillRegistry(project_root=tmp_path)
    assert registry.get("do-projeto") is not None
