"use strict";
const { test, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const { source, moduleUrl, domFixture, Element, settle, deferred } = require("./studio_test_helpers.cjs");
const cleanup = [];
afterEach(() => { while (cleanup.length) cleanup.pop()(); });
const all = node => [node, ...node.children.flatMap(all)];
async function fixture(options = {}) {
  const previous = globalThis.Option;
  globalThis.Option = class extends Element { constructor(text, value) { super("option"); this.textContent = text; this.value = value; } };
  cleanup.push(() => globalThis.Option = previous);
  const frames = [], calls = [], live = [];
  const events = [0, 1, 2].map(i => ({ id: String(i), at: `2026-11-10T08:0${i}:00+08:00`, path: `profiles/goals/2026/11/10/${i}.md`, action: "edit" }));
  const { createTimeline } = await import(moduleUrl(source("studio/timeline.js")));
  const timeline = createTimeline({ dom: domFixture(), events,
    api: { request: async path => { calls.push(path); return { id: new URLSearchParams(path.split("?")[1]).get("id") }; } },
    onSelect: frame => frames.push(frame.id), onCurrent: () => live.push(true), ...options });
  cleanup.push(timeline.destroy);
  const nodes = all(timeline.element);
  return { ...timeline, frames, calls, live, range: nodes.find(n => n.type === "range"),
    play: nodes.find(n => n["aria-label"] === "播放时间轴"), nodes };
}
test("defaults to the live endpoint; scrubbing back is historical and End returns live", async () => {
  const t = await fixture();
  assert.equal(t.range.value, "2000"); assert.equal(t.calls.length, 0);
  const stages = t.element.children.find(n => n["aria-label"] === "时间轴阶段");
  assert.equal(stages.children.length, 3);
  assert.equal(stages.children[2]["aria-pressed"], "true");
  assert.equal(t.nodes.some(n => n.textContent === "当前"), false);
  t.range.value = "0"; t.range.oninput(); await settle();
  assert.deepEqual(t.frames, ["0"]);
  assert.equal(stages.children[0]["aria-pressed"], "true");
  t.range.onkeydown({ key: "End", preventDefault() {} }); await settle();
  assert.equal(t.range.value, "2000"); assert.equal(t.live.length, 1);
  assert.equal(stages.children[2]["aria-pressed"], "true");
});
test("a late history response cannot overwrite a more recent seek", async () => {
  const pending = [deferred(), deferred()];
  const t = await fixture({ api: { request: path => pending[Number(new URLSearchParams(path.split("?")[1]).get("id"))].promise } });
  t.range.value = "0"; t.range.oninput();
  t.range.value = "1000"; t.range.oninput();
  pending[1].resolve({ id: "1" }); await settle();
  pending[0].resolve({ id: "0" }); await settle();
  assert.deepEqual(t.frames, ["1"]);
});
test("dirty edits block seeks and disposal cancels pending frames", async () => {
  let allowed = false; const pending = deferred();
  const t = await fixture({ canLeave: () => allowed, api: { request: () => pending.promise } });
  t.range.value = "0"; t.range.oninput(); assert.equal(t.range.value, "2000");
  allowed = true; t.range.value = "0"; t.range.oninput();
  t.destroy(); pending.resolve({ id: "0" }); await settle();
  assert.deepEqual(t.frames, []);
});
test("playback advances the progress continuously, resumes instead of restarting, and ends live", async () => {
  let now = 0, serial = 0; const timers = new Map();
  const originals = { timeout: globalThis.setTimeout, clear: globalThis.clearTimeout, now: Date.now };
  globalThis.setTimeout = fn => { timers.set(++serial, fn); return serial; };
  globalThis.clearTimeout = id => timers.delete(id); Date.now = () => now;
  cleanup.push(() => { globalThis.setTimeout = originals.timeout; globalThis.clearTimeout = originals.clear; Date.now = originals.now; });
  const advance = async ms => { now += ms; const callbacks = [...timers.values()]; timers.clear(); for (const fn of callbacks) await fn(); };
  const t = await fixture(); await t.play.onclick();
  assert.deepEqual(t.frames, ["0"]);
  await advance(500); assert.equal(t.range.value, "500");
  await t.play.onclick(); const stopped = t.range.value; await advance(500); assert.equal(t.range.value, stopped);
  await t.play.onclick(); await advance(500); assert.equal(t.range.value, "1000");
  assert.deepEqual(t.frames, ["0", "1"]);
  await advance(1000); assert.equal(t.range.value, "2000"); assert.equal(t.live.length, 1);
  assert.equal(t.play["aria-label"], "播放时间轴");
});
test("empty and single-stage days do not offer fake playback", async () => {
  for (const events of [[], [{ id: "one", at: "2026-11-10T00:00:00Z", action: "create", path: "one.md" }]]) {
    const t = await fixture({ events }); assert.equal(t.play.disabled, true); assert.equal(t.range.disabled, true);
  }
});
test("calendar navigation crosses month, year and leap-day boundaries", async () => {
  const { shiftDate } = await import(moduleUrl(source("studio/state.js")));
  assert.equal(shiftDate("2026-01-01", -1), "2025-12-31");
  assert.equal(shiftDate("2024-02-28", 1), "2024-02-29");
  assert.equal(shiftDate("2024-02-29", 1), "2024-03-01");
  assert.equal(shiftDate("2026-03-08", 1), "2026-03-09");
});

test("a second play click cancels startup while its first history frame is pending", async () => {
  const pending = deferred();
  const t = await fixture({ api: { request: () => pending.promise } });
  const startup = t.play.onclick();
  await t.play.onclick();
  pending.resolve({ id: "0" }); await startup;
  assert.equal(t.play["aria-label"], "播放时间轴");
});
