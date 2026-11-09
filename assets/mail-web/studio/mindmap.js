// A deterministic Markdown tree: depth controls x, subtree order controls y.
export function goalTree(view, date) {
  const root = { id: "day:" + date, title: date, children: [] };
  const paths = (view.entries || [view.entry]).filter(
    (path) => view.files[path]?.kind === "goal",
  );
  for (const path of paths) {
    const file = view.files[path],
      rows = file.outline.filter((r) => ["heading", "task"].includes(r.kind));
    const first = rows.find((r) => r.kind === "heading" && r.level === 1);
    const parent = {
      id: path,
      title: file.title,
      file,
      row: first,
      checked: first?.checked,
      children: [],
    };
    root.children.push(parent);
    const byLine = new Map();
    if (first) byLine.set(first.line, parent);
    for (const row of rows) {
      if (row === first) continue;
      const node = {
        id: path + "#" + row.line,
        title: row.text,
        row,
        file,
        checked: row.checked,
        children: [],
      };
      (byLine.get(row.parent) || parent).children.push(node);
      byLine.set(row.line, node);
    }
  }
  return root;
}
export function layoutTree(root, collapsed = new Set()) {
  const nodes = [],
    edges = [];
  let offset = 0;
  function visit(node, depth, parent) {
    const item = { ...node, x: depth * 240 + 120, y: 0 };
    nodes.push(item);
    const children = collapsed.has(node.id) ? [] : node.children;
    const shown = children.map((child) => visit(child, depth + 1, item));
    item.y = shown.length ? (shown[0].y + shown.at(-1).y) / 2 : (offset += 64);
    if (node.draft) offset += 32;
    if (parent) edges.push({ from: parent, to: item });
    return item;
  }
  visit(root, 0, null);
  return {
    nodes,
    edges,
    width: Math.max(520, ...nodes.map((n) => n.x + 150)),
    height: Math.max(320, offset + 64),
  };
}
// Reserve a real layout slot for an unsaved child without changing the document.
export function withDraftNode(tree, pendingAdd) {
  if (!pendingAdd) return tree;
  function copy(node) {
    const children = (node.children || []).map(copy);
    if (node.id === pendingAdd.id)
      children.push({
        id: "draft:" + node.id,
        parentId: node.id,
        draft: true,
        title: "",
        children: [],
      });
    return { ...node, children };
  }
  return copy(tree);
}
export function drawMindmap({
  dom,
  host,
  tree,
  collapsed,
  onSelect,
  onAdd,
  pendingAdd,
  onCommit,
  onCancel,
  onDraft,
  zoom = 1,
}) {
  const { nodes, edges, width, height } = layoutTree(
      withDraftNode(tree, pendingAdd),
      collapsed,
    ),
    ns = "http://www.w3.org/2000/svg";
  const make = (tag, attrs = {}) => {
    const n = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    return n;
  };
  const svg = make("svg", {
    width: width * zoom,
    height: height * zoom,
    viewBox: `0 0 ${width} ${height}`,
    role: "group",
    "aria-label": "目标思维导图",
  });
  for (const { from, to } of edges)
    svg.append(
      make("path", {
        d: `M${from.x + 92},${from.y} C${from.x + 120},${from.y} ${to.x - 140},${to.y} ${to.x - 92},${to.y}`,
        fill: "none",
        stroke: "#cfdaed",
        "stroke-width": 1.5,
        "stroke-dasharray": to.draft ? "4 4" : "",
      }),
    );
  for (const node of nodes) {
    if (node.draft) {
      const parent = nodes.find((n) => n.id === node.parentId);
      const editor = make("foreignObject", {
        x: node.x - 92,
        y: node.y - 19,
        width: 206,
        height: 84,
      });
      const form = document.createElement("form"),
        input = document.createElement("input"),
        controls = document.createElement("div"),
        save = document.createElement("button"),
        cancel = document.createElement("button");
      form.className = "mindmap-inline-editor";
      input.value = pendingAdd.title;
      input.placeholder = "子目标";
      input.setAttribute("aria-label", "新子目标标题");
      input.required = true;
      input.maxLength = 300;
      controls.className = "mindmap-inline-actions";
      save.type = "submit";
      save.textContent = "保存";
      cancel.type = "button";
      cancel.textContent = "取消";
      cancel.onclick = onCancel;
      controls.append(save, cancel);
      form.append(input, controls);
      editor.append(form);
      svg.append(editor);
      form.onsubmit = (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (input.value.trim()) return onCommit(parent, input.value.trim());
      };
      input.oninput = () => onDraft(input.value);
      input.onkeydown = (event) => {
        if (event.key === "Enter" && event.isComposing) {
          event.preventDefault();
          return;
        }
        if (event.key === "Escape") {
          event.preventDefault();
          onCancel();
        }
      };
      continue;
    }
    const g = make("g", {
      class: "mindmap-node" + (node.checked ? " done" : ""),
      transform: `translate(${node.x},${node.y})`,
      role: "button",
      tabindex: 0,
      "aria-label": node.title,
    });
    const box = make("rect", {
      x: -92,
      y: -19,
      width: 184,
      height: 38,
      rx: 9,
      fill: node.checked ? "#eef6f2" : "white",
      stroke: node.id.startsWith("day:") ? "#92a8cf" : "#dce4f0",
    });
    const text = make("text", { "text-anchor": "middle", y: 4 });
    text.textContent =
      (node.checked ? "✓ " : "") +
      (node.title.length > 17 ? node.title.slice(0, 17) + "…" : node.title);
    const title = make("title");
    title.textContent = node.title;
    g.append(box, text, title);
    g.onclick = () => onSelect(node);
    g.onkeydown = (e) => {
      if (["Enter", " "].includes(e.key)) {
        e.preventDefault();
        onSelect(node);
      }
    };
    svg.append(g);
    if (onAdd) {
      const add = make("g", {
        class: "mindmap-add",
        transform: `translate(${node.x + 112},${node.y})`,
        role: "button",
        tabindex: 0,
        "aria-label": "新增子目标：" + node.title,
      });
      add.append(make("circle", { r: 10, fill: "white", stroke: "#ccd8ea" }));
      const plus = make("text", { "text-anchor": "middle", y: 4 });
      plus.textContent = "+";
      add.append(plus);
      add.onclick = (event) => {
        event.stopPropagation();
        onAdd(node);
      };
      add.onkeydown = (event) => {
        if (["Enter", " "].includes(event.key)) {
          event.preventDefault();
          event.stopPropagation();
          onAdd(node);
        }
      };
      svg.append(add);
    }
  }
  host.replaceChildren(svg);
  const draftInput = host.querySelector(".mindmap-inline-editor input");
  draftInput?.focus();
  draftInput?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
}
