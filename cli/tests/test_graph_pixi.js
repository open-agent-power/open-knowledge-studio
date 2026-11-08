"use strict";
const { test, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const { source, moduleUrl } = require("./studio_test_helpers.cjs");
let active;
class Events {
  constructor() {
    this.listeners = new Map();
  }
  addEventListener(type, callback) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type).add(callback);
  }
  removeEventListener(type, callback) {
    this.listeners.get(type)?.delete(callback);
  }
  emit(type) {
    for (const callback of this.listeners.get(type) || []) callback();
  }
}
class Element extends Events {
  constructor(tag) {
    super();
    this.tagName = tag;
    this.children = [];
    this.dataset = {};
    this.clientWidth = 800;
    this.clientHeight = 600;
  }
  append(...children) {
    for (const child of children) {
      child.parent = this;
      this.children.push(child);
    }
  }
  remove() {
    if (this.parent)
      this.parent.children = this.parent.children.filter(
        (child) => child !== this,
      );
  }
  setAttribute(name, value) {
    this[name] = value;
  }
  getAttribute(name) {
    return this[name] ?? null;
  }
}
async function fixture({
  onSelect,
  options = {},
  reduced = false,
  hidden = false,
  failDuring,
} = {}) {
  const saved = new Map(
    [
      "window",
      "document",
      "ResizeObserver",
      "__renderer",
      "__layout",
      "__controls",
    ].map((name) => [name, global[name]]),
  );
  const motion = Object.assign(new Events(), { matches: reduced });
  const doc = Object.assign(new Events(), {
    hidden,
    createElement: (tag) => new Element(tag),
  });
  const observers = [],
    calls = [],
    selections = [];
  let callbacks, layoutCallbacks, rendererOptions;
  const renderer = {};
  for (const name of [
    "update",
    "focus",
    "fit",
    "zoomBy",
    "resize",
    "pause",
    "resume",
    "destroy",
    "configure",
    "positionsChanged",
    "focusNode",
    "setCamera",
    "settled",
    "setLasso",
  ])
    renderer[name] = (...args) => calls.push([name, ...args]);
  renderer.ready = Promise.resolve(true);
  renderer.getCamera = () => ({ scale: 2, x: 20, y: 30 });
  const layout = {};
  for (const name of [
    "update",
    "dragStart",
    "dragMove",
    "dragEnd",
    "pause",
    "resume",
    "destroy",
    "setParams",
  ])
    layout[name] = (...args) => calls.push(["layout." + name, ...args]);
  global.__renderer = (_host, cb, settings) => {
    callbacks = cb;
    rendererOptions = settings;
    if (failDuring === "renderer") cb.onError("Renderer unavailable");
    return renderer;
  };
  global.__layout = (cb) => {
    layoutCallbacks = cb;
    if (failDuring === "layout") cb.onError("Worker unavailable");
    return layout;
  };
  global.__controls = (_host, actions) => ({
    actions,
    destroy() {
      calls.push(["controls.destroy"]);
    },
  });
  global.window = { matchMedia: () => motion };
  global.document = doc;
  global.ResizeObserver = class {
    constructor(callback) {
      this.callback = callback;
      observers.push(this);
    }
    observe() {}
    disconnect() {
      this.disconnected = true;
    }
  };
  const script = source("studio/graph-pixi.js")
    .replace(
      'import { createRenderer } from "./graph-renderer.js";',
      "const createRenderer = globalThis.__renderer;",
    )
    .replace(
      'import { createLayout } from "./graph-layout.js";',
      "const createLayout = globalThis.__layout;",
    )
    .replace(
      'import { createGraphControls } from "./graph-controls.js";',
      "const createGraphControls = globalThis.__controls;",
    );
  const { createGraph, insidePolygon } = await import(
    moduleUrl(script + "\n// fixture " + Math.random())
  );
  const host = new Element("div"),
    tools = new Element("div");
  const button = (text, onclick) =>
    Object.assign(new Element("button"), { textContent: text, onclick });
  const graph = createGraph(
    host,
    tools,
    onSelect || ((data) => selections.push(data)),
    { button, ...options },
  );
  const f = {
    graph,
    host,
    tools,
    callbacks,
    rendererOptions,
    insidePolygon,
    layoutCallbacks,
    calls,
    selections,
    motion,
    document: doc,
    observers,
    count: (name) => calls.filter((call) => call[0] === name).length,
    last: (name) => calls.findLast((call) => call[0] === name),
    proxy: (id) =>
      host.children
        .find((child) => child.className === "graph-node-list")
        .children.find((child) => child.dataset.id === id),
    cleanup() {
      graph.destroy();
      for (const [name, value] of saved) {
        if (value === undefined) delete global[name];
        else global[name] = value;
      }
    },
  };
  active = f;
  return f;
}
afterEach(() => {
  active?.cleanup();
  active = null;
});
const items = () => [
  { id: "a", title: "Alpha", type: "wiki" },
  { id: "b", title: "Beta", type: "wiki" },
];
const edges = () => [{ from: "a", to: "b", type: "cites" }];

