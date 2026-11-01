/**
 * Arquivo: web/static/assets/app/components/intelligence-subview.js
 * Nome: intelligence-subview.js
 * Propósito: wrapper para renderização dinâmica das sub-visões de inteligência usando render function.
 * Responsabilidade: frontend/componente — evita erro compiler-34 ao usar render function em vez de template com v-if/v-else-if.
 * Componentes: IntelligenceSubView.
 * Dependências: CognitiveGraphView, IntelligencePerformance, IntelligenceBenchmarks, IntelligenceDiagnostics.
 */
import { CognitiveGraphView } from "./intelligence-graph.js";
import { IntelligencePerformance } from "./intelligence-pages.js";
import { IntelligenceBenchmarks } from "./intelligence-pages.js";
import { IntelligenceDiagnostics } from "./intelligence-pages.js";

const componentMap = {
  overview: CognitiveGraphView,
  performance: IntelligencePerformance,
  benchmarks: IntelligenceBenchmarks,
  diagnostics: IntelligenceDiagnostics,
};

export const IntelligenceSubView = {
  name: "IntelligenceSubView",
  props: {
    subView: {
      type: String,
      required: true,
      validator: (v) => Object.keys(componentMap).includes(v),
    },
    runId: {
      type: String,
      default: null,
    },
  },
  render() {
    const Comp = componentMap[this.subView] || componentMap.overview;
    return window.Vue.h(Comp, {
      key: this.subView,
      runId: this.runId,
    });
  },
};