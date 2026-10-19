// web/static/assets/app/components/providers.js — configuração de provedores pela interface
import { state, saveProviderConfig, removeProvider, setProviderSecret, clearProviderSecret, testProvider, loadModels, toast } from "../store.js";
import { icon } from "../ui.js";

const TYPES = [
  { id: "ollama", label: "Ollama (local ou remoto)", url: "http://127.0.0.1:11434", hint: "Servidor Ollama. Remoto: aponte a URL do VPS." },
  { id: "llamacpp", label: "llama.cpp (llama-server)", url: "http://127.0.0.1:8080", hint: "Servidor llama.cpp. Não precisa baixar o GGUF local." },
  { id: "openai_compatible", label: "Compatível com OpenAI", url: "https://meu-gateway.exemplo/v1", hint: "Qualquer API no formato OpenAI." },
  { id: "openai", label: "OpenAI", url: "https://api.openai.com/v1", hint: "API oficial da OpenAI." },
  { id: "openrouter", label: "OpenRouter", url: "https://openrouter.ai/api/v1", hint: "Catálogo de modelos de vários autores." },
  { id: "anthropic", label: "Anthropic", url: "https://api.anthropic.com", hint: "Messages API (formato próprio)." },
  { id: "gemini", label: "Gemini", url: "https://generativelanguage.googleapis.com/v1beta", hint: "generateContent (formato próprio)." },
  { id: "mock", label: "Mock", url: "", hint: "Sem rede, para testes." },
];

const emptyForm = () => ({
  name: "",
  type: "ollama",
  base_url: "http://127.0.0.1:11434",
  model: "",
  api_key_env: "",
  timeout: "",
  allow_private_hosts: true,
  verify_tls: true,
  max_retries: 1,
  referer: "",
  title: "",
  headers: {},
});

