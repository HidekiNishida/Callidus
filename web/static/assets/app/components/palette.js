/**
 * Arquivo: web/static/assets/app/components/palette.js
 * Nome: palette.js
 * Propósito: paleta de comandos (⌘K / Ctrl+K) com busca e navegação por teclado.
 * Responsabilidade: frontend/componente — reúne as ações da interface em uma lista filtrável.
 * Componentes: CommandPalette (componente Vue).
 * Dependências: `../store.js` (estado e ações), `../ui.js` (ícones).
 * Observações: os comandos contextuais (renomear, apagar) só entram na lista quando há conversa
 * ou projeto selecionado.
 */
import { state, openView, toast, deleteConversation, deleteProject } from "../store.js";
import { icon } from "../ui.js";

/**
 * Paleta de comandos: busca por texto, navegação por setas e execução com Enter.
 *
 * @returns {object} Objeto de opções do Vue com `setup()` e `template`.
 */
export const CommandPalette = {
  name: "CommandPalette",
  setup() {
    const query = Vue.ref("");
    const index = Vue.ref(0);
    const inputRef = Vue.ref(null);

    const commands = Vue.computed(() => {
      const items = [
        { group: "Navegar", label: "Nova conversa", icon: "plus", keys: "N", run: () => newConversation() },
        { group: "Navegar", label: "Novo projeto", icon: "folder", keys: "⇧N", run: () => window.dispatchEvent(new CustomEvent("callidus:new-project")) },
        { group: "Navegar", label: "Ver conversa", icon: "chat", keys: "1", run: () => openView("chat") },
        { group: "Navegar", label: "Acompanhamento", icon: "chart", keys: "2", run: () => openView("live") },
        { group: "Navegar", label: "Provedores", icon: "server", keys: "3", run: () => openView("providers") },
        { group: "Navegar", label: "Ajustes", icon: "cog", keys: "4", run: () => openView("settings") },
        { group: "Execução", label: "Um passo", icon: "play", run: () => window.dispatchEvent(new CustomEvent("callidus:step")) },
        { group: "Execução", label: "Executar automático", icon: "refresh", run: () => window.dispatchEvent(new CustomEvent("callidus:auto")) },
        { group: "Execução", label: "Pausar", icon: "pause", run: () => window.dispatchEvent(new CustomEvent("callidus:pause")) },
        { group: "Execução", label: "Parar execução", icon: "stop", run: () => window.dispatchEvent(new CustomEvent("callidus:cancel")) },
        { group: "Aparência", label: "Alternar tema", icon: state.theme === "dark" ? "sun" : "moon", run: () => toggleTheme() },
        { group: "Ajuda", label: "Atalhos de teclado", icon: "cog", run: () => openView("settings") },
      ];
      if (state.conversation) {
        items.push({
          group: "Ações",
          label: `Renomear conversa “${state.conversation.title || ""}”`,
          icon: "pencil",
          run: () => window.dispatchEvent(new CustomEvent("callidus:rename-conversation")),
        });
        items.push({
          group: "Ações",
          label: "Apagar conversa atual",
          icon: "trash",
          run: () => deleteConversation(state.conversation),
        });
      }
      if (state.selectedProject) {
        items.push({
          group: "Ações",
          label: `Remover projeto “${state.selectedProject.name}”`,
          icon: "trash",
          run: () => deleteProject(state.selectedProject),
        });
      }
      return items;
    });

    const results = Vue.computed(() => {
      const term = query.value.trim().toLowerCase();
      if (!term) return commands.value;
      return commands.value.filter((item) => item.label.toLowerCase().includes(term));
    });

    Vue.watch(
      () => state.paletteOpen,
      (open) => {
        if (open) {
          query.value = "";
          index.value = 0;
          setTimeout(() => inputRef.value?.focus(), 30);
        }
      },
    );

    Vue.watch(query, () => {
      index.value = 0;
    });

    /**
     * Fecha a paleta de comandos.
     *
     * @returns {void}
     */
    function close() {
      state.paletteOpen = false;
    }

    /**
     * Executa um comando e fecha a paleta.
     *
     * @param {object} item Comando escolhido (ou `null`).
     * @returns {void}
     */
    function run(item) {
      close();
      if (item) item.run();
    }

    /**
     * Trata as teclas da paleta (setas, Enter e Esc).
     *
     * @param {KeyboardEvent} event Evento de teclado.
     * @returns {void}
     */
    function onKeydown(event) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        index.value = Math.min(index.value + 1, results.value.length - 1);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        index.value = Math.max(index.value - 1, 0);
      } else if (event.key === "Enter") {
        event.preventDefault();
        run(results.value[index.value]);
      } else if (event.key === "Escape") {
        event.preventDefault();
        close();
      }
    }

    /**
     * Prepara uma conversa nova, limpando o contexto atual.
     *
     * @returns {void}
     */
    function newConversation() {
      openView("chat");
      state.conversation = null;
      state.tasks = [];
      toast("Nova conversa — escreva o objetivo abaixo", "ok");
    }

    /**
     * Alterna o tema claro/escuro e guarda a preferência no navegador.
     *
     * @returns {void}
     */
    function toggleTheme() {
      const next = state.theme === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      localStorage.setItem("callidus-theme", next);
      state.theme = next;
    }

    return { state, query, index, results, inputRef, close, run, onKeydown, icon };
  },
  template: `
    <Transition name="fade">
      <div class="palette-backdrop" v-if="state.paletteOpen" @click.self="close()" @keydown="onKeydown">
        <div class="palette" role="dialog" aria-modal="true" aria-label="Paleta de comandos">
          <input
            ref="inputRef"
            v-model="query"
            type="text"
            placeholder="Buscar comando… (Esc fecha)"
            aria-label="Buscar comando"
            @keydown="onKeydown"
          />
          <ul class="palette-list">
            <template v-for="(item, position) in results" :key="item.label + position">
              <li class="palette-group" v-if="position === 0 || results[position - 1].group !== item.group">{{ item.group }}</li>
              <li>
                <button
                  type="button"
                  class="palette-item"
                  :class="{ active: position === index }"
                  @mouseenter="index = position"
                  @click="run(item)"
                >
                  <span class="side-ico" v-html="icon(item.icon, 15)"></span>
                  <span>{{ item.label }}</span>
                  <span class="kbd" v-if="item.keys">{{ item.keys }}</span>
                </button>
              </li>
            </template>
            <li class="palette-group" v-if="!results.length">Nada encontrado</li>
          </ul>
        </div>
      </div>
    </Transition>
  `,
};
