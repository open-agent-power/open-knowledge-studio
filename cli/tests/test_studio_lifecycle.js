"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const { source, moduleUrl, settle, deferred, Element, domFixture } = require("./studio_test_helpers.cjs");
async function controller({ hash = "", empty = false, hook = () => {} } = {}) {
  const { createStudioState } = await import(
    moduleUrl(source("studio/state.js"))
  );
  const { createStudioApi } = await import(moduleUrl(source("studio/api.js")));
  const state = createStudioState(),
    dom = domFixture(),
    calls = [],
    intervals = [];
  const events = { document: {}, window: {} },
    renders = [];
  let actions;
  const context = { knowledge_base: "/kb", local_edit: true };
  const tabs = ["discuss", "goals", "learning"].map((tab) =>
    Object.assign(new Element("button"), { dataset: { tab } }),
  );
  const document = {
    hidden: false,
    querySelectorAll: () => tabs,
    addEventListener: (type, callback) => {
      events.document[type] = callback;
    },
  };
  const location = { hash };
  const window = {
    OksStudioModel: {},
    addEventListener: (type, callback) => {
      events.window[type] = callback;
    },
    OksWorkspace: {
      ready: Promise.resolve(context),
      recovery() {},
      request: async (url) => {
        calls.push(url);
        const response = hook(url);
        if (response !== undefined) return response;
        if (url.startsWith("/api/studio/scopes")) {
          const kind = url.endsWith("discuss") ? "discuss" : "goal";
          return {
            scopes: empty
              ? []
              : [{
                  path: kind,
                  files: [{ path: kind + "/one.md", title: "One" }],
                }],
            warnings: [],
          };
        }
        if (url.startsWith("/api/studio/view")) {
          const scope = new URL("http://local" + url).searchParams.get("scope");
          return {
            knowledge_base: "/kb",
            scope,
            version: 1,
            entry: scope,
            files: { [scope]: { kind: "goal" } },
            warnings: [],
          };
        }
        throw Error("Unexpected request " + url);
      },
    },
  };
  const view = (name) => (parameters) => {
    actions = parameters.actions;
    return { render: () => renders.push(name), destroy() {} };
  };
  const globals = {
    createStudioState: () => state,
    ...dom,
    createStudioApi,
    createDiscussionView: view("discuss"),
    createGoalsView: view("goals"),
    createLearningView: view("learning"),
    window,
    document,
    location,
    history: {
      replaceState: (_, __, route) => {
        location.hash = route;
      },
    },
    Option: class extends Element {
      constructor(title, value) {
        super("option");
        this.textContent = title;
        this.value = value;
      }
    },
    setInterval: (callback) => intervals.push(callback),
  };
  const controllerSource = source("studio.js").replace(/^import .+;\r?\n/gm, "");
  new Function(...Object.keys(globals), controllerSource)(
    ...Object.values(globals),
  );
  await settle();
  return {
    state,
    dom,
    calls,
    renders,
    events,
    tabs,
    location,
    actions,
    async tick(count = 1) {
      for (let i = 0; i < count; i++) {
        intervals[0]();
        await settle();
      }
    },
  };
}

test("document navigation renders once and keeps external file refresh", async () => {
  const page = await controller();
  assert.deepEqual(page.renders, ["discuss"]);
  await page.tabs[1].onclick();
  assert.deepEqual(page.renders, ["discuss", "goals"]);
  await page.tick();
  assert.deepEqual(page.renders, ["discuss", "goals"]);
  assert.equal(
    page.calls.filter((url) => url.startsWith("/api/studio/view")).length,
    3,
  );
});

test("learning direct routes, visibility and reconnect skip document APIs", async () => {
  const page = await controller({ hash: "#tab=learning&view=graph" });
  assert.deepEqual(page.renders, ["learning"]);
  await page.tick(8);
  page.events.document.visibilitychange();
  await page.events.document["oks:reconnected"]({
    detail: { changedRoot: false, context: page.state.context },
  });
  assert.deepEqual(page.calls, []);
  assert.deepEqual(page.renders, ["learning", "learning"]);
  page.state.settingsDirty = true;
  await page.tabs[0].onclick();
  assert.equal(page.state.tab, "learning");
  assert.equal(page.dom.$("status").textContent, "请先保存修改");
});

