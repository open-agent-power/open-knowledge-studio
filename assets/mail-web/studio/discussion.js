// Draft review and dated discussion history share the upstream SVG renderer.
import { drawGraph } from "./graph.js";
import { createDraftReader } from "./draft-reader.js";
import { createTimeline } from "./timeline.js";

function createSvgGraph(canvas, tools, onSelect, options) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", canvas.getAttribute("aria-label"));
  canvas.append(svg);
  let dispose = () => {};
  return {
    update(nodes, edges) {
      dispose();
      dispose = drawGraph(svg, nodes, edges, tools, onSelect, options);
    },
    destroy() {
      dispose();
    },
  };
}

export function createDiscussionView({ dom, state, actions, api, model }) {
  const { $, el, button } = dom;
  let dispose = () => {},
    update = null,
    selected = "",
    query = "",
    filter = "draft";
  let closeReader = () => {};
  const reader = createDraftReader({
    dom, state, actions, api,
    onChange: () => void actions.loadView(true),
    onClose: () => closeReader(),
    onOpen: (path) => {
      selected = path;
      state.scope = path;
      actions.updateRoute();
    },
  });
  function renderHistory() {
    const stage = el("div", "graph-stage discussion-stage"),
      canvas = el("div", "draft-graph-canvas"),
      tools = el("div", "graph-tools"),
      detail = el("div", "graph-detail");
    stage.setAttribute("aria-label", "讨论记录图谱");
    canvas.setAttribute("aria-label", "讨论历史图谱");
    detail.hidden = true;
    stage.append(canvas, detail, tools);
    $("content").append(stage);
    let currentFrame = state.view;
    const graph = createSvgGraph(canvas, tools, (node) => {
      detail.replaceChildren(el("strong", null, node.title));
      if (node.text) detail.append(el("p", null, node.text));
      const file = currentFrame.files?.[node.path];
      if (typeof file?.text === "string") {
        detail.append(el("span", "tiny",
          currentFrame.read_only ? "历史快照 · 只读" : "当前文件 · 只读"));
        if (typeof file.body_html === "string") {
          const body = el("article", "discussion-history-body markdown-body");
          body.innerHTML = file.body_html;
          detail.append(body);
        } else detail.append(el("pre", "discussion-history-body", file.text));
      }
      if (node.path) detail.append(el("code", null, node.path));
      detail.hidden = false;
    }, { button });
    const display = (view) => {
      currentFrame = view;
      const data = model.graph(view, true);
      graph.update(data.nodes, data.edges);
      detail.hidden = true;
    };
    display(state.view);
    const timeline = createTimeline({
      dom, api, events: state.view.timeline, canLeave: actions.canLeave,
      onSelect: display,
      onCurrent: () => display(state.view),
    });
    $("content").append(timeline.element);
    dispose = () => { timeline.destroy(); graph.destroy(); update = null; };
  }
  function render() {
    if (state.discuss === "history") return renderHistory();
    const workspace = el("div", "draft-discussion"),
      stage = el("section", "draft-graph"),
      sidebar = el("aside", "draft-reader"),
      heading = el("div", "draft-graph-heading"),
      tools = el("div", "graph-tools"),
      canvas = el("div", "draft-graph-canvas"),
      empty = el("p", "draft-graph-empty"),
      search = el("input"),
      status = el("select");
    sidebar.hidden = true;
    sidebar.setAttribute("aria-label", "草稿审阅");
    canvas.setAttribute("aria-label", "草稿与引用来源图谱");
    search.type = "search";
    search.placeholder = "查找草稿";
    search.setAttribute("aria-label", "查找草稿");
    search.value = query;
    status.setAttribute("aria-label", "草稿状态");
    for (const [value, label] of [
      ["draft", "待审阅"], ["promoted", "已入库"], ["all", "全部草稿"],
    ]) status.append(new Option(label, value));
    status.value = filter;
    const legend = el("div", "draft-legend");
    legend.append(el("span", "draft-legend-draft", "草稿"),
      el("span", "draft-legend-source", "引用来源"));
    heading.append(search, status, legend);
    stage.append(canvas, heading, empty, tools);
    workspace.append(stage, sidebar);
    $("content").append(workspace);
    let graph;
    const show = (path, restoring = false) => {
      const ownRestore = restoring && path === selected && reader.ownsDraft?.() &&
        !state.saving && !state.dirty && !state.settingsDirty;
      if (!ownRestore && actions.canLeave?.() === false) return false;
      selected = path;
      state.scope = path;
      const node = state.view?.nodes.find((item) => item.path === path);
      if (node?.type === "drafts" && filter !== "all") {
        const pending = !["promoted", "rejected", "not_proposed"].includes(node.review_status);
        if (filter === "draft" ? !pending : node.review_status !== filter)
          filter = status.value = "all";
      }
      actions.updateRoute();
      workspace.classList.add("has-reader");
      sidebar.hidden = false;
      void reader.open(sidebar, path);
      return true;
    };
    closeReader = () => {
      if (actions.canLeave?.() === false) return false;
      selected = "";
      state.scope = "";
      reader.close();
      sidebar.hidden = true;
      workspace.classList.remove("has-reader");
      actions.updateRoute();
      return true;
    };
    graph = createSvgGraph(canvas, tools, (node) => show(node.path), {
      button, showEdgeLabels: true, insetTop: 112, insetBottom: 60,
      nodeFill: (node) => node.type === "drafts" ? "#b79a59" : "#95a1b3",
      nodeRadius: (node) => node.type === "drafts" ? 12 : 6,
    });
    function display() {
      const view = state.view;
      const drafts = (view?.nodes || []).filter((node) =>
        node.type === "drafts" &&
        (filter === "all" || (filter === "draft"
          ? !["promoted", "rejected", "not_proposed"].includes(node.review_status)
          : node.review_status === filter)) &&
        (!query || node.title.toLocaleLowerCase().includes(query.toLocaleLowerCase())));
      const ids = new Set(drafts.map((node) => node.id));
      const edges = (view?.edges || []).filter((edge) => ids.has(edge.from));
      for (const edge of edges) ids.add(edge.to);
      const nodes = (view?.nodes || []).filter((node) => ids.has(node.id));
      graph.update(nodes, edges);
      empty.hidden = drafts.length > 0;
      empty.textContent = query ? "没有匹配的草稿"
        : filter === "promoted" ? "还没有已入库的草稿" : "暂无待审阅草稿";
    }
    search.oninput = () => { query = search.value.trim(); display(); };
    status.onchange = () => { filter = status.value; display(); };
    display();
    const initial = state.scope || selected;
    if ((state.view?.nodes || []).some((node) => node.path === initial))
      show(initial, true);
    else selected = "";
    update = () => {
      if ((state.scope || "") !== selected) {
        if ((state.view?.nodes || []).some((node) => node.path === state.scope))
          show(state.scope);
        else closeReader();
      }
      if (selected && !(state.view?.nodes || []).some((node) => node.path === selected))
        closeReader();
      display();
      void reader.refresh();
      return true;
    };
    dispose = () => { reader.close(); graph.destroy(); update = null; };
  }
  return {
    render,
    update: () => update?.() || false,
    destroy() { dispose(); dispose = () => {}; },
  };
}