export const ProvidersView = {
  name: "ProvidersView",
  setup() {
    const form = Vue.reactive(emptyForm());
    const editing = Vue.ref(false);
    const secretInput = Vue.ref("");
    const showSecret = Vue.ref(false);
    const saving = Vue.ref(false);
    const models = Vue.computed(() => state.providerModels[form.name] || []);

    function typeInfo() {
      return TYPES.find((item) => item.id === form.type) || TYPES[0];
    }

    function startNew() {
      Object.assign(form, emptyForm());
      editing.value = false;
      secretInput.value = "";
      state.selectedTaskId = null;
    }

    function edit(name) {
      const spec = state.providerConfig?.providers?.[name] || {};
      Object.assign(form, {
        ...emptyForm(),
        ...spec,
        name,
        type: spec.type || "ollama",
        base_url: spec.base_url || typeInfo().url,
        timeout: spec.timeout ?? "",
        allow_private_hosts: spec.allow_private_hosts ?? true,
        verify_tls: spec.verify_tls ?? true,
        max_retries: spec.max_retries ?? 1,
        headers: spec.headers || {},
        secret: spec.secret || { configured: false },
      });
      editing.value = true;
      secretInput.value = "";
    }

    function onTypeChange() {
      const info = typeInfo();
      form.base_url = info.url;
    }

    function entryFromForm() {
      const entry = {
        type: form.type,
        base_url: form.base_url || null,
        model: form.model || null,
        timeout: form.timeout === "" ? null : Number(form.timeout),
        allow_private_hosts: form.allow_private_hosts,
        verify_tls: form.verify_tls,
        max_retries: form.max_retries ?? null,
      };
      if (form.api_key_env) entry.api_key_env = form.api_key_env;
      if (form.referer) entry.referer = form.referer;
      if (form.title) entry.title = form.title;
      if (Object.keys(form.headers || {}).length) entry.headers = form.headers;
      return entry;
    }

    async function save() {
      const name = (form.name || "").trim();
      if (!name) {
        toast("Dê um nome ao provedor", "error");
        return;
      }
      saving.value = true;
      try {
        const current = { ...(state.providerConfig?.providers || {}) };
        for (const key of Object.keys(current)) {
          const spec = { ...current[key] };
          delete spec.secret;
          current[key] = spec;
        }
        current[name] = entryFromForm();
        await saveProviderConfig({
          default_provider: state.providerConfig?.default_provider || name,
          providers: current,
        });
        if (secretInput.value) {
          await setProviderSecret(name, secretInput.value);
          secretInput.value = "";
        }
        toast(`Provedor “${name}” salvo`, "ok");
        edit(name);
      } catch (err) {
        toast(err.message || "Falha ao salvar", "error");
      } finally {
        saving.value = false;
      }
    }

    async function remove(name) {
      if (!window.confirm(`Remover o provedor “${name}”? A credencial gravada vai junto.`)) return;
      try {
        await removeProvider(name);
        toast(`Provedor “${name}” removido`, "ok");
        if (form.name === name) startNew();
      } catch (err) {
        toast(err.message || "Falha ao remover", "error");
      }
    }

    async function makeDefault(name) {
      try {
        const current = {};
        for (const [key, spec] of Object.entries(state.providerConfig?.providers || {})) {
          const clean = { ...spec };
          delete clean.secret;
          current[key] = clean;
        }
        await saveProviderConfig({ default_provider: name, providers: current });
        toast(`“${name}” agora é o provedor padrão`, "ok");
      } catch (err) {
        toast(err.message || "Falha ao definir o padrão", "error");
      }
    }

    async function test(name) {
      const result = await testProvider(name);
      if (result.ok) {
        toast(`${name}: ok (${result.models?.length || 0} modelos, ${result.latency_ms ?? "?"} ms)`, "ok");
      } else {
        toast(`${name}: ${result.detail || "sem resposta"}`, "error");
      }
    }

    async function fetchModels(name) {
      const found = await loadModels(name);
      if (!found.length) {
        toast("O servidor não devolveu modelos", "error");
        return;
      }
      if (form.name === name && !form.model) form.model = found[0];
      toast(`${found.length} modelos encontrados`, "ok");
    }

    async function clearSecret(name) {
      try {
        await clearProviderSecret(name);
        toast("Credencial apagada", "ok");
        edit(name);
      } catch (err) {
        toast(err.message || "Falha ao apagar a credencial", "error");
      }
    }

    return {
      state,
      TYPES,
      form,
      editing,
      models,
      saving,
      secretInput,
      showSecret,
      startNew,
      edit,
      onTypeChange,
      save,
      remove,
      makeDefault,
      test,
      fetchModels,
      clearSecret,
      typeInfo,
      icon,
    };
  },
  template: `
    <section class="providers">
      <header class="page-head">
        <div>
          <h2>Provedores</h2>
          <p class="muted">
            Escolha onde o Callidus fala com o modelo. As credenciais ficam em arquivo protegido
            (nunca no repositório) e a configuração é gravada em
            <code>{{ state.providerConfig?.path || 'data/providers.yaml' }}</code>.
          </p>
        </div>
        <button type="button" class="btn-primary" @click="startNew()">
          <span v-html="icon('plus', 15)"></span> Adicionar provedor
        </button>
      </header>

      <div class="providers-grid">
        <div class="provider-list">
          <article
            v-for="item in state.providers"
            :key="item.name"
            class="provider-card"
            :class="{ selected: state.provider === item.name }"
          >
            <header>
              <div>
                <h3>{{ item.name }}</h3>
                <span class="tag">{{ item.type }}</span>
                <span class="tag" v-if="state.providerConfig?.default_provider === item.name">padrão</span>
              </div>
              <div class="card-actions">
                <button type="button" class="icon-btn ghost" title="Usar como padrão" aria-label="Usar como padrão" @click="makeDefault(item.name)" v-html="icon('check', 15)"></button>
                <button type="button" class="icon-btn ghost" title="Editar" aria-label="Editar" @click="edit(item.name)" v-html="icon('pencil', 15)"></button>
                <button type="button" class="icon-btn ghost danger" title="Remover" aria-label="Remover" @click="remove(item.name)" v-html="icon('trash', 15)"></button>
              </div>
            </header>
            <p class="muted url" v-if="item.base_url">{{ item.base_url }}</p>
            <p class="muted small" v-else>Sem URL base (usa o padrão do tipo).</p>
            <dl class="kv compact">
              <div><dt>Modelo</dt><dd>{{ item.model || '—' }}</dd></div>
              <div><dt>Credencial</dt><dd>{{ item.api_key_source ? item.api_key_source : 'nenhuma' }}</dd></div>
            </dl>
            <footer>
              <button type="button" class="btn-ghost small" @click="test(item.name)">Testar</button>
              <button type="button" class="btn-ghost small" @click="fetchModels(item.name)">Modelos</button>
              <span class="health" v-if="state.providerHealth[item.name]">
                <span
                  class="dot"
                  :class="state.providerHealth[item.name].ok ? 'dot-ok' : 'dot-err'"
                ></span>
                {{ state.providerHealth[item.name].ok
                  ? 'ok'
                  : (state.providerHealth[item.name].detail || 'sem resposta') }}
              </span>
            </footer>
          </article>

          <p class="muted" v-if="!state.providers.length">
            Nenhum provedor configurado ainda. Use “Adicionar provedor” para criar o primeiro.
          </p>
        </div>

        <div class="provider-form card">
          <h3>{{ editing ? 'Editar provedor' : 'Novo provedor' }}</h3>

          <label class="field">
            <span>Nome</span>
            <input v-model="form.name" type="text" placeholder="ex.: ollama_remoto" />
            <small class="muted">Como o provedor aparece nas listas e no run.</small>
          </label>

          <label class="field">
            <span>Tipo</span>
            <select v-model="form.type" @change="onTypeChange">
              <option v-for="item in TYPES" :key="item.id" :value="item.id">{{ item.label }}</option>
            </select>
            <small class="muted">{{ typeInfo().hint }}</small>
          </label>

          <label class="field" v-if="form.type !== 'mock'">
            <span>URL base</span>
            <input v-model="form.base_url" type="url" :placeholder="typeInfo().url" />
          </label>

          <label class="field">
            <span>Modelo</span>
            <input v-model="form.model" type="text" placeholder="ex.: llama3.2" list="model-list" />
            <datalist id="model-list">
              <option v-for="item in models" :key="item" :value="item"></option>
            </datalist>
            <small class="muted">Vazio = usa o modelo padrão do Callidus.</small>
          </label>

          <fieldset class="field secret-field">
            <legend>Credencial</legend>
            <label class="field">
              <span>Variável de ambiente</span>
              <input v-model="form.api_key_env" type="text" placeholder="ex.: OPENROUTER_API_KEY" />
              <small class="muted">A chave vem do ambiente do servidor — nada é gravado.</small>
            </label>
            <label class="field">
              <span>Ou cole a chave (gravada em arquivo protegido)</span>
              <div class="secret-row">
                <input v-model="secretInput" :type="showSecret ? 'text' : 'password'" placeholder="sk-…" autocomplete="off" />
                <button type="button" class="btn-ghost small" @click="showSecret = !showSecret">{{ showSecret ? 'ocultar' : 'mostrar' }}</button>
              </div>
              <small class="muted" v-if="state.providerConfig?.providers?.[form.name]?.secret?.configured">
                Já existe uma credencial gravada para este provedor.
                <button type="button" class="link-btn" @click="clearSecret(form.name)">apagar</button>
              </small>
            </label>
          </fieldset>

          <details class="advanced">
            <summary>Avançado</summary>
            <div class="grid-2">
              <label class="field">
                <span>Timeout (seg)</span>
                <input v-model="form.timeout" type="number" min="5" step="5" placeholder="120" />
              </label>
              <label class="field">
                <span>Tentativas extras</span>
                <input v-model="form.max_retries" type="number" min="0" max="5" />
              </label>
              <label class="field check">
                <input type="checkbox" v-model="form.allow_private_hosts" />
                <span>Permitir host interno (localhost, LAN)</span>
              </label>
              <label class="field check">
                <input type="checkbox" v-model="form.verify_tls" />
                <span>Verificar TLS</span>
              </label>
            </div>
            <div class="grid-2" v-if="form.type === 'openrouter'">
              <label class="field">
                <span>HTTP-Referer</span>
                <input v-model="form.referer" type="url" placeholder="https://callidus.local" />
              </label>
              <label class="field">
                <span>X-Title</span>
                <input v-model="form.title" type="text" placeholder="Callidus" />
              </label>
            </div>
          </details>

          <div class="form-actions">
            <button type="button" class="btn-primary" :disabled="saving" @click="save()">
              {{ saving ? 'Salvando…' : 'Salvar provedor' }}
            </button>
            <button type="button" class="btn-ghost" @click="startNew()">Limpar</button>
          </div>
        </div>
      </div>
    </section>
  `,
};
