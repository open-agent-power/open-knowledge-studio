"use strict";
const { test, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const { source, moduleUrl } = require("./studio_test_helpers.cjs");

const originalWorker = global.Worker;
afterEach(() => {
  global.Worker = originalWorker;
});

async function fixture(WorkerType) {
  const workers = [],
    frames = [],
    settled = [],
    errors = [];
  class Worker {
    constructor(url) {
      this.url = url;
      this.messages = [];
      this.terminated = 0;
      workers.push(this);
    }
    postMessage(message, transfer) {
      this.messages.push(structuredClone(message, { transfer }));
    }
    terminate() {
      this.terminated++;
    }
    emit(message) {
      this.onmessage?.({ data: message });
    }
  }
  global.Worker = WorkerType || Worker;
  const { createLayout } = await import(
    moduleUrl(source("studio/graph-layout.js"))
  );
  const layout = createLayout({
    onPositions: (positions, alpha) => frames.push({ positions, alpha }),
    onSettled: (positions) => settled.push(positions),
    onError: (error) => errors.push(error),
  });
  return { layout, workers, frames, settled, errors };
}

test("layout maps string IDs and retains coordinates across reordered topology updates", async () => {
  const { layout, workers, frames } = await fixture();
  layout.update(
    [
      { id: "a", x: 10, y: 20 },
      { id: "b", x: NaN, y: NaN },
    ],
    [
      { from: "a", to: "b", type: "cites" },
      { from: "a", to: "missing" },
      { from: "a", to: "a" },
    ],
  );
  const worker = workers[0],
    first = worker.messages[0];
  assert.equal(worker.url, "/vendor/graph-engine/layout.worker.js");
  assert.deepEqual([...first.edges], [0, 1]);
  assert.deepEqual([...first.positions].slice(0, 3), [10, 20, 0]);
  assert.ok(Number.isNaN(first.positions[3]));
  worker.emit({
    type: "tick",
    revision: first.revision,
    positions: new Float32Array([30, 40, 0, 50, 60, 0]),
    alpha: 0.5,
  });
  layout.update(
    [{ id: "b" }, { id: "c", x: 7, y: 8 }, { id: "a" }],
    [{ from: "a", to: "b" }],
  );
  const next = worker.messages.at(-1);
  assert.deepEqual([...next.positions], [50, 60, 0, 7, 8, 0, 30, 40, 0]);
  assert.deepEqual([...next.edges], [2, 0]);
  worker.emit({
    type: "tick",
    revision: first.revision,
    positions: new Float32Array(6),
    alpha: 1,
  });
  assert.equal(frames.length, 1);
  layout.destroy();
});

test("layout preserves parameter and paused state without restarting its Worker", async () => {
  const { layout, workers, settled } = await fixture();
  layout.setParams({ repel: 80 });
  layout.pause();
  layout.update([{ id: "a", x: 1, y: 2 }], []);
  const worker = workers[0];
  assert.equal(worker.messages[0].paused, true);
  assert.equal(worker.messages[0].params.repel, 80);
  layout.resume();
  layout.setParams({ linkDistance: 90 });
  layout.dragStart("a");
  layout.dragMove("a", 12, 34);
  layout.dragEnd();
  assert.deepEqual(
    worker.messages.slice(1).map((message) => message.type),
    ["resume", "params", "drag-start", "drag-move", "drag-end"],
  );
  assert.deepEqual(worker.messages.at(-2), {
    type: "drag-move",
    id: 0,
    x: 12,
    y: 34,
    revision: 1,
  });
  worker.emit({
    type: "end",
    revision: 1,
    positions: new Float32Array([12, 34, 0]),
  });
  assert.equal(settled.length, 1);
  assert.equal(workers.length, 1);
  layout.destroy();
});

test("layout destroy is idempotent and ignores already queued Worker callbacks", async () => {
  const { layout, workers, frames, errors } = await fixture();
  layout.update([{ id: "a" }], []);
  const worker = workers[0],
    lateMessage = worker.onmessage,
    lateError = worker.onerror;
  layout.destroy();
  layout.destroy();
  lateMessage({
    data: {
      type: "tick",
      revision: 1,
      positions: new Float32Array(3),
      alpha: 1,
    },
  });
  lateError({ message: "late error" });
  layout.update([{ id: "b" }], []);
  layout.resume();
  assert.equal(worker.terminated, 1);
  assert.equal(worker.onmessage, null);
  assert.equal(worker.onerror, null);
  assert.equal(worker.onmessageerror, null);
  assert.equal(frames.length, 0);
  assert.equal(errors.length, 0);
  assert.equal(workers.length, 1);
});

test("layout reports Worker startup and runtime failures once without a fallback simulation", async () => {
  const startup = await fixture(
    class Worker {
      constructor() {
        throw new Error("Worker unavailable");
      }
    },
  );
  startup.layout.update([{ id: "a" }], []);
  startup.layout.update([{ id: "a" }], []);
  assert.deepEqual(startup.errors, ["Worker unavailable"]);
  startup.layout.destroy();
  const runtime = await fixture();
  runtime.layout.update([{ id: "a" }], []);
  const worker = runtime.workers[0],
    error = worker.onerror;
  error({ message: "worker stopped" });
  error({ message: "duplicate error" });
  runtime.layout.resume();
  assert.deepEqual(runtime.errors, ["worker stopped"]);
  assert.equal(worker.terminated, 1);
  runtime.layout.destroy();
});

function engineFixture() {
  const output = [],
    timers = new Map();
  let timerId = 0;
  const self = {
    postMessage: (message, transfer) =>
      output.push(structuredClone(message, { transfer })),
  };
  const context = vm.createContext({
    self,
    console,
    performance: { now: () => 0 },
    Float32Array,
    Uint32Array,
    Int32Array,
    setTimeout: (callback) => {
      timers.set(++timerId, callback);
      return timerId;
    },
    clearTimeout: (id) => timers.delete(id),
    setInterval: () => ++timerId,
    clearInterval() {},
  });
  vm.runInContext(source("vendor/graph-engine/layout.worker.js"), context);
  const send = (message) =>
    self.onmessage({ data: { revision: 1, ...message } });
  return { send, output, timers };
}

test("bundled Advanced layout supplies finite 2D seeds and settles through the real d3 engine", () => {
  const { send, output } = engineFixture();
  send({
    type: "init",
    nodeCount: 3,
    edges: new Uint32Array([0, 1, 1, 2]),
    positions: new Float32Array([
      10,
      20,
      0,
      NaN,
      NaN,
      0,
      Infinity,
      -Infinity,
      0,
    ]),
    params: {},
    paused: false,
  });
  assert.equal(output[0].positions.length, 9);
  assert.ok([...output[0].positions].every(Number.isFinite));
  assert.deepEqual([...output[0].positions].slice(0, 3), [10, 20, 0]);
  for (let i = 0; i < 250; i++) send({ type: "step" });
  assert.ok(output.some((message) => message.type === "end"));
  for (const message of output) {
    assert.equal(message.revision, 1);
    assert.ok([...message.positions].every(Number.isFinite));
    assert.equal(message.positions[2], 0);
    assert.equal(message.positions[5], 0);
  }
  send({ type: "stop" });
});

test("bundled layout pauses, resumes, filters old messages and releases dragged pins", () => {
  const { send, output } = engineFixture();
  send({
    type: "init",
    nodeCount: 2,
    edges: new Uint32Array([0, 1]),
    positions: new Float32Array([0, 0, 0, 50, 0, 0]),
    params: {},
    paused: true,
  });
  send({ type: "step" });
  assert.equal(output.length, 1);
  send({ type: "resume" });
  send({ type: "drag-start", id: 0 });
  send({ type: "drag-move", id: 0, x: 150, y: 90 });
  assert.deepEqual([...output.at(-1).positions].slice(0, 3), [150, 90, 0]);
  send({ type: "step" });
  assert.deepEqual([...output.at(-1).positions].slice(0, 3), [150, 90, 0]);
  send({ type: "drag-end" });
  send({ type: "step" });
  assert.notEqual(output.at(-1).positions[0], 150);
  const count = output.length;
  send({ type: "drag-move", id: 0, x: 999, y: 999, revision: 0 });
  assert.equal(output.length, count);
  send({ type: "pause" });
  send({ type: "step" });
  assert.equal(output.length, count);
  send({ type: "stop" });
});

test("sparse document graph keeps linked branches apart among disconnected sources", () => {
  const { send, output } = engineFixture();
  send({
    type: "init",
    nodeCount: 90,
    edges: new Uint32Array(
      Array.from({ length: 12 }, (_, i) => [0, i + 1]).flat(),
    ),
    positions: new Float32Array(270).fill(NaN),
    params: {},
    paused: false,
  });
  for (let i = 0; i < 230; i++) send({ type: "step" });
  const positions = output.at(-1).positions;
  const lengths = Array.from({ length: 12 }, (_, i) =>
    Math.hypot(
      positions[(i + 1) * 3] - positions[0],
      positions[(i + 1) * 3 + 1] - positions[1],
    ),
  ).sort((a, b) => a - b);
  assert.ok([...positions].every(Number.isFinite));
  assert.ok(
    lengths[6] > 180,
    "linked branches must not collapse into a tiny central knot",
  );
  send({ type: "stop" });
});
