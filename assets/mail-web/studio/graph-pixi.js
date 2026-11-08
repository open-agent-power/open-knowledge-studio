import { createRenderer } from "./graph-renderer.js";
import { createLayout } from "./graph-layout.js";
import { createGraphControls } from "./graph-controls.js";

const palette = {
  goal: "#689f8d",
  todo: "#9dbda9",
  human_judgment: "#7f97c5",
  agent_understanding: "#9c91b9",
  open_question: "#c6aa7b",
  discuss: "#a18cb8",
  wiki: "#8d9fb9",
  raw: "#aab5c4",
  profiles: "#a2b9b0",
  skill: "#a89cc1",
  drafts: "#c2b18b",
};
const edgeKey = (edge) =>
  JSON.stringify([edge.from, edge.to, edge.type, edge.id ?? null]);

export function createGraph(host, tools, onSelect, options = {}) {
  const cache = new Map(),
    proxies = new Map();
  let nodes = [],
    edges = [],
    selected = null,
    hover = null,
    keyboard = null;
  let dragged = null,
    lassoButton = null,
    lassoActive = false,
    dead = false,
    query = "",
    initializing = true,
    pendingFailure = null;
  const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const list = document.createElement("div");
  list.className = "graph-node-list";
  list.setAttribute("role", "group");
  list.setAttribute("aria-label", "图谱节点");
  const error = document.createElement("div");
  error.className = "graph-error";
  error.setAttribute("role", "alert");
  error.hidden = true;
  host.append(list, error);
  function failed(message) {
    if (dead) return;
    if (initializing) {
      pendingFailure = message;
      return;
    }
    destroy();
    error.textContent = "图谱加载失败 · " + message;
    error.hidden = false;
    host.append(error);
  }
  const renderer = createRenderer(
    host,
    {
      onSelect: activate,
      onHover(id) {
        if (dead || (id && !cache.has(id))) return;
        hover = id;
        highlight();
      },
      onBackground() {
        if (dead || options.onBackground?.() === false) return;
        proxies.get(keyboard)?.blur?.();
        keyboard = null;
        setSelection(null);
      },
      onDragStart(id) {
        if (dead) return;
        dragged = id;
        layout.dragStart(id);
      },
      onDragMove(id, x, y) {
        if (dead || !cache.has(id)) return;
        const node = cache.get(id);
        Object.assign(node, { x, y, targetX: x, targetY: y });
        layout.dragMove(id, x, y);
      },
      onDragEnd() {
        if (dead) return;
        dragged = null;
        layout.dragEnd();
      },
      onError: failed,
      onLasso(ids) {
        if (dead) return;
        lassoActive = false;
        lassoButton?.setAttribute("aria-pressed", "false");
        options.onLasso?.(ids.map((id) => cache.get(id)?.data).filter(Boolean));
      },
    },
    {
      reducedMotion: motion.matches,
      showEdgeLabels: options.showEdgeLabels !== false,
      insetTop: options.insetTop,
      insetBottom: options.insetBottom,
      fitPadding: options.fitPadding,
      screenSize: options.screenSize,
      insidePolygon,
    },
  );
  const layout = createLayout({
    onPositions: receive,
    onSettled(positions) {
      receive(positions);
      if (!dead) renderer.settled();
    },
    onError: failed,
  });
  const controls = createGraphControls(tools, {
    zoom: (factor) => {
      if (!dead) renderer.zoomBy(factor);
    },
    fit: () => {
      if (!dead) renderer.fit();
    },
    display: (values) => {
      if (!dead) renderer.configure(values);
    },
    physics: (values) => {
      if (!dead) layout.setParams(values);
    },
  });
  if (options.onLasso) {
    lassoButton = options.button("圈选", () => {
      if (dead) return;
      lassoActive = !lassoActive;
      lassoButton.setAttribute("aria-pressed", String(lassoActive));
      renderer.setLasso(lassoActive);
    });
    lassoButton.setAttribute("aria-pressed", "false");
    tools.append(lassoButton);
  }
  renderer.ready?.catch((failure) =>
    failed(failure.message || String(failure)),
  );
  function receive(positions) {
    if (dead || positions.length !== nodes.length * 3) return;
    for (let index = 0; index < nodes.length; index++) {
      const node = nodes[index];
      if (node.id === dragged) continue;
      const x = positions[index * 3],
        y = positions[index * 3 + 1];
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      node.targetX = x;
      node.targetY = y;
      if (
        !Number.isFinite(node.x) ||
        !Number.isFinite(node.y) ||
        motion.matches
      ) {
        node.x = x;
        node.y = y;
      }
    }
    renderer.positionsChanged();
  }
  function highlight() {
    if (!dead) renderer.focus({ selected, hover, keyboard });
  }
  function setSelection(id) {
    if (dead) return;
    selected = cache.has(id) ? id : null;
    for (const [key, proxy] of proxies)
      proxy.setAttribute("aria-pressed", String(key === selected));
    highlight();
  }
  function activate(id) {
    const node = cache.get(id);
    if (dead || !node) return false;
    if (onSelect(node.data) === false || dead || !cache.has(id)) return false;
    setSelection(id);
    return true;
  }
  function style(node) {
    const data = node.data;
    const classes = options.nodeClass?.(data) || "";
    node.title = data.title || data.text || data.id;
    node.color = options.nodeFill?.(data) || palette[data.type] || "#8d9fb9";
    node.region = options.nodeRegion?.(data) || null;
    node.regionColor = options.regionColor?.(data) || "#dae4f3";
    node.dayActive = classes.includes("day-active");
    node.radius =
      options.nodeRadius?.(data) ??
      (data.id === options.entry ? 9 : data.type === "goal" ? 8 : 5);
    node.pending = Boolean(
      options.nodeDashed?.(data) ||
      data.pending ||
      classes.includes("pending-node"),
    );
    node.queryHit =
      classes.includes("query-hit") ||
      Boolean(query && String(node.title).toLocaleLowerCase().includes(query));
  }
  function syncProxies() {
    for (const [id, proxy] of proxies) {
      if (cache.has(id)) continue;
      proxy.remove();
      proxies.delete(id);
    }
    for (const node of nodes) {
      let proxy = proxies.get(node.id);
      if (!proxy) {
        proxy = options.button(node.title, () => activate(node.id));
        proxy.className = "graph-node-proxy";
        proxy.dataset.id = node.id;
        proxy.onfocus = () => {
          if (dead || !cache.has(node.id)) return;
          keyboard = node.id;
          highlight();
          renderer.focusNode(node.id);
        };
        proxy.onblur = () => {
          if (dead || keyboard !== node.id) return;
          keyboard = null;
          highlight();
        };
        list.append(proxy);
        proxies.set(node.id, proxy);
      }
      proxy.textContent = node.title;
      proxy.setAttribute(
        "aria-label",
        options.nodeTitle?.(node.data) || node.title,
      );
      proxy.setAttribute("aria-pressed", String(node.id === selected));
    }
  }
  function update(items, incomingEdges, state = {}) {
    if (dead) return;
    const data = new Map(items.map((item) => [item.id, item]));
    const previousIds = new Set(nodes.map((node) => node.id));
    const previousAnchors = new Map(
      nodes.map((node) => [node.id, node.anchor]),
    );
    const nextNodes = nodes.filter((node) => data.has(node.id));
    for (const item of items) {
      if (previousIds.has(item.id)) continue;
      const node = { id: item.id, x: NaN, y: NaN, targetX: NaN, targetY: NaN };
      nextNodes.push(node);
      cache.set(item.id, node);
    }
    for (const id of cache.keys()) if (!data.has(id)) cache.delete(id);
    const previousEdges = new Map();
    for (const edge of edges) {
      const key = edgeKey(edge);
      if (!previousEdges.has(key)) previousEdges.set(key, []);
      previousEdges.get(key).push(edge);
    }
    let topology =
      nextNodes.length !== nodes.length ||
      nextNodes.some((node, index) => node !== nodes[index]);
    const nextEdges = incomingEdges
      .filter((edge) => data.has(edge.from) && data.has(edge.to))
      .map((edge) => {
        const matches = previousEdges.get(edgeKey(edge));
        const old = matches?.shift();
        if (!old) topology = true;
        return { ...edge };
      });
    if (nextEdges.length !== edges.length) topology = true;
    nodes = nextNodes;
    edges = nextEdges;
    for (const node of nodes) {
      node.data = data.get(node.id);
      style(node);
    }
    const families = [
      ...new Set(nodes.map((node) => node.region).filter(Boolean)),
    ];
    const anchors = new Map(
      families.map((key, index) => [
        key,
        {
          x: ((index % 3) - Math.min(2, families.length - 1) / 2) * 650,
          y:
            (Math.floor(index / 3) -
              Math.floor((families.length - 1) / 3) / 2) *
            500,
        },
      ]),
    );
    for (const node of nodes) {
      node.anchor = options.separated ? anchors.get(node.region) : undefined;
      const previous = previousAnchors.get(node.id);
      if (previous?.x !== node.anchor?.x || previous?.y !== node.anchor?.y)
        topology = true;
    }
    if (!cache.has(hover)) hover = null;
    if (!cache.has(keyboard)) keyboard = null;
    selected = "selected" in state ? state.selected : selected;
    if (!cache.has(selected)) selected = null;
    syncProxies();
    renderer.update(nodes, edges);
    highlight();
    if (topology) layout.update(nodes, edges);
  }
  function setQuery(value) {
    if (dead) return;
    const next = String(value || "")
      .trim()
      .toLocaleLowerCase();
    if (next === query) return;
    query = next;
    nodes.forEach(style);
    renderer.update(nodes, edges);
    const matches = nodes.filter((node) => node.queryHit);
    if (query && matches.length === 1) renderer.focusNode(matches[0].id);
  }
  function visibility() {
    if (dead) return;
    if (document.hidden) {
      layout.pause();
      renderer.pause();
    } else {
      layout.resume();
      renderer.resume();
    }
  }
  function motionChanged() {
    if (dead) return;
    renderer.configure({ reducedMotion: motion.matches });
    if (motion.matches)
      for (const node of nodes) {
        if (Number.isFinite(node.targetX)) node.x = node.targetX;
        if (Number.isFinite(node.targetY)) node.y = node.targetY;
      }
    renderer.positionsChanged();
  }
  const observer = new ResizeObserver(() => {
    if (!dead) renderer.resize();
  });
  observer.observe(host);
  document.addEventListener("visibilitychange", visibility);
  motion.addEventListener("change", motionChanged);
  initializing = false;
  if (pendingFailure !== null) failed(pendingFailure);
  else visibility();
  function destroy() {
    if (dead) {
      error.remove();
      return;
    }
    dead = true;
    observer.disconnect();
    document.removeEventListener("visibilitychange", visibility);
    motion.removeEventListener("change", motionChanged);
    controls.destroy();
    lassoButton?.remove();
    layout.destroy();
    renderer.destroy();
    list.remove();
    error.remove();
    cache.clear();
    proxies.clear();
    nodes = [];
    edges = [];
  }
  return {
    update,
    setQuery,
    setSelection,
    destroy,
    fit: () => {
      if (!dead) renderer.fit();
    },
    focus: (id) => {
      if (!dead && cache.has(id)) renderer.focusNode(id);
    },
    getCamera: () => renderer.getCamera(),
    setCamera: (camera) => {
      if (!dead) renderer.setCamera(camera);
    },
  };
}

export function insidePolygon(point, polygon) {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const a = polygon[i],
      b = polygon[j];
    if (
      a.y > point.y !== b.y > point.y &&
      point.x < ((b.x - a.x) * (point.y - a.y)) / (b.y - a.y) + a.x
    )
      inside = !inside;
  }
  return inside;
}
