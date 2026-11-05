"use strict";
const { test, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const { source, moduleUrl, Element } = require("./studio_test_helpers.cjs");
const { createForceLayout } = require("../../assets/mail-web/force-layout.js");
const { graphLabelPositions } = require("../../assets/mail-web/graph-labels.js");
const originals = {};
let active = null;

class Events {
  constructor() { this.listeners = new Map(); }
  addEventListener(type, callback) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type).add(callback);
  }
  removeEventListener(type, callback) { this.listeners.get(type)?.delete(callback); }
  emit(type, properties = {}) {
    const event = {
      type, target: this, button: 0, pointerId: 1, deltaMode: 0,
      preventDefault() { this.defaultPrevented = true; },
      stopPropagation() { this.stopped = true; },
      ...properties,
    };
    if (type === "lostpointercapture") this.captures?.delete(event.pointerId);
    for (let node = this; node; node = node.parentNode) {
      node["on" + type]?.(event);
      for (const callback of [...node.listeners?.get(type) || []]) callback(event);
      if (event.stopped) break;
    }
    return event;
  }
}

async function fixture({ reduced = false, width = 800, height = 600, onSelect } = {}) {
  const metrics = { reads: 0, writes: [], steps: 0, creates: 0, labelWidths: new Map() },
    frames = new Map(), observers = [], engines = [];
  let nextFrame = 0;
  class SvgElement extends Element {
    constructor(tag) {
      super(tag);
      this.attributes = new Map();
      this.listeners = new Map();
      this.style = { setProperty(key, value) { this[key] = value; } };
      this.captures = new Set();
      this.classList = {
        add: (...names) => this.setClasses([...this.classes(), ...names]),
        remove: (...names) => this.setClasses(this.classes().filter((name) => !names.includes(name))),
        contains: (name) => this.classes().includes(name),
        toggle: (name, force) => {
          const include = force ?? !this.classes().includes(name);
          this.classList[include ? "add" : "remove"](name);
          return include;
        },
      };
      this.clientWidth = 800;
      this.clientHeight = 600;
    }
    classes() { return (this.getAttribute("class") || "").split(/\s+/).filter(Boolean); }
    setClasses(names) { this.setAttribute("class", [...new Set(names)].join(" ")); }
    setAttribute(name, value) {
      this.attributes.set(name, String(value));
      if (name.startsWith("data-")) this.dataset[name.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())] = String(value);
      metrics.writes.push({ node: this, name, value: String(value) });
    }
    getAttribute(name) { return this.attributes.get(name) ?? null; }
    removeAttribute(name) { this.attributes.delete(name); }
    append(...children) {
      for (const child of children) {
        child.remove?.();
        child.parentNode = this;
        this.children.push(child);
      }
    }
    appendChild(child) { this.append(child); return child; }
    replaceChildren(...children) {
      for (const child of this.children) child.parentNode = null;
      this.children = [];
      this.append(...children);
    }
    remove() {
      if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
      this.parentNode = null;
    }
    matches(selector) {
      if (selector.startsWith(".")) return this.classes().includes(selector.slice(1));
      if (selector.startsWith("[")) return this.getAttribute(selector.slice(1, -1)) !== null || selector === "[data-zoom]" && this.dataset.zoom !== undefined;
      return this.tagName.toLowerCase() === selector;
    }
    closest(selector) {
      for (let node = this; node; node = node.parentNode) if (node.matches?.(selector)) return node;
      return null;
    }
    querySelectorAll(selector) {
      return this.children.flatMap((child) => [
        ...(child.matches?.(selector) ? [child] : []),
        ...child.querySelectorAll?.(selector) || [],
      ]);
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    getComputedTextLength() {
      metrics.reads++;
      const viewport = this.closest("svg");
      if (this.style.display === "none" || !viewport?.clientWidth || !viewport.clientHeight) return 0;
      return String(this.textContent || "").length * (parseFloat(this.style.fontSize) || 11) * 0.55;
    }
    getBoundingClientRect() { return { left: 10, top: 20, width: this.clientWidth, height: this.clientHeight }; }
    setPointerCapture(id) { this.captures.add(id); }
    hasPointerCapture(id) { return this.captures.has(id); }
    releasePointerCapture(id) {
      if (this.captures.delete(id)) this.emit("lostpointercapture", { pointerId: id });
    }
    focus() { document.activeElement = this; }
  }
  for (const name of ["addEventListener", "removeEventListener", "emit"])
    SvgElement.prototype[name] = Events.prototype[name];
  const doc = new Events(), media = new Events(), svg = new SvgElement("svg"), tools = new SvgElement("div");
  svg.clientWidth = width;
  svg.clientHeight = height;
  doc.hidden = false;
  doc.createElementNS = (_, tag) => new SvgElement(tag);
  doc.createElement = (tag) => new SvgElement(tag);
  doc.fonts = new Events();
  media.matches = reduced;
  for (const name of ["document", "window", "ResizeObserver", "requestAnimationFrame", "cancelAnimationFrame"])
    originals[name] = globalThis[name];
  globalThis.document = doc;
  globalThis.window = {
    matchMedia: () => media,
    OksGraphLabels: {
      graphLabelPositions(labels, ...args) {
        labels.forEach((label) => metrics.labelWidths.set(label.id, label.width));
        return graphLabelPositions(labels, ...args);
      },
    },
    createForceLayout(nodes, edges, options) {
      metrics.creates++;
      const layout = createForceLayout(nodes, edges, options), step = layout.step;
      layout.step = () => { metrics.steps++; return step(); };
      engines.push(layout);
      return layout;
    },
  };
  globalThis.requestAnimationFrame = (callback) => { frames.set(++nextFrame, callback); return nextFrame; };
  globalThis.cancelAnimationFrame = (id) => frames.delete(id);
  globalThis.ResizeObserver = class {
    constructor(callback) { this.callback = callback; observers.push(this); }
    observe() {}
    disconnect() { this.disconnected = true; }
  };
  const { createGraph } = await import(moduleUrl(source("studio/graph.js")));
  const selected = [];
  const controller = createGraph(svg, tools, (node) => {
    selected.push(node.id);
    return onSelect?.(node);
  }, {
    button(label, action) {
      const node = new SvgElement("button"); node.textContent = label; node.onclick = action; return node;
    },
    nodeTitle: (node) => node.note || node.title + " detail",
    nodeClass: (node) => node.pending ? "pending-node" : "",
    nodeDashed: (node) => node.pending,
  });
  active = { controller };
  const nodes = [{ id: "a", title: "Alpha" }, { id: "b", title: "Beta" }, { id: "c", title: "Gamma" }];
  const edges = [{ from: "a", to: "b", type: "cites" }];
  return {
    controller, svg, tools, metrics, frames, observers, engines, doc, media, selected, nodes, edges,
    node: (id) => svg.querySelectorAll(".studio-node").find((node) => node.dataset.id === id),
    world: () => svg.querySelector(".graph-world"),
    flush() {
      const pending = [...frames.values()]; frames.clear();
      pending.forEach((callback) => callback(16.67));
    },
    drain() {
      for (let i = 0; frames.size && i < 250; i++) this.flush();
      assert.equal(frames.size, 0, "physics must stop within its frame budget");
    },
    resize(width, height) {
      svg.clientWidth = width; svg.clientHeight = height;
      observers.forEach((observer) => observer.callback([{ contentRect: { width, height } }]));
    },
  };
}

