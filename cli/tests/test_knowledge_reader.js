"use strict";
const { test, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const {
  source,
  moduleUrl,
  deferred,
  settle,
  Element,
} = require("./studio_test_helpers.cjs");

const cleanups = [];
afterEach(() => {
  while (cleanups.length) cleanups.pop()();
});

const all = (node) => [node, ...(node.children?.flatMap(all) || [])];
class Node extends Element {
  showModal() { this.open = true; }
  close() { this.open = false; }
  get firstElementChild() { return this.children[0] || null; }
  constructor(tag) {
    super(tag);
    const classes = () => (this.className || "").split(/\s+/).filter(Boolean);
    this.classList = {
      contains: (name) => classes().includes(name),
      add: (...names) => {
        this.className = [...new Set([...classes(), ...names])].join(" ");
      },
      remove: (...names) => {
        this.className = classes().filter((name) => !names.includes(name)).join(" ");
      },
      toggle: (name, force) => {
        const enabled = force ?? !this.classList.contains(name);
        this.classList[enabled ? "add" : "remove"](name);
        return enabled;
      },
    };
  }
  append(...children) {
    for (const child of children) {
      child.remove();
      child.parentNode = this;
      this.children.push(child);
    }
  }
  replaceChildren(...children) {
    for (const child of this.children) child.parentNode = null;
    this.children = [];
    this._text = this._html = "";
    this.append(...children);
  }
  remove() {
    if (this.parentNode)
      this.parentNode.children = this.parentNode.children.filter((node) => node !== this);
    this.parentNode = null;
  }
  before(node) {
    node.remove();
    node.parentNode = this.parentNode;
    this.parentNode.children.splice(this.parentNode.children.indexOf(this), 0, node);
  }
  set textContent(text) {
    this.replaceChildren();
    this._text = String(text ?? "");
  }
  get textContent() {
    return (this._text || this._html?.replace(/<[^>]*>/g, "") || "") +
      this.children.map((node) => node.textContent).join("");
  }
  set innerHTML(html) {
    this.replaceChildren();
    this._html = html;
  }
  get innerHTML() {
    return this._html || "";
  }
  querySelectorAll(selector) {
    const [tag, ...classes] = selector.split(".");
    return all(this).slice(1).filter((node) =>
      (!tag || node.tagName === tag) &&
      classes.every((name) => node.classList.contains(name)),
    );
  }
  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }
}

const richHtml = '<h2>Full article</h2><p>Complete body beyond the map preview.</p>' +
  '<img src="/api/studio/document-asset?path=raw%2Fimage.png" alt="Evidence">' +
  '<pre><code class="language-js">a &lt; b</code></pre>' +
  '<table><thead><tr><th>Source</th></tr></thead><tbody><tr><td>Local</td></tr></tbody></table>';

