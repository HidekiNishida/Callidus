/**
 * Arquivo: web/static/assets/app/components/intelligence-organization.js
 * Nome: intelligence-organization.js
 * Propósito: aba Organização da Inteligência — equipes e papéis, propriedade dos módulos, quadro de tarefas com etapa, responsável, revisor e portões, indicadores de entrega e revisão independente.
 * Responsabilidade: frontend/componente — consome `/organization`, `/projects/{id}/board`, `/tasks/{id}/gates`, `/tasks/{id}/reviews` e `/api/intelligence/metrics/delivery`.
 * Componentes: IntelligenceOrganization, GATE_LABEL, STAGE_LABEL, formatMetric.
 * Dependências: `../store.js` (workspaceId, toast), `../api.js` (requisições HTTP), `../ui.js` (ícones).
 * Observações: estados loading/empty/error; a interface não calcula portão nenhum — mostra o que a API devolve.
 */
import { workspaceId, toast } from "../store.js";
import { api } from "../api.js";
import { icon } from "../ui.js";

/** Nome legível dos estados de portão. */
export const GATE_LABEL = {
  passed: "aprovado",
  failed: "reprovado",
  pending: "pendente",
  not_applicable: "não se aplica",
};

/** Nome legível das etapas do fluxo de trabalho. */
export const STAGE_LABEL = {
  INBOX: "Entrada",
  ANALYSIS: "Análise",
  ARCHITECTURE_REVIEW: "Revisão de arquitetura",
  READY: "Pronta",
  IN_PROGRESS: "Em andamento",
  IMPLEMENTATION_COMPLETE: "Implementada",
  QA_REVIEW: "Em QA",
  TECHNICAL_AUDIT: "Auditoria técnica",
  READY_FOR_INTEGRATION: "Pronta para integrar",
  INTEGRATED: "Integrada",
  DONE: "Concluída",
  REWORK: "Retrabalho",
  BLOCKED: "Bloqueada",
  FAILED: "Falhou",
  CANCELLED: "Cancelada",
};

/**
 * Formata um indicador de entrega sem inventar valor: indisponível aparece como tal.
 *
 * @param {object} metric indicador devolvido pela API.
 * @returns {string} texto curto para a tabela.
 */
export function formatMetric(metric) {
  if (!metric || metric.kind === "unavailable") return "indisponível";
  if (metric.kind === "elsewhere") return "ver Consumo de contexto";
  if (metric.unit === "ratio") {
    return `${(metric.value * 100).toFixed(1)}% (${metric.numerator}/${metric.denominator})`;
  }
  if (metric.unit === "seconds") {
    const p = (v) => (v == null ? "—" : `${Math.round(v)}s`);
    return `P50 ${p(metric.p50)} · P95 ${p(metric.p95)} · P99 ${p(metric.p99)} (n=${metric.count})`;
  }
  return metric.value == null ? "indisponível" : String(metric.value);
}

