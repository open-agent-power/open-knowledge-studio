"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const { source, moduleUrl, domFixture, Element, settle, deferred } = require("./studio_test_helpers.cjs");

async function controller(options = {}) {
  const dom = domFixture(), events = {}, timers = [], calls = [], posts = [];
  const creations = [];
  let state, actions;
  const location = { hash: options.hash || "#tab=goals", href: "http://local/studio.html", origin: "http://local" };
  const tabs = ["discuss", "goals", "learning"].map(tab =>
    Object.assign(new Element("button"), { dataset: { tab } }));
  for (const name of ["newDialog", "fileDialog", "libraryDialog"])
    Object.assign(dom.$(name), { showModal() { this.open = true; }, close() { this.open = false; } });
  const { createStudioState, shiftDate } = await import(moduleUrl(source("studio/state.js")));
  const { createStudioApi } = await import(moduleUrl(source("studio/api.js")));
  const context = { knowledge_base: "/kb", local_edit: true, local_review: true, ...options.context };
  const request = async (url, config) => {
    calls.push(url);
    if (config) {
      posts.push({ url, body: JSON.parse(config.body) });
      if (options.postError) throw Error(options.postError);
      if (options.post) return options.post(url, JSON.parse(config.body));
      return {};
    }
    if (url === "/api/studio/onboarding") return { status: "skipped", steps: {} };
    if (options.request) {
      const result = options.request(url);
      if (result !== undefined) return result;
    }
    const kind = new URLSearchParams(url.split("?")[1]).get("kind") || "goal";
    const path = "profiles/" + (kind === "goal" ? "goals" : "discuss") + "/2026/11/11/one.md";
    return { knowledge_base: context.knowledge_base, scope: path, version: kind + "-v1",
      entry: path, entries: [path], files: { [path]: { kind, path, sha256: "old" } }, warnings: [] };
  };
  const view = name => ({ state: shared, actions: supplied }) => {
    state = shared; actions = supplied;
    return {
      render() {},
      destroy() {},
      startCreate() { creations.push(name); },
    };
  };
  const sandbox = {
    console, URLSearchParams, Date, setInterval: fn => timers.push(fn),
    createStudioState, shiftDate, createStudioApi,
    createDiscussionView: view("discuss"), createGoalsView: view("goals"),
    createLearningView: view("learning"), createSettingsView: () => ({}),
    createLibrariesView: () => ({ open() {} }), renderOnboarding() {},
    ...dom,
    history: { replaceState(a, b, hash) { location.hash = hash; } }, location,
    window: { OksStudioModel: {}, OksWorkspace: { ready: Promise.resolve(context), request, recovery() {} },
      addEventListener(name, fn) { events[name] = fn; } },
    document: { hidden: false, title: "", querySelector: () => dom.$("dateLabel"),
      querySelectorAll: () => tabs, addEventListener(name, fn) { events[name] = fn; } },
  };
  vm.runInNewContext(source("studio.js").replace(/^import .*;\r?\n/gm, ""), sandbox);
  await settle(); await settle();
  return { dom, state, actions, events, timers, calls, posts, creations, location };
}

test("goals expose the create action and learning keeps that action out of its toolbar", async () => {
  const page = await controller({ hash: "#tab=goals&date=2026-11-11" });
  assert.equal(page.dom.$("newGoal").hidden, false);
  assert.equal(page.dom.$("newGoal").textContent, "新增目标");
  page.dom.$("newGoal").onclick();
  assert.deepEqual(page.creations, ["goals"]);
  await page.actions.navigate("learning");
  assert.equal(page.dom.$("newGoal").hidden, true);
});

test("read-only create action remains visible with a concrete disabled reason", async () => {
  const page = await controller({ hash: "#tab=goals", context: { local_edit: false } });
  assert.equal(page.dom.$("newGoal").hidden, false);
  assert.equal(page.dom.$("newGoal").disabled, true);
  assert.match(page.dom.$("newGoal").title, /本地编辑/);
});

test("save failure preserves dirty state and reports failure to its editor", async () => {
  const page = await controller({ hash: "#tab=goals", postError: "Version conflict" });
  const saved = await page.actions.saveDocument({ path: "profiles/goals/one.md", sha256: "old" }, "# Revised");
  assert.equal(saved, false);
  assert.equal(page.state.dirty, true);
  assert.equal(page.state.saving, false);
  assert.match(page.dom.$("status").textContent, /Version conflict/);
});

test("a successful file write is not reported as unsaved when refreshing fails", async () => {
  let fail = false;
  const committed = { path: "profiles/goals/one.md", sha256: "new", text: "# Revised", outline: [] };
  const page = await controller({ hash: "#tab=goals", post: () => committed, request: url => {
    if (fail && url.startsWith("/api/studio/view?")) throw Error("Offline refresh");
  } });
  fail = true;
  const saved = await page.actions.saveDocument({ path: "profiles/goals/one.md", sha256: "old" }, "# Revised");
  assert.equal(saved, true);
  assert.equal(page.state.dirty, false);
  assert.equal(page.posts.length, 1);
  assert.equal(page.state.view.files[committed.path], committed);
  assert.match(page.dom.$("status").textContent, /已保存，刷新失败/);
});

test("unsaved goals block navigation and unload until the editor cancels", async () => {
  const page = await controller();
  page.state.dirty = true;
  await page.actions.navigate("learning");
  assert.equal(page.state.tab, "goals");
  assert.match(page.dom.$("status").textContent, /保存或取消/);
  let prevented = false;
  page.events.beforeunload({ preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  page.state.dirty = false;
  await page.actions.navigate("learning");
  assert.equal(page.state.tab, "learning");
});

test("an in-flight goal save blocks duplicate writes, navigation and unload", async () => {
  const pending = deferred();
  const page = await controller({ post: () => pending.promise });
  const file = { path: "profiles/goals/one.md", sha256: "old" };
  const save = page.actions.saveDocument(file, "# Revised");
  assert.equal(page.state.saving, true);
  assert.equal(await page.actions.saveDocument(file, "# Duplicate"), false);
  assert.equal(page.posts.length, 1);
  await page.actions.navigate("learning");
  assert.equal(page.state.tab, "goals");
  let prevented = false;
  page.events.beforeunload({ preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  pending.resolve({ ...file, text: "# Revised", sha256: "new" });
  assert.equal(await save, true);
  assert.equal(page.state.saving, false);
});
