import { createKnowledgeView } from "./knowledge.js";
import { createEvaluationView } from "./evaluation.js";
import { createFilesView } from "./files.js";

export function createLearningView({ dom, state, actions, api, settingsView }) {
  const { $, el, button } = dom;
  const graph = createKnowledgeView({ dom, state, actions, api });
  const evaluation = createEvaluationView({ dom, state, actions, api });
  const files = createFilesView({ dom, state, actions, api });
  function render() {
    const bar = el("div", "toolbar"),
      nav = el("div", "seg");
    // Old routes resolve into the same graph; there is no duplicate category UI.
    if (!["settings", "evaluation", "files"].includes(state.learn))
      state.learn = "graph";
    for (const [id, label] of [
      ["graph", "图谱"],
      ["files", "文件"],
      ["settings", "参数"],
      ["evaluation", "评测"],
    ])
      nav.append(
        button(
          label,
          () => {
            if (!actions.canLeave()) return;
            state.learn = id;
            state.legacyPanelHash = null;
            actions.render();
          },
          state.learn === id ? "active" : "",
        ),
      );
    bar.append(nav);
    $("content").append(bar);
    if (state.learn === "settings") void settingsView.render();
    else if (state.learn === "evaluation") void evaluation.render();
    else if (state.learn === "files") void files.render();
    else void graph.render();
  }
  return {
    render,
    destroy: () => {
      graph.destroy();
      evaluation.destroy();
      files.destroy();
    },
  };
}
