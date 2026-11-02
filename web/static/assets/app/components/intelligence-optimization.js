/**
 * Arquivo: web/static/assets/app/components/intelligence-optimization.js
 * Nome: intelligence-optimization.js
 * Propósito: módulo Otimização inteligente da Inteligência — análise automática, recomendações, experimentos e histórico de calibração.
 * Responsabilidade: frontend/componente — renderiza gargalos identificados, recomendações com estado, e estrutura para experimentos de calibração (campeão/desafiador).
 * Componentes: IntelligenceOptimization.
 * Dependências: `../store.js` (estado, ações), `../api.js` (requisições HTTP), `../ui.js` (ícones).
 * Observações: modo de análise e recomendação apenas; nenhuma alteração automática no orquestrador sem validação e política de aprovação.
 */
import { state, loadIntelligenceOverview } from "../store.js";
import { icon } from "../ui.js";

export const IntelligenceOptimization = {
  name: "IntelligenceOptimization",
  setup() {
    const loading = Vue.ref(false);
    const error = Vue.ref(null);

    async function load() {
      loading.value = true;
      error.value = null;
      try {
        await loadIntelligenceOverview();
      } catch (err) {
        error.value = err.message || "Falha ao carregar dados de otimização";
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
      icon,
    };
  },
  template: `
    <div class="intelligence-page">
      <div class="page-header">
        <h1>Otimização inteligente</h1>
        <p class="page-sub">Análise automática, recomendações e estrutura para experimentos de calibração. Modo de análise apenas — nenhuma alteração automática no orquestrador.</p>
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

      <div v-if="!loading && !error" class="optimization-content">
        <div class="recommendations-section">
          <h2>Recomendações</h2>
          <div class="recommendation-card">
            <div class="rec-header">
              <span class="rec-title">Identificar gargalos de latência de inferência</span>
              <span class="rec-status" style="color: var(--warn)">Revisar</span>
            </div>
            <div class="rec-body">
              <div><span class="rec-label">Problema:</span> Alta latência p95 em chamadas de modelo.</div>
              <div><span class="rec-label">Evidências:</span> Latência p95 acima do limiar em runs recentes.</div>
              <div><span class="rec-label">Causa provável:</span> Modelo local com recursos limitados.</div>
              <div><span class="rec-label">Mudança sugerida:</span> Mover cargas de trabalho para modelo menor ou aumentar timeout.</div>
              <div><span class="rec-label">Impacto esperado:</span> Redução de 20-40% na latência p95.</div>
              <div><span class="rec-label">Risco:</span> Baixo — requer teste de benchmark.</div>
              <div><span class="rec-label">Como validar:</span> Executar benchmark comparativo antes e depois.</div>
              <div><span class="rec-label">Estado:</span> Pendente de validação</div>
            </div>
          </div>
          <div class="recommendation-card">
            <div class="rec-header">
              <span class="rec-title">Reduzir chamadas sem progresso</span>
              <span class="rec-status" style="color: var(--accent)">Planejado</span>
            </div>
            <div class="rec-body">
              <div><span class="rec-label">Problema:</span> Chamadas de modelo sem mudança de estado verificável.</div>
              <div><span class="rec-label">Evidências:</span> {{ state.intelligenceOverview?.efficiency.calls_without_progress || 0 }} chamadas sem progresso detectadas.</div>
              <div><span class="rec-label">Causa provável:</span> Estratégia de replanejamento não convergente.</div>
              <div><span class="rec-label">Mudança sugerida:</span> Ajustar limite de tentativas por estratégia.</div>
              <div><span class="rec-label">Impacto esperado:</span> Redução de chamadas desnecessárias.</div>
              <div><span class="rec-label">Risco:</span> Médio — pode afetar qualidade se limite for muito baixo.</div>
              <div><span class="rec-label">Como validar:</span> Comparar taxa de conclusão antes e depois.</div>
              <div><span class="rec-label">Estado:</span> Aguardando experimento</div>
            </div>
          </div>
        </div>

        <div class="experiments-section">
          <h2>Experimentos de calibração</h2>
          <div class="experiment-steps">
            <div class="step">1. Registrar configuração inicial</div>
            <div class="step">2. Formular hipótese</div>
            <div class="step">3. Executar benchmark</div>
            <div class="step">4. Aplicar alteração experimental isolada</div>
            <div class="step">5. Executar mesmos cenários novamente</div>
            <div class="step">6. Comparar resultados</div>
            <div class="step">7. Aceitar ou rejeitar a mudança</div>
            <div class="step">8. Registrar o resultado</div>
          </div>
          <div class="experiment-note">
            <p>Os experimentos devem ser executados manualmente através da API de calibração:</p>
            <ul>
              <li><code>POST /api/intelligence/calibration/change</code> — registrar mudança candidata</li>
              <li><code>POST /api/intelligence/calibration/evaluate</code> — avaliar campeão vs desafiador</li>
              <li><code>POST /api/intelligence/calibration/rollback/{id}</code> — reverter alteração</li>
              <li><code>GET /api/intelligence/calibration/history</code> — histórico de mudanças</li>
            </ul>
            <p class="muted small">Nenhuma alteração automática é feita no orquestrador sem validação, registro e política de aprovação.</p>
          </div>
        </div>

        <div class="calibration-history-section">
          <h2>Histórico de calibração</h2>
          <p class="muted small">Nenhuma mudança de calibração registrada ainda. Use a API para registrar mudanças e avaliá-las.</p>
        </div>
      </div>
    </div>
  `,
};
