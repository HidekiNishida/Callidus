// web/static/assets/app/components/sidebar.js
import { state, selectProject, selectConversation, deleteConversation, deleteProject, conversationStatus, toast } from "../store.js";
import { icon, ago } from "../ui.js";

const STATUS_DOT = {
  working: "dot-live",
  attention: "dot-err",
  done: "dot-ok",
  idle: "dot-idle",
};

export const Sidebar = {
  name: "Sidebar",
  emits: ["new-project"],
  setup() {
    const filteredProjects = Vue.computed(() => {
      const term = state.search.trim().toLowerCase();
      if (!term) return state.projects;
      return state.projects.filter((project) => project.name.toLowerCase().includes(term));
    });
    const filteredLoose = Vue.computed(() => {
      const term = state.search.trim().toLowerCase();
      if (!term) return state.loose;
      return state.loose.filter((item) => (item.title || "").toLowerCase().includes(term));
    });
    const looseStatus = Vue.computed(() => {
      const map = {};
      state.loose.forEach((item) => {
        map[item.id] = conversationStatus(item);
      });
      return map;
    });
    return {
      state,
      filteredProjects,
      filteredLoose,
      looseStatus,
      STATUS_DOT,
      selectProject,
      selectConversation,
      deleteConversation,
      deleteProject,
      toast,
      icon,
      ago,
    };
  },
  template: `
    <aside class="sidebar" :class="{ open: state.railOpen }">
      <div class="sidebar-head">
        <img class="brand-lockup" src="/assets/brand/callidus-lockup.svg" alt="Callidus" width="132" height="34" />
        <button type="button" class="icon-btn" title="Novo projeto" aria-label="Novo projeto" @click="$emit('new-project')" v-html="icon('plus')"></button>
      </div>

      <div class="search-box">
        <span class="search-ico" v-html="icon('search', 14)"></span>
        <input type="search" v-model="state.search" placeholder="Buscar projeto…" aria-label="Buscar projeto" />
      </div>

      <div class="side-scroll">
        <p class="side-label" v-if="filteredLoose.length">
          Conversas <span class="count">{{ filteredLoose.length }}</span>
        </p>
        <ul class="side-list">
          <li v-for="item in filteredLoose" :key="item.id">
            <div class="side-item" :class="{ active: state.conversation && state.conversation.id === item.id }">
              <button type="button" class="side-hit" @click="selectConversation(item)">
                <span class="side-ico" v-html="icon('chat', 14)"></span>
                <span class="side-name">{{ item.title || 'Conversa' }}</span>
                <span class="dot" :class="STATUS_DOT[looseStatus[item.id] || 'idle']"></span>
                <span class="side-meta">{{ ago(item.updated_at) }}</span>
              </button>
              <button
                type="button"
                class="icon-btn ghost side-remove"
                title="Apagar conversa"
                aria-label="Apagar conversa"
                @click.stop="deleteConversation(item)"
                v-html="icon('trash', 14)"
              ></button>
            </div>
          </li>
        </ul>

        <p class="side-label" v-if="filteredProjects.length">
          Projetos <span class="count">{{ filteredProjects.length }}</span>
        </p>
        <ul class="side-list">
          <li v-for="project in filteredProjects" :key="project.id">
            <div class="side-item" :class="{ active: state.selectedProject && state.selectedProject.id === project.id }">
              <button type="button" class="side-hit" @click="selectProject(project)">
                <span class="side-ico" v-html="icon('folder', 14)"></span>
                <span class="side-name">{{ project.name }}</span>
              </button>
              <button
                type="button"
                class="icon-btn ghost side-remove"
                title="Remover projeto"
                aria-label="Remover projeto"
                @click.stop="deleteProject(project)"
                v-html="icon('trash', 14)"
              ></button>
            </div>
          </li>
        </ul>

        <p class="side-empty" v-if="!filteredProjects.length && !filteredLoose.length">
          Nenhum projeto ainda. Crie o primeiro para o Callidus trabalhar em uma pasta.
        </p>
      </div>

      <div class="sidebar-foot">
        <span class="dot dot-ok"></span>
        <span>API local</span>
        <span class="side-foot-version">v0.5</span>
      </div>
    </aside>
  `,
};
