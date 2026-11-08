const defaults = { labels: true, nodeScale: 1, edgeWidth: 1 };
const forces = { repel: 1000, linkDistance: 250, centering: 0.1 };

export function createGraphControls(host, actions) {
  const controls = document.createElement("div");
  controls.className = "graph-navigation";
  const icons = {
    plus: '<path d="M12 5v14M5 12h14"/>',
    minus: '<path d="M5 12h14"/>',
    fit: '<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/><circle cx="12" cy="12" r="3"/>',
    settings:
      '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="15" cy="17" r="3"/>',
  };
  function icon(name) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", "18");
    svg.setAttribute("height", "18");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.6");
    svg.setAttribute("aria-hidden", "true");
    svg.innerHTML = icons[name];
    return svg;
  }
  for (const [name, label, run] of [
    ["plus", "放大", () => actions.zoom(1.3)],
    ["minus", "缩小", () => actions.zoom(1 / 1.3)],
    ["fit", "适应画布", actions.fit],
  ]) {
    const button = document.createElement("button");
    button.type = "button";
    button.title = label;
    button.setAttribute("aria-label", label);
    button.append(icon(name));
    button.onclick = run;
    controls.append(button);
  }
  const settings = document.createElement("details");
  settings.className = "graph-settings";
  const summary = document.createElement("summary");
  summary.title = "图谱设置";
  summary.setAttribute("aria-label", "图谱设置");
  summary.append(icon("settings"));
  const body = document.createElement("div");
  body.className = "graph-settings-body";
  settings.append(summary, body);
  controls.append(settings);
  const values = { ...defaults },
    physics = { ...forces },
    inputs = [];
  function heading(title) {
    const node = document.createElement("strong");
    node.textContent = title;
    body.append(node);
  }
  function field(title, key, initial, min, max, step, target, changed) {
    const row = document.createElement("label");
    row.className = "graph-setting-row";
    const caption = document.createElement("span");
    caption.textContent = title;
    const input = document.createElement("input");
    input.setAttribute("aria-label", title);
    input.type = typeof initial === "boolean" ? "checkbox" : "range";
    if (input.type === "checkbox") input.checked = initial;
    else Object.assign(input, { min, max, step, value: initial });
    input.oninput = () => {
      target[key] =
        input.type === "checkbox" ? input.checked : Number(input.value);
      changed({ ...target });
    };
    row.append(caption, input);
    body.append(row);
    inputs.push({ input, initial });
  }
  heading("显示");
  field("显示名称", "labels", true, 0, 0, 0, values, actions.display);
  field("节点大小", "nodeScale", 1, 0.5, 2, 0.1, values, actions.display);
  field("连线粗细", "edgeWidth", 1, 0.4, 2.5, 0.1, values, actions.display);
  heading("布局");
  field(
    "排斥力",
    "repel",
    forces.repel,
    100,
    3000,
    100,
    physics,
    actions.physics,
  );
  field(
    "连线距离",
    "linkDistance",
    forces.linkDistance,
    50,
    500,
    10,
    physics,
    actions.physics,
  );
  field(
    "居中力度",
    "centering",
    forces.centering,
    0,
    0.3,
    0.01,
    physics,
    actions.physics,
  );
  const reset = document.createElement("button");
  reset.type = "button";
  reset.textContent = "恢复默认";
  reset.onclick = () => {
    Object.assign(values, defaults);
    Object.assign(physics, forces);
    for (const { input, initial } of inputs) {
      if (input.type === "checkbox") input.checked = initial;
      else input.value = initial;
    }
    actions.display({ ...values });
    actions.physics({ ...physics });
  };
  body.append(reset);
  host.append(controls);
  return { destroy: () => controls.remove() };
}
