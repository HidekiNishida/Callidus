# src/agent/observability/bus.py — barramento em memória: sequência por run, anel recente, assinantes e operações ativas
from __future__ import annotations

import asyncio
import copy
import threading
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

RESYNC = "stream.resync"

_OUTPUT_KEEP = 200_000
_OPERATION_TAIL = 20_000


@dataclass(eq=False)
class Subscription:
    run_id: str
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue
    closed: bool = False
    dropped: int = 0


@dataclass
class _RunState:
    seq: int = 0
    ring: deque = field(default_factory=deque)
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    operations: dict[str, dict[str, Any]] = field(default_factory=dict)
    published: int = 0
    ephemeral: int = 0


def _append(current: str, text: str, keep: int, *, tail: bool) -> str:
    joined = current + text
    if len(joined) <= keep:
        return joined
    return joined[-keep:] if tail else joined[:keep]


class EventBus:
    """Estado volátil do processo. Os fatos persistidos ficam em `event_logs`; aqui só o que ajuda a entregar
    rápido (anel com os últimos eventos, inclusive fragmentos) e o texto parcial do que ainda está rodando."""

    def __init__(self, *, ring_size: int = 3_000, queue_size: int = 1_000, max_runs: int = 64) -> None:
        self._lock = threading.RLock()
        self._runs: OrderedDict[str, _RunState] = OrderedDict()
        self._subs: dict[str, set[Subscription]] = {}
        self._steps: dict[str, int] = {}
        self.ring_size = ring_size
        self.queue_size = queue_size
        self.max_runs = max_runs

    def _state(self, run_id: str) -> _RunState | None:
        st = self._runs.get(run_id)
        if st is not None:
            self._runs.move_to_end(run_id)
        return st

    def _ensure(self, run_id: str, initial: Callable[[], int]) -> _RunState:
        st = self._state(run_id)
        if st is None:
            st = _RunState(seq=int(initial() or 0), ring=deque(maxlen=self.ring_size))
            self._runs[run_id] = st
            while len(self._runs) > self.max_runs:
                old, _ = next(iter(self._runs.items()))
                if self._subs.get(old):
                    self._runs.move_to_end(old)
                    break
                self._runs.popitem(last=False)
        return st

    def allocate_seq(self, run_id: str, initial: Callable[[], int]) -> int:
        """Próximo número da run. `initial` lê o maior `seq` gravado na primeira vez que a run aparece no processo."""
        with self._lock:
            st = self._ensure(run_id, initial)
            st.seq += 1
            return st.seq

    def last_seq(self, run_id: str) -> int | None:
        with self._lock:
            st = self._runs.get(run_id)
            return None if st is None else st.seq

    def publish(self, env: dict[str, Any]) -> None:
        run_id = env["run_id"]
        with self._lock:
            st = self._state(run_id)
            if st is not None:
                st.ring.append(env)
                st.published += 1
                if not env.get("persisted", True):
                    st.ephemeral += 1
                self._track(st, env)
            subs = list(self._subs.get(run_id, ()))
        for sub in subs:
            try:
                sub.loop.call_soon_threadsafe(self._deliver, sub, env)
            except RuntimeError:
                self.unsubscribe(sub)

    def _deliver(self, sub: Subscription, env: dict[str, Any]) -> None:
        if sub.closed:
            return
        if sub.queue.full():
            # Assinante lento: descarta o que estava na fila e pede ressincronização pelo banco.
            sub.dropped += sub.queue.qsize()
            while not sub.queue.empty():
                sub.queue.get_nowait()
            sub.queue.put_nowait({"type": RESYNC, "run_id": sub.run_id})
            return
        sub.queue.put_nowait(env)

    def subscribe(self, run_id: str, loop: asyncio.AbstractEventLoop | None = None) -> Subscription:
        sub = Subscription(run_id=run_id, loop=loop or asyncio.get_running_loop(), queue=asyncio.Queue(self.queue_size))
        with self._lock:
            self._subs.setdefault(run_id, set()).add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        sub.closed = True
        with self._lock:
            subs = self._subs.get(sub.run_id)
            if subs is not None:
                subs.discard(sub)
                if not subs:
                    self._subs.pop(sub.run_id, None)

    def subscriber_count(self, run_id: str | None = None) -> int:
        with self._lock:
            if run_id is not None:
                return len(self._subs.get(run_id, ()))
            return sum(len(s) for s in self._subs.values())

    def recent(self, run_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            st = self._runs.get(run_id)
            if st is None:
                return []
            return [e for e in st.ring if e["seq"] > after_seq]

    def live(self, run_id: str) -> dict[str, Any]:
        """Saídas do modelo e operações ainda abertas, com o texto parcial acumulado."""
        with self._lock:
            st = self._runs.get(run_id)
            if st is None:
                return {"outputs": [], "operations": [], "seq": None, "stats": {}}
            return {
                "outputs": copy.deepcopy(list(st.outputs.values())),
                "operations": copy.deepcopy(list(st.operations.values())),
                "seq": st.seq,
                "stats": {"published": st.published, "ephemeral": st.ephemeral},
            }

    def step_started(self, run_id: str) -> None:
        with self._lock:
            self._steps[run_id] = self._steps.get(run_id, 0) + 1

    def step_finished(self, run_id: str) -> None:
        with self._lock:
            left = self._steps.get(run_id, 0) - 1
            if left > 0:
                self._steps[run_id] = left
            else:
                self._steps.pop(run_id, None)

    def active_steps(self, run_id: str) -> int:
        """Passos do orquestrador rodando agora neste processo (zero depois de um reinício)."""
        with self._lock:
            return self._steps.get(run_id, 0)

    def reset(self) -> None:
        with self._lock:
            self._steps.clear()
            self._runs.clear()
            for subs in self._subs.values():
                for sub in subs:
                    sub.closed = True
            self._subs.clear()

    @staticmethod
    def _track(st: _RunState, env: dict[str, Any]) -> None:
        t = env["type"]
        d = env.get("data") or {}
        if t == "agent.started":
            st.outputs[d["output_id"]] = {
                "output_id": d["output_id"],
                "task_id": env.get("task_id"),
                "agent": env.get("agent"),
                "provider": d.get("provider"),
                "model": d.get("model"),
                "streaming": d.get("streaming"),
                "purpose": d.get("purpose"),
                "status": "waiting",
                "text": "",
                "started_at": env.get("ts"),
                "seq": env["seq"],
            }
        elif t == "agent.status":
            out = st.outputs.get(d["output_id"])
            if out is not None:
                out["status"] = d["status"]
        elif t == "agent.output.delta":
            out = st.outputs.get(d["output_id"])
            if out is not None:
                out["text"] = _append(out["text"], d.get("text", ""), _OUTPUT_KEEP, tail=False)
                out["status"] = "streaming"
                out["seq"] = env["seq"]
        elif t in ("agent.output.completed", "agent.output.failed"):
            st.outputs.pop(d.get("output_id"), None)
        elif t in ("tool.started", "command.started", "test.started"):
            kind = t.split(".", 1)[0]
            st.operations[f"{kind}:{d['call_id']}"] = {
                "kind": kind,
                "call_id": d["call_id"],
                "task_id": env.get("task_id"),
                "tool": d.get("tool"),
                "command": d.get("command"),
                "started_at": env.get("ts"),
                "output": "",
                "seq": env["seq"],
            }
        elif t in ("tool.output", "command.output", "test.output"):
            op = st.operations.get(f"{t.split('.', 1)[0]}:{d['call_id']}")
            if op is not None:
                op["output"] = _append(op["output"], d.get("text", ""), _OPERATION_TAIL, tail=True)
                op["seq"] = env["seq"]
        elif t.split(".", 1)[0] in ("tool", "command", "test") and t.endswith((".completed", ".failed")):
            st.operations.pop(f"{t.split('.', 1)[0]}:{d.get('call_id')}", None)
        elif t in ("run.completed", "run.failed", "run.cancelled", "run.paused"):
            st.outputs.clear()
            st.operations.clear()


_BUS: EventBus | None = None
_BUS_LOCK = threading.Lock()


def get_bus() -> EventBus:
    global _BUS
    if _BUS is None:
        with _BUS_LOCK:
            if _BUS is None:
                from agent.config import get_settings

                s = get_settings()
                _BUS = EventBus(ring_size=s.stream_ring_size, queue_size=s.stream_subscriber_queue)
    return _BUS
