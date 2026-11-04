// Native SVG charts: fixed axes, explicit units and real per-case observations.
const NS = "http://www.w3.org/2000/svg";
function node(tag, attrs = {}, text) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text !== undefined) n.textContent = text;
  return n;
}
function chart(title) {
  const svg = node("svg", {
    viewBox: "0 0 580 280",
    role: "img",
    "aria-label": title,
  });
  svg.append(node("title", {}, title));
  return svg;
}
function label(svg, x, y, text, anchor = "middle") {
  svg.append(node("text", { x, y, "text-anchor": anchor }, text));
}
export function qualityChart(runs, metricPairs = null) {
  const svg = chart("Recall and ranking metrics");
  const metrics = metricPairs || [
    ["recall_at_1", "R@1"],
    ["recall_at_3", "R@3"],
    ["recall_at_5", "R@5"],
    ["mrr", "MRR"],
    ["ndcg_at_5", "nDCG@5"],
  ];
  for (let i = 0; i <= 4; i++) {
    const value = i / 4,
      y = 224 - value * 185;
    svg.append(node("line", { x1: 44, x2: 560, y1: y, y2: y, class: "grid" }));
    label(svg, 35, y + 4, value.toFixed(2), "end");
  }
  metrics.forEach(([key, title], i) => {
    const x = 66 + i * 100;
    label(svg, x + 25, 246, title);
    runs.forEach((run, j) => {
      const value = run.metrics[key];
      if (value === null || !Number.isFinite(value)) return;
      const bx = x + j * 24;
      svg.append(
        node("rect", {
          x: bx,
          y: 224 - value * 185,
          width: 20,
          height: value * 185,
          fill: ["#7189c5", "#dba66f"][j],
          rx: 2,
        }),
      );
      label(svg, bx + 10, 219 - value * 185, value.toFixed(3));
    });
  });
  return svg;
}
export function latencyChart(runs) {
  const svg = chart("Empirical latency CDF, milliseconds");
  const values = runs.map((r) =>
    r.cases
      .map((c) => c.latency_ms)
      .filter(Number.isFinite)
      .sort((a, b) => a - b),
  );
  const max = Math.max(1, ...values.flat());
  for (const p of [0, 0.5, 0.95, 1]) {
    const y = 224 - p * 185;
    svg.append(node("line", { x1: 44, x2: 560, y1: y, y2: y, class: "grid" }));
    label(svg, 36, y + 4, String(p), "end");
  }
  for (let i = 0; i <= 4; i++) {
    const x = 44 + i * 129;
    label(svg, x, 246, ((max * i) / 4).toFixed(max > 100 ? 0 : 1));
  }
  values.forEach((list, index) => {
    if (!list.length) return;
    const points = ["44,224"];
    for (let i = 0; i < list.length; i++) {
      const x = 44 + (list[i] / max) * 516;
      points.push(
        `${x},${224 - (i / list.length) * 185}`,
        `${x},${224 - ((i + 1) / list.length) * 185}`,
      );
    }
    svg.append(
      node("polyline", {
        points: points.join(" "),
        fill: "none",
        stroke: ["#7189c5", "#dba66f"][index],
        "stroke-width": 2,
      }),
    );
  });
  label(svg, 300, 269, "Latency (ms)");
  return svg;
}
export function pairedChart(left, right) {
  const svg = chart("Paired reciprocal-rank comparison");
  for (const value of [0, 0.25, 0.5, 0.75, 1]) {
    const x = 44 + value * 516,
      y = 224 - value * 185;
    svg.append(
      node("line", { x1: x, x2: x, y1: 39, y2: 224, class: "grid" }),
      node("line", { x1: 44, x2: 560, y1: y, y2: y, class: "grid" }),
    );
    label(svg, x, 246, String(value));
    label(svg, 35, y + 4, String(value), "end");
  }
  svg.append(
    node("line", {
      x1: 44,
      y1: 224,
      x2: 560,
      y2: 39,
      stroke: "#c1c9d8",
      "stroke-dasharray": "4 4",
    }),
  );
  const byId = new Map(left.cases.map((c) => [c.case_id, c]));
  for (const c of right.cases) {
    const other = byId.get(c.case_id);
    if (!other) continue;
    const a = other.metrics.mrr,
      b = c.metrics.mrr;
    if (a === null || b === null) continue;
    const dot = node("circle", {
      cx: 44 + a * 516,
      cy: 224 - b * 185,
      r: 4,
      fill: b > a ? "#698fb7" : b < a ? "#cc9270" : "#a6b2c6",
      opacity: 0.55,
    });
    dot.append(
      node("title", {}, `${c.case_id} · ${a.toFixed(3)} → ${b.toFixed(3)}`),
    );
    svg.append(dot);
  }
  label(svg, 300, 269, "x: Baseline RR · y: Candidate RR");
  return svg;
}