test("metadata snapshots reuse node positions and do not restart the worker", async () => {
  const f = await fixture();
  f.graph.update(items(), edges(), { selected: "a" });
  const node = f.last("update")[1][0];
  f.layoutCallbacks.onPositions(new Float32Array([15, 25, 0, 45, 55, 0]));
  f.graph.update(
    [{ ...items()[0], title: "Changed", pending: true }, items()[1]],
    [{ ...edges()[0], pending: true }],
  );
  assert.equal(f.count("layout.update"), 1);
  assert.equal(f.last("update")[1][0], node);
  assert.deepEqual(
    [node.x, node.y, node.targetX, node.targetY],
    [15, 25, 15, 25],
  );
  assert.equal(node.pending, true);
  assert.equal(f.proxy("a").textContent, "Changed");
  assert.equal(f.proxy("a")["aria-pressed"], "true");
  f.graph.update(items(), edges());
  assert.equal(node.data.pending, undefined);
  assert.equal(node.pending, false);
});
test("input reordering preserves worker index order and existing coordinates", async () => {
  const f = await fixture();
  f.graph.update(items(), edges());
  f.layoutCallbacks.onPositions(new Float32Array([1, 2, 0, 3, 4, 0]));
  f.graph.update(items().reverse(), edges());
  assert.equal(f.count("layout.update"), 1);
  assert.deepEqual(
    f.last("update")[1].map((node) => node.id),
    ["a", "b"],
  );
  f.graph.update([...items(), { id: "c", title: "Gamma" }], edges());
  assert.equal(f.count("layout.update"), 2);
  assert.equal(f.last("layout.update")[1][0].x, 1);
});
test("typed parallel relations remain separate and topology changes restart layout once", async () => {
  const f = await fixture();
  f.graph.update(items(), [...edges(), { ...edges()[0], type: "source" }]);
  assert.equal(f.last("update")[2].length, 2);
  f.graph.update(items(), [{ ...edges()[0], type: "source" }, ...edges()]);
  assert.equal(f.count("layout.update"), 1);
  f.graph.update(items(), [{ ...edges()[0], type: "states" }]);
  assert.equal(f.count("layout.update"), 2);
});
test("selection rejection protects state for pointer and keyboard entry", async () => {
  let allow = false;
  const seen = [];
  const f = await fixture({
    onSelect: (data) => {
      seen.push(data.title);
      return allow;
    },
  });
  f.graph.update(items(), edges(), { selected: "a" });
  assert.equal(f.callbacks.onSelect("b"), false);
  f.proxy("b").onclick();
  assert.equal(f.proxy("a")["aria-pressed"], "true");
  allow = true;
  f.graph.update(
    items().map((node) => ({ ...node, title: node.title + " updated" })),
    edges(),
  );
  f.proxy("b").onclick();
  assert.equal(seen.at(-1), "Beta updated");
  assert.equal(f.proxy("b")["aria-pressed"], "true");
});
test("background veto and keyboard focus use the current node state", async () => {
  let allow = false;
  const f = await fixture({ options: { onBackground: () => allow } });
  f.graph.update(items(), edges(), { selected: "a" });
  f.callbacks.onBackground();
  assert.equal(f.proxy("a")["aria-pressed"], "true");
  allow = true;
  f.callbacks.onBackground();
  assert.equal(f.proxy("a")["aria-pressed"], "false");
  f.proxy("b").onfocus();
  assert.equal(f.last("focusNode")[1], "b");
  f.proxy("b").onblur();
  assert.equal(f.last("focus")[1].keyboard, null);
});
test("worker targets preserve dragged position and settled fit is requested", async () => {
  const f = await fixture();
  f.graph.update(items(), edges());
  f.callbacks.onDragStart("a");
  f.callbacks.onDragMove("a", 90, 80);
  f.layoutCallbacks.onPositions(new Float32Array([1, 2, 0, 3, 4, 0]));
  assert.equal(f.last("update")[1][0].x, 90);
  f.callbacks.onDragEnd();
  f.layoutCallbacks.onSettled(new Float32Array([90, 80, 0, 3, 4, 0]));
  assert.equal(f.count("settled"), 1);
  assert.equal(f.count("layout.dragEnd"), 1);
});
test("visibility and reduced motion are coordinated with resize", async () => {
  const f = await fixture({ hidden: true });
  assert.equal(f.count("layout.pause"), 1);
  assert.equal(f.count("pause"), 1);
  f.document.hidden = false;
  f.document.emit("visibilitychange");
  assert.equal(f.count("layout.resume"), 1);
  f.observers[0].callback();
  assert.equal(f.count("resize"), 1);
  f.motion.matches = true;
  f.motion.emit("change");
  assert.equal(f.last("configure")[1].reducedMotion, true);
});
test("search, empty data and complete idempotent teardown are supported", async () => {
  const f = await fixture();
  f.graph.update(items(), edges());
  f.graph.setQuery("alpha");
  assert.equal(f.last("update")[1][0].queryHit, true);
  assert.equal(f.last("focusNode")[1], "a");
  const focused = f.count("focusNode");
  f.graph.update(items(), edges());
  f.graph.setQuery("alpha");
  assert.equal(f.count("focusNode"), focused);
  f.graph.update([], []);
  assert.equal(f.last("update")[1].length, 0);
  const count = f.calls.length;
  f.graph.destroy();
  f.graph.destroy();
  f.layoutCallbacks.onPositions(new Float32Array(0));
  f.callbacks.onSelect("a");
  f.graph.update(items(), edges());
  assert.equal(f.count("layout.destroy"), 1);
  assert.equal(f.count("destroy"), 1);
  assert.ok(f.observers[0].disconnected);
  assert.equal(f.document.listeners.get("visibilitychange").size, 0);
  assert.equal(f.motion.listeners.get("change").size, 0);
  assert.equal(f.calls.length, count + 3);
});

