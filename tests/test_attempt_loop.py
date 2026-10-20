"""
Arquivo: tests/test_attempt_loop.py
Nome: test_attempt_loop.py
Propósito: Verificar a detecção de saída repetida no laço de tentativas.
Responsabilidade: camada de testes — impressão digital da resposta e detecção de repetição na janela configurada.
Componentes: detecção de saída repetida entre as últimas tentativas.
Dependências: agent.services.attempt_service e uma sessão falsa de banco.
Observações: nenhum banco real: a detecção é exercitada com uma sessão que devolve respostas repetidas.
"""

import uuid

from agent.services.attempt_service import AttemptService


def test_repeated_output_detected():
    """Três respostas idênticas na janela fazem o laço detectar a repetição."""
    class FakeSession:
        """Sessão falsa que devolve sempre as mesmas respostas, simulando saída repetida."""
        def scalars(self, _stmt):
            """Ignora a consulta e devolve um resultado com três respostas idênticas."""
            class R:
                """Resultado falso que entrega a lista fixa de respostas."""
                def all(inner_self):
                    """Devolve as três respostas idênticas que simulam a repetição."""
                    return [
                        type("A", (), {"response_json": {"x": 1}, "error_message": None})(),
                        type("A", (), {"response_json": {"x": 1}, "error_message": None})(),
                        type("A", (), {"response_json": {"x": 1}, "error_message": None})(),
                    ]

            return R()

    svc = AttemptService(FakeSession())  # type: ignore[arg-type]
    fp = AttemptService.fingerprint({"x": 1})
    assert svc.repeated_output_detected(uuid.uuid4(), fp, window=3)