test("empty document catalogs refresh every ten seconds", async () => {
  const page = await controller({ empty: true });
  assert.equal(page.calls.length, 1);
  await page.tick(4);
  assert.equal(page.calls.length, 1);
  await page.tick();
  assert.equal(page.calls.length, 2);
  assert.equal(page.dom.$("content").children[0].textContent, "暂无讨论");
});

test("slow catalogs share one request and late documents cannot replace learning", async () => {
  const catalog = deferred(),
    document = deferred();
  const page = await controller({
    hook: (url) => url.includes("/scopes") ? catalog.promise : document.promise,
  });
  await page.tick(5);
  assert.equal(page.calls.length, 1);
  catalog.resolve({
    scopes: [{
      path: "discuss",
      files: [{ path: "discuss/one.md", title: "One" }],
    }],
    warnings: [],
  });
  await settle();
  assert.equal(page.calls.length, 2);
  await page.tabs[2].onclick();
  document.resolve({
    knowledge_base: "/kb",
    scope: "discuss/one.md",
    version: 1,
    entry: "discuss/one.md",
    files: {},
    warnings: [],
  });
  await settle();
  assert.deepEqual(page.renders, ["learning"]);
  assert.equal(page.state.view, null);
});

test("hash navigation and reconnect preserve unsaved document state", async () => {
  const page = await controller();
  const original = page.state.view;
  page.state.dirty = true;
  page.location.hash = "#tab=learning";
  page.events.window.hashchange();
  assert.equal(page.state.tab, "discuss");
  await page.events.document["oks:reconnected"]({
    detail: { changedRoot: false, context: page.state.context },
  });
  assert.equal(page.state.view, original);
  assert.equal(page.state.dirty, true);
  assert.equal(page.renders.length, 1);
});

test("a pending save can finish after reconnecting to the same instance", async () => {
  const saved = deferred();
  const page = await controller({
    hook: (url) => url === "/api/studio/file" ? saved.promise : undefined,
  });
  page.state.dirty = true;
  const pending = page.actions.saveDocument(
    { path: "discuss/one.md", sha256: "old" },
    "# New",
  );
  await page.events.document["oks:reconnected"]({
    detail: {
      changedRoot: false,
      context: { knowledge_base: "/kb", local_edit: true },
    },
  });
  assert.equal(page.state.saving, true);
  assert.equal(page.calls.filter((url) => url.includes("/scopes")).length, 1);
  saved.resolve({});
  await pending;
  assert.equal(page.state.saving, false);
  assert.equal(page.state.dirty, false);
});

test("learning loads only the selected module and discards late imports", async () => {
  const dom = domFixture(),
    graph = deferred(),
    events = [],
    key = "__studioLazyTest";
  globalThis[key] = {
    graph: graph.promise,
    events,
    create: (id) => {
      events.push("create:" + id);
      return {
        render: () => events.push("render:" + id),
        destroy: () => events.push("destroy:" + id),
      };
    },
  };
  const names = {
    knowledge: "Knowledge",
    files: "Files",
    settings: "Settings",
    evaluation: "Evaluation",
  };
  const text = source("studio/learning.js").replace(
    /import\("\.\/(\w+)\.js"\)/g,
    (_, name) => {
      const id = name === "knowledge" ? "graph" : name;
      const stub = `
        const fixture = globalThis[${JSON.stringify(key)}];
        await fixture[${JSON.stringify(id)}];
        fixture.events.push("load:${id}");
        export function create${names[name]}View() {
          return fixture.create("${id}");
        }
      `;
      return `import(${JSON.stringify(moduleUrl(stub))})`;
    },
  );
  try {
    const { createLearningView } = await import(moduleUrl(text));
    const state = { tab: "learning", learn: "graph" };
    const view = createLearningView({
      dom,
      state,
      actions: {
        canLeave: () => true,
        status: (message) => {
          throw Error(message);
        },
      },
      api: {},
    });
    const pending = view.render();
    await settle();
    view.destroy();
    state.learn = "settings";
    await view.render();
    assert.deepEqual(events, ["load:settings", "create:settings", "render:settings"]);
    graph.resolve();
    await pending;
    assert.ok(!events.includes("create:graph"));
    view.destroy();
    await view.render();
    assert.equal(
      events.filter((event) => event === "create:settings").length,
      1,
    );
    assert.equal(
      events.filter((event) => event === "render:settings").length,
      2,
    );
    assert.ok(!events.includes("load:evaluation"));
    assert.ok(!events.includes("load:files"));
  } finally {
    delete globalThis[key];
  }
});

