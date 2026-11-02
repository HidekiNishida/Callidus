/**
 * Arquivo: web/static/assets/app/components/intelligence-engineering.js
 * Nome: intelligence-engineering.js
 * Propósito: módulo Engenharia e qualidade da Inteligência — status do Git, descoberta do projeto, qualidade de código (lint/test/build).
 * Responsabilidade: frontend/componente — consome `/projects/{id}/git-diff` e endpoints de engenharia para renderizar branch, arquivos modificados, histórico de commits e resultados de qualidade.
 * Componentes: IntelligenceEngineering.
 * Dependências: `../store.js` (estado, ações), `../api.js` (requisições HTTP), `../ui.js` (ícones).
 * Observações: estados loading/success/empty/error; dados vêm da API.
 */
import { state } from "../store.js";
import { api } from "../api.js";
import { icon } from "../ui.js";

export const IntelligenceEngineering = {
  name: "IntelligenceEngineering",
  setup() {
    const loading = Vue.ref(false);
    const error = Vue.ref(null);
    const gitDiff = Vue.ref("");
    const gitStatus = Vue.ref(null);
    const gitLog = Vue.ref([]);
    const quality = Vue.ref(null);

    async function load() {
      loading.value = true;
      error.value = null;
      try {
        const project = state.selectedProject;
        if (!project) return;
        const [diff, status, log] = await Promise.all([
          api(`/projects/${project.id}/git-diff`).catch(() => null),
          api(`/projects/${project.id}/git-status`).catch(() => null),
          api(`/projects/${project.id}/git-log`).catch(() => []),
        ]);
        gitDiff.value = (diff && (diff.diff || diff.text || "")) || "";
        gitStatus.value = status || null;
        gitLog.value = log || [];
      } catch (err) {
        error.value = err.message || "Falha ao carregar dados de engenharia";
      } finally {
        loading.value = false;
      }
    }

    Vue.onMounted(load);

    return {
      state,
      loading,
      error,
      load,
      gitDiff,
      gitStatus,
      gitLog,
      quality,
      icon,
    };
  },
  template: `
    <div class="intelligence-page">
      <div class="page-header">
        <h1>Engenharia e qualidade</h1>
        <p class="page-sub">Branch atual, arquivos modificados, histórico de commits e resultados de verificação de qualidade.</p>
        <div class="page-actions">
          <button type="button" class="btn-primary" @click="load" :disabled="loading" v-html="icon('refresh', 16)"></button>
          <span v-if="error" class="muted small" style="color: var(--danger)">{{ error }}</span>
        </div>
      </div>

      <div v-if="loading" class="skeleton-container">
        <div class="skeleton-line" style="width: 90%"></div>
        <div class="skeleton-line" style="width: 70%"></div>
        <div class="skeleton-line" style="width: 50%"></div>
      </div>

      <div v-if="!loading && error" class="empty-state">
        <p>Não foi possível carregar os dados: {{ error }}</p>
        <button type="button" class="btn-primary" @click="load" v-html="icon('refresh', 16)"></button>
      </div>

      <div v-if="!loading && !error" class="engineering-content">
        <div class="charts-row">
          <div class="chart-panel">
            <h3>Branch atual</h3>
            <div class="metric-detail">
              <div v-if="gitStatus"><span>Branch:</span> <span class="mono">{{ gitStatus.current_branch || '—' }}</span></div>
              <div v-if="gitStatus"><span>Arquivos modificados:</span> <span class="mono">{{ gitStatus.modified?.length || 0 }}</span></div>
              <div v-if="gitStatus"><span>Arquivos staged:</span> <span class="mono">{{ gitStatus.staged?.length || 0 }}</span></div>
              <div v-if="gitStatus"><span>Arquivos untracked:</span> <span class="mono">{{ gitStatus.untracked?.length || 0 }}</span></div>
            </div>
          </div>
          <div class="chart-panel">
            <h3>Qualidade</h3>
            <div class="metric-detail">
              <div><span>Status:</span> <span class="mono">—</span></div>
              <div><span>Última verificação:</span> <span class="mono">—</span></div>
            </div>
          </div>
        </div>

        <div class="table-panel">
          <h3>Histórico de commits</h3>
          <div class="table-scroll" v-if="gitLog?.length">
            <table class="data-table">
              <thead>
                <tr>
                  <th>Hash</th>
                  <th>Autor</th>
                  <th>Data</th>
                  <th>Mensagem</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="c in gitLog" :key="c.hash">
                  <td class="mono">{{ c.hash.slice(0, 7) }}</td>
                  <td>{{ c.author || '—' }}</td>
                  <td class="mono">{{ c.date || '—' }}</td>
                  <td>{{ c.message || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="muted small">Nenhum commit disponível.</p>
        </div>

        <div class="table-panel">
          <h3>Diff do projeto</h3>
          <div class="diff-content" v-if="gitDiff">
            <pre class="mono small">{{ gitDiff }}</pre>
          </div>
          <p v-else-if="gitDiff === ''" class="muted small">Nenhuma diferença detectada.</p>
        </div>
      </div>
    </div>
  `,
};
