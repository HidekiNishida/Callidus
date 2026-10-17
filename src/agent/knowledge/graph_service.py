# src/agent/knowledge/graph_service.py — grafo persistente do projeto
from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from agent.knowledge.indexer import scan_project
from agent.persistence.models import KgEdgeModel, KgNodeModel


class KnowledgeGraphService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def reindex(self, project_id: uuid.UUID, root_path: str) -> dict:
        nodes, edges = scan_project(root_path)
        self._session.execute(delete(KgEdgeModel).where(KgEdgeModel.project_id == project_id))
        self._session.execute(delete(KgNodeModel).where(KgNodeModel.project_id == project_id))
        ref_to_id: dict[str, uuid.UUID] = {}
        for n in nodes:
            row = KgNodeModel(
                project_id=project_id,
                kind=n["kind"],
                ref=n["ref"],
                label=n.get("label", n["ref"]),
                meta_json={k: v for k, v in n.items() if k not in {"kind", "ref", "label"}},
            )
            self._session.add(row)
            self._session.flush()
            ref_to_id[n["ref"]] = row.id

        edge_count = 0
        for e in edges:
            src = ref_to_id.get(e["src_ref"])
            dst = ref_to_id.get(e["dst_ref"])
            if not src or not dst:
                continue
            self._session.add(
                KgEdgeModel(project_id=project_id, src_id=src, dst_id=dst, rel=e["rel"])
            )
            edge_count += 1
        return {"nodes": len(nodes), "edges": edge_count}

    def neighbors(self, project_id: uuid.UUID, ref: str, depth: int = 1) -> list[dict]:
        stmt = select(KgNodeModel).where(KgNodeModel.project_id == project_id, KgNodeModel.ref == ref)
        start = self._session.scalar(stmt)
        if start is None:
            return []
        seen = {start.id}
        frontier = {start.id}
        out: list[dict] = [self._node_dict(start)]
        for _ in range(depth):
            nxt: set[uuid.UUID] = set()
            for nid in frontier:
                for edge in self._session.scalars(
                    select(KgEdgeModel).where(
                        KgEdgeModel.project_id == project_id,
                        (KgEdgeModel.src_id == nid) | (KgEdgeModel.dst_id == nid),
                    )
                ):
                    other = edge.dst_id if edge.src_id == nid else edge.src_id
                    if other in seen:
                        continue
                    seen.add(other)
                    nxt.add(other)
                    node = self._session.get(KgNodeModel, other)
                    if node:
                        d = self._node_dict(node)
                        d["rel"] = edge.rel
                        out.append(d)
            frontier = nxt
        return out

    def search(self, project_id: uuid.UUID, query: str, limit: int = 20) -> list[dict]:
        q = query.lower()
        stmt = select(KgNodeModel).where(KgNodeModel.project_id == project_id).limit(500)
        rows = list(self._session.scalars(stmt).all())
        hits = [self._node_dict(r) for r in rows if q in r.ref.lower() or q in r.label.lower()]
        return hits[:limit]

    def touch_file(self, project_id: uuid.UUID, root_path: str, rel_path: str) -> None:
        from agent.knowledge.indexer import _py_symbols

        root = Path(root_path).expanduser().resolve()
        path = root / rel_path
        if not path.is_file() or path.suffix != ".py":
            return
        file_ref = str(path.relative_to(root))
        self._upsert_node(project_id, {"kind": "file", "ref": file_ref, "label": path.name})
        for sym in _py_symbols(path, root):
            if sym["kind"] in {"function", "class"}:
                self._upsert_node(project_id, sym)

    def _upsert_node(self, project_id: uuid.UUID, spec: dict) -> KgNodeModel:
        stmt = select(KgNodeModel).where(
            KgNodeModel.project_id == project_id,
            KgNodeModel.kind == spec["kind"],
            KgNodeModel.ref == spec["ref"],
        )
        row = self._session.scalar(stmt)
        if row is None:
            row = KgNodeModel(
                project_id=project_id,
                kind=spec["kind"],
                ref=spec["ref"],
                label=spec.get("label", spec["ref"]),
                meta_json={k: v for k, v in spec.items() if k not in {"kind", "ref", "label"}},
            )
            self._session.add(row)
            self._session.flush()
        return row

    @staticmethod
    def _node_dict(n: KgNodeModel) -> dict:
        return {"id": str(n.id), "kind": n.kind, "ref": n.ref, "label": n.label, "meta": n.meta_json}