afterEach(() => {
  active?.controller.destroy();
  active = null;
  for (const [name, value] of Object.entries(originals)) globalThis[name] = value;
});
function transform(node) {
  return (node.getAttribute("transform") || "").match(/[-+]?(?:\d*\.)?\d+(?:e[-+]?\d+)?/gi)?.map(Number);
}
function close(actual, expected) { assert.ok(Math.abs(actual - expected) < 1e-7, `${actual} differs from ${expected}`); }

test("empty and single-node graphs do not schedule background physics", async () => {
  const page = await fixture();
  page.controller.update([], []);
  page.drain();
  assert.equal(page.metrics.steps, 0);
  page.controller.update([page.nodes[0]], []);
  page.drain();
  assert.equal(page.metrics.steps, 0);
  assert.ok(page.node("a"));
});

test("same-topology updates reuse nodes, positions, camera and physics while changing current metadata", async () => {
  const page = await fixture();
  page.controller.update(page.nodes, page.edges, { selected: "a" }); page.drain();
  const node = page.node("a"), position = node.getAttribute("transform"), camera = page.world().getAttribute("transform"), creates = page.metrics.creates;
  page.controller.update(page.nodes.map((item) => item.id === "a" ? { ...item, title: "Updated", pending: true } : item), page.edges);
  page.drain();
  assert.equal(page.node("a"), node);
  assert.equal(node.getAttribute("transform"), position);
  assert.equal(page.world().getAttribute("transform"), camera);
  assert.equal(page.metrics.creates, creates);
  assert.equal(node.querySelector("text").textContent, "Updated");
  assert.equal(node.querySelector("title").textContent, "Updated detail");
  assert.equal(node.getAttribute("aria-pressed"), "true");
  assert.ok(node.classList.contains("pending-node"));
});

