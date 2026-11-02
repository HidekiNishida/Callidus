/**
 * Arquivo: web/static/assets/app/components/narration.js
 * Nome: narration.js
 * Propósito: mostrar a fala do agente na linha do tempo, crescendo conforme os fragmentos chegam do modelo.
 * Responsabilidade: frontend/componente — uma narração (em andamento, concluída ou interrompida).
 * Componentes: NarrationEntry (componente Vue), narrationState().
 * Dependências: `../store.js` (tarefas, para dizer qual etapa fala), `../ui.js` (`icon`).
 * Observações: o texto é o que chegou do servidor, na ordem recebida; não há temporizador
 * revelando caracteres. O cursor é só um indicador visual de geração ativa. Este componente é o
 * único leitor de `entry.text`: cada fragmento redesenha só esta linha, não a conversa.
 */
import { state } from "../store.js";
import { icon } from "../ui.js";

/**
 * Estado visível de uma narração.
 *
 * Uma narração ainda "em andamento" numa mensagem que já parou foi cortada (processo
 * reiniciado, conexão perdida antes do fim): é mostrada como interrompida, sem cursor.
 *
 * @param {object} entry Linha de narração do feed.
 * @param {boolean} busy A mensagem ainda está em execução.
 * @returns {"streaming"|"done"|"interrupted"|"failed"} O estado para a interface.
 */
export function narrationState(entry, busy) {
  const status = entry?.status;
  if (status === "running") return busy ? "streaming" : "interrupted";
  if (status === "interrupted") return "interrupted";
  if (status === "error") return "failed";
  return "done";
}

export const NarrationEntry = {
  name: "NarrationEntry",
  props: {
    entry: { type: Object, required: true },
    busy: { type: Boolean, default: false },
    rootId: { type: String, default: "" },
  },
  setup(props) {
    const view = Vue.computed(() => narrationState(props.entry, props.busy));
    // Quem fala: numa execução com etapas, a etapa filha que gerou o texto.
    const speaker = Vue.computed(() => {
      const taskId = props.entry.taskId;
      if (!taskId || taskId === props.rootId) return "";
      const task = (state.tasks || []).find((item) => item.id === taskId);
      return task ? task.display_title || task.title || "" : "";
    });
    const note = Vue.computed(() => {
      if (view.value === "interrupted") return "interrompida";
      if (view.value === "failed") return "a geração falhou";
      if (props.entry.gap && view.value === "streaming") return "reconectando o texto…";
      if (props.entry.truncated) return "texto longo: gravado em parte";
      return "";
    });
    return { view, speaker, note, icon };
  },
  template: `
    <div
      class="narration"
      :class="'narration-' + view"
      :aria-busy="view === 'streaming' ? 'true' : 'false'"
    >
      <span class="narration-ico" v-html="icon('spark', 13)"></span>
      <div class="narration-body">
        <span class="narration-speaker" v-if="speaker">{{ speaker }}</span>
        <p class="narration-text">{{ entry.text }}<span
            class="narration-cursor"
            v-if="view === 'streaming'"
            aria-hidden="true"
          ></span></p>
        <span class="narration-note" v-if="note">{{ note }}</span>
      </div>
    </div>
  `,
};
