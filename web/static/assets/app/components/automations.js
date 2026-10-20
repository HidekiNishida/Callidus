// web/static/assets/app/components/automations.js — painel das automações
import {
  state,
  loadAutomations,
  loadAutomationDetail,
  createAutomation,
  automationAction,
  deleteAutomation,
  loadSupervisorStatus,
  toast,
} from "../store.js";

const emptyForm = () => ({
  name: "",
  project_id: "",
  trigger_kind: "cron",
  cron: "0 9 * * *",
  timezone: "UTC",
  run_at: "",
  interval_seconds: "3600",
  event_type: "task.completed",
  action_kind: "callidus",
  objective: "",
  command: "",
  cwd: "",
  missed_policy: "run_once",
  target_kind: "local",
  allow_scripts: false,
  allowed_commands: "",
  max_attempts: "3",
});

export const AutomationsView = {
  name: "AutomationsView",
  setup() {
    const form = Vue.reactive(emptyForm());
    const detail = Vue.ref(null);
    const busy = Vue.ref(false);

    const projectId = Vue.computed(
      () => form.project_id || state.selectedProject?.id || state.projects?.[0]?.id || "",
    );

    Vue.onMounted(async () => {
      await loadAutomations();
      await loadSupervisorStatus();
      if (!form.project_id && projectId.value) form.project_id = projectId.value;
    });

    function definition() {
      const trigger = { kind: form.trigger_kind, timezone: form.timezone };
      if (form.trigger_kind === "cron") trigger.cron = form.cron;
      if (form.trigger_kind === "interval") trigger.interval_seconds = Number(form.interval_seconds) || 60;
      if (form.trigger_kind === "once") trigger.run_at = new Date(form.run_at).toISOString();
      if (form.trigger_kind === "event") trigger.event_type = form.event_type;

      const action = { kind: form.action_kind };
      if (form.action_kind === "callidus") {
        action.objective = form.objective;
        action.objective_mode = "frozen";
        action.autonomous = true;
      } else {
        action.command = form.command.split(/\s+/).filter(Boolean);
        if (form.cwd) action.cwd = form.cwd;
      }

      return {
        name: form.name,
        project_id: projectId.value,
        target_kind: form.target_kind,
        trigger,
        action,
        missed_policy: form.missed_policy,
        timezone: form.timezone,
        permissions: {
          allow_scripts: form.action_kind === "script" ? form.allow_scripts : false,
          allowed_commands: form.allowed_commands.split(",").map((item) => item.trim()).filter(Boolean),
        },
        policy: { max_attempts: Number(form.max_attempts) || 3 },
      };
    }

    async function submit(activate) {
      if (!form.name.trim()) {
        toast("Dê um nome à automação", "error");
        return;
      }
      if (!projectId.value) {
        toast("Escolha o projeto da automação", "error");
        return;
      }
      busy.value = true;
      try {
        await createAutomation(definition(), activate);
        toast(activate ? "Automação criada e ativada" : "Automação criada", "ok");
        Object.assign(form, emptyForm(), { project_id: projectId.value });
        await loadSupervisorStatus();
      } catch (err) {
        toast(err.message || "Falha ao criar a automação", "error");
      } finally {
        busy.value = false;
      }
    }

    async function act(item, action) {
      try {
        await automationAction(item.id, action, action === "test" ? { execute: false } : {});
        toast("Pronto", "ok");
        await loadSupervisorStatus();
      } catch (err) {
        toast(err.message || "Falha na ação", "error");
      }
    }

    async function open(item) {
      detail.value = await loadAutomationDetail(item.id);
    }

    async function remove(item) {
      if (!window.confirm(`Remover a automação "${item.name}"?`)) return;
      try {
        await deleteAutomation(item.id);
        toast("Automação removida", "ok");
        if (detail.value?.id === item.id) detail.value = null;
      } catch (err) {
        toast(err.message || "Falha ao remover", "error");
      }
    }

    function stateLabel(value) {
      return { enabled: "ativa", suspended: "suspensa", disabled: "desativada" }[value] || value;
    }

    function when(value) {
      if (!value) return "—";
      try {
        return new Date(value).toLocaleString();
      } catch {
        return value;
      }
    }

    return {
      state,
      form,
      detail,
      busy,
      projectId,
      submit,
      act,
      open,
      remove,
      stateLabel,
      when,
    };
  },
  template: `
    <section class="auto-pane">
      <header class="auto-head">
        <h2>Automações</h2>
        <p class="muted">Trabalhos que o Callidus executa sozinho, mesmo sem a interface aberta.</p>
      </header>

      <div class="auto-grid">
        <article class="card">
          <h3>Nova automação</h3>
          <label class="field">
            <span>Nome</span>
            <input v-model="form.name" type="text" placeholder="Relatório da madrugada" />
          </label>
          <label class="field">
            <span>Projeto</span>
            <select v-model="form.project_id">
              <option v-for="p in state.projects" :key="p.id" :value="p.id">{{ p.name }}</option>
            </select>
          </label>
          <div class="grid-2">
            <label class="field">
              <span>Gatilho</span>
              <select v-model="form.trigger_kind">
                <option value="cron">Recorrência (cron)</option>
                <option value="interval">Intervalo</option>
                <option value="once">Data e hora</option>
                <option value="event">Evento interno</option>
              </select>
            </label>
            <label class="field">
              <span>Fuso</span>
              <input v-model="form.timezone" type="text" placeholder="UTC" />
            </label>
          </div>
          <label class="field" v-if="form.trigger_kind === 'cron'">
            <span>Expressão cron</span>
            <input v-model="form.cron" type="text" placeholder="0 9 * * *" />
          </label>
          <label class="field" v-if="form.trigger_kind === 'interval'">
            <span>Intervalo (segundos)</span>
            <input v-model="form.interval_seconds" type="text" />
          </label>
          <label class="field" v-if="form.trigger_kind === 'once'">
            <span>Quando</span>
            <input v-model="form.run_at" type="datetime-local" />
          </label>
          <label class="field" v-if="form.trigger_kind === 'event'">
            <span>Evento</span>
            <input v-model="form.event_type" type="text" placeholder="task.completed" />
          </label>

          <label class="field">
            <span>Ação</span>
            <select v-model="form.action_kind">
              <option value="callidus">Tarefa do Callidus</option>
              <option value="script">Script (sem inferência)</option>
            </select>
          </label>
          <label class="field" v-if="form.action_kind === 'callidus'">
            <span>Objetivo</span>
            <textarea v-model="form.objective" rows="3" placeholder="O que o Callidus deve fazer"></textarea>
          </label>
          <template v-else>
            <label class="field">
              <span>Comando</span>
              <input v-model="form.command" type="text" placeholder="./scripts/backup.sh" />
            </label>
            <label class="field">
              <span>Diretório de trabalho</span>
              <input v-model="form.cwd" type="text" placeholder="(pasta do projeto)" />
            </label>
            <label class="field check">
              <input v-model="form.allow_scripts" type="checkbox" />
              <span>Autorizar execução de scripts</span>
            </label>
            <label class="field">
              <span>Comandos permitidos (separados por vírgula)</span>
              <input v-model="form.allowed_commands" type="text" placeholder="./scripts/backup.sh" />
            </label>
          </template>

          <div class="grid-2">
            <label class="field">
              <span>Disparos perdidos</span>
              <select v-model="form.missed_policy">
                <option value="run_once">Executar uma vez</option>
                <option value="catch_up">Recuperar todos</option>
                <option value="group">Agrupar</option>
                <option value="skip">Ignorar</option>
              </select>
            </label>
            <label class="field">
              <span>Tentativas</span>
              <input v-model="form.max_attempts" type="text" />
            </label>
          </div>
          <div class="form-actions">
            <button type="button" :disabled="busy" @click="submit(true)">Criar e ativar</button>
            <button type="button" class="ghost" :disabled="busy" @click="submit(false)">Criar</button>
          </div>
        </article>

        <article class="card">
          <h3>Situação do runtime</h3>
          <dl class="kv" v-if="state.supervisor">
            <div><dt>Supervisor</dt><dd>{{ state.supervisor.running ? 'em execução' : 'parado' }}</dd></div>
            <div>
              <dt>Serviço nativo</dt>
              <dd>
                {{ state.supervisor.service?.platform || '—' }} ·
                {{ state.supervisor.service?.installed ? 'instalado' : 'não instalado' }} ·
                {{ state.supervisor.service?.active ? 'ativo' : 'inativo' }}
              </dd>
            </div>
            <div><dt>Próximo disparo</dt><dd>{{ when(state.supervisor.next_run_at) }}</dd></div>
            <div><dt>Disparos</dt><dd>{{ state.supervisor.firings?.total ?? 0 }}</dd></div>
          </dl>
          <p class="muted" v-else>Carregando a situação do runtime…</p>
          <p class="auto-hint">
            Para funcionar sem a interface, instale o serviço nativo:
            <code>callidus-supervisor install</code>
          </p>
        </article>

        <article class="card auto-wide">
          <h3>Automações</h3>
          <p class="muted" v-if="!state.automations.length">Nenhuma automação ainda.</p>
          <ul class="auto-list" v-else>
            <li v-for="item in state.automations" :key="item.id" class="auto-row">
              <div class="auto-main">
                <strong>{{ item.name }}</strong>
                <span class="muted">
                  {{ item.trigger?.kind }} · {{ item.target }} · {{ stateLabel(item.state) }}
                </span>
                <span class="muted">
                  próximo: {{ when(item.next_run_at) }} · política de perdidos: {{ item.missed_policy }}
                </span>
              </div>
              <div class="auto-actions">
                <button type="button" class="ghost" @click="act(item, 'enable')">Ativar</button>
                <button type="button" class="ghost" @click="act(item, 'suspend')">Suspender</button>
                <button type="button" class="ghost" @click="act(item, 'run')">Executar agora</button>
                <button type="button" class="ghost" @click="act(item, 'test')">Testar</button>
                <button type="button" class="ghost" @click="act(item, 'cancel')">Cancelar</button>
                <button type="button" class="ghost" @click="open(item)">Detalhes</button>
                <button type="button" class="danger" @click="remove(item)">Remover</button>
              </div>
            </li>
          </ul>
        </article>

        <article class="card wide" v-if="detail">
          <h3>Detalhes — {{ detail.name }}</h3>
          <dl class="kv">
            <div><dt>Estado</dt><dd>{{ stateLabel(detail.state) }}</dd></div>
            <div><dt>Próximo disparo</dt><dd>{{ when(detail.next_run_at) }}</dd></div>
            <div><dt>Última execução</dt><dd>{{ when(detail.last_run_at) }}</dd></div>
            <div><dt>Destino</dt><dd>{{ detail.target }}</dd></div>
            <div><dt>Ação</dt><dd>{{ detail.action?.kind }}</dd></div>
            <div><dt>Dependências</dt><dd>{{ (detail.dependencies || []).length }}</dd></div>
            <div><dt>Disparos perdidos</dt><dd>{{ detail.missed_policy }}</dd></div>
          </dl>
          <h4>Últimos disparos</h4>
          <ul class="auto-list">
            <li v-for="f in detail.firings" :key="f.id" class="auto-row">
              <div class="auto-main">
                <strong>{{ f.state }}</strong>
                <span class="muted">{{ when(f.scheduled_for) }} · tentativa {{ f.attempt }}/{{ f.max_attempts }}</span>
                <span class="muted" v-if="f.error">{{ f.error }}</span>
              </div>
            </li>
          </ul>
        </article>
      </div>
    </section>
  `,
};