test("complete metadata snapshots remove obsolete node and edge fields without resetting physics or the view", async () => {
  const page = await fixture();
  page.controller.update(page.nodes, page.edges); page.drain();
  const node = page.node("a"),
    line = page.svg.querySelector(".graph-edges").querySelector("line"),
    normalStroke = line.getAttribute("stroke");
  page.controller.update(
    page.nodes.map((item) => item.id === "a" ? { ...item, pending: true, note: "Old note" } : item),
    page.edges.map((edge) => ({ ...edge, pending: true, origin: "written_section" })),
  );
  page.drain();
  assert.ok(node.classList.contains("pending-node"));
  assert.equal(node.children[1].getAttribute("stroke-dasharray"), "3 3");
  assert.equal(node.querySelector("title").textContent, "Old note");
  assert.equal(line.getAttribute("stroke-dasharray"), "4 4");
  assert.notEqual(line.getAttribute("stroke"), normalStroke);
  const physical = page.engines[0].nodes.find((item) => item.id === "a"),
    keys = ["x", "y", "vx", "vy", "fx", "fy"],
    values = keys.map((key) => physical[key]),
    edge = page.engines[0].edges[0],
    endpoints = [edge.source, edge.target],
    position = node.getAttribute("transform"),
    camera = page.world().getAttribute("transform");
  page.controller.update(page.nodes, page.edges); page.drain();
  assert.equal(page.metrics.creates, 1);
  assert.equal(page.node("a"), node);
  assert.deepEqual(keys.map((key) => physical[key]), values);
  assert.equal(node.getAttribute("transform"), position);
  assert.equal(page.world().getAttribute("transform"), camera);
  assert.ok(!Object.hasOwn(physical, "pending") && !Object.hasOwn(physical, "note"));
  assert.ok(!Object.hasOwn(edge, "pending") && !Object.hasOwn(edge, "origin"));
  assert.equal(edge.source, endpoints[0]);
  assert.equal(edge.target, endpoints[1]);
  assert.ok(!node.classList.contains("pending-node"));
  assert.equal(node.children[1].getAttribute("stroke-dasharray"), "");
  assert.equal(node.querySelector("title").textContent, "Alpha detail");
  assert.equal(line.getAttribute("stroke-dasharray"), "");
  assert.equal(line.getAttribute("stroke"), normalStroke);
});

test("wheel bursts share one frame, reuse label widths and keep the pointer world point anchored", async () => {
  const page = await fixture();
  page.controller.update(page.nodes, page.edges); page.drain();
  const before = transform(page.world()), reads = page.metrics.reads, writes = page.metrics.writes.length;
  const cursor = { x: 210, y: 170 }, world = { x: (cursor.x - before[0]) / before[2], y: (cursor.y - before[1]) / before[2] };
  for (let i = 0; i < 100; i++) page.svg.emit("wheel", { clientX: cursor.x + 10, clientY: cursor.y + 20, deltaY: 1 });
  assert.equal(page.frames.size, 1);
  assert.equal(page.metrics.writes.length, writes);
  page.flush();
  const after = transform(page.world());
  close((cursor.x - after[0]) / after[2], world.x);
  close((cursor.y - after[1]) / after[2], world.y);
  assert.equal(page.metrics.reads, reads);
  page.svg.emit("pointerdown", { clientX: 100, clientY: 100 });
  for (let i = 1; i <= 50; i++) page.svg.emit("pointermove", { clientX: 100 + i, clientY: 100 + i });
  const transformsBefore = page.metrics.writes.filter((item) => item.name === "transform" && item.node.classList.contains("studio-node")).length;
  page.flush();
  assert.equal(page.metrics.writes.filter((item) => item.name === "transform" && item.node.classList.contains("studio-node")).length, transformsBefore);
  assert.equal(page.metrics.reads, reads);
  page.svg.emit("pointerup", { clientX: 150, clientY: 150 }); page.drain();
});

