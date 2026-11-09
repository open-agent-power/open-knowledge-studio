"use strict";
const { test, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const {
  source,
  moduleUrl,
  settle,
  deferred,
  Element,
  domFixture,
} = require("./studio_test_helpers.cjs");
const previous = {};
let mounted = null;
function all(node) {
  return [node, ...(node.children?.flatMap(all) || [])];
}
function text(node) {
  return all(node)
    .map((item) =>
      item.innerHTML
        ? item.innerHTML.replace(/<[^>]*>/g, " ")
        : item.textContent || "",
    )
    .join(" ");
}
function hasClass(node, name) {
  return node.className?.split(/\s+/).includes(name);
}

async function fixture() {
  const dom = domFixture(),
    originalEl = dom.el,
    timers = [],
    fileReads = [],
    queryReads = [],
    workflowReads = [];
  dom.el = (...args) => {
    const node = originalEl(...args),
      classes = new Set();
    node.classList = {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
    };
    node.style = {
      setProperty(name, value) {
        this[name] = value;
      },
    };
    return node;
  };
  const originalButton = dom.button;
  dom.button = (...args) => {
    const node = originalButton(...args);
    node.style = { setProperty(name, value) { this[name] = value; } };
    return node;
  };
  const state = {
    tab: "learning",
    learn: "graph",
    saving: false,
    context: { knowledge_base: "/kb" },
  };
  const graph = { creates: 0, updates: [] },
    review = {
      renders: 0,
      destroys: 0,
      marker: dom.el("p", "review-marker", "Exact review remains open"),
    };
  const snapshot = {
    map: {
      domains: [
        {
          id: "d",
          label: "Domain",
          clusters: [
            {
              id: "c",
              label: "Cluster",
              points: [
                {
                  id: "wiki/a.md",
                  path: "wiki/a.md",
                  title: "Original title",
                  kind: "wiki",
                  body: "Original body",
                  metadata: { source: "Original attribute" },
                  url: "https://example.test/original",
                },
                {
                  id: "wiki/b.md",
                  path: "wiki/b.md",
                  title: "Second title",
                  kind: "wiki",
                  body: "Second body",
                },
              ],
            },
          ],
        },
      ],
      edges: [],
    },
    usage: { entries: [{ slug: "a", count: 1 }], warnings: [] },
    skills: { skills: [], warnings: [] },
    contexts: { entries: [], edges: [], warnings: [] },
    activity: { queried_paths: [], used_slugs: [] },
    workflow: { path: "", references: [], outline: [], runs: [], warnings: [] },
  };
  const discussionReview = { mounts: [], opened: [] },
    harness = { graph, review, discussionReview };
  for (const name of [
    "document",
    "setInterval",
    "clearInterval",
    "knowledgeViewHarness",
  ])
    previous[name] = globalThis[name];
  globalThis.document = {
    hidden: false,
    createElementNS: (_, tag) => new Element(tag),
  };
  globalThis.setInterval = (callback) => timers.push(callback);
  globalThis.clearInterval = () => {};
  globalThis.knowledgeViewHarness = harness;
  const modules = {
    "graph-pixi": `export function createGraph(svg, tools, onSelect, options) {
      const graph = globalThis.knowledgeViewHarness.graph;
      graph.creates++; graph.select = onSelect; graph.background = options.onBackground; graph.options = options;
      return { update(nodes, edges, state) { graph.nodes = nodes; graph.edges = edges; graph.selected = state.selected; graph.updates.push(nodes.map(n => n.id)); }, fit() {}, destroy() {} };
    }`,
    "draft-review": `export function createDraftReview(options) {
      const review = globalThis.knowledgeViewHarness.review;
      review.onBusy = options.onBusy;
      return { render(host) { review.renders++; host.replaceChildren(review.marker); }, destroy() { review.destroys++; } };
    }`,
    "discussion-review": `export function createDiscussionReview({dom, actions}) {
      return { mount(host, path, options) {
        globalThis.knowledgeViewHarness.discussionReview.mounts.push({path, options});
        host.append(dom.button("查看复核结果", () => actions.openDiscussionReview(path)));
      }, refresh() {}, destroy() {} };
    }`,
    "knowledge-model": source("studio/knowledge-model.js"),
    "call-trace": source("studio/call-trace.js"),
    workflow: source("studio/workflow.js"),
  };
  const script = source("studio/knowledge.js").replace(
    /(["'])\.\/(graph-pixi|graph|draft-review|discussion-review|knowledge-model|call-trace|workflow)\.js\1/g,
    (_, quote, name) => JSON.stringify(moduleUrl(modules[name])),
  );
  const { createKnowledgeView } = await import(moduleUrl(script));
  const view = createKnowledgeView({
    dom,
    state,
    actions: {
      canLeave: () => !state.saving,
      openDiscussionReview: (path) => discussionReview.opened.push(path),
      status: (message) => {
        harness.status = message;
      },
    },
    api: {
      async request(route) {
        if (route === "/api/mail/knowledge-map") return snapshot.map;
        if (route === "/api/studio/usage") return snapshot.usage;
        if (route === "/api/studio/skills") return snapshot.skills;
        if (route === "/api/studio/contexts") return snapshot.contexts;
        if (route.startsWith("/api/studio/file?"))
          return { text: "---\ntitle: Skill\n---\n# Skill\n\n**正文**", body: "# Skill\n\n**正文**", body_html: "<h1>Skill</h1><p><strong>正文</strong></p>" };
        if (route.startsWith("/api/studio/activity?")) return snapshot.activity;
        if (route.startsWith("/api/studio/workflow?")) {
          workflowReads.push(route);
          return snapshot.workflow;
        }
        if (route.startsWith("/api/mail/memory/item?")) {
          const path = new URL("http://local" + route).searchParams.get("path");
          if (fileReads.length) {
            const result = await fileReads.shift();
            if (result instanceof Error) throw result;
            return result;
          }
          const points = snapshot.map.domains.flatMap((d) =>
            d.clusters.flatMap((c) => c.points),
          );
          const point = [...points, ...(snapshot.map.materials || [])].find(
            (p) => p.path === path,
          );
          return {
            body: point.body || "",
            body_html: `<p>${point.body || ""}</p>`,
          };
        }
        if (route === "/api/workspace/query") {
          if (queryReads.length) {
            const result = await queryReads.shift();
            if (result instanceof Error) throw result;
            return result;
          }
          return {
            knowledge: [{ source_path: "wiki/a.md", title: "Original title" }],
          };
        }
        throw Error("Unexpected route " + route);
      },
    },
  });
  mounted = view;
  await view.render();
  const page = {
    dom,
    state,
    snapshot,
    graph,
    review,
    discussionReview,
    fileReads,
    queryReads,
    workflowReads,
    status: () => harness.status,
    aside: () =>
      all(dom.$("content")).find((node) => hasClass(node, "knowledge-detail")),
    points: () => snapshot.map.domains[0].clusters[0].points,
    hierarchy() {
      const mode = all(dom.$("content")).find(
        (node) => node["aria-label"] === "图谱视图",
      );
      if (mode.value === "hierarchy") return;
      mode.value = "hierarchy";
      mode.onchange();
      const overview = graph.nodes.find((node) => node.id === "overview:wiki");
      if (overview) graph.select(overview);
    },
    async select(id) {
      const node = graph.nodes.find((item) => item.id === id);
      assert.ok(node, "Node must be present in the current projection: " + id);
      const accepted = graph.select(node);
      await settle();
      return accepted;
    },
    async openLeaves() {
      this.hierarchy();
      await this.select("domain:d");
      await this.select('cluster:["d","c"]');
    },
    async tick() {
      timers[0]();
      await settle();
    },
  };
  return page;
}
afterEach(() => {
  mounted?.destroy();
  mounted = null;
  for (const [name, value] of Object.entries(previous))
    globalThis[name] = value;
});

test("all asset types survive state, lasso and reset", async () => {
  const page = await fixture();
  page.points().push({
    id: "drafts/p.md",
    path: "drafts/p.md",
    title: "Pending",
    kind: "candidate",
  });
  page.snapshot.map.materials = [
    {
      id: "raw/source.md",
      path: "raw/source.md",
      title: "Source",
      kind: "raw",
      content_role: "source_material",
    },
  ];
  page.snapshot.activity.queried_paths.push("wiki/a.md");
  await page.tick();
  assert.deepEqual(
    page.graph.nodes.map((n) => n.id),
    ["wiki/a.md", "wiki/b.md", "drafts/p.md", "raw/source.md"],
  );
  const stateFilter = all(page.dom.$("content")).find(
    (n) => n["aria-label"] === "图谱状态",
  );
  stateFilter.value = "used";
  stateFilter.onchange();
  assert.deepEqual(
    page.graph.nodes.map((n) => n.id),
    ["wiki/a.md"],
  );
  assert.match(page.graph.options.nodeClass(page.graph.nodes[0]), /day-active/);
  const reset = all(page.dom.$("content")).find(
    (n) => n.textContent === "重置",
  );
  reset.onclick();
  page.graph.options.onLasso([page.graph.nodes[0]]);
  all(page.dom.$("content"))
    .find((n) => n.textContent === "仅看选中")
    .onclick();
  assert.equal(page.graph.nodes.length, 1);
  reset.onclick();
  assert.equal(page.graph.nodes.length, 4);
  assert.equal(page.graph.creates, 1);
  assert.equal(page.snapshot.map.materials.length, 1);
});

test("Learning includes goal and skill definitions and allows toggling them", async () => {
  const page = await fixture();
  page.snapshot.contexts.entries = [
    { id: "goal/g.md", path: "goal/g.md", title: "Goal", type: "goal" },
  ];
  page.snapshot.skills.skills = [
    { path: "skill/demo/SKILL.md", title: "Skill" },
  ];
  await page.tick();
  assert.ok(page.graph.nodes.some((n) => n.path === "goal/g.md"));
  assert.ok(page.graph.nodes.some((n) => n.path === "skill/demo/SKILL.md"));
  const skill = all(page.dom.$("content")).find((n) => n.textContent === "技能" && n["aria-pressed"] !== undefined);
  skill.onclick();
  assert.ok(!page.graph.nodes.some((n) => n.path === "skill/demo/SKILL.md"));
  skill.onclick();
  assert.ok(page.graph.nodes.some((n) => n.path === "skill/demo/SKILL.md"));
  await page.select("skill/demo/SKILL.md");
  const body = all(page.aside()).find((n) => hasClass(n, "knowledge-body"));
  assert.match(body.innerHTML, /<strong>正文<\/strong>/);
  assert.doesNotMatch(body.innerHTML, /title:/);
  assert.equal(page.workflowReads.length, 0);
});

test("each asset category can be hidden and restored", async () => {
  const page = await fixture();
  page.points().push({ id: "drafts/p.md", path: "drafts/p.md", title: "Draft", kind: "candidate" });
  page.snapshot.map.materials = [{ id: "raw/s.md", path: "raw/s.md", title: "Source", kind: "raw" }];
  page.snapshot.skills.skills = [{ path: "skill/demo/SKILL.md", title: "Skill" }];
  for (const type of ["profile", "project", "goal", "discuss", "team", "mail"])
    page.snapshot.contexts.entries.push({ id: `${type}/item.md`, path: `${type}/item.md`, title: type, type });
  await page.tick();
  for (const [label, id] of [["知识", "wiki/a.md"], ["待审核", "drafts/p.md"], ["来源", "raw/s.md"], ["技能", "skill/demo/SKILL.md"], ["画像", "profile/item.md"], ["项目", "project/item.md"], ["目标", "goal/item.md"], ["讨论", "discuss/item.md"], ["团队", "team/item.md"], ["交接", "mail/item.md"]]) {
    const chip = all(page.dom.$("content")).find((n) => n.textContent === label && n["aria-pressed"] !== undefined);
    assert.ok(page.graph.nodes.some((n) => n.id === id), label);
    chip.onclick();
    assert.ok(!page.graph.nodes.some((n) => n.id === id), label);
    chip.onclick();
    assert.ok(page.graph.nodes.some((n) => n.id === id), label);
  }
  await page.select("drafts/p.md");
  const review = all(page.aside()).find((n) => n.textContent === "打开草稿审核");
  assert.ok(review.href.includes("/review?detail=1&draft=drafts%2Fp.md"));
});

test("Learning is a reader without Draft or Agent review controls", async () => {
  const page = await fixture();
  page.snapshot.contexts.entries = [
    {
      id: "discuss/a.md",
      path: "discuss/a.md",
      title: "Discussion",
      type: "discuss",
    },
  ];
  await page.tick();
  await page.select("wiki/a.md");
  assert.deepEqual(page.discussionReview.mounts, []);
  assert.equal(page.review.renders, 0);
  assert.equal(
    all(page.aside()).some((n) =>
      ["入库审核", "查看复核结果", "提请整篇复核"].includes(n.textContent),
    ),
    false,
  );
  const body = all(page.aside()).find((n) => hasClass(n, "knowledge-body"));
  const attrs = all(page.aside()).find((n) => hasClass(n, "node-attributes"));
  assert.equal(body.innerHTML, "<p>Original body</p>");
  assert.ok(
    page.aside().children.indexOf(body) < page.aside().children.indexOf(attrs),
  );
  assert.ok(!attrs.open);
});

test("selected leaf details track current title, body, uses, attributes and source without recreating the graph", async () => {
  const page = await fixture();
  await page.openLeaves();
  await page.select("wiki/a.md");
  const projection = page.graph.nodes.map((node) => node.id);
  Object.assign(page.points()[0], {
    title: "Updated title",
    body: "Updated body",
    metadata: { state: "Updated attribute" },
    url: "https://example.test/updated",
    evidence_url: "https://example.test/evidence",
    approval_url: "https://example.test/approval",
  });
  page.snapshot.usage.entries[0].count = 9;
  await page.tick();
  const details = text(page.aside()),
    links = all(page.aside())
      .filter((node) => node.tagName === "a")
      .map((node) => node.href);
  assert.ok(
    details.includes("Updated title") && details.includes("Updated body"),
  );
  assert.ok(
    details.includes("显式使用 9") && details.includes("Updated attribute"),
  );
  assert.ok(
    !details.includes("Original title") &&
      !details.includes("Original attribute"),
  );
  assert.deepEqual(links, [
    "https://example.test/updated",
    "https://example.test/evidence",
    "https://example.test/approval",
  ]);
  assert.equal(page.graph.selected, "wiki/a.md");
  assert.equal(page.graph.creates, 1);
  assert.deepEqual(
    page.graph.nodes.map((node) => node.id),
    projection,
  );
});

test("refreshing a selected group preserves its expanded projection", async () => {
  const page = await fixture();
  await page.openLeaves();
  const projection = page.graph.nodes.map((node) => node.id);
  page.points()[0].body = "Updated in the open group";
  await page.tick();
  assert.equal(page.graph.selected, 'cluster:["d","c"]');
  assert.deepEqual(
    page.graph.nodes.map((node) => node.id),
    projection,
  );
  assert.ok(page.graph.nodes.some((node) => node.id === "wiki/a.md"));
});

test("saving postpones detail updates and an unchanged next snapshot catches up", async () => {
  const page = await fixture();
  await page.openLeaves();
  await page.select("wiki/a.md");
  page.state.saving = true;
  page.points()[0].body = "Available after saving";
  await page.tick();
  assert.ok(text(page.aside()).includes("Original body"));
  page.state.saving = false;
  await page.tick();
  assert.ok(text(page.aside()).includes("Available after saving"));
});

test("Wiki read failures retain a visible retry and recover with server-rendered Markdown", async () => {
  const page = await fixture();
  page.fileReads.push(new Error("read failed"));
  await page.select("wiki/a.md");
  assert.match(text(page.aside()), /read failed/);
  page.fileReads.push({
    body: "**Recovered**",
    body_html: "<p><strong>Recovered</strong></p>",
  });
  await all(page.aside())
    .find((n) => n.textContent === "重试")
    .onclick();
  assert.equal(
    all(page.aside()).find((n) => hasClass(n, "knowledge-body")).innerHTML,
    "<p><strong>Recovered</strong></p>",
  );
  assert.equal(page.review.renders, 0);
});

test("a late same-id Wiki read cannot overwrite a newer refreshed selection", async () => {
  const page = await fixture(),
    old = deferred(),
    current = deferred();
  page.fileReads.push(old.promise);
  await page.select("wiki/a.md");
  page.points()[0].title = "Updated Wiki";
  page.fileReads.push(current.promise);
  await page.tick();
  current.resolve({ body: "Newest body", body_html: "<p>Newest body</p>" });
  await settle();
  assert.match(text(page.aside()), /Updated Wiki/);
  assert.match(text(page.aside()), /Newest body/);
  old.resolve({ body: "Stale body", body_html: "<p>Stale body</p>" });
  await settle();
  assert.match(text(page.aside()), /Newest body/);
  assert.doesNotMatch(text(page.aside()), /Stale body/);
});

test("document layout is ungrouped; hierarchy restores categories without replacing the graph", async () => {
  const page = await fixture();
  assert.equal(page.graph.options.fitPadding, 24);
  const node = page.graph.nodes[0];
  assert.equal(page.graph.options.nodeRegion(node), null);
  const mode = all(page.dom.$("content")).find(
    (item) => item["aria-label"] === "图谱视图",
  );
  mode.value = "hierarchy";
  mode.onchange();
  assert.equal(page.graph.options.nodeRegion(node), "wiki");
  mode.value = "documents";
  mode.onchange();
  assert.equal(page.graph.options.nodeRegion(node), null);
  assert.equal(page.graph.creates, 1);
});

test("reset restores mail and profile category visibility", async () => {
  const page = await fixture();
  page.snapshot.contexts.entries = [
    { id: "mail/a.md", path: "mail/a.md", title: "Mail", type: "mail" },
    {
      id: "profiles/person.md",
      path: "profiles/person.md",
      title: "Person",
      type: "profile",
    },
  ];
  await page.tick();
  const mail = all(page.dom.$("content")).find((n) => n.textContent === "交接" && n["aria-pressed"] !== undefined);
  mail.onclick();
  assert.ok(!page.graph.nodes.some((n) => n.id === "mail/a.md"));
  all(page.dom.$("content"))
    .find((n) => n.textContent === "重置")
    .onclick();
  assert.deepEqual(
    page.graph.nodes.map((n) => n.id),
    ["wiki/a.md", "wiki/b.md", "profiles/person.md", "mail/a.md"],
  );
  assert.equal(page.snapshot.contexts.entries.length, 2);
});

test("graph retains Wiki and cross-category links and narrows by source", async () => {
  const page = await fixture();
  page.snapshot.map.internal_links = [
    {
      a: "wiki/a.md",
      b: "wiki/b.md",
      type: "internal_link",
      sources: ["正文链接"],
    },
  ];
  page.snapshot.contexts.entries = [
    { id: "goal/g.md", path: "goal/g.md", title: "Goal", type: "goal" },
  ];
  page.snapshot.contexts.edges = [
    { a: "goal/g.md", b: "wiki/a.md", type: "cites" },
  ];
  await page.tick();
  assert.equal(page.graph.nodes.length, 3);
  assert.equal(page.graph.edges.length, 2);
  const source = all(page.dom.$("content")).find(
    (n) => n["aria-label"] === "筛选分类",
  );
  source.value = "domain:d";
  source.onchange();
  assert.deepEqual(
    page.graph.nodes.map((n) => n.id),
    ["wiki/a.md", "wiki/b.md"],
  );
  assert.equal(page.graph.edges.length, 1);
});

test("background clears details only when leaving is allowed and Query maps exact document hits", async () => {
  const page = await fixture();
  await page.select("wiki/a.md");
  page.state.saving = true;
  assert.equal(page.graph.background(), false);
  assert.equal(page.graph.selected, "wiki/a.md");
  page.state.saving = false;
  page.graph.background();
  assert.equal(page.graph.selected, null);
  assert.equal(page.aside().hidden, true);
  const search = all(page.dom.$("content")).find(
    (node) => node["aria-label"] === "搜索图谱",
  );
  search.value = "Original";
  search.oninput();
  const run = all(page.dom.$("content")).find(
    (node) => node.tagName === "button" && node.textContent === "Query",
  );
  await run.onclick();
  assert.deepEqual(
    page.graph.nodes.map((node) => node.id),
    ["wiki/a.md"],
  );
  assert.ok(text(page.aside()).includes("Original title"));
});

test("removing the selected file clears the selection and its old detail content", async () => {
  const page = await fixture();
  await page.openLeaves();
  await page.select("wiki/a.md");
  page.snapshot.map.domains[0].clusters[0].points = page
    .points()
    .filter((point) => point.id !== "wiki/a.md");
  await page.tick();
  assert.equal(page.graph.selected, null);
  assert.equal(page.aside().hidden, true);
  assert.equal(page.aside().children.length, 0);
});

function queryControls(page) {
  const nodes = all(page.dom.$("content"));
  return {
    search: nodes.find((node) => node["aria-label"] === "搜索图谱"),
    run: nodes.find(
      (node) => node.tagName === "button" && node.textContent === "Query",
    ),
    info: nodes.find((node) => hasClass(node, "query-status")),
  };
}

for (const action of [
  "search",
  "mode",
  "source",
  "background",
  "reset",
  "expand",
  "collapse",
  "selection",
  "lasso",
]) {
  for (const outcome of ["success", "failure"]) {
    test(`${action} invalidates an in-flight Query ${outcome}`, async () => {
      const page = await fixture();
      if (action === "expand" || action === "collapse") await page.openLeaves();
      const { search, run, info } = queryControls(page),
        pending = deferred();
      page.queryReads.push(pending.promise);
      search.value = "Original";
      search.oninput();
      const request = run.onclick();
      if (action === "search") {
        search.value = "";
        search.oninput();
      }
      if (action === "mode") page.hierarchy();
      if (action === "source") {
        const filter = all(page.dom.$("content")).find(
          (node) => node["aria-label"] === "筛选分类",
        );
        filter.value = "domain:d";
        filter.onchange();
      }
      if (action === "background") page.graph.background();
      if (action === "reset")
        all(page.dom.$("content"))
          .find((node) => node.textContent === "重置")
          .onclick();
      if (action === "expand" || action === "collapse") {
        const label = action === "expand" ? "展开本区" : "收起本区";
        all(page.aside())
          .find((node) => node.textContent === label)
          .onclick();
      }
      if (action === "selection") await page.select("wiki/a.md");
      if (action === "lasso") page.graph.options.onLasso([page.graph.nodes[0]]);
      const nodes = page.graph.nodes.map((node) => node.id),
        detail = text(page.aside()),
        selected = page.graph.selected;
      assert.equal(run.disabled, false);
      if (outcome === "success")
        pending.resolve({
          knowledge: [{ source_path: "wiki/b.md", title: "Stale result" }],
        });
      else pending.resolve(Error("Stale query failed"));
      await request;
      assert.deepEqual(
        page.graph.nodes.map((node) => node.id),
        nodes,
      );
      assert.equal(page.graph.selected, selected);
      assert.equal(text(page.aside()), detail);
      assert.equal(info.textContent, "");
      assert.equal(page.status(), undefined);
      if (action === "lasso") {
        const selection = all(page.dom.$("content")).find(
          (node) => node.className === "knowledge-selection",
        );
        assert.equal(selection.hidden, false);
        assert.equal(selection["aria-label"], "已圈选 1 个节点");
      }
    });
  }
}

for (const outcome of ["success", "failure"]) {
  for (const order of ["old-first", "new-first"]) {
    test(`a newer Query owns status and busy state when old ${outcome} arrives ${order}`, async () => {
      const page = await fixture(),
        old = deferred(),
        current = deferred();
      const { search, run, info } = queryControls(page);
      page.queryReads.push(old.promise, current.promise);
      search.value = "Original";
      search.oninput();
      const first = run.onclick();
      search.value = "Second";
      search.oninput();
      const second = run.onclick();
      const finishOld = () =>
        outcome === "success"
          ? old.resolve({
              knowledge: [{ source_path: "wiki/a.md", title: "Stale result" }],
            })
          : old.resolve(Error("Stale query failed"));
      if (order === "old-first") {
        finishOld();
        await first;
        assert.equal(run.disabled, true);
        assert.equal(info.textContent, "查询中…");
      }
      current.resolve({
        knowledge: [{ source_path: "wiki/b.md", title: "Second title" }],
      });
      await second;
      const status = info.textContent;
      if (order === "new-first") {
        finishOld();
        await first;
      }
      assert.equal(info.textContent, status);
      assert.match(status, /1 命中/);
      assert.equal(run.disabled, false);
      assert.equal(page.status(), undefined);
      assert.deepEqual(
        page.graph.nodes.map((node) => node.id),
        ["wiki/b.md"],
      );
      assert.ok(text(page.aside()).includes("Second title"));
    });
  }
}

test("selected document switches to direct neighbors and returns to all without recreating graph", async () => {
  const f = await fixture();
  f.snapshot.map.domains[0].clusters[0].points.push({
    id: "wiki/c.md",
    path: "wiki/c.md",
    title: "Unrelated",
    kind: "wiki",
  });
  f.snapshot.map.edges = [{ a: "wiki/a.md", b: "wiki/b.md", type: "supports" }];
  await f.tick();
  f.graph.select(f.graph.nodes.find((n) => n.id === "wiki/a.md"));
  await settle();
  const button = (label) =>
    all(f.dom.$("content")).find(
      (n) => n.tagName === "button" && n.textContent === label,
    );
  button("只看直接关联").onclick();
  assert.deepEqual(
    f.graph.nodes.map((n) => n.id),
    ["wiki/a.md", "wiki/b.md"],
  );
  assert.equal(f.graph.edges.length, 1);
  button("返回全图").onclick();
  assert.equal(f.graph.nodes.length, 3);
  assert.equal(f.graph.creates, 1);
});

test("a late Wiki body cannot overwrite a different selection", async () => {
  const page = await fixture(),
    delayed = deferred();
  page.fileReads.push(delayed.promise);
  await page.select("wiki/a.md");
  await page.select("wiki/b.md");
  delayed.resolve({
    body: "Old source body",
    body_html: "<p>Old source body</p>",
  });
  await settle();
  assert.doesNotMatch(text(page.aside()), /Old source body/);
  assert.match(text(page.aside()), /Second body/);
});

test("a related document opens even when it does not match the current search", async () => {
  const f = await fixture();
  f.snapshot.map.edges = [{ a: "wiki/a.md", b: "wiki/b.md", type: "supports" }];
  await f.tick();
  const { search } = queryControls(f);
  search.value = "Original";
  search.oninput();
  f.graph.select(f.graph.nodes.find((n) => n.id === "wiki/a.md"));
  await settle();
  all(f.aside())
    .find((n) => n.tagName === "button" && n.textContent === "Second title")
    .onclick();
  await settle();
  assert.equal(search.value, "");
  assert.equal(f.aside().hidden, false);
  assert.ok(text(f.aside()).includes("Second title"));
});
