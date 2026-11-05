"use strict";
const { test, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const { source, moduleUrl, settle, deferred, Element, domFixture } = require("./studio_test_helpers.cjs");
const previous = {};
let mounted = null;
function all(node) { return [node, ...(node.children?.flatMap(all) || [])]; }
function text(node) { return all(node).map((item) => item.textContent || "").join(" "); }
function hasClass(node, name) { return node.className?.split(/\s+/).includes(name); }

async function fixture() {
  const dom = domFixture(), originalEl = dom.el, timers = [], fileReads = [];
  dom.el = (...args) => {
    const node = originalEl(...args), classes = new Set();
    node.classList = {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
    };
    return node;
  };
  const state = { tab: "learning", learn: "graph", saving: false, context: { knowledge_base: "/kb" } };
  const graph = { creates: 0, updates: [] }, review = { renders: 0, destroys: 0, marker: dom.el("p", "review-marker", "Exact review remains open") };
  const snapshot = {
    map: { domains: [{ id: "d", label: "Domain", clusters: [{ id: "c", label: "Cluster", points: [
      { id: "wiki/a.md", path: "wiki/a.md", title: "Original title", kind: "wiki", body: "Original body", metadata: { source: "Original attribute" }, url: "https://example.test/original" },
      { id: "wiki/b.md", path: "wiki/b.md", title: "Second title", kind: "wiki", body: "Second body" },
    ] }] }], edges: [] },
    usage: { entries: [{ slug: "a", count: 1 }], warnings: [] },
    skills: { skills: [], warnings: [] }, contexts: { entries: [], edges: [], warnings: [] },
  };
  const harness = { graph, review };
  for (const name of ["document", "setInterval", "clearInterval", "knowledgeViewHarness"])
    previous[name] = globalThis[name];
  globalThis.document = { hidden: false, createElementNS: (_, tag) => new Element(tag) };
  globalThis.setInterval = (callback) => timers.push(callback);
  globalThis.clearInterval = () => {};
  globalThis.knowledgeViewHarness = harness;
  const modules = {
    graph: `export function createGraph(svg, tools, onSelect) {
      const graph = globalThis.knowledgeViewHarness.graph;
      graph.creates++; graph.select = onSelect;
      return { update(nodes, edges, state) { graph.nodes = nodes; graph.selected = state.selected; graph.updates.push(nodes.map(n => n.id)); }, destroy() {} };
    }`,
    "draft-review": `export function createDraftReview(options) {
      const review = globalThis.knowledgeViewHarness.review;
      review.onBusy = options.onBusy;
      return { render(host) { review.renders++; host.replaceChildren(review.marker); }, destroy() { review.destroys++; } };
    }`,
    "knowledge-model": source("studio/knowledge-model.js"),
    "call-trace": source("studio/call-trace.js"),
  };
  const script = source("studio/knowledge.js").replace(
    /(["'])\.\/(graph|draft-review|knowledge-model|call-trace)\.js\1/g,
    (_, quote, name) => JSON.stringify(moduleUrl(modules[name])),
  );
  const { createKnowledgeView } = await import(moduleUrl(script));
  const view = createKnowledgeView({
    dom, state,
    actions: { canLeave: () => !state.saving, status: (message) => { harness.status = message; } },
    api: { async request(route) {
      if (route === "/api/mail/knowledge-map") return snapshot.map;
      if (route === "/api/studio/usage") return snapshot.usage;
      if (route === "/api/studio/skills") return snapshot.skills;
      if (route === "/api/studio/contexts") return snapshot.contexts;
      if (route.startsWith("/api/studio/file?")) return fileReads.shift() || { text: "Current Skill body" };
      throw Error("Unexpected route " + route);
    } },
  });
  mounted = view;
  await view.render();
  const page = {
    dom, state, snapshot, graph, review, fileReads,
    aside: () => all(dom.$("content")).find((node) => hasClass(node, "knowledge-detail")),
    points: () => snapshot.map.domains[0].clusters[0].points,
    async select(id) {
      const node = graph.nodes.find((item) => item.id === id);
      assert.ok(node, "Node must be present in the current projection: " + id);
      const accepted = graph.select(node);
      await settle();
      return accepted;
    },
    async openLeaves() {
      await this.select("domain:d");
      await this.select('cluster:["d","c"]');
    },
    async tick() { timers[0](); await settle(); },
  };
  return page;
}
afterEach(() => {
  mounted?.destroy(); mounted = null;
  for (const [name, value] of Object.entries(previous)) globalThis[name] = value;
});

test("selected leaf details track current title, body, uses, attributes and source without recreating the graph", async () => {
  const page = await fixture();
  await page.openLeaves(); await page.select("wiki/a.md");
  const projection = page.graph.nodes.map((node) => node.id);
  Object.assign(page.points()[0], {
    title: "Updated title", body: "Updated body", metadata: { state: "Updated attribute" },
    url: "https://example.test/updated", evidence_url: "https://example.test/evidence", approval_url: "https://example.test/approval",
  });
  page.snapshot.usage.entries[0].count = 9;
  await page.tick();
  const details = text(page.aside()), links = all(page.aside()).filter((node) => node.tagName === "a").map((node) => node.href);
  assert.ok(details.includes("Updated title") && details.includes("Updated body"));
  assert.ok(details.includes("显式使用 9") && details.includes("Updated attribute"));
  assert.ok(!details.includes("Original title") && !details.includes("Original attribute"));
  assert.deepEqual(links, ["https://example.test/updated", "https://example.test/evidence", "https://example.test/approval"]);
  assert.equal(page.graph.selected, "wiki/a.md");
  assert.equal(page.graph.creates, 1);
  assert.deepEqual(page.graph.nodes.map((node) => node.id), projection);
});

test("refreshing a selected group preserves its expanded projection", async () => {
  const page = await fixture();
  await page.openLeaves();
  const projection = page.graph.nodes.map((node) => node.id);
  page.points()[0].body = "Updated in the open group";
  await page.tick();
  assert.equal(page.graph.selected, 'cluster:["d","c"]');
  assert.deepEqual(page.graph.nodes.map((node) => node.id), projection);
  assert.ok(page.graph.nodes.some((node) => node.id === "wiki/a.md"));
});

test("saving postpones detail updates and an unchanged next snapshot catches up", async () => {
  const page = await fixture();
  await page.openLeaves(); await page.select("wiki/a.md");
  page.state.saving = true;
  page.points()[0].body = "Available after saving";
  await page.tick();
  assert.ok(text(page.aside()).includes("Original body"));
  page.state.saving = false;
  await page.tick();
  assert.ok(text(page.aside()).includes("Available after saving"));
});

test("an open review is protected and leaving it permits later normal detail refreshes", async () => {
  const page = await fixture();
  Object.assign(page.points()[0], { id: "drafts/a.md", path: "drafts/a.md", kind: "candidate" });
  await page.tick(); await page.openLeaves(); await page.select("drafts/a.md");
  const open = all(page.aside()).find((node) => node.tagName === "button" && node.textContent === "审核");
  await open.onclick();
  page.review.onBusy(true);
  page.points()[0].body = "New candidate body";
  await page.tick();
  assert.ok(all(page.aside()).includes(page.review.marker));
  assert.equal(page.review.renders, 1);
  assert.equal(await page.select("wiki/b.md"), false);
  page.review.onBusy(false);
  await page.select("wiki/b.md");
  assert.equal(page.review.destroys, 1);
  page.points()[1].body = "Updated after leaving review";
  await page.tick();
  assert.ok(text(page.aside()).includes("Updated after leaving review"));
});

test("a late same-id Skill read cannot overwrite a newer refreshed selection", async () => {
  const page = await fixture(), old = deferred(), current = deferred();
  page.snapshot.skills.skills = [{ path: "skill/demo/SKILL.md", title: "Old Skill" }];
  await page.tick(); await page.select("skills");
  page.fileReads.push(old.promise);
  await page.select("skill/demo/SKILL.md");
  page.snapshot.skills.skills[0].title = "Updated Skill";
  page.fileReads.push(current.promise);
  await page.tick();
  current.resolve({ text: "Newest Skill body" }); await settle();
  assert.ok(text(page.aside()).includes("Updated Skill"));
  assert.ok(text(page.aside()).includes("Newest Skill body"));
  old.resolve({ text: "Stale Skill body" }); await settle();
  assert.ok(text(page.aside()).includes("Newest Skill body"));
  assert.ok(!text(page.aside()).includes("Stale Skill body"));
});

test("removing the selected file clears the selection and its old detail content", async () => {
  const page = await fixture();
  await page.openLeaves(); await page.select("wiki/a.md");
  page.snapshot.map.domains[0].clusters[0].points = page.points().filter((point) => point.id !== "wiki/a.md");
  await page.tick();
  assert.equal(page.graph.selected, null);
  assert.equal(page.aside().hidden, true);
  assert.equal(page.aside().children.length, 0);
});