test("pointer thresholds preserve click targets and drag offsets, cancel and lost capture never select", async () => {
  const page = await fixture();
  page.controller.update(page.nodes, page.edges); page.drain();
  const node = page.node("a"), hit = node.querySelector("circle"), start = transform(node), camera = transform(page.world());
  const x = camera[0] + start[0] * camera[2] + 16, y = camera[1] + start[1] * camera[2] + 20;
  page.svg.emit("pointerdown", { target: hit, clientX: x, clientY: y });
  page.svg.emit("pointermove", { target: hit, clientX: x + 2, clientY: y });
  page.svg.emit("pointerup", { target: hit, clientX: x + 2, clientY: y });
  assert.deepEqual(page.selected, ["a"]);
  page.svg.emit("pointerdown", { target: hit, clientX: x, clientY: y });
  page.svg.emit("pointermove", { target: hit, clientX: x + 12, clientY: y }); page.flush();
  close(transform(node)[0], start[0] + 12 / camera[2]);
  close(transform(node)[1], start[1]);
  page.svg.emit("pointercancel"); page.drain();
  assert.deepEqual(page.selected, ["a"]);
  assert.equal(page.svg.captures.size, 0);
  page.svg.emit("pointerdown", { target: hit, clientX: x, clientY: y });
  page.svg.emit("lostpointercapture"); page.drain();
  assert.deepEqual(page.selected, ["a"]);
  assert.equal(page.svg.captures.size, 0);
});

test("selection highlights only neighbors, retains selection when omitted and supports keyboard activation", async () => {
  const page = await fixture();
  page.controller.update(page.nodes, page.edges, { selected: "a" }); page.drain();
  assert.ok(page.world().classList.contains("has-selection"));
  assert.ok(page.node("b").classList.contains("is-neighbor"));
  assert.ok(!page.node("c").classList.contains("is-neighbor"));
  page.node("b").emit("keydown", { key: "Enter" });
  page.node("c").emit("keydown", { key: " " });
  assert.deepEqual(page.selected, ["b", "c"]);
  page.controller.update(page.nodes, page.edges); page.drain();
  assert.equal(page.node("c").getAttribute("aria-pressed"), "true");
  page.controller.update(page.nodes, page.edges, { selected: null }); page.drain();
  assert.ok(!page.world().classList.contains("has-selection"));
  assert.equal(page.node("c").getAttribute("aria-pressed"), "false");
});

test("a rejected pointer or Enter activation leaves the existing selection unchanged", async () => {
  const page = await fixture({ onSelect: () => false });
  page.controller.update(page.nodes, page.edges, { selected: "a" }); page.drain();
  const target = page.node("b"),
    hit = target.querySelector("circle"),
    node = transform(target), camera = transform(page.world()),
    point = { target: hit, clientX: camera[0] + node[0] * camera[2] + 10, clientY: camera[1] + node[1] * camera[2] + 20 };
  page.svg.emit("pointerdown", point);
  page.svg.emit("pointerup", point);
  page.drain();
  assert.deepEqual(page.selected, ["b"]);
  assert.equal(page.node("a").getAttribute("aria-pressed"), "true");
  assert.equal(target.getAttribute("aria-pressed"), "false");
  page.node("c").emit("keydown", { key: "Enter" });
  page.drain();
  assert.deepEqual(page.selected, ["b", "c"]);
  assert.equal(page.node("a").getAttribute("aria-pressed"), "true");
  assert.equal(page.node("c").getAttribute("aria-pressed"), "false");
});