async function fixture(read) {
  const wiki = (id) => ({
    id, kind: "wiki", path: `wiki/computing/${id}.md`, title: id,
    body: "MAP PREVIEW MUST NOT DISPLAY", body_truncated: true,
  });
  const map = {
    domains: [{ id: "computing", label: "Computing", clusters: [{
      id: "reader", label: "Reader", points: [wiki("a"), wiki("b"), {
        id: "draft", kind: "candidate", title: "Draft", path: "drafts/reader.md",
        body: "DRAFT PREVIEW MUST NOT DISPLAY",
      }],
    }] }],
    materials: [{ id: "raw", kind: "raw", title: "Source", path: "raw/reader/raw.md" }],
    edges: [],
  };
  const skills = { skills: [{ title: "Reader skill", path: ".claude/skills/reader/SKILL.md" }], warnings: [] };
  const contexts = { entries: [
    { id: "profile", type: "profile", title: "Profile", group: "Users", path: "profiles/users/reader.md" },
    { id: "mail:reader", type: "mail", title: "Mail article", group: "Handoff", path: "mail/messages/reader.md",
      body: "MAIL PREVIEW MUST NOT DISPLAY", body_truncated: true },
    { id: "team:shared:reader", type: "team", title: "Team article", group: "Shared", asset_kind: "wiki",
      path: "team/display/reader.md", source_path: "wiki/actual-reader.md", library_id: "shared", revision: "team-v7" },
  ], edges: [], warnings: [] };
  const seeds = new Map([
    ["/api/mail/knowledge-map", map],
    ["/api/studio/usage", { entries: [{ slug: "a", count: 2 }], warnings: [] }],
    ["/api/studio/skills", skills],
    ["/api/studio/contexts", contexts],
    ["/api/studio/activity?date=2026-11-12", { queried_paths: [], used_slugs: [] }],
  ]);
  const inputBefore = JSON.stringify([...seeds.values()]);
  const ids = new Map(), graphs = [], reads = [], writes = [], statuses = [], timers = new Map();
  const reviewCalls = [], reviewCloses = [];
  const state = { tab: "learning", learn: "graph", date: "2026-11-12" };
  const dom = {
    $(id) {
      if (!ids.has(id)) ids.set(id, new Node("div"));
      return ids.get(id);
    },
    el: (tag, className, text) => Object.assign(new Node(tag), { className, textContent: text }),
    button: (text, onclick, className) => Object.assign(new Node("button"), { textContent: text, onclick, className }),
  };
  const api = {
    async request(url, options) {
      if (options?.method && options.method !== "GET") {
        writes.push({ url, options });
        throw Error("Reading must not write");
      }
      if (seeds.has(url)) return seeds.get(url);
      reads.push(url);
      const result = read?.(url, reads.length);
      return result === undefined ? { body_html: richHtml, revision: "team-v7" } : result;
    },
    async post(url, body) {
      writes.push({ url, body });
      throw Error("Reading must not write");
    },
  };
  const model = await import(moduleUrl(source("studio/knowledge-model.js")));
  const sandbox = {
    ...model, URLSearchParams, performance,
    document: { hidden: false, createElementNS: (_, tag) => new Node(tag) },
    setInterval(fn) { const id = timers.size + 1; timers.set(id, fn); return id; },
    clearInterval: (id) => timers.delete(id),
    drawGraph(svg, nodes, edges, tools, onSelect) {
      graphs.push({ nodes, edges, onSelect });
      return () => {};
    },
    callTimeline: () => new Node("div"),
    showWorkflow() { throw Error("Reading a document must not start a workflow"); },
    createDraftReader(options) {
      return {
        open(container, path) { reviewCalls.push({ container, path, options }); },
        close() { reviewCloses.push(true); },
      };
    },
  };
  const code = source("studio/knowledge.js")
    .replace(/^import\s+[\s\S]*?\s+from\s+["'][^"']+["'];\r?\n/gm, "")
    .replace("export function createKnowledgeView", "function createKnowledgeView");
  vm.runInNewContext(code + "\nthis.createKnowledgeView = createKnowledgeView;", sandbox);
  const view = sandbox.createKnowledgeView({
    dom, api, state,
    actions: { status: (message) => statuses.push(message), canLeave: () => !state.commentDraft },
  });
  cleanups.push(() => view.destroy());
  await view.render();
  const pathTo = (nodes, id) => {
    for (const node of nodes) {
      if (node.id === id) return [node];
      const path = pathTo(node.children || [], id);
      if (path) return [node, ...path];
    }
  };
  return {
    view, reads, writes, statuses, graphs, timers, state, reviewCalls, reviewCloses,
    aside: dom.$("content").querySelector("aside"),
    shell: dom.$("content").querySelector(".knowledge-map"),
    input: () => JSON.stringify([...seeds.values()]), inputBefore,
    async reveal(id) {
      while (!graphs.at(-1).nodes.some((node) => node.id === id)) {
        const graph = graphs.at(-1), path = pathTo(graph.nodes, id);
        assert.ok(path, `No graph path to ${id}`);
        const parent = path.find((node) => graph.nodes.some((shown) => shown.id === node.id) &&
          node.children?.some((child) => !graph.nodes.some((shown) => shown.id === child.id)));
        assert.ok(parent, `Cannot reveal ${id}`);
        await graph.onSelect(parent);
      }
    },
    click(id) {
      const graph = graphs.at(-1), node = graph.nodes.find((item) => item.id === id);
      assert.ok(node, `${id} must be visible before clicking`);
      return graph.onSelect(node);
    },
    close() {
      all(this.aside).find((node) => node["aria-label"] === "关闭详情").onclick();
    },
    article() { return this.aside.querySelector("article.knowledge-body.markdown-body"); },
  };
}

