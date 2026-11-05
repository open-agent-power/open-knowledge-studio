// Owns the live SVG, camera and simulation for one mounted graph.
export function createGraph(svg, tools, onSelect, options) {
  const ns = "http://www.w3.org/2000/svg";
  const make = (tag, attrs = {}) => {
    const element = document.createElementNS(ns, tag);
    for (const [name, value] of Object.entries(attrs)) element.setAttribute(name, value);
    return element;
  };
  const set = (element, name, value) => {
    const text = String(value);
    if (element.getAttribute(name) !== text) element.setAttribute(name, text);
  };
  const world = make("g", { class: "graph-world" });
  const regionLayer = make("g", { class: "graph-regions", "pointer-events": "none" });
  const edgeLayer = make("g", { class: "graph-edges", "pointer-events": "none" });
  const dotLayer = make("g", { class: "graph-dots" });
  world.append(regionLayer, edgeLayer, dotLayer);
  svg.replaceChildren(world);
  const dots = new Map(), regions = new Map(), positions = new Map();
  const physicalKeys = new Set(["x", "y", "vx", "vy", "fx", "fy"]);
  const endpointKeys = new Set(["source", "target"]);
  const replaceMetadata = (target, snapshot, retained) => {
    for (const key of Object.keys(target)) {
      if (!retained.has(key) && !(key in snapshot)) delete target[key];
    }
    Object.assign(target, snapshot);
  };
  let lines = [], layout = null, selected = null, neighbors = new Set();
  let width = svg.clientWidth, height = svg.clientHeight;
  let zoom = 1, panX = 0, panY = 0, initialized = false;
  let raf = 0, dead = false, gesture = null, stepsLeft = 0;
  let cameraDirty = true, geometryDirty = true, labelsDirty = true;
  const motion = window.matchMedia?.("(prefers-reduced-motion: reduce)");
  const colors = {
    goal: "#67a18b", todo: "#a6c7b7", human_judgment: "#8299c6",
    agent_understanding: "#9c91b9", open_question: "#c6aa7b",
    discuss: "#9daecc", wiki: "#aab8d1", raw: "#c1c9d5",
    profiles: "#a2b9b0", skill: "#a89cc1", drafts: "#c2b18b",
  };

  function schedule() {
    if (!dead && !document.hidden && !raf) raf = requestAnimationFrame(frame);
  }
  function drawGeometry() {
    for (const { items, element } of regions.values()) {
      let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
      for (const node of items) {
        x0 = Math.min(x0, node.x);
        x1 = Math.max(x1, node.x);
        y0 = Math.min(y0, node.y);
        y1 = Math.max(y1, node.y);
      }
      set(element, "cx", (x0 + x1) / 2);
      set(element, "cy", (y0 + y1) / 2);
      set(element, "rx", (x1 - x0) / 2 + 38);
      set(element, "ry", (y1 - y0) / 2 + 38);
    }
    for (const { edge, line, label } of lines) {
      set(line, "x1", edge.source.x);
      set(line, "y1", edge.source.y);
      set(line, "x2", edge.target.x);
      set(line, "y2", edge.target.y);
      if (label) {
        set(label, "x", (edge.source.x + edge.target.x) / 2);
        set(label, "y", (edge.source.y + edge.target.y) / 2 - 5);
      }
    }
    for (const { node, group } of dots.values()) {
      set(group, "transform", `translate(${node.x},${node.y})`);
    }
  }
  function drawLabels() {
    // Text writes happen in update(). Read the changed titles as one batch.
    for (const record of dots.values()) {
      if (record.measure) {
        record.width = record.text.getComputedTextLength();
        record.measure = false;
      }
    }
    const screen = [...dots.values()].map(({ node, radius, width: textWidth }) => ({
      id: node.id,
      x: width / 2 + panX + node.x * zoom,
      y: height / 2 + panY + node.y * zoom,
      width: textWidth,
      radius: Math.max(3, radius * zoom + 2),
      priority: node.id === selected ? 30 : neighbors.has(node.id) ? 20 : node.id === options.entry ? 10 : 0,
    }));
    const obstacles = screen.map((node) => ({
      left: node.x - node.radius, right: node.x + node.radius,
      top: node.y - node.radius, bottom: node.y + node.radius,
    }));
    const placed = window.OksGraphLabels?.graphLabelPositions(screen, width, height, obstacles);
    for (const { node, text } of dots.values()) {
      text.style.fontSize = 11 / zoom + "px";
      const position = placed?.get(node.id);
      text.style.display = placed && !position ? "none" : "";
      set(text, "x", position ? (position.x - width / 2 - panX) / zoom - node.x : 0);
      set(text, "y", position ? (position.y - height / 2 - panY) / zoom - node.y : 26 / zoom);
    }
  }
  function frame() {
    raf = 0;
    if (dead || document.hidden || width <= 0 || height <= 0) return;
    if (stepsLeft && !gesture) {
      if (!layout.step()) stepsLeft = 0;
      else stepsLeft--;
      geometryDirty = true;
    }
    if (geometryDirty) drawGeometry();
    if (cameraDirty) {
      set(world, "transform", `translate(${width / 2 + panX},${height / 2 + panY}) scale(${zoom})`);
    }
    if (labelsDirty || geometryDirty || cameraDirty) drawLabels();
    cameraDirty = geometryDirty = labelsDirty = false;
    if (stepsLeft && !gesture) schedule();
  }
  function selection() {
    neighbors = new Set();
    for (const { edge, line, label } of lines) {
      const linked = edge.from === selected || edge.to === selected;
      if (linked) {
        neighbors.add(edge.from);
        neighbors.add(edge.to);
      }
      line.classList.toggle("is-neighbor", linked);
      label?.classList.toggle("is-neighbor", linked);
    }
    world.classList.toggle("has-selection", selected !== null);
    for (const record of dots.values()) {
      const active = record.node.id === selected;
      record.group.classList.toggle("selected", active);
      record.group.classList.toggle("is-neighbor", neighbors.has(record.node.id));
      set(record.group, "aria-pressed", active);
    }
    labelsDirty = true;
    schedule();
  }
  function activate(record) {
    if (dead || onSelect(record.node) === false) return;
    selected = record.node.id;
    selection();
  }
  function fit() {
    if (!layout?.nodes.length || width <= 0 || height <= 0) return;
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    for (const node of layout.nodes) {
      x0 = Math.min(x0, node.x);
      x1 = Math.max(x1, node.x);
      y0 = Math.min(y0, node.y);
      y1 = Math.max(y1, node.y);
    }
    zoom = Math.max(0.05, Math.min(1.2, (width - 64) / (x1 - x0 + 160), (height - 90) / (y1 - y0 + 140)));
    panX = -(x0 + x1) * zoom / 2;
    panY = -(y0 + y1) * zoom / 2;
    initialized = true;
    cameraDirty = true;
    schedule();
  }
  function update(items, edges, state = {}) {
    if (dead) return;
    const ids = new Set(items.map((node) => node.id));
    const links = edges.filter((edge) => ids.has(edge.from) && ids.has(edge.to));
    const changed = !layout || items.length !== dots.size || items.some((node) => !dots.has(node.id)) ||
      links.length !== lines.length || links.some((edge, i) => {
        const previous = lines[i].edge;
        return edge.from !== previous.from || edge.to !== previous.to || edge.type !== previous.type;
      });
    if (changed) {
      if (gesture) up({ type: "pointercancel", pointerId: gesture.id });
      for (const { node } of dots.values()) {
        positions.set(node.id, { x: node.x, y: node.y, vx: node.vx, vy: node.vy });
      }
      layout = window.createForceLayout(items, links, { distance: 160, repel: 3300 });
      const anchors = new Map();
      for (const edge of links) {
        if (positions.has(edge.from) && !anchors.has(edge.to)) anchors.set(edge.to, positions.get(edge.from));
        if (positions.has(edge.to) && !anchors.has(edge.from)) anchors.set(edge.from, positions.get(edge.to));
      }
      for (const [i, node] of layout.nodes.entries()) {
        const saved = positions.get(node.id);
        if (saved) Object.assign(node, saved);
        else {
          const anchor = anchors.get(node.id);
          if (anchor) {
            const angle = i * 2.399963, radius = 45 + Math.sqrt(i) * 9;
            node.x = anchor.x + Math.cos(angle) * radius;
            node.y = anchor.y + Math.sin(angle) * radius;
          }
        }
      }
      stepsLeft = motion?.matches || layout.nodes.length < 2 ? 0 : 220;
      geometryDirty = true;
    } else {
      const incoming = new Map(items.map((node) => [node.id, node]));
      for (const node of layout.nodes) replaceMetadata(node, incoming.get(node.id), physicalKeys);
      layout.edges.forEach((edge, i) => replaceMetadata(edge, links[i], endpointKeys));
    }
    for (const [id, record] of dots) {
      if (!ids.has(id)) {
        record.group.remove();
        dots.delete(id);
      }
    }
    for (const node of layout.nodes) {
      let record = dots.get(node.id);
      if (!record) {
        const group = make("g", { class: "studio-node", tabindex: 0, role: "button", "data-id": node.id });
        const hit = make("circle", { r: 20, fill: "transparent", "pointer-events": "all" });
        const dot = make("circle", { "stroke-width": 1.5 });
        const text = make("text", { "text-anchor": "middle" });
        const title = make("title");
        group.append(hit, dot, text, title);
        dotLayer.append(group);
        record = { node, group, dot, text, title, label: null, measure: true, width: 0 };
        dots.set(node.id, record);
        group.onkeydown = (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            activate(record);
          }
        };
      }
      record.node = node;
      set(record.group, "class", ["studio-node", options.nodeClass?.(node)].filter(Boolean).join(" "));
      set(record.group, "aria-label", node.title);
      record.radius = options.nodeRadius?.(node) ?? (node.id === options.entry ? 13 : node.type === "goal" ? 10 : 7);
      set(record.dot, "r", record.radius);
      set(record.dot, "fill", options.nodeFill?.(node) || colors[node.type] || "#b0bdd1");
      set(record.dot, "stroke", options.nodeDashed?.(node) ? "#a1aaba" : "var(--white, white)");
      set(record.dot, "stroke-dasharray", options.nodeDashed?.(node) ? "3 3" : "");
      const label = node.title.length > 18 ? node.title.slice(0, 18) + "…" : node.title;
      if (label !== record.label) {
        record.text.textContent = label;
        record.text.style.fontSize = "11px";
        record.text.style.display = "";
        record.label = label;
        record.measure = true;
      }
      record.title.textContent = options.nodeTitle?.(node) || node.text || node.title;
    }
    if (changed) {
      edgeLayer.replaceChildren();
      lines = layout.edges.map((edge) => {
        const line = make("line");
        const label = options.showEdgeLabels === false ? null : make("text", { "text-anchor": "middle", class: "edge-label" });
        edgeLayer.append(line);
        if (label) edgeLayer.append(label);
        return { edge, line, label };
      });
    }
    for (const { edge, line, label } of lines) {
      set(line, "stroke", edge.origin === "written_section" ? "#b8c5dc" : "#ccd5e3");
      set(line, "stroke-width", 1);
      set(line, "stroke-dasharray", edge.pending ? "4 4" : "");
      if (label) label.textContent = { contains: "包含", cites: "引用", states: "记录", source: "来源" }[edge.type] || edge.type;
    }
    const families = new Map();
    if (options.nodeRegion) for (const node of layout.nodes) {
      const family = options.nodeRegion(node);
      if (!family) continue;
      if (!families.has(family)) families.set(family, []);
      families.get(family).push(node);
    }
    for (const [family, record] of regions) {
      if ((families.get(family)?.length || 0) < 2) {
        record.element.remove();
        regions.delete(family);
      }
    }
    for (const [family, members] of families) {
      if (members.length < 2) continue;
      let record = regions.get(family);
      if (!record) {
        record = { element: make("ellipse", { opacity: 0.15 }), items: members };
        regionLayer.append(record.element);
        regions.set(family, record);
        geometryDirty = true;
      }
      record.items = members;
      set(record.element, "fill", options.regionColor?.(members[0]) || "#dae4f3");
    }
    geometryDirty = true;
    if ("selected" in state) selected = state.selected;
    if (!ids.has(selected)) selected = null;
    selection();
    if (!initialized) fit();
    labelsDirty = true;
    schedule();
  }
  const point = (event) => {
    const rect = svg.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  };
  function setZoom(value, x = width / 2, y = height / 2) {
    const next = Math.max(0.05, Math.min(3.5, value));
    if (next === zoom) return;
    panX = x - width / 2 - (x - width / 2 - panX) * next / zoom;
    panY = y - height / 2 - (y - height / 2 - panY) * next / zoom;
    zoom = next;
    cameraDirty = true;
    schedule();
  }
  const down = (event) => {
    if (event.button !== 0 || gesture) return;
    const p = point(event);
    const record = dots.get(event.target.closest(".studio-node")?.dataset.id);
    gesture = { id: event.pointerId, p, record, panX, panY, moved: false,
      offsetX: record ? (p.x - width / 2 - panX) / zoom - record.node.x : 0,
      offsetY: record ? (p.y - height / 2 - panY) / zoom - record.node.y : 0 };
    svg.setPointerCapture(event.pointerId);
    event.preventDefault();
  };
  const move = (event) => {
    if (!gesture || gesture.id !== event.pointerId) return;
    const p = point(event), dx = p.x - gesture.p.x, dy = p.y - gesture.p.y;
    if (Math.hypot(dx, dy) > 4) gesture.moved = true;
    if (!gesture.moved) return;
    if (gesture.record) {
      const node = gesture.record.node;
      node.x = node.fx = (p.x - width / 2 - panX) / zoom - gesture.offsetX;
      node.y = node.fy = (p.y - height / 2 - panY) / zoom - gesture.offsetY;
      geometryDirty = true;
    } else {
      panX = gesture.panX + dx;
      panY = gesture.panY + dy;
      cameraDirty = true;
    }
    schedule();
  };
  const up = (event) => {
    if (!gesture || gesture.id !== event.pointerId) return;
    const previous = gesture;
    gesture = null;
    if (previous.record) {
      previous.record.node.fx = previous.record.node.fy = null;
      if (!previous.moved && event.type === "pointerup") activate(previous.record);
      else if (previous.moved && !motion?.matches && layout.nodes.length > 1) {
        layout.reheat();
        stepsLeft = 180;
      }
    }
    if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
    schedule();
  };
  const wheel = (event) => {
    event.preventDefault();
    const p = point(event);
    const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? height : 1;
    setZoom(zoom * Math.exp(-event.deltaY * unit * 0.0015), p.x, p.y);
  };
  const visibility = () => {
    if (document.hidden) {
      cancelAnimationFrame(raf);
      raf = 0;
    } else schedule();
  };
  const reduceMotion = () => {
    if (motion.matches) stepsLeft = 0;
  };
  const fonts = () => {
    for (const record of dots.values()) {
      record.text.style.fontSize = "11px";
      record.text.style.display = "";
      record.measure = true;
    }
    labelsDirty = true;
    schedule();
  };
  const listeners = { pointerdown: down, pointermove: move, pointerup: up, pointercancel: up, lostpointercapture: up, wheel };
  for (const [name, handler] of Object.entries(listeners)) svg.addEventListener(name, handler, name === "wheel" ? { passive: false } : undefined);
  document.addEventListener("visibilitychange", visibility);
  motion?.addEventListener("change", reduceMotion);
  document.fonts?.addEventListener("loadingdone", fonts);
  const observer = new ResizeObserver(() => {
    const nextWidth = svg.clientWidth, nextHeight = svg.clientHeight;
    if (width === nextWidth && height === nextHeight) return;
    width = nextWidth;
    height = nextHeight;
    cameraDirty = true;
    if (!width || !height) {
      cancelAnimationFrame(raf);
      raf = 0;
      return;
    }
    if (!initialized) fit();
    schedule();
  });
  observer.observe(svg);
  const buttons = [["＋", "放大", () => setZoom(zoom * 1.2)], ["−", "缩小", () => setZoom(zoom / 1.2)], ["⌾", "适应画布", fit]].map(([label, name, action]) => {
    const element = options.button(label, action);
    element.dataset.zoom = "1";
    element.setAttribute("aria-label", name);
    tools.append(element);
    return element;
  });
  function destroy() {
    if (dead) return;
    dead = true;
    if (gesture?.record) gesture.record.node.fx = gesture.record.node.fy = null;
    if (gesture && svg.hasPointerCapture(gesture.id)) svg.releasePointerCapture(gesture.id);
    gesture = null;
    cancelAnimationFrame(raf);
    raf = 0;
    observer.disconnect();
    for (const [name, handler] of Object.entries(listeners)) svg.removeEventListener(name, handler);
    document.removeEventListener("visibilitychange", visibility);
    motion?.removeEventListener("change", reduceMotion);
    document.fonts?.removeEventListener("loadingdone", fonts);
    for (const button of buttons) button.remove();
    for (const record of dots.values()) record.group.onkeydown = null;
    dots.clear();
    regions.clear();
    positions.clear();
    lines = [];
    layout = null;
  }
  return { update, fit, destroy };
}
