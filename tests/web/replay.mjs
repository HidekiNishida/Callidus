// Passa uma foto do servidor e as mensagens SSE recebidas pelo mesmo redutor da interface e imprime o estado final.
// Entrada (stdin): {"snapshot": {...}, "messages": [{"event": null|"live"|"resync"|"end"|"rotate", "data": {...}}]}
import {
  applyEvent,
  applyLive,
  buildTree,
  createState,
  markConnection,
  markResync,
  verificationList,
} from "../../web/static/assets/observe-core.js";

const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const { snapshot, messages } = JSON.parse(Buffer.concat(chunks).toString("utf8"));

const state = createState(snapshot);
for (const msg of messages) {
  if (!msg.event) applyEvent(state, msg.data);
  else if (msg.event === "live") applyLive(state, msg.data);
  else if (msg.event === "resync") markResync(state);
  else if (msg.event === "end") markConnection(state, "ended");
}

const tree = buildTree(state);
process.stdout.write(
  JSON.stringify({
    header: { status: state.header.status, mode: state.header.mode, progress: state.header.progress },
    ended: state.ended,
    connection: state.connection,
    lastSeq: state.lastSeq,
    tasks: Object.fromEntries([...state.tasks.values()].map((t) => [t.id, { status: t.status, interrupted: Boolean(t.interrupted), parent_id: t.parent_id }])),
    tree: tree.map((n) => ({ id: n.task.id, done: n.done, total: n.total, children: n.children.length })),
    outputs: [...state.outputs.values()].map((o) => ({ status: o.status, text: o.text, streaming: o.streaming, gap: o.gap })),
    ops: [...state.ops.values()].map((o) => ({ kind: o.kind, status: o.status, tool: o.tool, command: o.command, exit_code: o.exit_code, counts: o.counts })),
    files: state.files.map((f) => ({ type: f.type, path: f.path, sensitive: f.sensitive, hasDiff: Boolean(f.diff) })),
    verifications: verificationList(state, {}).map((v) => ({ status: v.status, verifier: v.verifier })),
    metrics: { duplicates: state.metrics.duplicates, stale: state.metrics.stale, persisted: state.metrics.persisted, ephemeral: state.metrics.ephemeral },
  }),
);
