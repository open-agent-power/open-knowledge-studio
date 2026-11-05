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
    const replay = el("div", "replay-tools"),
      play = button("▶", () => {}),
      speed = el("select"),
      seek = el("input");
    play.setAttribute("aria-label", "逐步展开当前图谱");
    for (const n of [0.5, 1, 2, 4]) speed.append(new Option(n + "×", n));
    speed.value = "1";
    speed.setAttribute("aria-label", "展开倍速");
    seek.type = "range";
    seek.min = 1;
    seek.max = Math.max(1, data.nodes.length);
    seek.value = seek.max;
    seek.setAttribute("aria-label", "展开进度");
    replay.append(play, speed, seek);
    stage.append(replay);
    $("content").append(stage);
    let graphDispose = () => {},
      timer = null,
      playing = false;
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
    const pause = () => {
      playing = false;
      clearTimeout(timer);
      play.textContent = "▶";
    };
    const tick = () => {
      if (!playing) return;
      let n = Number(seek.value) + 1;
      if (n > data.nodes.length) {
        pause();
        return;
      }
      seek.value = n;
      display(n);
      timer = setTimeout(tick, 1000 / Number(speed.value));
    };
    play.onclick = () => {
      if (playing) {
        pause();
        return;
      }
      if (!data.nodes.length) return;
      seek.value = 1;
      display(1);
      playing = true;
      play.textContent = "Ⅱ";
      timer = setTimeout(tick, 1000 / Number(speed.value));
    };
    seek.oninput = () => {
      pause();
      display(Number(seek.value));
    };
    speed.onchange = () => {
      if (playing) {
        clearTimeout(timer);
        timer = setTimeout(tick, 1000 / Number(speed.value));
      }
    };
    display(data.nodes.length);
    const timeline = createTimeline({
      dom,
      api,
      events: state.view.timeline,
      onSelect: (frame) => {
        pause();
        data = M.graph(frame, true);
        seek.max = Math.max(1, data.nodes.length);
        seek.value = seek.max;
        display(data.nodes.length);
        detail.hidden = true;
      },
      onCurrent: () => {
        data = M.graph(state.view, expanded);
        seek.max = Math.max(1, data.nodes.length);
        seek.value = seek.max;
        display(data.nodes.length);
      },
    });
    $("content").append(timeline.element);
    destroyGraph = () => {
      timeline.destroy();
      pause();
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