for (const failDuring of ["renderer", "layout"]) {
  test(`synchronous ${failDuring} failure tears down the completed graph without a TDZ error`, async () => {
    const f = await fixture({ failDuring });
    assert.equal(f.count("layout.destroy"), 1);
    assert.equal(f.count("destroy"), 1);
    assert.equal(f.count("controls.destroy"), 1);
    assert.ok(f.observers[0].disconnected);
    assert.equal(f.host.children.length, 1);
    assert.equal(f.host.children[0].className, "graph-error");
    assert.equal(f.host.children[0].hidden, false);
    f.graph.update(items(), edges());
    f.layoutCallbacks.onPositions(new Float32Array([1, 2, 0]));
    f.layoutCallbacks.onSettled(new Float32Array([1, 2, 0]));
    assert.equal(f.count("layout.update"), 0);
    assert.equal(f.count("positionsChanged"), 0);
    f.graph.destroy();
    assert.equal(f.host.children.length, 0);
    assert.equal(f.count("layout.destroy"), 1);
  });
}

test("a failed renderer stops an active layout and ignores queued callbacks", async () => {
  const f = await fixture();
  f.graph.update(items(), edges());
  assert.equal(f.count("layout.update"), 1);
  f.callbacks.onError("WebGL initialization failed");
  f.layoutCallbacks.onPositions(new Float32Array([1, 2, 0, 3, 4, 0]));
  f.layoutCallbacks.onSettled(new Float32Array([1, 2, 0, 3, 4, 0]));
  f.layoutCallbacks.onError("Late Worker error");
  f.observers[0].callback();
  f.document.emit("visibilitychange");
  assert.equal(f.count("positionsChanged"), 0);
  assert.equal(f.count("settled"), 0);
  assert.equal(f.count("resize"), 0);
  assert.equal(f.count("layout.destroy"), 1);
  assert.equal(f.count("destroy"), 1);
  assert.equal(
    f.host.children[0].textContent,
    "图谱加载失败 · WebGL initialization failed",
  );
  assert.ok(
    [...f.document.listeners.values()].every(
      (listeners) => listeners.size === 0,
    ),
  );
  assert.ok(
    [...f.motion.listeners.values()].every((listeners) => listeners.size === 0),
  );
  f.graph.destroy();
  assert.equal(f.host.children.length, 0);
});