test("a graph leaf opens a loading article immediately and renders the complete server HTML without changing the map", async () => {
  const pending = deferred(), page = await fixture(() => pending.promise);
  await page.reveal("a");
  const opening = page.click("a");
  assert.equal(page.aside.hidden, false);
  assert.equal(page.shell.classList.contains("with-detail"), true);
  assert.ok(page.article(), "The original sidebar must contain a Markdown article before the read finishes");
  assert.match(page.article().textContent, /加载|读取/);
  assert.equal(page.article()["aria-busy"], "true");
  assert.equal(page.aside.querySelector("pre"), null);
  assert.doesNotMatch(page.aside.textContent, /MAP PREVIEW|正文已截断/);
  pending.resolve({ body_html: richHtml });
  await opening;
  assert.equal(page.article().innerHTML, richHtml);
  assert.equal(page.article()["aria-busy"], undefined);
  assert.match(page.article().innerHTML, /<img .*<pre><code .*<table>/);
  assert.doesNotMatch(page.aside.textContent, /MAP PREVIEW|正文已截断/);
  assert.equal(page.input(), page.inputBefore);
  assert.deepEqual(page.writes, []);
});

test("document reads use the complete-document API for each graph source and bind the team source revision", async () => {
  const page = await fixture();
  const cases = [
    ["a", "/api/mail/memory/item", { path: "wiki/computing/a.md" }],
    ["raw", "/api/studio/draft-reader", { path: "raw/reader/raw.md" }],
    ["draft", "/api/studio/draft-reader", { path: "drafts/reader.md" }],
    ["team:shared:reader", "/api/studio/library-document", { library: "shared", path: "wiki/actual-reader.md", revision: "team-v7" }],
    ["profile", "/api/studio/file", { path: "profiles/users/reader.md" }],
    ["mail:reader", "/api/studio/file", { path: "mail/messages/reader.md" }],
    [".claude/skills/reader/SKILL.md", "/api/studio/file", { path: ".claude/skills/reader/SKILL.md" }],
  ];
  for (const [id, route, parameters] of cases) {
    await page.reveal(id);
    const previous = page.reads.length;
    await page.click(id);
    assert.equal(page.reads.length, previous + 1, `${id} needs one complete-document read`);
    const request = new URL(page.reads.at(-1), "http://local");
    assert.equal(request.pathname, route, id);
    assert.deepEqual(Object.fromEntries(request.searchParams), parameters, id);
    assert.equal(page.article().innerHTML, richHtml, id);
  }
  assert.equal(page.input(), page.inputBefore);
  assert.deepEqual(page.writes, []);
});

test("A to B to A keeps the latest article when an earlier request for the same ID arrives late", async () => {
  const pending = [deferred(), deferred(), deferred()];
  const page = await fixture((_, index) => pending[index - 1].promise);
  await page.reveal("a");
  const firstA = page.click("a"), firstArticle = page.article();
  const b = page.click("b"), bArticle = page.article();
  const latestA = page.click("a"), latestArticle = page.article();
  pending[2].resolve({ body_html: "<p>Latest A</p>" });
  await latestA;
  pending[0].resolve({ body_html: "<p>Stale A</p>" });
  pending[1].resolve(Promise.reject(Error("Stale B failed")));
  await Promise.all([firstA, b]);
  assert.equal(page.article(), latestArticle);
  assert.equal(page.article().innerHTML, "<p>Latest A</p>");
  assert.doesNotMatch(firstArticle.innerHTML + bArticle.innerHTML, /Stale/);
  assert.deepEqual(page.statuses, []);
});