test("formula resources load once and settings wait for the stylesheet", async () => {
  const dom = domFixture(),
    head = new Element("head"),
    formulas = [];
  const previous = {
    window: globalThis.window,
    document: globalThis.document,
    Option: globalThis.Option,
  };
  globalThis.window = { katex: { render: (tex) => formulas.push(tex) } };
  globalThis.document = {
    head,
    createElement: (tag) => new Element(tag),
    createElementNS: (_, tag) => new Element(tag),
  };
  globalThis.Option = class extends Element {
    constructor(title, value) {
      super("option");
      this.textContent = title;
      this.value = value;
    }
  };
  const text = source("studio/settings.js").replace(
    '"./formulas.js"',
    JSON.stringify(moduleUrl(source("studio/formulas.js"))),
  );
  const state = { tab: "learning", learn: "settings" };
  const late = deferred();
  let reads = 0;
  try {
    const { createSettingsView } = await import(moduleUrl(text));
    const view = createSettingsView({
      dom,
      state,
      actions: {
        writable: () => false,
        status: (message) => {
          throw Error(message);
        },
      },
      api: {
        request: async () => {
          reads++;
          return reads === 3 ? late.promise : {
            values: {},
            fixed: { decay_lambda: { strategy: 0.014 } },
          };
        },
      },
    });
    const pending = view.render();
    await settle();
    assert.deepEqual(
      head.children.map((node) => node.tagName),
      ["link", "script"],
    );
    head.children[1].onload();
    await settle();
    assert.equal(dom.$("content").children.length, 0);
    head.children[0].onload();
    await pending;
    assert.equal(dom.$("content").children.length, 1);
    assert.ok(formulas.length >= 3);
    view.destroy();
    await view.render();
    assert.equal(head.children.length, 2);
    view.destroy();
    const staleRender = view.render();
    view.destroy();
    await view.render();
    const count = dom.$("content").children.length;
    late.resolve({});
    await staleRender;
    assert.equal(dom.$("content").children.length, count);
  } finally {
    globalThis.window = previous.window;
    globalThis.document = previous.document;
    globalThis.Option = previous.Option;
  }
});

