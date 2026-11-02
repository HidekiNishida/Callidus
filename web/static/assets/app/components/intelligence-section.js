/**
 * Arquivo: web/static/assets/app/components/intelligence-section.js
 * Nome: intelligence-section.js
 * Propósito: seção completa de inteligência (abas + sub-visões) usando render function.
 * Responsabilidade: frontend/componente — evita erro compiler-34 ao isolar a seção de inteligência.
 * Componentes: IntelligenceSection.
 * Dependências: CognitiveGraphView, IntelligencePerformance, IntelligenceBenchmarks, IntelligenceDiagnostics.
 */
import { CognitiveGraphView } from "./intelligence-graph.js";
import { IntelligencePerformance } from "./intelligence-pages.js";
import { IntelligenceBenchmarks } from "./intelligence-pages.js";
import { IntelligenceDiagnostics } from "./intelligence-pages.js";
import { IntelligenceContextConsumption } from "./intelligence-pages.js";
import { icon } from "../ui.js";

const componentMap = {
  overview: CognitiveGraphView,
  performance: IntelligencePerformance,
  benchmarks: IntelligenceBenchmarks,
  diagnostics: IntelligenceDiagnostics,
  consumo: IntelligenceContextConsumption,
};

export const IntelligenceSection = {
  name: "IntelligenceSection",
  props: {
    subView: {
      type: String,
      required: true,
      validator: (v) => ["overview", "performance", "benchmarks", "diagnostics", "consumo"].includes(v),
    },
    runId: {
      type: String,
      default: null,
    },
  },
  render() {
    const subView = this.subView;
    const runId = this.runId;
    const Comp = componentMap[subView] || componentMap.overview;

    return window.Vue.h("div", { class: "intelligence-container" }, [
      window.Vue.h("nav", {
        class: "intelligence-tabs",
        role: "tablist",
        "aria-label": "Seções de inteligência",
      }, [
        window.Vue.h("button", {
          role: "tab",
          class: { active: subView === "overview" },
          onClick: () => this.$emit("set-sub-view", "overview"),
          "aria-selected": subView === "overview",
        }, [
          window.Vue.h("span", { domProps: { innerHTML: icon("layout", 15) } }),
          "Overview",
        ]),
        window.Vue.h("button", {
          role: "tab",
          class: { active: subView === "performance" },
          onClick: () => this.$emit("set-sub-view", "performance"),
          "aria-selected": subView === "performance",
        }, [
          window.Vue.h("span", { domProps: { innerHTML: icon("activity", 15) } }),
          "Desempenho",
        ]),
        window.Vue.h("button", {
          role: "tab",
          class: { active: subView === "benchmarks" },
          onClick: () => this.$emit("set-sub-view", "benchmarks"),
          "aria-selected": subView === "benchmarks",
        }, [
          window.Vue.h("span", { domProps: { innerHTML: icon("bar-chart", 15) } }),
          "Benchmarks",
        ]),
        window.Vue.h("button", {
          role: "tab",
          class: { active: subView === "diagnostics" },
          onClick: () => this.$emit("set-sub-view", "diagnostics"),
          "aria-selected": subView === "diagnostics",
        }, [
          window.Vue.h("span", { domProps: { innerHTML: icon("alert-circle", 15) } }),
          "Diagnósticos",
        ]),
        window.Vue.h("button", {
          role: "tab",
          class: { active: subView === "consumo" },
          onClick: () => this.$emit("set-sub-view", "consumo"),
          "aria-selected": subView === "consumo",
        }, [
          window.Vue.h("span", { domProps: { innerHTML: icon("layers", 15) } }),
          "Consumo de contexto",
        ]),
      ]),
      window.Vue.h("div", { class: "intelligence-sub-views" }, [
        window.Vue.h(componentMap.overview, {
          key: "intelligence-overview",
          runId: this.runId,
          style: { display: subView === "overview" ? "block" : "none" },
        }),
        window.Vue.h(componentMap.performance, {
          key: "intelligence-performance",
          runId: this.runId,
          style: { display: subView === "performance" ? "block" : "none" },
        }),
        window.Vue.h(componentMap.benchmarks, {
          key: "intelligence-benchmarks",
          style: { display: subView === "benchmarks" ? "block" : "none" },
        }),
        window.Vue.h(componentMap.diagnostics, {
          key: "intelligence-diagnostics",
          runId: this.runId,
          style: { display: subView === "diagnostics" ? "block" : "none" },
        }),
        window.Vue.h(componentMap.consumo, {
          key: "intelligence-consumo",
          runId: this.runId,
          style: { display: subView === "consumo" ? "block" : "none" },
        }),
      ]),
    ]);
  },
};