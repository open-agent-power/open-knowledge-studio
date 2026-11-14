"use strict";
const { test, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const { source, moduleUrl, domFixture, Element, settle } = require("./studio_test_helpers.cjs");
let restore;
afterEach(() => restore?.());
const all = node => [node, ...node.children.flatMap(all)];

async function fixture(options = {}) {
  const dom = domFixture(), previous = { document: globalThis.document, Option: globalThis.Option };
  const make = dom.el;
  dom.el = (...args) => {
    const node = make(...args);
    node.getAttribute = key => node[key];
    node.classList.remove = () => {};
    return node;
  };
  globalThis.document = { createElementNS: (ns, tag) => new Element(tag) };
  globalThis.Option = class extends Element {
    constructor(label, value) { super("option"); this.textContent = label; this.value = value; }
  };
  const calls = { graphs: [], opens: [], closes: 0, refreshes: 0, disposed: 0 };
  globalThis.__discussionTest = calls;
  const graphModule = `export function drawGraph(svg,nodes,edges,tools,select,options) {
    const calls=globalThis.__discussionTest; calls.select=select; calls.options=options;
    calls.graphs.push({nodes,edges}); return ()=>calls.disposed++;
  }`;
  const readerModule = `export function createDraftReader(options) {
    const calls=globalThis.__discussionTest; calls.reader=options;
    return {open(host,path){calls.opens.push(path)},close(){calls.closes++},
      refresh(){calls.refreshes++},ownsDraft(){return calls.ownsDraft===true}};
  }`;
  const text = source("studio/discussion.js")
    .replace('"./graph.js"', JSON.stringify(moduleUrl(graphModule)))
    .replace('"./draft-reader.js"', JSON.stringify(moduleUrl(readerModule)))
    .replace('"./timeline.js"', JSON.stringify(moduleUrl(source("studio/timeline.js"))));
  const { createDiscussionView } = await import(moduleUrl(text));
  const state = { context: { knowledge_base: "/kb" }, discuss: options.history ? "history" : "graph",
    scope: options.scope || "", view: {
      nodes: [
        { id: "drafts/a.md", path: "drafts/a.md", type: "drafts", title: "First", review_status: "draft" },
        { id: "drafts/b.md", path: "drafts/b.md", type: "drafts", title: "Reviewed", review_status: "promoted" },
        { id: "raw/source.md", path: "raw/source.md", type: "source", title: "Evidence" },
        { id: "section", path: "drafts/a.md", type: "human_judgment", title: "Section" },
      ],
      edges: [{ from: "drafts/a.md", to: "raw/source.md", type: "reference" },
        { from: "drafts/b.md", to: "raw/source.md", type: "reference" }],
      timeline: [{id:"old",at:"2026-11-11T09:00:00Z"},{id:"live",at:"2026-11-11T10:00:00Z"}],
    } };
  let blocked = false;
  const view = createDiscussionView({ dom, state,
    actions: { canLeave: () => !blocked, updateRoute() {}, loadView() {} },
    model: { graph: data => ({ nodes: data.nodes, edges: data.edges }) },
    api: { request: async () => ({read_only:true,nodes:[{id:"old",path:"profiles/discuss/old.md",title:"Old"}],edges:[],
      files:{"profiles/discuss/old.md":{text:"Original",body_html:"<p>Original</p>"}}}) } });
  view.render();
  restore = () => {view.destroy();globalThis.document=previous.document;globalThis.Option=previous.Option;delete globalThis.__discussionTest;};
  const stage = dom.$("content").children[0];
  return { state, view, calls, stage, block:()=>blocked=true,
    filter:all(stage).find(n=>n["aria-label"]==="草稿状态"),
    search:all(stage).find(n=>n["aria-label"]==="查找草稿"),
    timeline:dom.$("content").children[1] };
}

test("discussion draws pending Drafts and explicit sources through the upstream SVG API", async () => {
  const page=await fixture();
  assert.deepEqual(page.calls.graphs.at(-1).nodes.map(n=>n.id),["drafts/a.md","raw/source.md"]);
  assert.equal(page.calls.graphs.at(-1).edges.length,1);
  assert.equal(page.calls.options.nodeRadius({type:"drafts"}),12);
});

test("selecting a Draft opens its card without rebuilding the graph", async () => {
  const page=await fixture(); const before=page.calls.graphs.length;
  page.calls.select(page.state.view.nodes[0]);
  assert.deepEqual(page.calls.opens,["drafts/a.md"]);
  assert.equal(page.calls.graphs.length,before);
  assert.equal(page.stage.children[1].hidden,false);
  page.view.update();
  assert.equal(page.calls.opens.length,1);
  assert.equal(page.calls.refreshes,1);
});

test("search and status preserve only the selected Drafts' declared evidence", async () => {
  const page=await fixture();
  page.filter.value="all";page.filter.onchange();
  page.search.value="Reviewed";page.search.oninput();
  assert.deepEqual(page.calls.graphs.at(-1).nodes.map(n=>n.id),["drafts/b.md","raw/source.md"]);
  assert.deepEqual(page.calls.graphs.at(-1).edges,[page.state.view.edges[1]]);
});

test("pending opinions prevent card dismissal and another document selection", async () => {
  const page=await fixture({scope:"drafts/a.md"});page.block();
  page.calls.reader.onClose();
  assert.equal(page.state.scope,"drafts/a.md");
  assert.equal(page.calls.select(page.state.view.nodes[1]),false);
  assert.deepEqual(page.calls.opens,["drafts/a.md"]);
});

test("remount preserves its own opinion while respecting other unsaved edits", async () => {
  const page=await fixture({scope:"drafts/a.md"});page.calls.ownsDraft=true;page.block();
  page.view.destroy();page.view.render();
  assert.deepEqual(page.calls.opens,["drafts/a.md","drafts/a.md"]);
  page.state.dirty=true;page.view.destroy();page.view.render();
  assert.equal(page.calls.opens.length,2);
});

test("discussion history uses the upstream slider and retained Markdown snapshot", async () => {
  const page=await fixture({history:true});
  const range=all(page.timeline).find(n=>n.type==="range");
  range.value="0";range.oninput();await settle();
  assert.equal(page.calls.graphs.at(-1).nodes[0].id,"old");
  page.calls.select({path:"profiles/discuss/old.md",title:"Old"});
  const article=all(page.stage).find(n=>n.tagName==="article");
  assert.equal(article.innerHTML,"<p>Original</p>");
  range.onkeydown({key:"End",preventDefault(){}});await settle();
  assert.equal(page.calls.graphs.at(-1).nodes[0].id,"drafts/a.md");
  assert.deepEqual(page.calls.opens,[]);
});