test("main graph regions, viewport options and activity survive metadata updates", async () => {
  const f = await fixture({
    options: {
      nodeRegion: (node) => node.family,
      regionColor: () => "#dae4f3",
      separated: true,
      screenSize: true,
      insetTop: 110,
      insetBottom: 35,
      fitPadding: 24,
      nodeClass: () => "day-active",
    },
  });
  const data = [
    { id: "a", title: "A", family: "wiki" },
    { id: "b", title: "B", family: "raw" },
  ];
  f.graph.update(data, []);
  const nodes = f.last("layout.update")[1];
  assert.deepEqual(
    nodes.map((node) => node.anchor),
    [
      { x: -325, y: 0 },
      { x: 325, y: 0 },
    ],
  );
  assert.deepEqual(
    nodes.map((node) => node.region),
    ["wiki", "raw"],
  );
  assert.ok(nodes.every((node) => node.dayActive));
  assert.equal(f.rendererOptions.insetTop, 110);
  assert.equal(f.rendererOptions.insetBottom, 35);
  assert.equal(f.rendererOptions.fitPadding, 24);
  assert.equal(f.rendererOptions.screenSize, true);
  f.graph.update(
    data.map((node) => ({ ...node, title: node.title + " updated" })),
    [],
  );
  assert.equal(f.count("layout.update"), 1);
  f.graph.update(
    data.map((node) => ({ ...node, family: "wiki" })),
    [],
  );
  assert.equal(f.count("layout.update"), 2);
  assert.deepEqual(
    nodes.map((node) => node.anchor),
    [
      { x: 0, y: 0 },
      { x: 0, y: 0 },
    ],
  );
});

test("lasso returns current data nodes and its mode is disposed with the controller", async () => {
  const chosen = [];
  const f = await fixture({
    options: { onLasso: (nodes) => chosen.push(nodes) },
  });
  f.graph.update(items(), edges());
  const toggle = f.tools.children.find((node) => node.textContent === "圈选");
  toggle.onclick();
  assert.equal(f.last("setLasso")[1], true);
  f.callbacks.onLasso(["a", "missing"]);
  assert.deepEqual(chosen, [[items()[0]]]);
  assert.equal(toggle.getAttribute("aria-pressed"), "false");
  assert.equal(
    f.insidePolygon({ x: 5, y: 5 }, [
      { x: 0, y: 0 },
      { x: 10, y: 0 },
      { x: 10, y: 10 },
      { x: 0, y: 10 },
    ]),
    true,
  );
  assert.equal(f.insidePolygon({ x: 5, y: 5 }, []), false);
  f.graph.destroy();
  assert.equal(f.tools.children.includes(toggle), false);
  f.callbacks.onLasso(["a"]);
  assert.equal(chosen.length, 1);
});

test("bundled Worker applies the per-node region anchors", () => {
  const vm = require("node:vm"),
    output = [];
  const self = { postMessage: (message) => output.push(message) };
  const context = vm.createContext({
    self,
    performance: { now: () => 0 },
    Float32Array,
    Uint32Array,
    Int32Array,
    setTimeout: () => 1,
    clearTimeout() {},
    setInterval: () => 1,
    clearInterval() {},
  });
  vm.runInContext(source("vendor/graph-engine/layout.worker.js"), context);
  const send = (message) =>
    self.onmessage({ data: { revision: 1, ...message } });
  send({
    type: "init",
    nodeCount: 2,
    edges: new Uint32Array(),
    positions: new Float32Array(6),
    anchors: new Float32Array([-325, 0, 325, 0]),
    paused: false,
    params: { repel: 0, linkStrength: 0, centering: 0.1 },
  });
  for (let i = 0; i < 250; i++) send({ type: "step" });
  const positions = output.at(-1).positions;
  assert.ok(positions[0] < -300);
  assert.ok(positions[3] > 300);
  assert.ok([...positions].every(Number.isFinite));
  send({ type: "stop" });
});
