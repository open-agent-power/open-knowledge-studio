// SVG interaction and lifecycle; reuses the existing force-layout engine.
export function drawGraph(
  svg,
  nodes,
  edges,
  tools,
  onSelect,
  { entry, button, nodeFill, nodeRadius, nodeDashed, nodeRegion, regionColor, showEdgeLabels = true, separated = false, onLasso, insetTop = 0, insetBottom = 0, screenSize = false },
) {
  const ns = "http://www.w3.org/2000/svg",
    make = (tag, attrs = {}) => {
      const n = document.createElementNS(ns, tag);
      for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
      return n;
    };
  svg.replaceChildren();
  tools.querySelectorAll("[data-zoom]").forEach((n) => n.remove());
  const families = [...new Set(nodes.map(n => nodeRegion?.(n)).filter(Boolean))];
  const anchors = new Map(families.map((key, i) => [key, {x:(i % 3 - Math.min(2, families.length - 1) / 2) * 650, y:(Math.floor(i / 3) - Math.floor((families.length - 1) / 3) / 2) * 500}]));
  const layout = window.createForceLayout(nodes, edges, {
      distance: 160,
      repel: 3300,
      ...(separated ? {center:.035, anchor:n => anchors.get(nodeRegion?.(n))} : {}),
    }),
    layer = make("g");
  svg.append(layer);
  let width = svg.clientWidth,
    height = svg.clientHeight,
    zoom = 1,
    panX = 0,
    panY = 0,
    raf = 0,
    dead = false,
    gesture = null,
    lasso = false;
  const centerY = () => (height + insetTop - insetBottom) / 2;
  const selection = make('path', {class:'graph-lasso', fill:'#6386c51a', stroke:'#6386c5', 'stroke-width':1.5, 'stroke-dasharray':'5 4', 'pointer-events':'none'});
  svg.append(selection);
  const colors = {
    goal: "#67a18b",
    todo: "#a6c7b7",
    human_judgment: "#8299c6",
    agent_understanding: "#9c91b9",
    open_question: "#c6aa7b",
    discuss: "#9daecc",
    wiki: "#aab8d1",
    raw: "#c1c9d5",
    profiles: "#a2b9b0",
    skill: "#a89cc1",
    drafts: "#c2b18b",
  };
  // Background regions follow explicit catalog families, not invented semantic
  // community edges. Recompute envelopes as the force layout moves.
  const grouped = new Map();
  if (nodeRegion) for (const node of layout.nodes) {
    const key = nodeRegion(node); if (!key) continue;
    if (!grouped.has(key)) grouped.set(key, []); grouped.get(key).push(node);
  }
  const regions = [...grouped.values()].filter(items => items.length > 1).map(items => {
    const n = make('ellipse', { fill: regionColor?.(items[0]) || '#dae4f3', opacity: '.18', 'pointer-events': 'none' });
    layer.append(n); return {items, n};
  });
  const lines = layout.edges.map((edge) => {
    const n = make("line", {
      stroke: edge.origin === "written_section" ? "#d5dced" : "#dfe5ef",
      "stroke-width": 1,
      "stroke-dasharray": edge.pending ? "4 4" : "",
    });
    layer.append(n);
    return { edge, n };
  });
  const labels = (showEdgeLabels ? layout.edges : []).map((edge) => {
    const n = make("text", { "text-anchor": "middle", class: "edge-label" });
    n.textContent =
      { contains: "包含", cites: "引用", states: "记录", source: "来源" }[
        edge.type
      ] || edge.type;
    layer.append(n);
    return { edge, n };
  });
  const dots = layout.nodes.map((node) => {
    const g = make("g", {
      class: "studio-node",
      tabindex: 0,
      role: "button",
      "aria-label": node.title,
      "data-id": node.id,
    });
    const dot = make("circle", {
      r: nodeRadius
        ? nodeRadius(node)
        : node.id === entry
          ? 13
          : node.type === "goal"
            ? 10
            : 7,
      fill: nodeFill ? nodeFill(node) : colors[node.type] || "#b0bdd1",
      stroke: nodeDashed?.(node)
        ? "#a1aaba"
        : node.type === "open_question"
          ? "#c5a373"
          : "white",
      "stroke-width": 1.5,
      "stroke-dasharray": nodeDashed?.(node) ? "3 3" : "",
    });
    const text = make("text", {
      "text-anchor": "middle",
      y: node.id === entry ? 31 : 26,
    });
    text.textContent =
      node.title.length > 18 ? node.title.slice(0, 18) + "…" : node.title;
    const title = make("title");
    title.textContent = node.text || node.title;
    const hit = make("circle", {
      r: 20,
      fill: "transparent",
      "pointer-events": "all",
    });
    g.append(hit, dot, text, title);
    g.onkeydown = (e) => {
      if (["Enter", " "].includes(e.key)) {
        e.preventDefault();
        onSelect(node);
      }
    };
    layer.append(g);
    return { node, g, text, dot, hit, radius:Number(dot.getAttribute('r')) };
  });
  function draw() {
    for (const {items, n} of regions) {
      const xs = items.map(i => i.x), ys = items.map(i => i.y);
      const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
      n.setAttribute('cx', (minX + maxX) / 2); n.setAttribute('cy', (minY + maxY) / 2);
      n.setAttribute('rx', (maxX - minX) / 2 + 38); n.setAttribute('ry', (maxY - minY) / 2 + 38);
    }
    layer.setAttribute(
      "transform",
      `translate(${width / 2 + panX},${centerY() + panY}) scale(${zoom})`,
    );
    for (const { edge, n } of lines) {
      n.setAttribute("x1", edge.source.x);
      n.setAttribute("y1", edge.source.y);
      n.setAttribute("x2", edge.target.x);
      n.setAttribute("y2", edge.target.y);
    }
    for (const { edge, n } of labels) {
      n.setAttribute("x", (edge.source.x + edge.target.x) / 2);
      n.setAttribute("y", (edge.source.y + edge.target.y) / 2 - 5);
    }
    for (const { node, g, dot, hit, radius } of dots) {
      g.setAttribute("transform", `translate(${node.x},${node.y})`);
      if (screenSize) {
        dot.setAttribute('r', Math.max(node.children ? 12 : 5, radius * zoom) / zoom);
        hit.setAttribute('r', Math.max(20, radius * zoom + 5) / zoom);
      }
    }
    if (window.OksGraphLabels) {
      const screen = dots.map(({ node, text, radius }) => {
        text.style.display = "";
        text.style.fontSize = 11 / zoom + "px";
        return {
          id: node.id,
          x: width / 2 + panX + node.x * zoom,
          y: centerY() + panY + node.y * zoom,
          width: text.getComputedTextLength() * zoom,
          radius: screenSize ? Math.max(node.children ? 12 : 5, radius * zoom) + 3 : 15,
          priority: node.id === entry ? 10 : node.children ? 5 : 0,
        };
      });
      const obstacles = screen.map((n) => ({
        left: n.x - n.radius,
        right: n.x + n.radius,
        top: n.y - n.radius,
        bottom: n.y + n.radius,
      }));
      const positions = window.OksGraphLabels.graphLabelPositions(
        screen,
        width,
        height,
        obstacles,
      );
      for (const { node, text } of dots) {
        const pos = positions.get(node.id);
        text.style.display = pos ? "" : "none";
        if (pos) {
          text.setAttribute("x", (pos.x - width / 2 - panX) / zoom - node.x);
          text.setAttribute("y", (pos.y - centerY() - panY) / zoom - node.y);
        }
      }
    }
  }
  function animate() {
    if (dead) return;
    if (layout.step()) {
      draw();
      raf = requestAnimationFrame(animate);
    } else {
      draw();
      raf = 0;
    }
  }
  function start() {
    if (!raf && !dead) raf = requestAnimationFrame(animate);
  }
  function fit() {
    if (!layout.nodes.length) return;
    const xs = layout.nodes.map((n) => n.x),
      ys = layout.nodes.map((n) => n.y),
      x0 = Math.min(...xs) - 100,
      x1 = Math.max(...xs) + 100,
      y0 = Math.min(...ys) - 65,
      y1 = Math.max(...ys) + 80;
    zoom = Math.max(
      0.2,
      Math.min(1.2, (width - 35) / (x1 - x0), (height - insetTop - insetBottom - 65) / (y1 - y0)),
    );
    panX = (-(x0 + x1) / 2) * zoom;
    panY = (-(y0 + y1) / 2) * zoom;
    draw();
  }
  layout.settle();
  fit();
  function addZoom(label, fn) {
    const b = button(label, fn);
    b.dataset.zoom = "1";
    tools.append(b);
  }
  addZoom("＋", () => {
    zoom = Math.min(3.5, zoom * 1.2);
    draw();
  });
  addZoom("−", () => {
    zoom = Math.max(0.2, zoom / 1.2);
    draw();
  });
  addZoom("⌾", fit);
  let lassoButton;
  if (onLasso) {
    lassoButton = button('圈选', () => {
      lasso = !lasso;
      lassoButton.setAttribute('aria-pressed', String(lasso));
      svg.classList.toggle('lasso-mode', lasso);
      selection.setAttribute('d', '');
    });
    lassoButton.dataset.zoom = '1';
    lassoButton.setAttribute('aria-pressed', 'false');
    tools.append(lassoButton);
  }
  const point = (e) => {
    const r = svg.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };
  const down = (e) => {
    if (e.button !== 0) return;
    if (lasso) {
      gesture = {id:e.pointerId, points:[point(e)]};
      svg.setPointerCapture(e.pointerId);
      e.preventDefault(); return;
    }
    const p = point(e),
      node = layout.nodes.find(
        (n) => n.id === e.target.closest(".studio-node")?.dataset.id,
      );
    gesture = { id: e.pointerId, p, node, panX, panY, moved: false };
    svg.setPointerCapture(e.pointerId);
    if (node) {
      node.fx = node.x;
      node.fy = node.y;
    }
    e.preventDefault();
  };
  const move = (e) => {
    if (!gesture || gesture.id !== e.pointerId) return;
    if (gesture.points) {
      const p = point(e), last = gesture.points.at(-1);
      if (Math.hypot(p.x-last.x,p.y-last.y) > 3) gesture.points.push(p);
      selection.setAttribute('d', gesture.points.map((p,i) => `${i?'L':'M'}${p.x},${p.y}`).join(' ')+' Z');
      return;
    }
    const p = point(e),
      dx = p.x - gesture.p.x,
      dy = p.y - gesture.p.y;
    if (Math.hypot(dx, dy) > 4) gesture.moved = true;
    if (!gesture.moved) return;
    if (gesture.node) {
      gesture.node.fx = (p.x - width / 2 - panX) / zoom;
      gesture.node.fy = (p.y - centerY() - panY) / zoom;
      gesture.node.x = gesture.node.fx;
      gesture.node.y = gesture.node.fy;
    } else {
      panX = gesture.panX + dx;
      panY = gesture.panY + dy;
    }
    draw();
  };
  const up = (e) => {
    if (!gesture || gesture.id !== e.pointerId) return;
    if (gesture.points) {
      const polygon = gesture.points;
      const chosen = e.type === 'pointerup' && polygon.length > 2 ? dots.filter(({node}) => insidePolygon({x:width/2+panX+node.x*zoom,y:centerY()+panY+node.y*zoom}, polygon)) : [];
      dots.forEach(dot => dot.g.classList.toggle('lasso-selected', chosen.includes(dot)));
      gesture = null; lasso = false;
      svg.classList.remove('lasso-mode');
      lassoButton.setAttribute('aria-pressed','false');
      if (svg.hasPointerCapture(e.pointerId)) svg.releasePointerCapture(e.pointerId);
      onLasso(chosen.map(dot => dot.node)); return;
    }
    if (gesture.node) {
      gesture.node.fx = null;
      gesture.node.fy = null;
      if (!gesture.moved && e.type === "pointerup") onSelect(gesture.node);
      else {
        layout.reheat();
        start();
      }
    }
    gesture = null;
    if (svg.hasPointerCapture(e.pointerId))
      svg.releasePointerCapture(e.pointerId);
  };
  const wheel = (e) => {
    e.preventDefault();
    zoom = Math.max(0.2, Math.min(3.5, zoom * Math.exp(-e.deltaY * 0.0015)));
    draw();
  };
  svg.addEventListener("pointerdown", down);
  svg.addEventListener("pointermove", move);
  svg.addEventListener("pointerup", up);
  svg.addEventListener("pointercancel", up);
  svg.addEventListener("wheel", wheel, { passive: false });
  const observer = new ResizeObserver(() => {
    width = svg.clientWidth;
    height = svg.clientHeight;
    fit();
  });
  observer.observe(svg);
  return () => {
    dead = true;
    cancelAnimationFrame(raf);
    observer.disconnect();
    svg.classList.remove('lasso-mode');
    svg.removeEventListener("pointerdown", down);
    svg.removeEventListener("pointermove", move);
    svg.removeEventListener("pointerup", up);
    svg.removeEventListener("pointercancel", up);
    svg.removeEventListener("wheel", wheel);
  };
}

export function insidePolygon(point, polygon) {
  let inside = false;
  for (let i=0,j=polygon.length-1; i<polygon.length; j=i++) {
    const a=polygon[i],b=polygon[j];
    if ((a.y>point.y)!==(b.y>point.y) && point.x<(b.x-a.x)*(point.y-a.y)/(b.y-a.y)+a.x) inside=!inside;
  }
  return inside;
}