export const IntelligenceOrganization = {
  name: "IntelligenceOrganization",
  setup() {
    const loading = Vue.ref(false);
    const error = Vue.ref(null);
    const directory = Vue.ref(null);
    const board = Vue.ref([]);
    const metrics = Vue.ref(null);
    const selected = Vue.ref(null);
    const detail = Vue.ref(null);
    const handoff = Vue.ref(null);
    const review = Vue.reactive({ role: "qa_engineer", decision: "approved", reason: "" });

    const roleName = (id) => directory.value?.roles.find((r) => r.id === id)?.name || id || "—";
    const teamName = (id) => directory.value?.teams.find((t) => t.id === id)?.name || id || "—";
    const teamsByOffice = Vue.computed(() => {
      const dir = directory.value;
      if (!dir) return [];
      return dir.offices
        .map((office) => ({
          ...office,
          teams: dir.teams
            .filter((t) => t.office === office.id)
            .map((t) => ({ ...t, roles: dir.roles.filter((r) => r.team === t.id) })),
        }))
        .filter((o) => o.teams.length);
    });

    async function load() {
      loading.value = true;
      error.value = null;
      try {
        const project = workspaceId();
        const query = project ? `?project_id=${encodeURIComponent(project)}` : "";
        const [dir, rows, delivery] = await Promise.all([
          api(`/organization${query}`),
          project ? api(`/projects/${encodeURIComponent(project)}/board`).catch(() => []) : Promise.resolve([]),
          api(`/api/intelligence/metrics/delivery${query}`).catch(() => null),
        ]);
        directory.value = dir;
        board.value = rows || [];
        metrics.value = delivery;
      } catch (err) {
        error.value = err.message || "Falha ao carregar a organização";
      } finally {
        loading.value = false;
      }
    }

    async function open(row) {
      selected.value = row;
      detail.value = null;
      handoff.value = null;
      try {
        const [gates, transfer] = await Promise.all([
          api(`/tasks/${encodeURIComponent(row.task_id)}/gates`),
          api(`/tasks/${encodeURIComponent(row.task_id)}/handoff`),
        ]);
        detail.value = gates;
        handoff.value = transfer;
      } catch (err) {
        toast(err.message || "Falha ao carregar os portões e o handoff", "error");
      }
    }

    async function submitReview() {
      if (!selected.value) return;
      try {
        await api(`/tasks/${encodeURIComponent(selected.value.task_id)}/reviews`, {
          method: "POST",
          body: JSON.stringify({ role: review.role, decision: review.decision, reason: review.reason }),
        });
        toast("Revisão registrada", "ok");
        review.reason = "";
        await open(selected.value);
        await load();
      } catch (err) {
        toast(err.message || "Revisão recusada", "error");
      }
    }

    Vue.onMounted(load);
    // O quadro é do projeto aberto: trocar de projeto recarrega e fecha o detalhe anterior.
    Vue.watch(() => workspaceId(), () => {
      selected.value = null;
      detail.value = null;
      handoff.value = null;
      load();
    });

    return {
      loading, error, directory, board, metrics, selected, detail, handoff, review,
      teamsByOffice, roleName, teamName, load, open, submitReview,
      icon, GATE_LABEL, STAGE_LABEL, formatMetric,
    };
  },
  template: `
    <div class="intelligence-page org-page">
      <div class="page-header">
        <h1>Organização</h1>
        <p class="page-sub">Quem é dono de cada módulo, quem executa, quem revisa e em que portão cada tarefa está.</p>
        <div class="page-actions">
          <button type="button" class="btn-primary" @click="load" :disabled="loading" aria-label="Atualizar" v-html="icon('refresh', 16)"></button>
          <span v-if="error" class="muted small" style="color: var(--danger)">{{ error }}</span>
        </div>
      </div>

      <div v-if="loading" class="skeleton-container">
        <div class="skeleton-line" style="width: 90%"></div>
        <div class="skeleton-line" style="width: 60%"></div>
      </div>

      <div v-if="!loading && !error && directory" class="org-content">
        <div class="table-panel">
          <h3>Quadro de tarefas</h3>
          <div class="table-scroll" v-if="board.length">
            <table class="data-table">
              <thead>
                <tr><th>Tarefa</th><th>Etapa</th><th>Responsável</th><th>Revisor</th><th>Risco</th><th>Portões</th></tr>
              </thead>
              <tbody>
                <tr v-for="row in board" :key="row.task_id" class="org-row" :class="{ active: selected && selected.task_id === row.task_id }"
                    tabindex="0" @click="open(row)" @keydown.enter="open(row)">
                  <td>{{ row.title }}</td>
                  <td><span class="status-badge" :class="'stage-' + row.stage">{{ STAGE_LABEL[row.stage] || row.stage }}</span></td>
                  <td>{{ roleName(row.role) }}<div class="muted small">{{ teamName(row.team) }}</div></td>
                  <td>{{ roleName(row.reviewer_role) }}</td>
                  <td>{{ row.risk || '—' }}</td>
                  <td class="gate-chips">
                    <span v-for="(state, id) in row.gates" :key="id" class="gate-chip" :class="'gate-' + state"
                          :title="id + ': ' + (GATE_LABEL[state] || state)">{{ id }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="muted small">Nenhuma tarefa neste projeto ainda.</p>
        </div>

        <div v-if="selected" class="table-panel org-detail">
          <h3>{{ selected.title }}</h3>
          <p v-if="!detail" class="muted small">Carregando portões…</p>
          <template v-else>
            <p class="muted small">Etapa: <strong>{{ STAGE_LABEL[detail.stage] || detail.stage }}</strong> · status {{ detail.status }}</p>
            <div class="org-gates">
              <div v-for="gate in detail.gates" :key="gate.id" class="chart-panel">
                <h4><span class="gate-chip" :class="'gate-' + gate.state">{{ gate.id }}</span> {{ gate.name }} — {{ GATE_LABEL[gate.state] }}</h4>
                <ul class="org-checks">
                  <li v-for="check in gate.checks" :key="check.name">
                    <span :class="check.ok === true ? 'ok' : check.ok === false ? 'bad' : 'muted'">{{ check.ok === true ? '✓' : check.ok === false ? '✗' : '…' }}</span>
                    {{ check.name }}<span v-if="check.detail" class="muted small"> — {{ check.detail }}</span>
                  </li>
                </ul>
              </div>
            </div>
            <h4>Avaliação da entrega</h4>
            <ul class="org-checks">
              <li v-for="dim in detail.evaluation.dimensions" :key="dim.id">
                <span :class="dim.ok === true ? 'ok' : dim.ok === false ? 'bad' : 'muted'">{{ dim.ok === true ? '✓' : dim.ok === false ? '✗' : '—' }}</span>
                {{ dim.name }} <span class="muted small">({{ dim.source }})</span>
              </li>
            </ul>
            <h4>Revisões</h4>
            <ul class="org-checks" v-if="detail.reviews.length">
              <li v-for="r in detail.reviews" :key="r.at">{{ roleName(r.role) }}: {{ r.decision === 'approved' ? 'aprovou' : 'reprovou' }}<span v-if="r.reason" class="muted small"> — {{ r.reason }}</span></li>
            </ul>
            <p v-else class="muted small">Nenhuma revisão registrada.</p>
            <section v-if="handoff" class="org-handoff" aria-labelledby="org-handoff-title">
              <h4 id="org-handoff-title">Passagem de trabalho</h4>
              <p v-if="handoff.next_owner"><strong>Próximo responsável:</strong> {{ roleName(handoff.next_owner) }}</p>
              <p v-if="handoff.results">{{ handoff.results }}</p>
              <p v-if="handoff.next_action"><strong>Próxima ação:</strong> {{ handoff.next_action }}</p>
              <div v-if="handoff.findings && handoff.findings.length">
                <strong>Descobertas</strong>
                <ul class="org-checks"><li v-for="(finding, index) in handoff.findings" :key="index">{{ typeof finding === 'string' ? finding : finding.text || finding.title || JSON.stringify(finding) }}</li></ul>
              </div>
              <div v-if="handoff.pending && handoff.pending.length">
                <strong>Pendente</strong>
                <ul class="org-checks"><li v-for="(item, index) in handoff.pending" :key="index">{{ item }}</li></ul>
              </div>
              <p v-if="!handoff.results && !handoff.next_action && !(handoff.findings || []).length && !(handoff.pending || []).length" class="muted small">Nenhuma passagem registrada para esta tarefa.</p>
            </section>
            <form class="org-review" @submit.prevent="submitReview">
              <label>Papel <select v-model="review.role"><option v-for="r in directory.roles" :key="r.id" :value="r.id">{{ r.name }}</option></select></label>
              <label>Decisão <select v-model="review.decision"><option value="approved">Aprovar</option><option value="rejected">Reprovar</option></select></label>
              <label class="org-reason">Motivo <input v-model="review.reason" type="text" placeholder="obrigatório para reprovar" /></label>
              <button type="submit" class="btn-primary">Registrar revisão</button>
            </form>
          </template>
        </div>

        <div class="table-panel" v-if="metrics">
          <h3>Indicadores de entrega</h3>
          <p class="muted small">{{ metrics.sample.verified }} de {{ metrics.sample.tasks }} tarefa(s) concluídas e comprovadas.</p>
          <table class="data-table">
            <tbody>
              <tr v-for="m in metrics.metrics" :key="m.id">
                <td>{{ m.definition }}</td>
                <td class="mono">{{ formatMetric(m) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="table-panel">
          <h3>Equipes e papéis</h3>
          <div class="org-offices">
            <div v-for="office in teamsByOffice" :key="office.id" class="chart-panel">
              <h4>{{ office.name }}</h4>
              <div v-for="team in office.teams" :key="team.id" class="org-team">
                <strong>{{ team.name }}</strong> <span class="muted small">— {{ team.mission }}</span>
                <ul><li v-for="role in team.roles" :key="role.id">{{ role.name }}<span v-if="role.human" class="muted small"> (humano)</span></li></ul>
              </div>
            </div>
          </div>
        </div>

        <div class="table-panel">
          <h3>Propriedade dos módulos</h3>
          <div class="table-scroll">
            <table class="data-table">
              <thead><tr><th>Caminho</th><th>Equipe</th><th>Papel</th><th>Coordenação</th></tr></thead>
              <tbody>
                <tr v-for="rule in directory.ownership" :key="rule.pattern">
                  <td class="mono">{{ rule.pattern }}<span v-if="rule.protected" class="muted small"> · protegido</span><span v-else-if="rule.shared_contract" class="muted small"> · contrato</span></td>
                  <td>{{ teamName(rule.team) }}</td>
                  <td>{{ roleName(rule.role) }}</td>
                  <td>{{ rule.coordination ? roleName(rule.coordination) : '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  `,
};
