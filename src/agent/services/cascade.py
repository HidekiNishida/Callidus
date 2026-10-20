"""
Arquivo: src/agent/services/cascade.py
Nome: cascade.py
Propósito: remover em cascata uma linha e tudo que depende dela, guiado pelo grafo de chaves estrangeiras.
Responsabilidade: camada de infraestrutura — remoção ordenada e segura das linhas dependentes.
Componentes: delete_cascade.
Dependências: agent.persistence.models, sqlalchemy.
Observações: a ordem topológica garante que filhos sejam apagados antes dos pais.
"""
from __future__ import annotations

from collections import deque
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from agent.persistence.models import Base


def _children_map() -> dict[str, list[tuple[Any, str]]]:
    """Tabela pai → [(tabela filha, coluna filha)] segundo as chaves estrangeiras do modelo.

    `fk.column` é a coluna remota (no pai) e `fk.parent` é a coluna local (no filho) —
    a coluna local é a que precisa ser filtrada.
    """
    children: dict[str, list[tuple[Any, str]]] = {}
    for table in Base.metadata.sorted_tables:
        for fk in table.foreign_keys:
            children.setdefault(fk.column.table.name, []).append((table, fk.parent.name))
    return children


def _scope(session: Session, root_table: str, root_id: Any) -> dict[str, set]:
    """Conjunto de ids por tabela que descendem da linha raiz.

    Args:
        session: sessão usada nas consultas.
        root_table: tabela da linha raiz.
        root_id: identificador da linha raiz.

    Returns:
        Um dicionário de tabela para o conjunto de identificadores alcançados.
    """
    children = _children_map()
    scope: dict[str, set] = {root_table: {root_id}}
    queue: deque[tuple[str, set]] = deque([(root_table, {root_id})])
    while queue:
        parent_name, parent_ids = queue.popleft()
        for child_table, child_col in children.get(parent_name, []):
            if not parent_ids:
                continue
            pk = list(child_table.primary_key.columns)[0]
            stmt = select(pk).where(child_table.c[child_col].in_(parent_ids))
            ids = {value for value in session.scalars(stmt).all() if value is not None}
            if not ids:
                continue
            known = scope.setdefault(child_table.name, set())
            fresh = ids - known
            if not fresh:
                continue
            known |= fresh
            queue.append((child_table.name, fresh))
    return scope


def _deletion_order(scope: dict[str, set]) -> list[str]:
    """Ordem topológica: cada tabela é apagada antes das tabelas que ela referencia.

    Sem isso, apagar `operation_attempts` antes de `evidences` (que aponta para o
    attempt) viola a FOREIGN KEY.

    Args:
        scope: tabelas do escopo com seus identificadores.

    Returns:
        A lista de tabelas na ordem de remoção.
    """
    scoped = set(scope)
    edges: dict[str, set[str]] = {name: set() for name in scoped}
    indegree: dict[str, int] = {name: 0 for name in scoped}
    for table in Base.metadata.sorted_tables:
        if table.name not in scoped:
            continue
        for fk in table.foreign_keys:
            parent = fk.column.table.name
            if parent == table.name or parent not in scoped:
                continue
            if parent not in edges[table.name]:
                edges[table.name].add(parent)
                indegree[parent] += 1
    queue = deque(name for name in scoped if indegree[name] == 0)
    order: list[str] = []
    while queue:
        name = queue.popleft()
        order.append(name)
        for parent in edges[name]:
            indegree[parent] -= 1
            if indegree[parent] == 0:
                queue.append(parent)
    # Tabelas em ciclo (raro): entram no fim, na ordem inversa do escopo.
    leftovers = [name for name in scoped if name not in order]
    leftovers.sort(key=lambda name: -len(scope.get(name, ())))
    return order + leftovers


def delete_cascade(session: Session, root_table: str, root_id: Any) -> dict[str, int]:
    """Remove a linha e tudo que depende dela, na ordem segura (filhos antes dos pais).

    Usa o grafo de chaves estrangeiras do modelo, então tabelas novas entram na remoção
    sem precisar de lista manual. Devolve quantas linhas foram removidas por tabela.

    Args:
        session: sessão usada nas remoções.
        root_table: tabela da linha raiz.
        root_id: identificador da linha raiz.

    Returns:
        Um dicionário de tabela para a quantidade de linhas removidas.
    """
    scope = _scope(session, root_table, root_id)
    removed: dict[str, int] = {}
    for name in _deletion_order(scope):
        ids = scope.get(name) or set()
        if not ids:
            continue
        table = Base.metadata.tables[name]
        pk = list(table.primary_key.columns)[0]
        result = session.execute(delete(table).where(pk.in_(ids)))
        removed[name] = removed.get(name, 0) + (result.rowcount or 0)
    # As remoções são em lote: o mapa de identidade do ORM ainda guarda as linhas apagadas.
    # Solta só esses objetos (os demais continuam utilizáveis na sessão).
    for obj in list(session.identity_map.values()):
        if getattr(type(obj), "__tablename__", None) in removed:
            session.expunge(obj)
    return removed
