import { drawGraph } from "./graph.js";
import { callTimeline } from './call-trace.js';
import {
  knowledgeTree,
  projectKnowledge,
  projectQuery,
  usageColor,
  nodeHue,
  findNode,
  revealNode,
  mapQueryHits,
} from "./knowledge-model.js";

export function createKnowledgeView({ dom, state, actions, api }) {
  const { $, el, button } = dom;
  let dispose = () => {},
    timer = null,
    ticket = 0,
    expanded = new Set(),
    depth = 1,
    hits = [],
    queryMode = false,
    querySequence = 0,
    query = "",
    selected = null;
  function destroy() {
    ticket++;
    dispose();
    dispose = () => {};
    clearInterval(timer);
  }
  async function render() {
    destroy();
    const current = ticket;
    const shell = el("div", "knowledge-map"),
      stage = el("div", "graph-stage knowledge-stage"),
      aside = el("aside", "knowledge-detail");
    aside.hidden = true;
    aside.setAttribute("aria-label", "知识详情");
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("aria-label", "知识、草稿与技能分层图谱");
    svg.setAttribute("role", "group");
    stage.append(svg);
    const tools = el("div", "knowledge-controls"),
      search = el("input");
    search.type = "search";
    search.placeholder = "搜索";
    search.value = query;
    search.setAttribute("aria-label", "搜索图谱");
    const reset = button("收起", () => {
      expanded.clear();
      depth = 1;
      selected = null;
      aside.hidden = true;
      shell.classList.remove("with-detail");
      paint();
    });
    const run = button("Query", runQuery, "soft");
    run.title = "执行现有 Wiki 召回；耗时包含请求往返";
    const info = el("span", "query-status");
    info.setAttribute("role", "status");
    tools.append(search, run, reset, info);
    stage.append(tools);
    const zoom = el("div", "graph-tools");
    stage.append(zoom);
    shell.append(stage, aside);
    $("content").append(shell);
    let map,
      usage,
      skills,
      contexts,
      roots = [],
      signature = "",
      refreshing = false;
    function paint() {
      dispose();
      const relations = [...map.edges, ...(contexts?.edges || [])];
      const projection = queryMode
        ? projectQuery(roots, hits, relations)
        : projectKnowledge(roots, expanded, depth, query, relations);
      if (selected && !projection.nodes.some((n) => n.id === selected)) {
        selected = null;
        aside.hidden = true;
        shell.classList.remove("with-detail");
      }
      const maxUses = Math.max(1, ...roots.map((n) => n.uses));
      dispose = drawGraph(
        svg,
        projection.nodes,
        projection.edges,
        zoom,
        select,
        {
          button,
          showEdgeLabels: false,
          nodeFill: (n) => usageColor(n.uses, maxUses, n.pending, nodeHue(n)),
          nodeRadius: (n) => (n.children ? 13 : 8),
          nodeDashed: (n) => n.pending,
          nodeRegion: (n) => n.family,
          regionColor: (n) => `hsl(${nodeHue(n)} 45% 78%)`,
        },
      );
      for (const n of svg.querySelectorAll(".studio-node")) {
        const node = projection.nodes.find((item) => item.id === n.dataset.id);
        n.querySelector("title").textContent =
          `${node.title} · 显式使用 ${node.uses}${node.pending ? " · 待审核" : ""}`;
        n.classList.toggle("selected", node.id === selected);
        n.classList.toggle("pending-node", node.pending || node.has_pending);
        n.classList.toggle(
          "query-hit",
          hits.some((h) => h.nodeId === node.id),
        );
      }
    }
    async function select(node) {
      if (current !== ticket) return;
      revealNode(roots, node.id, expanded);
      selected = node.id;
      aside.hidden = false;
      shell.classList.add("with-detail");
      aside.replaceChildren();
      const heading = el("header"),
        close = button("×", () => {
          selected = null;
          aside.hidden = true;
          shell.classList.remove("with-detail");
          paint();
        });
      close.setAttribute("aria-label", "关闭详情");
      heading.append(el("h2", null, node.title), close);
      aside.append(heading);
      if (node.children) {
        expanded.has(node.id)
          ? expanded.delete(node.id)
          : expanded.add(node.id);
        aside.append(
          el(
            "span",
            "detail-meta",
            `${node.children.length} 项 · 显式使用 ${node.uses}`,
          ),
        );
        const branchTools = el("div", "branch-tools");
        branchTools.append(
          button(
            "展开本区",
            () => {
              const open = (n) => {
                if (n.children) {
                  expanded.add(n.id);
                  n.children.forEach(open);
                }
              };
              queryMode = false;
              query = "";
              search.value = "";
              open(findNode(roots, node.id) || node);
              paint();
            },
            "soft",
          ),
          button(
            "收起本区",
            () => {
              const fold = (n) => {
                expanded.delete(n.id);
                n.children?.forEach(fold);
              };
              queryMode = false;
              query = "";
              search.value = "";
              fold(findNode(roots, node.id) || node);
              paint();
            },
            "soft",
          ),
        );
        aside.append(branchTools);
        for (const child of node.children)
          aside.append(
            button(child.title, () => select(child), "knowledge-child"),
          );
      } else {
        aside.append(
          el(
            "div",
            "detail-meta",
            [
              node.pending
                ? "待审核"
                : node.type === "skill"
                  ? "Skill"
                  : {
                      profile: "画像",
                      project: "项目",
                      goal: "目标",
                      discuss: "讨论",
                      team: "团队",
                      mail: "交接",
                    }[node.type] ||
                    node.review?.label ||
                    "Wiki",
              `显式使用 ${node.uses}`,
            ].join(" · "),
          ),
          el("code", "detail-path", node.path),
        );
        if (node.tags?.length)
          aside.append(el("div", "detail-meta", node.tags.join(" · ")));
        const body = el("pre", "knowledge-body", node.body || "");
        if (node.type === "skill") {
          try {
            const file = await api.request(
              "/api/studio/file?" + new URLSearchParams({ path: node.path }),
            );
            if (current === ticket && selected === node.id)
              body.textContent = file.text;
          } catch (error) {
            actions.status(error.message);
          }
        }
        if (node.url) {
          const link = el('a', 'detail-meta', '来源 ↗');
          link.href = node.url; link.target = '_blank'; link.rel = 'noopener noreferrer'; aside.append(link);
        }
        for (const [url, label] of [[node.evidence_url, '证据 ↗'], [node.approval_url, '审核 ↗']]) {
          if (!url) continue;
          const link = el('a', 'detail-meta', label); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; aside.append(link);
        }
        if (node.pending && node.type !== 'team') {
          aside.append(
            button(
              "审核",
              () => {
                aside.replaceChildren(heading);
                const frame = el("iframe", "knowledge-review");
                frame.title = "审核 " + node.title;
                frame.src =
                  "/review?panel=1&detail=1&draft=" +
                  encodeURIComponent(node.path);
                aside.append(frame);
              },
              "soft",
            ),
          );
        }
        aside.append(body);
        if (node.metadata || node.governance) {
          const attrs = el("details", "node-attributes");
          attrs.append(el("summary", null, "属性"));
          for (const [key, value] of Object.entries(
            node.metadata || node.governance,
          )) {
            const row = el("div", "attribute-row");
            row.append(el("span", null, key), el("span", null, String(value)));
            attrs.append(row);
          }
          aside.append(attrs);
        }
        if (node.body_truncated)
          aside.append(el("small", "detail-meta", "正文已截断"));
        if (current !== ticket) return;
        const related = (node.relations || []).filter((item) => item.resolved);
        if (related.length) {
          aside.append(el("div", "detail-meta", "关联"));
          for (const relation of related) {
            const other = map.domains
              .flatMap((d) => d.clusters.flatMap((c) => c.points))
              .find((p) => p.id === relation.target_id);
            if (other)
              aside.append(
                button(
                  other.title,
                  () => {
                    const find = (items) => {
                      for (const item of items) {
                        if (item.id === other.id) return item;
                        const found = item.children && find(item.children);
                        if (found) return found;
                      }
                    };
                    const target = find(roots);
                    if (target) select(target);
                  },
                  "knowledge-child",
                ),
              );
          }
        }
      }
      paint();
    }
    search.oninput = () => {
      querySequence++;
      query = search.value;
      queryMode = false;
      hits = [];
      info.textContent = "";
      paint();
    };
    search.onkeydown = (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        void runQuery();
      }
    };
    async function runQuery() {
      const text = search.value.trim();
      if (!text) return;
      const sequence = ++querySequence,
        start = performance.now();
      run.disabled = true;
      info.textContent = "查询中…";
      try {
        const result = await api.request("/api/workspace/query", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: text }),
        });
        if (current !== ticket || sequence !== querySequence) return;
        hits = mapQueryHits(roots, [...(result.knowledge || []), ...(result.team_knowledge || [])]);
        queryMode = true;
        for (const hit of hits)
          if (hit.nodeId) revealNode(roots, hit.nodeId, expanded);
        selected = null;
        aside.hidden = false;
        shell.classList.add("with-detail");
        aside.replaceChildren();
        const header = el("header");
        const close = button("×", () => {
          aside.hidden = true;
          shell.classList.remove("with-detail");
        });
        close.setAttribute("aria-label", "关闭详情");
        header.append(el("h2", null, text), close);
        aside.append(header);
        const elapsed = Math.round(performance.now() - start);
        info.textContent = `${elapsed} ms · ${hits.length} 命中`;
        const backend =
          result.diagnostics?.actual_backends?.join(", ") || "未报告";
        aside.append(
          el("div", "detail-meta", `${backend} · ${elapsed} ms（请求往返）`),
        );
        if (result.diagnostics?.call_trace) aside.append(callTimeline(dom, result.diagnostics.call_trace));
        for (const hit of hits) {
          const row = button(
            hit.title || hit.slug,
            () => {
              const target = findNode(roots, hit.nodeId);
              if (target) void select(target);
            },
            "knowledge-child",
          );
          row.disabled = !hit.nodeId;
          row.title = hit.nodeId || "不在当前图谱中";
          row.append(
            el(
              "small",
              "detail-meta",
              `相关性 ${Number.isFinite(hit.relevance ?? hit.score) ? Number(hit.relevance ?? hit.score).toFixed(3) : "—"}${hit.nodeId ? "" : " · 图谱未收录"}`,
            ),
          );
          aside.append(row);
        }
        const diagnostics = el("details", "node-attributes");
        diagnostics.append(
          el("summary", null, "诊断"),
          el("pre", null, JSON.stringify(result.diagnostics || {}, null, 2)),
        );
        aside.append(diagnostics);
        paint();
      } catch (error) {
        if (current === ticket) {
          info.textContent = "查询失败";
          actions.status(error.message);
        }
      } finally {
        if (current === ticket) run.disabled = false;
      }
    }
    async function refresh() {
      if (refreshing) return;
      refreshing = true;
      try {
        const result = await Promise.all([
          api.request("/api/mail/knowledge-map"),
          api.request("/api/studio/usage"),
          api.request("/api/studio/skills"),
          api.request("/api/studio/contexts"),
        ]);
        if (
          current !== ticket ||
          state.tab !== "learning" ||
          state.learn !== "graph"
        )
          return;
        const next = JSON.stringify(result);
        if (next === signature) return;
        signature = next;
        [map, usage, skills, contexts] = result;
        roots = knowledgeTree(map, usage, skills, contexts);
        paint();
        const warnings = [
          ...(usage.warnings || []),
          ...(skills.warnings || []),
          ...(contexts.warnings || []),
        ];
        if (map.scope?.truncated) warnings.push("图谱已达读取上限");
        if (warnings.length) actions.status(warnings.join("；"));
      } catch (error) {
        if (current === ticket) actions.status(error.message);
      } finally {
        refreshing = false;
      }
    }
    await refresh();
    if (current === ticket)
      timer = setInterval(() => {
        if (!document.hidden) void refresh();
      }, 10000);
  }
  return { render, destroy };
}
