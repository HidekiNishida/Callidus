// web/static/assets/app/components/palette.js — paleta de comandos (⌘K / Ctrl+K)
import { state, openView, toast, deleteConversation, deleteProject } from "../store.js";
import { icon } from "../ui.js";

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

    function close() {
      state.paletteOpen = false;
    }

    function run(item) {
      close();
      if (item) item.run();
    }

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

    function newConversation() {
      openView("chat");
      state.conversation = null;
      state.tasks = [];
      toast("Nova conversa — escreva o objetivo abaixo", "ok");
    }

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