test("closing the sidebar or destroying its view invalidates an unfinished document read", async () => {
  for (const finish of ["close", "destroy"]) {
    const pending = deferred(), page = await fixture(() => pending.promise);
    await page.reveal("a");
    const opening = page.click("a"), article = page.article();
    const before = article.innerHTML;
    if (finish === "close") page.close();
    else page.view.destroy();
    const graphsBefore = page.graphs.length;
    pending.resolve({ body_html: "<p>Late closed article</p>" });
    await opening;
    await settle();
    assert.equal(article.innerHTML, before, finish);
    assert.equal(page.graphs.length, graphsBefore, `${finish} must not repaint a stale selection`);
    if (finish === "close") {
      assert.equal(page.aside.hidden, true);
      assert.equal(page.shell.classList.contains("with-detail"), false);
    } else assert.equal(page.timers.size, 0);
  }
});

test("category clicks only expand and collapse the graph without fetching or displaying a document", async () => {
  const page = await fixture();
  assert.deepEqual(page.graphs.at(-1).nodes.map((node) => node.id), ["overview:wiki", "materials", "skills", "context:profile", "context:team", "context:mail"]);
  await page.click("overview:wiki");
  assert.ok(page.graphs.at(-1).nodes.some((node) => node.id === "domain:computing"));
  assert.equal(page.article(), null);
  await page.click("overview:wiki");
  assert.ok(!page.graphs.at(-1).nodes.some((node) => node.id === "domain:computing"));
  assert.deepEqual(page.reads, []);
  assert.deepEqual(page.writes, []);
});

test("a failed read shows a retry that fetches the document again without using its truncated map body", async () => {
  const page = await fixture((_, index) => {
    if (index === 1) return Promise.reject(Error("Document temporarily unavailable"));
  });
  await page.reveal("a");
  await page.click("a");
  assert.match(page.aside.textContent, /无法打开|失败/);
  assert.ok(page.statuses.includes("Document temporarily unavailable"));
  assert.doesNotMatch(page.aside.textContent, /MAP PREVIEW|正文已截断/);
  const retry = all(page.aside).find((node) => node.tagName === "button" && node.textContent === "重试");
  assert.ok(retry, "A failed article must offer an inline retry");
  await retry.onclick();
  await settle();
  assert.equal(page.reads.length, 2);
  assert.equal(page.reads[0], page.reads[1]);
  assert.equal(page.article().innerHTML, richHtml);
  assert.doesNotMatch(page.aside.textContent, /Document temporarily unavailable/);
  assert.equal(page.input(), page.inputBefore);
  assert.deepEqual(page.writes, []);
});

test("Learning reviews a Draft with the shared reader and preserves unsent comments on close", async () => {
  const page = await fixture();
  await page.reveal("draft");
  await page.click("draft");
  const review = all(page.aside).find(node => node.tagName === "button" && node.textContent === "审核");
  assert.ok(review);
  review.onclick();
  assert.equal(page.reviewCalls.length, 1);
  const call = page.reviewCalls[0], dialog = call.container.parentNode;
  assert.equal(call.path, "drafts/reader.md");
  assert.equal(dialog.open, true);
  assert.equal(page.aside.querySelector("iframe"), null);
  page.state.commentDraft = Symbol("pending");
  call.options.onClose();
  assert.equal(dialog.open, true);
  page.state.commentDraft = null;
  call.options.onClose();
  assert.equal(dialog.open, false);
  assert.equal(page.writes.length, 0);
});
