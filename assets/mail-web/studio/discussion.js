import { createTimeline } from "./timeline.js";
// View module. State and side effects are supplied explicitly by the controller.
import { drawGraph as drawForceGraph } from "./graph.js";
export function createDiscussionView({ dom, state, actions, model: M, api }) {
  const { $, el, button } = dom;
  const { render, scopeFile } = actions;
  let expanded = false,
    destroyGraph = () => {};
  const drawGraph = (...args) =>
    drawForceGraph(...args, { entry: state.view.entry, button });
  function renderDiscussion() {
    let data = M.graph(state.view, expanded);
    const stage = el("div", "graph-stage");
    stage.setAttribute("aria-label", "目标及关联知识");
    const ns = "http://www.w3.org/2000/svg",
      svg = document.createElementNS(ns, "svg");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "目标、判断、知识与来源图谱");
    stage.append(svg);
    const detail = el("div", "graph-detail");
    detail.hidden = true;
    stage.append(detail);
    const tools = el("div", "graph-tools"),
      children = button(expanded ? "收起子目标" : "子目标", () => {
        expanded = !expanded;
        render();
      });
    tools.append(children);
    stage.append(tools);
    $("content").append(stage);
    let graphDispose = () => {};
    const display = (count) => {
      graphDispose();
      const nodes = data.nodes.slice(0, count),
        ids = new Set(nodes.map((n) => n.id));
      graphDispose = drawGraph(
        svg,
        nodes,
        data.edges.filter((e) => ids.has(e.from) && ids.has(e.to)),
        tools,
        (node) => {
          detail.replaceChildren(el("strong", null, node.title));
          if (node.text) detail.append(el("p", null, node.text));
          detail.append(el("code", null, node.path));
          const facts = el(
            "span",
            "tiny",
            node.alignment && node.alignment !== "unspecified"
              ? "记录状态：" + node.alignment
              : "",
          );
          detail.append(
            facts,
            button(
              node.type === "goal" || node.type === "todo"
                ? "打开目标文件"
                : "查看原文",
              () => scopeFile(node.path),
            ),
          );
          detail.hidden = false;
        },
      );
    };
    display(data.nodes.length);
    const timeline = createTimeline({
      dom,
      api,
      canLeave: actions.canLeave,
      events: state.view.timeline,
      onSelect: (frame) => {
        data = M.graph(frame, true);
        display(data.nodes.length);
        detail.hidden = true;
      },
      onCurrent: () => {
        data = M.graph(state.view, expanded);
        display(data.nodes.length);
      },
    });
    $("content").append(timeline.element);
    destroyGraph = () => {
      timeline.destroy();
      graphDispose();
    };
  }
  return {
    render: renderDiscussion,
    destroy() {
      destroyGraph();
      destroyGraph = () => {};
    },
  };
}
