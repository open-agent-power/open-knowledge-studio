"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const { source, moduleUrl, domFixture, Element, settle, deferred } = require("./studio_test_helpers.cjs");

async function controller(options = {}) {
  const dom = domFixture(), events = {}, timers = [], calls = [], posts = [];
  const renders = [], updates = [];
  let state, actions;
  const location = { hash: options.hash || "#tab=discuss", href: "http://local/studio.html", origin: "http://local" };
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
    if (url === "/api/studio/drafts") return {
      knowledge_base: context.knowledge_base, scope: "drafts", version: "draft-v1",
      nodes: [{ id: "drafts/one.md", path: "drafts/one.md", type: "drafts", title: "One" }],
      edges: [], files: {}, warnings: [],
    };
    const kind = new URLSearchParams(url.split("?")[1]).get("kind") || "goal";
    const path = "profiles/" + (kind === "goal" ? "goals" : "discuss") + "/2026/11/11/one.md";
    return { knowledge_base: context.knowledge_base, scope: path, version: kind + "-v1",
      entry: path, entries: [path], files: { [path]: { kind, path, sha256: "old" } }, warnings: [] };
  };
  const view = name => ({ state: shared, actions: supplied }) => {
    state = shared; actions = supplied;
    return {
      render() { renders.push(name); },
      update() { updates.push(name); return true; },
      destroy() {},
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
  return { dom, state, actions, events, timers, calls, posts, renders, updates, location };
}

test("default discussion loads pending Drafts and explicit scope stays addressable", async () => {
  const page = await controller({ hash: "#tab=discuss&scope=drafts%2Fone.md" });
  assert.ok(page.calls.includes("/api/studio/drafts"));
  assert.equal(page.state.scope, "drafts/one.md");
  assert.equal(page.state.discuss, "graph");
  assert.equal(page.dom.$("scope").hidden, true);
});

test("read-only discussion create action remains visible with a concrete disabled reason", async () => {
  const page = await controller({ hash: "#tab=discuss", context: { local_edit: false } });
  assert.equal(page.dom.$("newGoal").hidden, false);
  assert.equal(page.dom.$("newGoal").disabled, true);
  assert.match(page.dom.$("newGoal").title, /本地编辑/);
});

test("pending comments block primary navigation and browser unload", async () => {
  const page = await controller();
  page.state.commentDraft = Symbol("pending");
  await page.actions.navigate("goals");
  assert.equal(page.state.tab, "discuss");
  assert.match(page.dom.$("status").textContent, /留言/);
  let prevented = false;
  page.events.beforeunload({ preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
});

test("refresh updates the mounted draft reader instead of remounting it", async () => {
  const page = await controller();
  const rendered = page.renders.length;
  await page.actions.loadView(true);
  assert.equal(page.renders.length, rendered);
  assert.deepEqual(page.updates, ["discuss"]);
});

test("discussion history keeps upstream dates and changing mode requests the matching data", async () => {
  const page = await controller({ hash: "#tab=discuss&view=history&date=2026-11-11" });
  assert.equal(page.state.discuss, "history");
  assert.equal(page.dom.$("scope").hidden, false);
  assert.ok(page.calls.some(url => url.includes("kind=discuss") && url.includes("date=2026-11-11")));
  await page.actions.setDiscussionMode("graph");
  assert.equal(page.calls.at(-1), "/api/studio/drafts");
  assert.equal(page.dom.$("scope").hidden, true);
});

test("discussion create dialog has an explicit cancel action", async () => {
  const page = await controller();
  page.dom.$("newGoal").onclick();
  assert.equal(page.dom.$("newDialog").open, true);
  page.dom.$("cancelNew").onclick();
  assert.equal(page.dom.$("newDialog").open, false);
  assert.equal(page.posts.length, 0);
});

test("a discussion cannot be dismissed or submitted twice while its creation is saving", async () => {
  const pending = deferred();
  const page = await controller({ hash: "#tab=discuss&date=2026-11-11", post: () => pending.promise });
  page.dom.$("newGoal").onclick();
  const save = page.dom.$("newForm").onsubmit({ preventDefault() {} });
  assert.equal(page.dom.$("createNew").disabled, true);
  let prevented = false;
  page.dom.$("newDialog").oncancel({ preventDefault() { prevented = true; } });
  page.dom.$("cancelNew").onclick();
  assert.equal(page.dom.$("newDialog").open, true);
  assert.equal(prevented, true);
  await page.dom.$("newForm").onsubmit({ preventDefault() {} });
  assert.equal(page.posts.length, 1);
  pending.resolve({});
  await save;
  assert.equal(page.dom.$("newDialog").open, false);
  assert.equal(page.state.discuss, "history");
  assert.equal(page.dom.$("createNew").disabled, false);
});

test("late draft listing cannot overwrite a more recently selected goal view", async () => {
  const pending = deferred(); let hold = false;
  const page = await controller({ request: url => url === "/api/studio/drafts" && hold ? pending.promise : undefined });
  hold = true;
  const refresh = page.actions.loadView(true);
  await page.actions.navigate("goals");
  const current = page.state.view;
  pending.resolve({ knowledge_base: "/kb", scope: "drafts", version: "late", nodes: [], edges: [], warnings: [] });
  await refresh;
  assert.equal(page.state.view, current);
  assert.equal(page.state.tab, "goals");
});
