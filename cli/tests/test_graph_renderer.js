"use strict";
const { test, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const { source, moduleUrl } = require("./studio_test_helpers.cjs");
let restore;
afterEach(() => {
  restore?.();
  restore = null;
});

async function fixture({
  pendingInit = false,
  partialInit = false,
  throwTextureAt = 0,
  zeroTextBounds = false,
  callbacks = {},
  options = {},
} = {}) {
  const names = [
    "window",
    "PIXI",
    "document",
    "requestAnimationFrame",
    "cancelAnimationFrame",
    "performance",
  ];
  const saved = new Map(
    names.map((name) => [name, Object.getOwnPropertyDescriptor(global, name)]),
  );
  let time = 0,
    frameId = 0;
  const frames = new Map(),
    applications = [],
    meshes = [],
    textures = [],
    textObjects = [],
    graphics = [];
  const textWork = { measurements: 0, textureUpdates: 0 };
  const init = {};
  init.promise = new Promise((resolve, reject) =>
    Object.assign(init, { resolve, reject }),
  );
  const pair = () => ({
    x: 0,
    y: 0,
    set(x, y = x) {
      this.x = x;
      this.y = y;
    },
  });
  class Display {
    constructor() {
      this.children = [];
      this.position = pair();
      this.scale = pair();
      this.alpha = 1;
      this.visible = true;
    }
    addChild(...children) {
      for (const child of children) {
        child.parent = this;
        this.children.push(child);
      }
    }
    destroy(options = {}) {
      this.destroyed = true;
      this.destroyCount = (this.destroyCount || 0) + 1;
      if (options.children)
        for (const child of [...this.children]) child.destroy(options);
      if (this.parent)
        this.parent.children = this.parent.children.filter(
          (child) => child !== this,
        );
    }
  }
  class Canvas {
    constructor() {
      this.style = {};
      this.events = new Map();
    }
    getContext() {
      return {
        font: "",
        fillRect() {},
        measureText(value) {
          textWork.measurements++;
          return { width: [...value].length * 8 };
        },
      };
    }
    getBoundingClientRect() {
      return { left: 0, top: 0, width: 800, height: 600 };
    }
    addEventListener(type, callback, options) {
      if (!this.events.has(type)) this.events.set(type, new Set());
      this.events.get(type).add(callback);
      options.signal.addEventListener("abort", () =>
        this.events.get(type).delete(callback),
      );
    }
    emit(type, values = {}) {
      const event = {
        type,
        button: 0,
        pointerId: 1,
        clientX: 400,
        clientY: 300,
        preventDefault() {},
        ...values,
      };
      for (const callback of this.events.get(type) || []) callback(event);
    }
    setPointerCapture() {}
    remove() {
      if (this.parent)
        this.parent.children = this.parent.children.filter(
          (child) => child !== this,
        );
    }
  }
  class Graphics extends Display {
    constructor() {
      super();
      this.strokes = 0;
      this.ellipses = [];
      graphics.push(this);
    }
    clear() {
      this.strokes = 0;
      this.ellipses = [];
      return this;
    }
    ellipse(...args) {
      this.ellipses.push(args);
      return this;
    }
    stroke() {
      this.strokes++;
      return this;
    }
  }
  for (const method of [
    "circle",
    "fill",
    "moveTo",
    "lineTo",
    "arc",
    "closePath",
  ])
    Graphics.prototype[method] = function () {
      return this;
    };
  class Sprite extends Display {
    constructor(texture) {
      super();
      this.texture = texture;
      this.anchor = pair();
    }
  }
  class Text extends Display {
    constructor({ text }) {
      super();
      this.text = text;
      this.anchor = pair();
      textObjects.push(this);
    }
    get text() {
      return this._text;
    }
    set text(value) {
      if (value !== this._text) textWork.textureUpdates++;
      this._text = value;
    }
    get width() {
      return zeroTextBounds ? 0 : [...this.text].length * 8;
    }
  }
  class Mesh extends Display {
    constructor({ geometry }) {
      super();
      this.geometry = geometry;
      meshes.push(this);
    }
  }
  class MeshGeometry {
    constructor({ positions, uvs }) {
      const buffer = (data) => ({
        data,
        updates: 0,
        update() {
          this.updates++;
        },
        destroy() {},
      });
      this.buffers = [buffer(positions), buffer(uvs)];
      this.indexBuffer = { destroy() {} };
    }
    getBuffer(name) {
      return this.buffers[name === "aUV" ? 1 : 0];
    }
    destroy() {}
  }
  class CanvasSource {
    constructor(options) {
      Object.assign(this, options);
    }
    destroy() {
      this.dead = this.destroyed = true;
    }
  }
  class Texture {
    static WHITE = {};
    constructor({ source }) {
      this.source = source;
      textures.push(this);
    }
    destroy() {
      this.dead = this.destroyed = true;
      this.source.destroy();
    }
  }
  class Application {
    constructor() {
      this.canvas = new Canvas();
      this.stage = new Display();
      this.ticker = { stop() {} };
      let generated = 0;
      this.renderer = partialInit
        ? undefined
        : {
            resize() {},
            generateTexture() {
              if (++generated === throwTextureAt)
                throw new Error("texture allocation failed");
              const texture = {
                destroy() {
                  texture.dead = texture.destroyed = true;
                },
              };
              textures.push(texture);
              return texture;
            },
            destroy() {
              this.destroyed = true;
              this.destroyCount = (this.destroyCount || 0) + 1;
            },
          };
      if (partialInit) this.ticker = undefined;
      applications.push(this);
    }
    async init() {
      if (pendingInit) await init.promise;
    }
    render() {
      this.renders = (this.renders || 0) + 1;
    }
    destroy(_, options) {
      this.destroyCount = (this.destroyCount || 0) + 1;
      this.stage.destroy(options);
      this.renderer.destroy();
      this.canvas.remove();
    }
  }
  const PIXI = {
    Application,
    Container: Display,
    Graphics,
    Sprite,
    Text,
    Mesh,
    MeshGeometry,
    Texture,
    CanvasSource,
  };
  const document = { hidden: false, createElement: () => new Canvas() };
  for (const [name, value] of Object.entries({
    window: { PIXI, devicePixelRatio: 1 },
    PIXI,
    document,
    requestAnimationFrame: (callback) => {
      const id = ++frameId;
      frames.set(id, callback);
      return id;
    },
    cancelAnimationFrame: (id) => frames.delete(id),
    performance: { now: () => time },
  }))
    Object.defineProperty(global, name, {
      value,
      configurable: true,
      writable: true,
    });
  const host = {
    clientWidth: 800,
    clientHeight: 600,
    children: [],
    append(child) {
      child.parent = this;
      this.children.push(child);
    },
  };
  const imports = [
    ["../vendor/graph-engine/edge-mesh.js", "vendor/graph-engine/edge-mesh.js"],
    [
      "../vendor/graph-engine/position-smoothing.js",
      "vendor/graph-engine/position-smoothing.js",
    ],
    ["./graph-camera.js", "studio/graph-camera.js"],
  ];
  let code = source("studio/graph-renderer.js");
  for (const [specifier, path] of imports)
    code = code.replace(`"${specifier}"`, `"${moduleUrl(source(path))}"`);
  const { createRenderer, createCollisionGrid } = await import(moduleUrl(code));
  const renderer = createRenderer(host, callbacks, options);
  restore = () => {
    renderer.destroy();
    for (const [name, descriptor] of saved) {
      if (descriptor) Object.defineProperty(global, name, descriptor);
      else delete global[name];
    }
  };
  return {
    renderer,
    createCollisionGrid,
    host,
    frames,
    applications,
    meshes,
    textures,
    textObjects,
    graphics,
    textWork,
    init,
    advance(count = 1) {
      for (let index = 0; index < count; index++) {
        time += 1000 / 60;
        const pending = [...frames.values()];
        frames.clear();
        for (const callback of pending) callback(time);
      }
    },
  };
}

const node = (id, x, y) => ({
  id,
  title: id,
  x,
  y,
  targetX: x,
  targetY: y,
  radius: 7,
  color: "#879fc3",
});

test("renderer waits for real positions and eventually stops its RAF", async () => {
  const { renderer, frames, applications, advance } = await fixture();
  const data = node("待定位节点", NaN, NaN);
  renderer.update([data], []);
  await renderer.ready;
  advance(2);
  assert.equal(frames.size, 0);
  assert.ok(Number.isNaN(data.x));
  Object.assign(data, { x: 80, y: 40, targetX: 80, targetY: 40 });
  renderer.positionsChanged();
  advance(100);
  assert.deepEqual(renderer.getCamera(), { x: 80, y: 40, scale: 1.2 });
  assert.equal(frames.size, 0);
  assert.ok(applications[0].renders > 0);
});

test("metadata updates and repeated focus retain base edge geometry", async () => {
  const { renderer, applications, meshes, advance } = await fixture();
  const nodes = [node("a", -100, 0), node("b", 100, 0)];
  const edges = [
    { from: "a", to: "b", type: "cites" },
    { from: "a", to: "b", type: "contains" },
  ];
  renderer.update(nodes, edges);
  await renderer.ready;
  advance(100);
  assert.equal(meshes.length, 2);
  const bases = [...meshes];
  const sprite = applications[0].stage.children[0].children[2].children[0];
  assert.equal(sprite.tint, nodes[0].color);
  nodes[0].title = "更新后的标题";
  nodes[0].color = "#a88b58";
  renderer.update(
    [...nodes],
    edges.map((edge) => ({ ...edge, label: "关系" })),
  );
  renderer.focus({ selected: null, hover: null, keyboard: null });
  advance(100);
  assert.equal(sprite.tint, "#a88b58");
  assert.equal(meshes.length, 2);
  renderer.focus({ hover: "a" });
  advance(100);
  assert.equal(meshes.length, 3);
  renderer.focus({ hover: "a" });
  assert.equal(meshes.length, 3);
  renderer.focus({ hover: "b" });
  assert.equal(meshes.length, 4);
  assert.ok(bases.every((mesh) => !mesh.destroyCount));
});

test("pending and shared-tag edges share repeated dash textures in mesh batches", async () => {
  const { renderer, meshes, applications, advance } = await fixture();
  renderer.update(
    [node("a", -100, 0), node("b", 100, 0)],
    [
      { from: "a", to: "b", type: "shared_tag" },
      { from: "b", to: "a", type: "cites", dashed: true },
    ],
  );
  await renderer.ready;
  advance(100);
  assert.equal(meshes.length, 2);
  assert.equal(applications[0].stage.children[1].strokes, 0);
  assert.equal(meshes[0].texture, meshes[1].texture);
  assert.equal(meshes[0].texture.source.addressMode, "repeat");
  assert.equal(meshes[0].texture.source.resource.width, 8);
  assert.ok(meshes.every((mesh) => mesh.geometry.getBuffer("aUV").data[4] > 1));
});

test("a rejected node selection keeps camera and selection unchanged", async () => {
  const selections = [];
  const { renderer, applications, advance } = await fixture({
    callbacks: {
      onSelect(id) {
        selections.push(id);
        return false;
      },
    },
  });
  renderer.update([node("a", 0, 0)], []);
  await renderer.ready;
  advance(100);
  const before = renderer.getCamera(),
    canvas = applications[0].canvas;
  canvas.emit("pointerdown");
  canvas.emit("pointerup");
  advance(100);
  assert.deepEqual(selections, ["a"]);
  assert.deepEqual(renderer.getCamera(), before);
  assert.equal(
    applications[0].stage.children[2].children.filter((ring) => ring.visible)
      .length,
    0,
  );
});

test("dragged positions take priority over stale worker targets", async () => {
  let starts = 0,
    ends = 0;
  const { renderer, applications, advance } = await fixture({
    callbacks: {
      onDragStart() {
        starts++;
      },
      onDragEnd() {
        ends++;
      },
    },
  });
  const data = node("a", 0, 0);
  renderer.update([data], []);
  await renderer.ready;
  advance(100);
  const canvas = applications[0].canvas;
  canvas.emit("pointerdown");
  canvas.emit("pointermove", { clientX: 460 });
  const draggedX = data.x;
  data.targetX = -1000;
  renderer.positionsChanged();
  advance(3);
  assert.equal(data.x, draggedX);
  canvas.emit("pointercancel");
  advance(1);
  assert.equal(starts, 1);
  assert.equal(ends, 1);
  assert.equal(data.x, draggedX);
});

test("pause cancels scheduled work and destroy removes handlers and textures", async () => {
  const { renderer, applications, frames, textures, advance } = await fixture();
  const data = node("a", 0, 0);
  renderer.update([data], []);
  await renderer.ready;
  advance(100);
  data.targetX = 100;
  renderer.positionsChanged();
  renderer.pause();
  assert.equal(frames.size, 0);
  renderer.positionsChanged();
  assert.equal(frames.size, 0);
  renderer.resume();
  advance(1);
  assert.ok(data.x > 0);
  renderer.destroy();
  renderer.destroy();
  assert.equal(frames.size, 0);
  assert.ok(
    [...applications[0].canvas.events.values()].every(
      (listeners) => listeners.size === 0,
    ),
  );
  assert.ok(textures.every((texture) => texture.dead));
  assert.equal(applications[0].destroyCount, 1);
});

test("destroying during asynchronous Pixi initialization never mounts a canvas", async () => {
  const { renderer, applications, host, frames, init } = await fixture({
    pendingInit: true,
  });
  renderer.update([node("a", 0, 0)], []);
  renderer.destroy();
  init.resolve();
  assert.equal(await renderer.ready, false);
  assert.equal(host.children.length, 0);
  assert.equal(applications[0].destroyCount, 1);
  assert.equal(frames.size, 0);
});

test("initial reduced motion snaps targets without an animation tail", async () => {
  const { renderer, frames, advance } = await fixture({
    options: { reducedMotion: true },
  });
  const data = node("a", 0, 0);
  renderer.update([data], []);
  await renderer.ready;
  advance(2);
  data.targetX = 200;
  renderer.positionsChanged();
  advance(2);
  assert.equal(data.x, 200);
  assert.equal(frames.size, 0);
});

test("settled layout is fitted again until the user takes control", async () => {
  const { renderer, advance } = await fixture();
  const nodes = [node("a", -200, 0), node("b", 200, 0)];
  renderer.update(nodes, []);
  await renderer.ready;
  advance(100);
  const initialScale = renderer.getCamera().scale;
  nodes[0].targetX = -50;
  nodes[1].targetX = 50;
  renderer.positionsChanged();
  renderer.settled();
  advance(100);
  assert.equal(renderer.getCamera().scale, 3);
  assert.ok(initialScale < 3);
  renderer.zoomBy(0.5);
  advance(100);
  const userCamera = renderer.getCamera();
  nodes[0].targetX = -20;
  nodes[1].targetX = 20;
  renderer.positionsChanged();
  renderer.settled();
  advance(100);
  assert.deepEqual(renderer.getCamera(), userCamera);
});

test("label collisions use measured text even before Pixi texture bounds exist", async () => {
  const { renderer, applications, advance } = await fixture({
    zeroTextBounds: true,
  });
  const nodes = [node("中文标题一", -20, 0), node("中文标题二", 20, 0)];
  renderer.update(nodes, []);
  await renderer.ready;
  advance(100);
  renderer.setCamera({ x: 0, y: 0, scale: 0.3 });
  advance(100);
  const visible = applications[0].stage.children[3].children.filter(
    (label) => label.visible,
  );
  assert.ok(visible.length > 0);
  for (let index = 0; index < visible.length; index++) {
    for (const other of visible.slice(index + 1)) {
      const label = visible[index];
      const horizontalGap = Math.abs(label.position.x - other.position.x);
      const requiredWidth =
        (([...label.text].length + [...other.text].length) * 8) / 2 + 8;
      assert.ok(
        horizontalGap >= requiredWidth ||
          Math.abs(label.position.y - other.position.y) >= 20,
      );
    }
  }
});

test("collision-rejected cold labels never become visible at the origin", async () => {
  const { renderer, applications, textObjects, advance } = await fixture();
  const nodes = Array.from({ length: 10 }, (_, index) =>
    node(`拥挤标题${index}`, index * 0.5, 0),
  );
  renderer.update(nodes, []);
  await renderer.ready;
  renderer.setCamera({ x: 0, y: 0, scale: 0.3 });
  advance(1);
  const visible = applications[0].stage.children[3].children.filter(
    (label) => label.visible,
  );
  assert.ok(visible.length > 0);
  assert.ok(
    visible.every((label) => label.position.x !== 0 || label.position.y !== 0),
  );
  assert.equal(textObjects.length, visible.length);
  assert.ok(textObjects.length < nodes.length);
});

test("hovered document remains readable when surrounding dots block every label position", async () => {
  const { renderer, applications, advance } = await fixture();
  const nodes = [node("正在查看的文档", 0, 0)];
  for (let y = -40; y <= 40; y += 10) {
    for (let x = -160; x <= 160; x += 20) {
      if (x || y) nodes.push(node(`周围-${x}-${y}`, x, y));
    }
  }
  renderer.update(nodes, []);
  await renderer.ready;
  renderer.setCamera({ x: 0, y: 0, scale: 1 });
  renderer.focus({ hover: nodes[0].id });
  advance(100);
  const label = applications[0].stage.children[3].children.find(
    (item) => item.text === nodes[0].title,
  );
  assert.ok(label?.visible);
  assert.ok(label.alpha > 0.95);
});

test("large graph overview keeps readable labels below half scale", async () => {
  const { renderer, applications, advance } = await fixture();
  const nodes = [
    node("可读来源", 0, 0),
    ...Array.from({ length: 90 }, (_, index) =>
      node(`远处${index}`, 5000 + index * 100, 5000),
    ),
  ];
  renderer.update(nodes, []);
  await renderer.ready;
  renderer.setCamera({ x: 0, y: 0, scale: 0.3 });
  advance(100);
  const label = applications[0].stage.children[3].children.find(
    (item) => item.text === "可读来源" && item.visible,
  );
  assert.ok(label);
  assert.ok(label.alpha >= 0.6);
});

test("cold labels and metadata texture updates share a four-per-frame budget", async () => {
  const { renderer, textObjects, textWork, advance } = await fixture();
  const nodes = Array.from({ length: 20 }, (_, index) =>
    node(
      `节点${index}`,
      -240 + (index % 5) * 120,
      -150 + Math.floor(index / 5) * 100,
    ),
  );
  renderer.update(nodes, []);
  await renderer.ready;
  renderer.setCamera({ x: 0, y: 0, scale: 1 });
  for (let frame = 0; frame < 5; frame++) {
    const before = textWork.textureUpdates;
    advance(1);
    assert.ok(textWork.textureUpdates - before <= 4);
  }
  assert.equal(textObjects.length, nodes.length);
  const measured = textWork.measurements;
  renderer.positionsChanged();
  advance(100);
  assert.equal(textWork.measurements, measured);
  nodes.forEach((data) => {
    data.title += "更新";
  });
  renderer.update(nodes, []);
  for (let frame = 0; frame < 5; frame++) {
    const before = textWork.textureUpdates;
    advance(1);
    assert.ok(textWork.textureUpdates - before <= 4);
  }
  assert.equal(textObjects.length, nodes.length);
  assert.equal(textWork.textureUpdates, nodes.length * 2);
});

test("collision cells preserve overlap checks across boundaries", async () => {
  const { createCollisionGrid } = await fixture();
  const grid = createCollisionGrid(64);
  grid.add({ left: 60, right: 75, top: 60, bottom: 75 });
  assert.equal(
    grid.overlaps({ left: 65, right: 80, top: 65, bottom: 80 }),
    true,
  );
  assert.equal(
    grid.overlaps({ left: 75, right: 90, top: 60, bottom: 75 }),
    false,
  );
  assert.equal(
    grid.overlaps({ left: 200, right: 220, top: 200, bottom: 220 }),
    false,
  );
  grid.add({ left: -20, right: -10, top: -20, bottom: -10 });
  assert.equal(
    grid.overlaps({ left: -15, right: -5, top: -15, bottom: -5 }),
    true,
  );
});

test("pure pan retains edge buffers while zoom refreshes screen-space dashes", async () => {
  const { renderer, applications, meshes, advance } = await fixture();
  renderer.update(
    [node("a", -100, 0), node("b", 100, 0)],
    [{ from: "a", to: "b", type: "shared_tag" }],
  );
  await renderer.ready;
  advance(100);
  const buffer = meshes[0].geometry.getBuffer("aPosition"),
    uvs = meshes[0].geometry.getBuffer("aUV");
  const uploads = buffer.updates,
    repeat = uvs.data[4],
    canvas = applications[0].canvas;
  canvas.emit("pointerdown", { clientX: 20, clientY: 20 });
  canvas.emit("pointermove", { clientX: 70, clientY: 30 });
  advance(1);
  assert.equal(buffer.updates, uploads);
  canvas.emit("pointerup", { clientX: 70, clientY: 30 });
  advance(100);
  renderer.zoomBy(1.3);
  advance(100);
  assert.ok(buffer.updates > uploads);
  assert.ok(uvs.data[4] > repeat);
});

test("pending node rings reuse textures without rebuilding per-node graphics", async () => {
  const { renderer, applications, textures, advance } = await fixture();
  const nodes = [node("a", -100, 0), node("b", 100, 0)];
  nodes.forEach((data) => {
    data.pending = true;
  });
  renderer.update(nodes, []);
  await renderer.ready;
  advance(100);
  const ringLayer = applications[0].stage.children[2],
    rings = [...ringLayer.children];
  const textureCount = textures.length;
  assert.equal(rings.length, 2);
  assert.equal(rings[0].texture, rings[1].texture);
  renderer.focus({ hover: "a" });
  advance(100);
  assert.equal(ringLayer.children.length, 2);
  assert.equal(textures.length, textureCount);
  assert.notEqual(rings[0].texture, rings[1].texture);
});

test("restoring a camera directly refreshes dash UVs and line widths", async () => {
  const { renderer, meshes, advance } = await fixture();
  renderer.update(
    [node("a", -100, 0), node("b", 100, 0)],
    [{ from: "a", to: "b", type: "shared_tag" }],
  );
  await renderer.ready;
  advance(100);
  const positions = meshes[0].geometry.getBuffer("aPosition"),
    uvs = meshes[0].geometry.getBuffer("aUV");
  const uploads = positions.updates;
  renderer.setCamera({ x: 20, y: 10, scale: 0.6 });
  advance(1);
  assert.equal(positions.updates, uploads + 1);
  assert.ok(Math.abs(Math.abs(positions.data[1]) - 1 / 1.2) < 0.001);
  assert.ok(Math.abs(uvs.data[4] - 12) < 0.001);
});

test("initialization rejection frees the constructor stage before or after destroy", async () => {
  for (const destroyFirst of [false, true]) {
    const errors = [];
    const { renderer, applications, frames, host, init } = await fixture({
      pendingInit: true,
      partialInit: true,
      callbacks: { onError: (message) => errors.push(message) },
    });
    if (destroyFirst) renderer.destroy();
    init.reject(new Error("renderer initialization failed"));
    assert.equal(await renderer.ready, false);
    renderer.destroy();
    assert.equal(applications[0].stage.destroyCount, 1);
    assert.equal(applications[0].destroyCount, undefined);
    assert.equal(host.children.length, 0);
    assert.equal(frames.size, 0);
    assert.deepEqual(
      errors,
      destroyFirst ? [] : ["renderer initialization failed"],
    );
    restore();
    restore = null;
  }
});

test("texture allocation failure releases temporary graphics and owned GPU resources once", async () => {
  const errors = [];
  const { renderer, applications, frames, host, textures, graphics } =
    await fixture({
      throwTextureAt: 2,
      callbacks: { onError: (message) => errors.push(message) },
    });
  assert.equal(await renderer.ready, false);
  renderer.destroy();
  renderer.destroy();
  assert.deepEqual(errors, ["texture allocation failed"]);
  assert.equal(applications[0].destroyCount, 1);
  assert.equal(applications[0].renderer.destroyCount, 1);
  assert.ok(textures.every((texture) => texture.dead));
  assert.ok(graphics.every((graphic) => graphic.destroyCount === 1));
  assert.equal(host.children.length, 0);
  assert.equal(frames.size, 0);
});

test("insets keep hit testing, zoom and lasso on the rendered node pixels", async () => {
  const { insidePolygon } = await import(
    moduleUrl(source("studio/graph.js").replace(/^import .*;$/gm, ""))
  );
  const selections = [],
    lassos = [];
  const page = await fixture({
    options: {
      insetTop: 110,
      insetBottom: 35,
      screenSize: true,
      reducedMotion: true,
      insidePolygon,
    },
    callbacks: {
      onSelect: (id) => selections.push(id),
      onLasso: (ids) => lassos.push(ids),
    },
  });
  const a = {
    ...node("a", 0, 0),
    data: { children: [] },
    dayActive: true,
    region: "wiki",
    regionColor: "#dae4f3",
  };
  const b = { ...node("b", 250, 0), region: "wiki", regionColor: "#dae4f3" };
  page.renderer.update([a, b, node("c", -250, 0)], []);
  await page.renderer.ready;
  page.renderer.setCamera({ x: 0, y: 0, scale: 0.25 });
  page.advance(100);
  const app = page.applications[0],
    world = app.stage.children[0];
  assert.equal(world.position.y, 337.5);
  assert.deepEqual(world.children[0].ellipses, [[125, 0, 200, 60]]);
  assert.equal(world.children[2].children[0].width * 0.25, 24);
  assert.equal(world.children[2].children[1].width * 0.25, 7);
  assert.equal(app.stage.children[2].children[0].tint, 0x7d9bce);
  app.canvas.emit("pointerdown", { clientX: 400, clientY: 337.5 });
  app.canvas.emit("pointerup", { clientX: 400, clientY: 337.5 });
  assert.deepEqual(selections, ["a"]);
  page.renderer.setLasso(true);
  app.canvas.emit("pointerdown", { clientX: 390, clientY: 325 });
  for (const [x, y] of [
    [410, 325],
    [410, 350],
    [390, 350],
  ])
    app.canvas.emit("pointermove", { clientX: x, clientY: y });
  app.canvas.emit("pointerup", { clientX: 390, clientY: 325 });
  assert.deepEqual(lassos, [["a"]]);
  assert.deepEqual(selections, ["a"]);
  app.canvas.emit("wheel", {
    clientX: 462.5,
    clientY: 337.5,
    deltaY: -120,
    deltaMode: 0,
  });
  page.advance(100);
  app.canvas.emit("pointerdown", { clientX: 462.5, clientY: 337.5 });
  app.canvas.emit("pointerup", { clientX: 462.5, clientY: 337.5 });
  assert.deepEqual(selections, ["a", "b"]);
});

test("initial fit follows expanding region targets until the user takes control", async () => {
  const page = await fixture({ options: { insetTop: 110, insetBottom: 35 } });
  const nodes = [node("a", -20, 0), node("b", 20, 0)];
  page.renderer.update(nodes, []);
  await page.renderer.ready;
  page.advance(20);
  const initial = page.renderer.getCamera();
  Object.assign(nodes[0], { targetX: -650, targetY: -250 });
  Object.assign(nodes[1], { targetX: 650, targetY: 250 });
  page.renderer.positionsChanged();
  page.advance(100);
  const fitted = page.renderer.getCamera();
  assert.ok(fitted.scale < initial.scale / 2);
  for (const node of nodes) {
    const x = 400 + (node.x - fitted.x) * fitted.scale;
    const y = 337.5 + (node.y - fitted.y) * fitted.scale;
    assert.ok(x > 0 && x < 800);
    assert.ok(y > 110 && y < 565);
  }
  page.renderer.setCamera({ x: 130, y: 25, scale: 0.5 });
  Object.assign(nodes[0], { targetX: -1200, targetY: -500 });
  page.renderer.positionsChanged();
  page.advance(100);
  assert.deepEqual(page.renderer.getCamera(), { x: 130, y: 25, scale: 0.5 });
});

test("configured fit padding applies to initial, settled and manual fit", async () => {
  async function scales(fitPadding) {
    const page = await fixture({
      options: {
        insetTop: 110,
        insetBottom: 35,
        reducedMotion: true,
        fitPadding,
      },
    });
    const nodes = [node("a", 0, -200), node("b", 0, 200)];
    page.renderer.update(nodes, []);
    await page.renderer.ready;
    page.advance(100);
    const initial = page.renderer.getCamera().scale;
    page.renderer.settled();
    const settled = page.renderer.getCamera().scale;
    page.renderer.fit();
    const manual = page.renderer.getCamera().scale;
    page.renderer.destroy();
    return { initial, settled, manual };
  }
  const standard = await scales(undefined);
  const compact = await scales(24);
  for (const stage of ["initial", "settled", "manual"]) {
    assert.ok(compact[stage] > standard[stage], stage);
  }
  assert.deepEqual(await scales(64), standard);
});