test("knowledge refresh shares API batches and interactions reuse the renderer", async () => {
  const dom = domFixture(),
    pending = deferred(),
    calls = [],
    timers = [];
  const previous = {
    document: globalThis.document,
    setInterval: globalThis.setInterval,
    clearInterval: globalThis.clearInterval,
  };
  globalThis.document = {
    hidden: false,
    createElementNS: (_, tag) => new Element(tag),
  };
  globalThis.setInterval = (callback) => timers.push(callback);
  globalThis.clearInterval = () => {};
  const graphCalls = { created: 0, updated: 0, destroyed: 0 };
  globalThis.knowledgeGraphCalls = graphCalls;
  const graph = `export function createGraph(svg, tools, onSelect) {
    globalThis.knowledgeGraphCalls.created++;
    globalThis.knowledgeGraphCalls.select = onSelect;
    return {
      update() { globalThis.knowledgeGraphCalls.updated++; },
      destroy() { globalThis.knowledgeGraphCalls.destroyed++; }
    };
  }`;
  const modules = {
    graph,
    "knowledge-model": source("studio/knowledge-model.js"),
    "call-trace": source("studio/call-trace.js"),
  };
  const text = source("studio/knowledge.js").replace(
    /(["'])\.\/(graph|knowledge-model|call-trace)\.js\1/g,
    (_, quote, name) => JSON.stringify(moduleUrl(modules[name])),
  );
  const result = {
    domains: [], edges: [], entries: [], skills: [], warnings: [],
  };
  let blocked = false, canLeave = true;
  try {
    const { createKnowledgeView } = await import(moduleUrl(text));
    const view = createKnowledgeView({
      dom,
      state: { tab: "learning", learn: "graph" },
      actions: {
        canLeave: () => canLeave,
        status: (message) => {
          throw Error(message);
        },
      },
      api: {
        request: async (url) => {
          calls.push(url);
          return blocked ? pending.promise : result;
        },
      },
    });
    await view.render();
    assert.equal(calls.length, 4);
    const shell = dom.$("content").children[0];
    const controls = shell.children[0].children[1];
    const search = controls.children[0];
    for (const value of ["alpha", "beta"]) {
      search.value = value;
      search.oninput();
    }
    assert.equal(graphCalls.created, 1);
    assert.equal(graphCalls.updated, 3);
    canLeave = false;
    assert.equal(graphCalls.select({ id: "blocked" }), false);
    assert.equal(graphCalls.updated, 3);
    canLeave = true;
    blocked = true;
    timers[0]();
    timers[0]();
    assert.equal(calls.length, 8);
    pending.resolve(result);
    await settle();
    timers[0]();
    assert.equal(calls.length, 12);
    view.destroy();
    assert.equal(graphCalls.destroyed, 1);
  } finally {
    delete globalThis.knowledgeGraphCalls;
    globalThis.document = previous.document;
    globalThis.setInterval = previous.setInterval;
    globalThis.clearInterval = previous.clearInterval;
  }
});

test("discussion replay and child expansion update one graph controller", async () => {
  const dom = domFixture();
  const previous = { document: globalThis.document, Option: globalThis.Option };
  const calls = { created: 0, counts: [], destroyed: 0 };
  globalThis.discussionGraphCalls = calls;
  globalThis.document = { createElementNS: (_, tag) => new Element(tag) };
  globalThis.Option = class extends Element {
    constructor(text, value) {
      super("option");
      this.textContent = text;
      this.value = value;
    }
  };
  const graph = `export function createGraph() {
    globalThis.discussionGraphCalls.created++;
    return {
      update(nodes) { globalThis.discussionGraphCalls.counts.push(nodes.length); },
      destroy() { globalThis.discussionGraphCalls.destroyed++; }
    };
  }`;
  const text = source("studio/discussion.js").replace(
    '"./graph.js"', JSON.stringify(moduleUrl(graph)),
  );
  try {
    const { createDiscussionView } = await import(moduleUrl(text));
    const view = createDiscussionView({
      dom,
      state: { view: { entry: "goal" } },
      actions: { render: () => assert.fail("child expansion recreated the view") },
      model: {
        graph: (_, expanded) => ({
          nodes: Array.from({ length: expanded ? 4 : 2 }, (_, id) => ({ id })),
          edges: [],
        }),
      },
    });
    view.render();
    const stage = dom.$("content").children[0];
    const tools = stage.children[2];
    const replay = stage.children[3];
    tools.children[0].onclick();
    replay.children[2].value = 1;
    replay.children[2].oninput();
    assert.equal(calls.created, 1);
    assert.deepEqual(calls.counts, [2, 4, 1]);
    assert.equal(replay.children[2].max, 4);
    view.destroy();
    assert.equal(calls.destroyed, 1);
  } finally {
    delete globalThis.discussionGraphCalls;
    globalThis.document = previous.document;
    globalThis.Option = previous.Option;
  }
});
