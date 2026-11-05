export function createLearningView({ dom, state, actions, api }) {
  const { $, el, button } = dom;
  const views = new Map(),
    loaders = {
      graph: () => import("./knowledge.js").then((m) => m.createKnowledgeView),
      files: () => import("./files.js").then((m) => m.createFilesView),
      settings: () => import("./settings.js").then((m) => m.createSettingsView),
      evaluation: () =>
        import("./evaluation.js").then((m) => m.createEvaluationView),
    };
  let ticket = 0,
    active = null;
  function destroy() {
    ticket++;
    active?.destroy?.();
    active = null;
  }
  async function render() {
    const current = ++ticket;
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
    const id = state.learn;
    try {
      let view = views.get(id);
      if (!view) {
        const createView = await loaders[id]();
        if (current !== ticket) return;
        view = createView({ dom, state, actions, api });
        views.set(id, view);
      }
      if (current !== ticket) return;
      active = view;
      await view.render();
    } catch (error) {
      if (current === ticket) actions.status(error.message);
    }
  }
  return { render, destroy };
}
