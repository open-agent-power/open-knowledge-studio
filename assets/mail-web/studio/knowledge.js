import { createGraph } from "./graph-pixi.js";
import { callTimeline } from "./call-trace.js";
import {
  knowledgeTree,
  projectKnowledge,
  projectDocuments,
  documentNeighborhood,
  knowledgeRelations,
  projectQuery,
  usageColor,
  nodeHue,
  findNode,
  revealNode,
  mapQueryHits,
  categoryLabels,
  nodeCategory,
  nodeSize,
  filterKnowledge,
  subtreeIds,
  knowledgeOverview,
} from "./knowledge-model.js";

export function createKnowledgeView({ dom, state, actions, api }) {
  const { $, el, button } = dom;
  let dispose = () => {},
    timer = null,
    ticket = 0,
    expanded = new Set(),
    depth = 1,
    projectionMode = "documents",
    filterScope = "",
    hits = [],
    queryMode = false,
    querySequence = 0,
    query = "",
    selected = null,
    localFocus = null;
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
    aside.setAttribute("aria-label", "文档正文");
    const canvasHost = el("div", "graph-canvas-host");
    canvasHost.setAttribute("aria-label", "学习图谱");
    canvasHost.setAttribute("role", "group");
    stage.append(canvasHost);
    const tools = el("div", "knowledge-controls"),
      search = el("input");
    const categories = new Set(Object.keys(categoryLabels)),
      hidden = new Set();
    let only = null,
      visibleState = "all",
      selection = [];
    search.type = "search";
    search.placeholder = "搜索文件、标题或标签";
    search.value = query;
    search.setAttribute("aria-label", "搜索图谱");
    const reset = button("重置", () => {
      if (!actions.canLeave()) return;
      expanded.clear();
      depth = 1;
      query = "";
      localFocus = null;
      search.value = "";
      queryMode = false;
      hits = [];
      info.textContent = "";
      filterScope = "";
      sourceFilter.value = "";
      hidden.clear();
      only = null;
      selection = [];
      visibleState = "all";
      categories.clear();
      Object.keys(categoryLabels).forEach((kind) => categories.add(kind));
      for (const chip of categoryButtons) chip.setAttribute("aria-pressed", "true");
      stateFilter.value = "all";
      selectionTools.hidden = true;
      clearSelection(false);
      paint();
      graph.fit();
    });
    const run = button("Query", runQuery, "soft");
    run.title = "执行现有 Wiki 召回；耗时包含请求往返";
    const info = el("span", "query-status");
    info.setAttribute("role", "status");
    const filterMenu = el("details", "knowledge-filter-menu"),
      filterPanel = el("div", "knowledge-filter-panel");
    filterMenu.append(el("summary", null, "筛选"), filterPanel);
    const localBar = el("div", "knowledge-local"),
      localTitle = el("span"),
      globalButton = button("返回全图", () => {
        if (!actions.canLeave()) return;
        localFocus = null;
        paint();
        graph.fit();
      });
    localBar.hidden = true;
    localBar.append(globalButton, localTitle);
    tools.append(search, reset, filterMenu, info, localBar);
    const mode = el("select");
    mode.setAttribute("aria-label", "图谱视图");
    for (const [value, label] of [
      ["documents", "文档关系"],
      ["hierarchy", "分类层级"],
    ]) {
      const option = el("option", null, label);
      option.value = value;
      mode.append(option);
    }
    mode.value = projectionMode;
    mode.onchange = () => {
      if (!actions.canLeave()) {
        mode.value = projectionMode;
        return;
      }
      projectionMode = mode.value;
      localFocus = null;
      clearSelection(false);
      paint();
      graph.fit();
    };
    const sourceFilter = el("select");
    sourceFilter.setAttribute("aria-label", "筛选分类");
    sourceFilter.onchange = () => {
      if (!actions.canLeave()) {
        sourceFilter.value = filterScope;
        return;
      }
      filterScope = sourceFilter.value;
      localFocus = null;
      clearSelection(false);
      paint();
      graph.fit();
    };
    filterPanel.append(mode, sourceFilter);
    const filters = el("div", "knowledge-filters");
    const categoryButtons = [];
    for (const [kind, label] of Object.entries(categoryLabels)) {
      const chip = button(label, () => {
        if (!actions.canLeave()) return;
        categories.has(kind) ? categories.delete(kind) : categories.add(kind);
        chip.setAttribute("aria-pressed", String(categories.has(kind)));
        localFocus = null;
        clearSelection(false);
        paint();
      });
      chip.setAttribute("aria-pressed", "true");
      chip.style.setProperty("--category-color", `hsl(${nodeHue({ type: kind })} 48% 49%)`);
      categoryButtons.push(chip);
      filters.append(chip);
    }
    const stateFilter = el("select");
    stateFilter.setAttribute("aria-label", "图谱状态");
    for (const [value, label] of [
      ["all", "全部"],
      ["used", "已使用"],
    ]) {
      const option = el("option", null, label);
      option.value = value;
      stateFilter.append(option);
    }
    stateFilter.value = visibleState;
    stateFilter.onchange = () => {
      if (!actions.canLeave()) {
        stateFilter.value = visibleState;
        return;
      }
      visibleState = stateFilter.value;
      clearSelection(false);
      paint();
    };
    filters.append(stateFilter);
    filterPanel.append(filters, run);
    stage.append(tools);
    const selectionTools = el("div", "knowledge-selection");
    selectionTools.hidden = true;
    const selectedIds = () => new Set(selection.flatMap(subtreeIds));
    selectionTools.append(
      button("仅看选中", () => {
        if (!actions.canLeave()) return;
        only = selectedIds();
        clearSelection(false);
        paint();
      }),
      button("隐藏选中", () => {
        if (!actions.canLeave()) return;
        selectedIds().forEach((id) => hidden.add(id));
        clearSelection(false);
        paint();
      }),
    );
    stage.append(selectionTools);
    const legend = el("div", "knowledge-key");
    stage.append(legend);
    const zoom = el("div", "graph-tools");
    stage.append(zoom);
    const summary = el("div", "graph-summary");
    summary.setAttribute("aria-live", "polite");
    const empty = el("div", "graph-empty");
    const emptyMessage = el("p", null, "正在读取图谱…");
    const retry = button("重新读取", () => void refresh());
    retry.hidden = true;
    empty.append(emptyMessage, retry);
    const inputs = [search, run, reset, mode, sourceFilter, stateFilter];
    for (const input of inputs) input.disabled = true;
    stage.append(summary, empty);
    shell.append(stage, aside);
    $("content").append(shell);
    let map,
      usage,
      contexts = { entries: [], edges: [] },
      activity = { queried_paths: [], used_slugs: [] },
      roots = [],
      signature = "",
      refreshing = false,
      maxUses = 1,
      hitIds = new Set(),
      selectionSequence = 0,
      detailNode = null;
    const graph = createGraph(canvasHost, zoom, select, {
      button,
      showEdgeLabels: false,
      dimUnrelated: false,
      onBackground: clearSelection,
      nodeFill: (n) =>
        nodeCategory(n) === "raw"
          ? "#8795a9"
          : usageColor(n.uses, maxUses, false, nodeHue(n)),
      nodeRadius: nodeSize,
      nodeDashed: (n) => n.pending,
      nodeRegion: (node) =>
        projectionMode === "hierarchy" ? nodeCategory(node) : null,
      regionColor: (n) => `hsl(${nodeHue(n)} 45% 78%)`,
      separated: true,
      screenSize: true,
      insetTop: 82,
      insetBottom: 35,
      fitPadding: 24,
      onLasso: (nodes) => {
        if (!actions.canLeave()) return;
        invalidateQuery();
        selection = nodes;
        selectionTools.hidden = !nodes.length;
        selectionTools.setAttribute(
          "aria-label",
          `已圈选 ${nodes.length} 个节点`,
        );
      },
      nodeTitle: (n) =>
        `${n.title} · 显式使用 ${n.uses}${n.pending ? " · 待审核" : ""}`,
      nodeClass: (n) =>
        [
          n.pending || n.has_pending ? "pending-node" : "",
          hitIds.has(n.id) ? "query-hit" : "",
          activity.queried_paths.includes(n.path) ||
          activity.used_slugs.includes(
            n.path?.split("/").pop().replace(/\.md$/, ""),
          )
            ? "day-active"
            : "",
        ]
          .filter(Boolean)
          .join(" "),
    });
    dispose = () => graph.destroy();
    function invalidateQuery() {
      querySequence++;
      run.disabled = false;
      if (info.textContent === "查询中…") info.textContent = "";
    }
    function clearSelection(redraw = true) {
      if (!actions.canLeave()) return false;
      invalidateQuery();
      selectionSequence++;
      detailNode = null;
      selected = null;
      aside.hidden = true;
      aside.replaceChildren();
      shell.classList.remove("with-detail");
      if (redraw) paint();
      return true;
    }
    function paint() {
      legend.textContent = `大小 · ${projectionMode === "documents" ? "关联数" : "条目数"}`;
      if (!map) return;
      selection = [];
      selectionTools.hidden = true;
      const relations = knowledgeRelations(map, contexts);
      const scopeRoots = filterScope
        ? roots.filter((root) => root.id === filterScope)
        : roots;
      const scoped = filterKnowledge(scopeRoots, {
          categories,
          state: visibleState,
          hidden,
          only,
        }),
        hierarchy = filterScope ? scoped : knowledgeOverview(scoped);
      let projection =
        projectionMode === "documents"
          ? projectDocuments(
              scoped,
              relations,
              queryMode ? "" : query,
              queryMode ? new Set(hits.map((hit) => hit.nodeId)) : null,
            )
          : queryMode
            ? projectQuery(hierarchy, hits, relations)
            : projectKnowledge(hierarchy, expanded, depth, query, relations);
      if (
        localFocus &&
        !projection.nodes.some((node) => node.id === localFocus)
      )
        localFocus = null;
      if (localFocus) projection = documentNeighborhood(projection, localFocus);
      localBar.hidden = !localFocus;
      localTitle.textContent = localFocus
        ? findNode(roots, localFocus)?.title || ""
        : "";
      if (selected && !projection.nodes.some((n) => n.id === selected)) {
        selectionSequence++;
        detailNode = null;
        selected = null;
        aside.hidden = true;
        aside.replaceChildren();
        shell.classList.remove("with-detail");
      }
      maxUses = Math.max(
        1,
        ...projection.nodes.filter((n) => !n.children).map((n) => n.uses),
      );
      hitIds = new Set(hits.map((hit) => hit.nodeId));
      graph.update(projection.nodes, projection.edges, { selected });
      graph.setQuery?.(queryMode ? "" : query);
      empty.hidden = projection.nodes.length > 0;
      emptyMessage.textContent = "当前筛选没有文档";
      retry.hidden = true;
      summary.textContent = `${projection.nodes.length} ${projectionMode === "documents" ? "份文档" : "个节点"} · ${projection.edges.length} 条关系`;
    }
    function select(node) {
      if (current !== ticket || !actions.canLeave()) return false;
      invalidateQuery();
      if (localFocus) localFocus = node.id;
      void showSelection(findNode(roots, node.id) || node);
      return true;
    }
    async function showSelection(node) {
      const sequence = ++selectionSequence;
      detailNode = node;
      revealNode(roots, node.id, expanded);
      selected = node.id;
      aside.hidden = false;
      shell.classList.add("with-detail");
      aside.replaceChildren();
      const heading = el("header"),
        close = button("×", clearSelection);
      close.setAttribute("aria-label", "关闭详情");
      const detailHeading = el("h2", null, node.title);
      detailHeading.title = node.title;
      heading.append(detailHeading, close);
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
              invalidateQuery();
              queryMode = false;
              query = "";
              search.value = "";
              hits = [];
              info.textContent = "";
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
              invalidateQuery();
              queryMode = false;
              query = "";
              search.value = "";
              hits = [];
              info.textContent = "";
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
        const documentTools = el("div", "branch-tools");
        documentTools.append(
          button(
            "只看直接关联",
            () => {
              if (!actions.canLeave()) return;
              projectionMode = "documents";
              mode.value = projectionMode;
              query = search.value = "";
              queryMode = false;
              hits = [];
              info.textContent = "";
              localFocus = node.id;
              paint();
              graph.fit();
            },
            "soft",
          ),
        );
        const label = el("p", "knowledge-kind", node.pending ? "待审核" : categoryLabels[nodeCategory(node)] || "文档");
        const body = el("article", "knowledge-body markdown-body");
        body.setAttribute("aria-label", "文档正文");
        body.textContent = "正在读取正文…";
        const metadata = el("details", "node-attributes");
        metadata.append(
          el("summary", null, "文件信息"),
          el("code", "detail-path", node.path),
        );
        if (node.uses)
          metadata.append(el("span", "detail-meta", `显式使用 ${node.uses}`));
        if (node.tags?.length)
          metadata.append(el("span", "detail-meta", node.tags.join(" · ")));
        for (const [key, value] of Object.entries(
          node.metadata || node.governance || {},
        )) {
          const row = el("div", "attribute-row");
          row.append(el("span", null, key), el("span", null, String(value)));
          metadata.append(row);
        }
        const links = el("div", "knowledge-reading-links");
        for (const [url, title] of [
          [node.url, "来源"],
          [node.evidence_url, "依据"],
          [node.approval_url, "审核记录"],
        ]) {
          if (!url) continue;
          const link = el("a", null, title);
          link.href = url;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          links.append(link);
        }
        // Reading leads; graph actions and file internals remain secondary.
        aside.append(label, body, links, metadata, documentTools);
        if (node.pending && node.path?.startsWith("drafts/")) {
          const reviewLink = el("a", "knowledge-child", "打开草稿审核");
          reviewLink.href = "/review?detail=1&draft=" + encodeURIComponent(node.path);
          aside.append(reviewLink);
        }
        const active = () =>
          current === ticket &&
          sequence === selectionSequence &&
          selected === node.id;
        const loadBody = async () => {
          body.textContent = "正在读取正文…";
          try {
            const isMemory = node.path?.startsWith("wiki/") || node.path?.startsWith("drafts/");
            const file = await api.request((isMemory ? "/api/mail/memory/item?" : "/api/studio/file?") +
              new URLSearchParams(isMemory ? { path: node.path, full: "1" } : { path: node.path }));
            if (!active()) return;
            if (typeof file.body_html !== "string")
              throw Error("正文格式不完整，请重试");
            body.innerHTML = file.body_html;
            const first = body.firstElementChild;
            if (
              /^H[1-6]$/.test(first?.tagName) &&
              first.textContent.trim() === node.title.trim()
            )
              first.remove();
            if (!file.body?.trim())
              body.append(el("p", "detail-meta", "这篇文档暂无正文。"));
            if (file.truncated)
              body.append(
                el("p", "detail-meta", "正文超出读取上限，当前显示部分内容。"),
              );
          } catch (error) {
            if (!active()) return;
            body.replaceChildren(
              el("p", null, "正文读取失败：" + error.message),
              button("重试", loadBody, "soft"),
            );
          }
        };
        await loadBody();
        if (!active()) return;
        if (current !== ticket) return;
        const neighborIds = new Set();
        for (const edge of knowledgeRelations(map, contexts)) {
          if (edge.type === "shared_tag") continue;
          if (edge.a === node.id) neighborIds.add(edge.b);
          if (edge.b === node.id) neighborIds.add(edge.a);
        }
        const related = [...neighborIds]
          .map((id) => findNode(roots, id))
          .filter(Boolean);
        if (related.length) {
          aside.append(
            el("div", "detail-meta", `直接关联 · ${related.length}`),
          );
          for (const other of related) {
            if (other)
              aside.append(
                button(
                  other.title,
                  () => {
                    if (!actions.canLeave()) return;
                    query = search.value = "";
                    queryMode = false;
                    hits = [];
                    filterScope = sourceFilter.value = "";
                    visibleState = stateFilter.value = "all";
                    projectionMode = mode.value = "documents";
                    only = null;
                    hidden.delete(other.id);
                    select(other);
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
      if (!actions.canLeave()) {
        search.value = query;
        return;
      }
      invalidateQuery();
      query = search.value;
      localFocus = null;
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
      if (!actions.canLeave()) return;
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
        if (
          current !== ticket ||
          sequence !== querySequence ||
          !actions.canLeave()
        )
          return;
        hits = mapQueryHits(roots, [
          ...(result.knowledge || []),
          ...(result.team_knowledge || []),
        ]);
        queryMode = true;
        localFocus = null;
        for (const hit of hits)
          if (hit.nodeId) revealNode(roots, hit.nodeId, expanded);
        selected = null;
        aside.hidden = false;
        shell.classList.add("with-detail");
        aside.replaceChildren();
        const header = el("header");
        const close = button("×", clearSelection);
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
        if (result.diagnostics?.call_trace)
          aside.append(callTimeline(dom, result.diagnostics.call_trace));
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
        if (current === ticket && sequence === querySequence) {
          info.textContent = "查询失败";
          actions.status(error.message);
        }
      } finally {
        if (current === ticket && sequence === querySequence)
          run.disabled = false;
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
          api.request(
            "/api/studio/activity?" +
              new URLSearchParams({ date: state.date || "" }),
          ),
        ]);
        if (
          current !== ticket ||
          state.tab !== "learning" ||
          state.learn !== "graph"
        )
          return;
        const next = JSON.stringify(result);
        if (next !== signature) {
          signature = next;
          if (!map) for (const input of inputs) input.disabled = false;
          let skills;
          [map, usage, skills, contexts, activity] = result;
          roots = knowledgeTree(map, usage, skills, contexts);
          const all = el("option", null, "全部分类");
          all.value = "";
          sourceFilter.replaceChildren(all);
          for (const root of roots) {
            const option = el("option", null, root.title);
            option.value = root.id;
            sourceFilter.append(option);
          }
          if (!roots.some((root) => root.id === filterScope)) filterScope = "";
          sourceFilter.value = filterScope;
          paint();
          const warnings = [...(map.warnings || []), ...(usage.warnings || []), ...(skills.warnings || []), ...(contexts.warnings || [])];
          if (map.scope?.truncated) warnings.push("图谱已达读取上限");
          if (warnings.length) actions.status(warnings.join("；"));
        }
        const node = selected && findNode(roots, selected);
        if (node && !node.children && node !== detailNode && !state.saving) {
          void showSelection(node);
        }
      } catch (error) {
        if (current === ticket) {
          actions.status(error.message);
          if (!map) {
            emptyMessage.textContent = "图谱读取失败";
            retry.hidden = false;
          }
        }
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