test("resize preserves the camera, hidden pages stop work and destroy releases all owned resources", async () => {
  const page = await fixture();
  page.controller.update(page.nodes, page.edges); page.drain();
  page.svg.emit("wheel", { clientX: 310, clientY: 240, deltaY: -80 }); page.flush();
  const before = transform(page.world()), node = page.node("a"), position = node.getAttribute("transform");
  page.resize(600, 500); page.flush();
  const after = transform(page.world());
  close(after[2], before[2]);
  close(after[0] - 300, before[0] - 400);
  close(after[1] - 250, before[1] - 300);
  assert.equal(node.getAttribute("transform"), position);
  page.controller.update([...page.nodes, { id: "d", title: "Delta" }], [...page.edges, { from: "b", to: "d", type: "cites" }]);
  page.doc.hidden = true; page.doc.emit("visibilitychange");
  assert.equal(page.frames.size, 0);
  page.doc.hidden = false; page.doc.emit("visibilitychange");
  assert.equal(page.frames.size, 1);
  const steps = page.metrics.steps; page.flush();
  assert.ok(page.metrics.steps - steps <= 1);
  page.svg.emit("pointerdown", { target: node.querySelector("circle"), clientX: 100, clientY: 100 });
  page.controller.destroy();
  assert.equal(page.frames.size, 0);
  assert.equal(page.svg.captures.size, 0);
  assert.ok(page.observers.every((observer) => observer.disconnected));
  assert.equal(page.svg.listeners.get("wheel").size, 0);
  node.emit("keydown", { key: "Enter" });
  assert.deepEqual(page.selected, []);
});

test("wheel line and page deltas use the same coordinate-anchored scale as pixel deltas", async () => {
  const page = await fixture();
  page.controller.update(page.nodes, page.edges); page.drain();
  const scale = (deltaY, deltaMode) => {
    page.controller.fit(); page.flush();
    page.svg.emit("wheel", { clientX: 220, clientY: 190, deltaY, deltaMode });
    page.flush();
    return transform(page.world())[2];
  };
  close(scale(16, 0), scale(1, 1));
  close(scale(page.svg.clientHeight, 0), scale(1, 2));
});

test("normal motion is bounded and reduced motion has no background physics loop", async () => {
  const page = await fixture();
  page.controller.update(page.nodes, page.edges);
  for (let frame = 0; page.frames.size && frame < 230; frame++) {
    const steps = page.metrics.steps;
    page.flush();
    assert.ok(page.metrics.steps - steps <= 1);
  }
  assert.equal(page.frames.size, 0);
  assert.ok(page.metrics.steps > 0 && page.metrics.steps <= 220);
  page.media.matches = true;
  page.media.emit("change");
  page.controller.update([...page.nodes, { id: "d", title: "Delta" }], page.edges);
  const stopped = page.metrics.steps;
  page.drain();
  assert.equal(page.metrics.steps, stopped);
});

test("zero-size mounts defer measurement and hidden titles are measurable after metadata or font changes", async () => {
  const page = await fixture({ reduced: true, width: 0, height: 0 });
  page.controller.update(page.nodes, page.edges);
  page.drain();
  assert.equal(page.metrics.reads, 0);
  assert.equal(page.metrics.labelWidths.size, 0);
  page.resize(800, 600);
  page.drain();
  assert.equal(page.metrics.reads, page.nodes.length);
  assert.ok(page.metrics.labelWidths.get("a") > 0);

  const title = page.node("a").querySelector("text");
  title.style.display = "none";
  const reads = page.metrics.reads;
  page.controller.update(page.nodes.map((node) => node.id === "a"
    ? { ...node, title: "Changed while hidden" } : node), page.edges);
  page.drain();
  assert.equal(page.metrics.reads, reads + 1);
  assert.ok(page.metrics.labelWidths.get("a") > 0);

  for (const node of page.svg.querySelectorAll(".studio-node"))
    node.querySelector("text").style.display = "none";
  const beforeFonts = page.metrics.reads;
  page.doc.fonts.emit("loadingdone");
  page.drain();
  assert.equal(page.metrics.reads, beforeFonts + page.nodes.length);
  assert.ok([...page.metrics.labelWidths.values()].every((value) => value > 0));

  page.resize(0, 0);
  const hiddenReads = page.metrics.reads;
  page.controller.update(page.nodes.map((node) => node.id === "b"
    ? { ...node, title: "Changed in a zero-size viewport" } : node), page.edges);
  page.drain();
  assert.equal(page.metrics.reads, hiddenReads);
  page.resize(800, 600);
  page.drain();
  assert.ok(page.metrics.reads > hiddenReads);
  assert.ok(page.metrics.labelWidths.get("b") > 0);
});
