// web/static/assets/app/components/chat.js
import {
  state,
  roots,
  childrenOf,
  descendantIds,
  sendMessage,
  loadModels,
  selectTask,
  toast,
  stepRun,
  autoRun,
  pauseRun,
  cancelRun,
  resumeRun,
  cancelQueued,
} from "../store.js";
import {
  icon,
  renderMarkdown,
  stamp,
  modelLabel,
  statusLabel,
  toolOf as toolOfTask,
  TOOL_ICON,
  BUSY_STATUSES,
  summarizeActivity,
  diffLines,
} from "../ui.js";
import { filesList, currentTask } from "../live-state.js";

export const ChatView = {
  name: "ChatView",
  emits: ["new-project"],
  setup() {
    const messages = Vue.computed(() => {
      return roots().map((root) => {
        const kids = childrenOf(root.id);
        const ids = descendantIds(root.id);
        const answer = root.consolidated_result_json?.final_answer || null;
        const reply = answer ? renderMarkdown(answer) : "";
        const busy = BUSY_STATUSES.includes(root.status) || kids.some((task) => BUSY_STATUSES.includes(task.status));
        const meta = root.metadata_json || {};
        const pause = (root.metadata_json || {}).pause || null;
        const isLast = roots().length > 0 && root.id === roots()[roots().length - 1].id;
        return {
          id: root.id,
          title: root.display_title || root.title,
          pause,
          activity: state.feeds[root.id] || [],
          summary: summarizeActivity(state.feeds[root.id] || []),
          objective: String(root.objective || "").split("\n\nAnexos do usuário:")[0],
          attachments: meta.attachments || [],
          createdAt: stamp(root.created_at),
          model: modelLabel(root, state.live),
          status: root.status,
          statusText: statusLabel(root.status),
          busy,
          reply,
          stages: kids.map((task) => ({
            id: task.id,
            title: task.display_title || task.title,
            status: task.status,
            statusText: statusLabel(task.status),
            tool: toolOfTask(task),
            glyph: TOOL_ICON[toolOfTask(task)] || "circle",
            active: BUSY_STATUSES.includes(task.status),
            selected: state.selectedTaskId === task.id,
          })),
          focusHere: !state.live?.focus || ids.has(state.live.focus.id),
        };
      });
    });

    const providerOptions = Vue.computed(() => state.providers);
    const models = Vue.computed(() => state.providerModels[state.provider] || []);
    const logRef = Vue.ref(null);

    // Rolagem automática: acompanha o feed enquanto o usuário estiver no fim; se ele
    // subiu para ler, a rolagem é parada até ele voltar ao fim.
    Vue.watch(
      () =>
        messages.value
          .map((message) => `${message.stages.length}:${message.activity.length}`)
          .join(","),
      () => {
        const element = logRef.value;
        if (!element) return;
        const stick = atBottom.value && !userTookOver.value;
        Vue.nextTick(() => {
          if (stick && !userTookOver.value) {
            element.scrollTo({ top: element.scrollHeight, behavior: "smooth" });
          }
        });
      },
      { flush: "pre" },
    );
    const thoughts = Vue.computed(() => {
      const live = state.live;
      if (!live) return [];
      const noisy = /^(Planejando|Pronta para executar|Concluída sem teste|Liberada|Aguardando|Começando)/;
      return (live.thoughts || []).filter((item) => !noisy.test(item.text || ""));
    });

    // Etiquetas do plano (estilo Kilo): as tarefas da mensagem atual que ainda estão
    // em aberto; somem quando concluem e mudam quando o planejamento muda.
    const planTags = Vue.computed(() => {
      const rootsNow = roots();
      const last = rootsNow[rootsNow.length - 1];
      if (!last) return [];
      return childrenOf(last.id)
        .filter((task) => task.status !== "COMPLETED" && task.status !== "CANCELLED")
        .map((task) => ({
          id: task.id,
          title: task.display_title || task.title,
          status: task.status,
          statusText: statusLabel(task.status),
          active: ["RUNNING", "PLANNING", "VERIFYING", "RETRY_PENDING"].includes(task.status),
        }));
    });

    const changedFiles = Vue.computed(() => {
      const reducer = state.liveState?.data;
      if (!reducer) return [];
      return filesList(reducer, {});
    });

    const currentStage = Vue.computed(() => {
      const reducer = state.liveState?.data;
      if (!reducer) return null;
      const task = currentTask(reducer);
      return task ? task.title : null;
    });

    const atBottom = Vue.ref(true);
    // O usuário assumiu o controle da rolagem (roda do mouse/toque): a rolagem automática
    // para até ele voltar ao fim.
    const userTookOver = Vue.ref(false);
    // Entradas abertas e fechadas pelo usuário (o que tem diff abre sozinho).
    const openIds = Vue.reactive(new Set());
    const closedIds = Vue.reactive(new Set());
    const collapsedTurns = Vue.reactive(new Set());

    function isOpen(entry) {
      if (closedIds.has(entry.id)) return false;
      if (openIds.has(entry.id)) return true;
      return Boolean(entry.diff);
    }

    function toggleEntry(entry) {
      if (isOpen(entry)) {
        closedIds.add(entry.id);
        openIds.delete(entry.id);
      } else {
        openIds.add(entry.id);
        closedIds.delete(entry.id);
      }
    }

    function isTurnCollapsed(message) {
      return collapsedTurns.has(message.id);
    }

    function toggleTurn(message) {
      if (isTurnCollapsed(message)) collapsedTurns.delete(message.id);
      else collapsedTurns.add(message.id);
    }

    function onScroll() {
      const element = logRef.value;
      if (!element) return;
      atBottom.value = element.scrollHeight - element.scrollTop - element.clientHeight < 80;
      if (atBottom.value) userTookOver.value = false;
    }

    function onUserScrollIntent() {
      userTookOver.value = true;
      const element = logRef.value;
      // Cancela a rolagem suave em andamento para não arrastar o usuário até o fim.
      if (element) element.scrollTo({ top: element.scrollTop, behavior: "auto" });
    }

    function scrollToBottom() {
      const element = logRef.value;
      if (element) element.scrollTop = element.scrollHeight;
    }

    async function onProviderChange() {
      state.modelId = "";
      const found = await loadModels(state.provider);
      if (found.length) state.modelId = found[0];
    }

    function onKeydown(event) {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
      }
    }

    async function onFiles(event) {
      const files = Array.from(event.target.files || []);
      event.target.value = "";
      for (const file of files) {
        if (state.attachments.length >= 6) {
          toast("Máximo de 6 anexos por mensagem", "error");
          break;
        }
        const base64 = await readAsBase64(file);
        state.attachments.push({
          kind: file.type.startsWith("image/") ? "image" : "file",
          name: file.name,
          mime: file.type || "application/octet-stream",
          content_base64: base64,
        });
      }
    }

    function readAsBase64(file) {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(file);
      });
    }

    function removeAttachment(index) {
      state.attachments.splice(index, 1);
    }

    return {
      state,
      messages,
      logRef,
      changedFiles,
      planTags,
      currentStage,
      atBottom,
      onScroll,
      onUserScrollIntent,
      scrollToBottom,
      isOpen,
      toggleEntry,
      isTurnCollapsed,
      toggleTurn,
      diffLines,
      providerOptions,
      models,
      thoughts,
      onProviderChange,
      onKeydown,
      onFiles,
      removeAttachment,
      toast,
      sendMessage,
      selectTask,
      icon,
      stamp,
    };
  },
  template: `
    <section class="chat">
      <div
        class="chat-log"
        ref="logRef"
        v-if="messages.length"
        @scroll="onScroll"
        @wheel="onUserScrollIntent"
        @touchstart="onUserScrollIntent"
      >
        <article v-for="message in messages" :key="message.id" class="turn">
          <div class="bubble user">
            <div class="bubble-meta">
              <span class="avatar avatar-user">Você</span>
              <span class="muted">{{ message.createdAt }}</span>
            </div>
            <p class="bubble-text">{{ message.objective }}</p>
            <div class="chips" v-if="message.attachments.length">
              <span class="chip" v-for="item in message.attachments" :key="item.name">
                <span v-html="icon('paperclip', 12)"></span>{{ item.name || item.path }}
              </span>
            </div>
          </div>

          <div class="bubble agent" :class="{ live: message.busy }">
            <div class="bubble-meta">
              <img class="avatar avatar-mark" src="/assets/brand/callidus-mark.svg" alt="" width="20" height="20" />
              <span class="agent-name">Callidus</span>
              <span class="muted" v-if="message.model">{{ message.model }}</span>
              <span class="status-pill" :class="'status-' + message.status">{{ message.statusText }}</span>
            </div>

            <div class="activity" v-if="message.activity.length">
              <div class="activity-head">
                <span class="activity-head-title">
                  <span class="activity-ico" v-html="icon('spark', 13)"></span>
                  Atividade do agente
                </span>
                <span class="activity-counts" v-if="message.summary">
                  <span class="tag" v-if="message.summary.escritas">{{ message.summary.escritas }} escrita(s)</span>
                  <span class="tag" v-if="message.summary.leituras">{{ message.summary.leituras }} leitura(s)</span>
                  <span class="tag" v-if="message.summary.comandos">{{ message.summary.comandos }} comando(s)</span>
                  <span class="tag" v-if="message.summary.testes">{{ message.summary.testes }} teste(s)</span>
                </span>
                <button
                  type="button"
                  class="activity-collapse"
                  @click="toggleTurn(message)"
                >
                  {{ isTurnCollapsed(message) ? 'abrir detalhes' : 'recolher' }}
                </button>
              </div>

              <TransitionGroup v-if="!isTurnCollapsed(message)" name="activity" tag="div" class="activity-items">
                <div
                  v-for="entry in message.activity"
                  :key="entry.id"
                  class="activity-row"
                  :class="['activity-' + entry.kind, 'state-' + entry.status]"
                >
                  <button type="button" class="activity-toggle" @click="toggleEntry(entry)">
                    <span class="activity-ico" v-html="icon(entry.icon, 13)"></span>
                    <span class="activity-body">
                      <span class="activity-title">{{ entry.title }}</span>
                      <span class="activity-detail" v-if="entry.detail && !isOpen(entry)">{{ entry.detail }}</span>
                    </span>
                    <span class="activity-state">
                      <span class="spinner" v-if="entry.status === 'running'"></span>
                      <span class="activity-ms" v-else-if="entry.duration != null">{{ entry.duration }} ms</span>
                    </span>
                    <span class="activity-chevron" :class="{ open: isOpen(entry) }" v-html="icon('down', 13)"></span>
                  </button>

                  <Transition name="expand">
                    <div class="activity-details" v-if="isOpen(entry)">
                      <p class="activity-explanation" v-if="entry.explanation">{{ entry.explanation }}</p>
                      <p class="activity-stats muted small" v-if="entry.stats">{{ entry.stats }}</p>
                      <pre class="activity-output" v-if="entry.output">{{ entry.output }}</pre>
                      <pre class="activity-diff" v-if="entry.diff">
                        <span
                          v-for="(line, index) in diffLines(entry.diff.text)"
                          :key="index"
                          :class="'diff-' + line.type"
                        >{{ line.text }}</span>
                      </pre>
                      <p class="muted small" v-if="entry.sensitive">Arquivo sensível: conteúdo não transmitido.</p>
                    </div>
                  </Transition>
                </div>
              </TransitionGroup>
            </div>

            <ul class="thoughts" v-if="thoughts.length && message.focusHere">
              <li v-for="(thought, index) in thoughts" :key="index" :class="thought.phase">
                <span class="thought-dot"></span>{{ thought.text }}
              </li>
            </ul>

            <div class="stages" v-if="message.stages.length">
              <button
                type="button"
                class="stage"
                :class="{ active: stage.active, selected: stage.selected }"
                v-for="stage in message.stages"
                :key="stage.id"
                @click="selectTask(stage.id)"
              >
                <span class="stage-ico" v-html="icon(stage.glyph, 14)"></span>
                <span class="stage-title">{{ stage.title }}</span>
                <span class="status-dot" :class="'status-' + stage.status"></span>
              </button>
            </div>

            <div class="pause-banner" v-if="message.pause">
              <span class="pause-ico" v-html="icon('pause', 15)"></span>
              <div class="pause-body">
                <strong>Execução pausada</strong>
                <span>{{ message.pause.reason || 'limite operacional atingido' }}</span>
                <span class="muted small" v-if="message.pause.next_action">Próximo passo: {{ message.pause.next_action }}</span>
              </div>
              <button type="button" class="btn-ghost small" @click="resumeRun()">Retomar</button>
            </div>

            <div class="answer" v-if="message.reply" v-html="message.reply"></div>
            <p class="muted thinking" v-else-if="message.busy">
              <span class="spinner"></span> Trabalhando…
            </p>
          </div>
        </article>
      </div>

      <div class="chat-empty" v-else>
        <img class="brand-mark-img brand-mark-lg" src="/assets/brand/callidus-mark.svg" alt="" width="52" height="52" />
        <h2>O que vamos construir?</h2>
        <p>Escreva embaixo como no chat. O Callidus divide o trabalho, edita arquivos e mostra cada passo aqui.</p>
      </div>

      <button
        type="button"
        class="scroll-bottom"
        :class="{ show: !atBottom }"
        title="Rolar para o fim"
        aria-label="Rolar para o fim"
        @click="scrollToBottom"
        v-html="icon('down', 16)"
      ></button>

      <div class="context-bar" :class="{ 'context-bar-always': true }">
        <div class="run-controls compact-run" v-if="state.currentRun || state.compact">
          <button type="button" class="icon-btn" title="Um passo" aria-label="Um passo" :disabled="!state.currentRun" @click="stepRun()" v-html="icon('play', 15)"></button>
          <button type="button" class="icon-btn" title="Pausar" aria-label="Pausar" :disabled="!state.currentRun" @click="pauseRun()" v-html="icon('pause', 15)"></button>
          <button type="button" class="icon-btn danger" title="Parar" aria-label="Parar" :disabled="!state.currentRun" @click="cancelRun()" v-html="icon('stop', 15)"></button>
          <button type="button" class="btn-ghost small" :disabled="!state.currentRun" @click="autoRun()">Auto</button>
        </div>
        <span class="context-chip" v-if="state.currentRun">
          <span class="dot" :class="state.currentRun ? 'dot-live' : 'dot-idle'"></span>
          {{ state.currentRun ? 'Run ' + state.currentRun.status : 'parado' }}
        </span>
        <span class="context-chip" v-if="currentStage">
          <span v-html="icon('spark', 12)"></span>{{ currentStage }}
        </span>
        <span class="context-chip" v-if="changedFiles.length">
          <span v-html="icon('file', 12)"></span>{{ changedFiles.length }} arquivo(s) alterado(s)
        </span>
      </div>

      <p class="composer-hint" v-if="state.running || state.currentRun?.status === 'ACTIVE'">
        <span class="spinner"></span> Execução em andamento — o agente segue sozinho até o fim.
      </p>

      <p class="composer-hint queued" v-if="state.queued">
        <span class="side-ico" v-html="icon('clock', 13)"></span>
        Mensagem agendada: «{{ state.queued.objective.slice(0, 60) }}{{ state.queued.objective.length > 60 ? '…' : '' }}»
        <button type="button" class="link-btn" @click="cancelQueued()">cancelar</button>
      </p>

      <div class="plan-strip" v-if="planTags.length" aria-label="Tarefas do plano">
        <div class="plan-strip-inner">
          <button
            type="button"
            class="plan-tag"
            v-for="tag in planTags"
            :key="tag.id"
            :class="['plan-' + tag.status.toLowerCase(), { active: tag.active }]"
            :title="tag.title + ' — ' + tag.statusText"
            @click="selectTask(tag.id)"
          >
            <span class="status-dot" :class="'status-' + tag.status"></span>
            <span class="plan-tag-title">{{ tag.title }}</span>
            <span class="plan-tag-status">{{ tag.statusText }}</span>
          </button>
        </div>
      </div>

      <form class="composer" @submit.prevent="sendMessage()">
        <div class="chips" v-if="state.attachments.length">
          <span class="chip" v-for="(item, index) in state.attachments" :key="item.name + index">
            <span v-html="icon('paperclip', 12)"></span>{{ item.name }}
            <button type="button" class="chip-remove" @click="removeAttachment(index)" aria-label="Remover anexo">×</button>
          </span>
        </div>
        <div class="composer-box">
          <textarea
            v-model="state.objective"
            rows="2"
            placeholder="Pedir ao Callidus… (Enter envia)"
            aria-label="Pedido"
            @keydown="onKeydown"
          ></textarea>
          <div class="composer-bar">
            <button type="button" class="icon-btn ghost" title="Anexar imagem ou documento" aria-label="Anexar" @click="$refs.fileInput.click()" v-html="icon('paperclip', 15)"></button>
            <input ref="fileInput" type="file" multiple hidden accept="image/*,.pdf,.txt,.md,.py,.json,.csv,.js,.ts,.tsx,.html,.css,.xml,.yaml,.yml,.toml,.zip,.doc,.docx,.svg" @change="onFiles" />
            <div class="composer-pickers">
              <label class="picker">
                <span class="picker-label">Provedor</span>
                <select v-model="state.provider" @change="onProviderChange" aria-label="Provedor">
                  <option v-for="item in providerOptions" :key="item.name" :value="item.name">
                    {{ item.name }}<template v-if="item.type && item.type !== item.name"> · {{ item.type }}</template>
                  </option>
                </select>
              </label>
              <label class="picker">
                <span class="picker-label">Modelo</span>
                <select v-model="state.modelId" aria-label="Modelo">
                  <option v-if="!models.length" :value="state.modelId">{{ state.modelId || 'modelo' }}</option>
                  <option v-for="item in models" :key="item" :value="item">{{ item }}</option>
                </select>
              </label>
              <label class="picker">
                <span class="picker-label">Navegador</span>
                <select v-model="state.browserMode" aria-label="Navegador">
                  <option value="off">Desligado</option>
                  <option value="headless">Invisível</option>
                  <option value="visible">Janela</option>
                </select>
              </label>
              <label class="picker picker-check" title="Permitir comandos e scripts">
                <input type="checkbox" v-model="state.approveTools" />
                <span>Ferramentas</span>
              </label>
            </div>
            <button
              type="submit"
              class="btn-primary send-btn"
              :disabled="state.sending || !state.objective.trim()"
              :title="state.running ? 'A mensagem entra na fila e é enviada quando a execução atual terminar' : 'Enviar'"
            >
              <span v-html="icon('send', 15)"></span> Enviar
            </button>
          </div>
        </div>
      </form>
    </section>
  `,
};
