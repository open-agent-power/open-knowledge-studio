"use strict";
const { test, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const {
  source,
  moduleUrl,
  domFixture,
  Element,
} = require("./studio_test_helpers.cjs");
const model = require("../../assets/mail-web/studio-model.js");
const cleanups = [];
afterEach(() => {
  for (const cleanup of cleanups.splice(0).reverse()) cleanup();
});
function all(node) {
  return [node, ...(node.children?.flatMap(all) || [])];
}
function event(key, extra = {}) {
  return {
    key,
    defaultPrevented: false,
    propagationStopped: false,
    preventDefault() {
      this.defaultPrevented = true;
    },
    stopPropagation() {
      this.propagationStopped = true;
    },
    ...extra,
  };
}
function editorDom() {
  const previous = { document: globalThis.document, Option: globalThis.Option };
  class EditorElement extends Element {
    focus() {
      this.focusCount = (this.focusCount || 0) + 1;
      globalThis.document.activeElement = this;
    }
    scrollIntoView(options) {
      this.scrollOptions = options;
    }
    querySelector(selector) {
      if (selector === ".mindmap-inline-editor input") {
        const form = all(this).find(
          (node) => node.className === "mindmap-inline-editor",
        );
        return form ? all(form).find((node) => node.tagName === "input") : null;
      }
      return null;
    }
  }
  globalThis.document = {
    activeElement: null,
    createElement: (tag) => new EditorElement(tag),
    createElementNS: (_, tag) => new EditorElement(tag),
    createTextNode: (text) =>
      Object.assign(new EditorElement("#text"), { textContent: text }),
  };
  globalThis.Option = class extends EditorElement {
    constructor(text, value) {
      super("option");
      this.textContent = text;
      this.value = value;
    }
  };
  cleanups.push(() => Object.assign(globalThis, previous));
  const dom = domFixture(),
    baseDollar = dom.$;
  dom.el = (tag, className, text) =>
    Object.assign(new EditorElement(tag), { className, textContent: text });
  const content = baseDollar("content");
  dom.$ = (id) => all(content).find((node) => node.id === id) || baseDollar(id);
  return { dom, host: new EditorElement("div") };
}
function editor(host) {
  const form = all(host).find(
    (node) => node.className === "mindmap-inline-editor",
  );
  assert.ok(form, "The draft editor is visible");
  return {
    form,
    input: all(form).find((node) => node.tagName === "input"),
    save: all(form).find((node) => node.textContent === "保存"),
    cancel: all(form).find((node) => node.textContent === "取消"),
  };
}
async function drawing(
  tree = { id: "root", title: "Root", children: [] },
  parentId = "root",
) {
  const { dom, host } = editorDom(),
    commits = [],
    drafts = [],
    cancellations = [];
  const module = await import(moduleUrl(source("studio/mindmap.js")));
  module.drawMindmap({
    dom,
    host,
    tree,
    collapsed: new Set(),
    pendingAdd: { id: parentId, title: "111" },
    onSelect() {},
    onAdd() {},
    onCommit: (parent, title) => commits.push({ id: parent.id, title }),
    onDraft: (title) => drafts.push(title),
    onCancel: () => cancellations.push(true),
  });
  return { ...module, host, commits, drafts, cancellations, ...editor(host) };
}

test("the draft has explicit save and non-submit cancel, with one trimmed form submission", async () => {
  const page = await drawing();
  assert.equal(page.save.type, "submit");
  assert.equal(page.cancel.type, "button");
  assert.equal(page.input["aria-label"], "新子目标标题");
  assert.equal(globalThis.document.activeElement, page.input);
  assert.deepEqual(page.input.scrollOptions, { block: "nearest", inline: "nearest" });
  page.input.value = "   ";
  await page.form.onsubmit(event());
  assert.deepEqual(page.commits, []);
  page.input.value = "  111  ";
  page.input.oninput();
  const enter = event("Enter");
  page.input.onkeydown(enter);
  assert.equal(
    enter.defaultPrevented,
    false,
    "Ordinary Enter keeps the browser's form submit behavior",
  );
  const submit = event();
  await page.form.onsubmit(submit);
  assert.equal(submit.defaultPrevented, true);
  assert.equal(submit.propagationStopped, true);
  assert.deepEqual(page.drafts, ["  111  "]);
  assert.deepEqual(page.commits, [{ id: "root", title: "111" }]);
});

test("IME Enter cannot submit, blur keeps the draft, and Escape is an explicit cancellation", async () => {
  const page = await drawing(),
    composing = event("Enter", { isComposing: true });
  page.input.onkeydown(composing);
  assert.equal(composing.defaultPrevented, true);
  assert.deepEqual(page.commits, []);
  page.input.onblur?.();
  assert.deepEqual(page.commits, []);
  assert.deepEqual(page.cancellations, []);
  const escape = event("Escape");
  page.input.onkeydown(escape);
  assert.equal(escape.defaultPrevented, true);
  assert.equal(page.cancellations.length, 1);
  assert.deepEqual(page.commits, []);
});

test("a draft editor fits before the following branch while ordinary rows keep their spacing", async () => {
  const tree = {
    id: "root",
    title: "Root",
    children: [
      {
        id: "a",
        title: "A",
        children: [{ id: "a1", title: "A1", children: [] }],
      },
      { id: "b", title: "B", children: [] },
      { id: "c", title: "C", children: [] },
    ],
  };
  const page = await drawing(tree, "a"),
    before = page.layoutTree(tree).nodes,
    after = page.layoutTree(page.withDraftNode(tree, { id: "a" })).nodes,
    slot = all(page.host).find((node) => node.tagName === "foreignObject"),
    next = after.find((node) => node.id === "b");
  assert.ok(
    Number(slot.y) + Number(slot.height) <= next.y - 19,
    "The save/cancel area does not cover the next node's box",
  );
  assert.equal(
    after.find((node) => node.id === "c").y - next.y,
    before.find((node) => node.id === "c").y -
      before.find((node) => node.id === "b").y,
  );
  assert.equal(
    tree.children[0].children.length,
    1,
    "Layout does not persist a draft in the saved tree",
  );
});

function goalState() {
  const file = {
    path: "profiles/goals/2026/11/08/existing.md",
    title: "Existing goal",
    kind: "goal",
    text: "# Existing goal\n\n## [ ] Existing child\n",
    sha256: "source-sha",
    outline: [
      {
        kind: "heading",
        level: 1,
        line: 0,
        parent: null,
        text: "Existing goal",
        checked: false,
      },
      {
        kind: "heading",
        level: 2,
        line: 2,
        parent: 0,
        text: "Existing child",
        checked: false,
      },
    ],
  };
  return {
    tab: "goals",
    date: "2026-11-08",
    scope: "",
    mode: "list",
    selected: file.path,
    context: { knowledge_base: "/kb", local_edit: true },
    dirty: false,
    saving: false,
    view: {
      entry: file.path,
      entries: [file.path],
      files: { [file.path]: file },
      edges: [],
      timeline: [],
    },
  };
}
async function goals({ postHook } = {}) {
  const { dom } = editorDom(),
    posts = [],
    saves = [],
    loads = [],
    state = goalState();
  let status = "",
    renders = 0,
    view;
  const canLeave = () => {
    if (state.saving) {
      status = "保存中…";
      return false;
    }
    if (state.dirty) {
      status = "请先保存修改";
      return false;
    }
    return true;
  };
  const render = () => {
    renders++;
    dom.$("content").replaceChildren();
    view.render();
  };
  const script = source("studio/goals.js")
    .replace(
      '"./mindmap.js"',
      JSON.stringify(moduleUrl(source("studio/mindmap.js"))),
    )
    .replace(
      '"./timeline.js"',
      JSON.stringify(moduleUrl(source("studio/timeline.js"))),
    );
  const { createGoalsView } = await import(moduleUrl(script));
  view = createGoalsView({
    dom,
    state,
    model,
    actions: {
      canLeave,
      writable: () => true,
      status: (text) => {
        status = text;
      },
      render,
      async loadView(...args) {
        loads.push(args);
        status = "";
        render();
      },
      async saveDocument(at, text) {
        saves.push({ path: at.path, text });
        state.dirty = false;
        status = "";
        render();
      },
    },
    api: {
      async post(route, payload) {
        posts.push({ route, payload });
        return postHook?.(posts.length);
      },
    },
  });
  cleanups.push(() => view.destroy());
  render();
  return {
    dom,
    state,
    posts,
    saves,
    loads,
    canLeave,
    status: () => status,
    renders: () => renders,
    button: (label) =>
      all(dom.$("content")).find(
        (node) => node.tagName === "button" && node.textContent === label,
      ),
    start(title) {
      all(dom.$("content"))
        .find((node) => node["aria-label"] === "新增子目标：" + title)
        .onclick(event());
      return editor(dom.$("content"));
    },
    editor: () => editor(dom.$("content")),
  };
}

for (const target of ["2026-11-08", "Existing goal"]) {
  for (const cancelWith of ["button", "Escape"]) {
    test(`${target} draft can be cancelled with ${cancelWith}, clearing dirty/status and allowing navigation without a write`, async () => {
      const page = await goals(),
        draft = page.start(target);
      draft.input.value = "111";
      draft.input.oninput();
      draft.input.onblur?.();
      assert.equal(page.state.dirty, true);
      assert.equal(page.posts.length + page.saves.length, 0);
      page.button("原文").onclick();
      assert.equal(page.status(), "请先保存修改");
      assert.equal(page.state.mode, "list");
      const focusCount = draft.input.focusCount;
      all(page.dom.$("content"))
        .find(
          (node) =>
            node.tagName === "g" && node["aria-label"] === "Existing goal",
        )
        .onclick();
      assert.ok(
        draft.input.focusCount > focusCount,
        "Selecting another node returns focus to the unsubmitted draft",
      );
      if (cancelWith === "button") draft.cancel.onclick();
      else draft.input.onkeydown(event("Escape"));
      assert.equal(page.state.dirty, false);
      assert.equal(page.status(), "");
      assert.equal(
        all(page.dom.$("content")).some(
          (node) => node.className === "mindmap-inline-editor",
        ),
        false,
      );
      assert.equal(page.posts.length + page.saves.length, 0);
      assert.equal(page.canLeave(), true);
      page.button("原文").onclick();
      assert.equal(page.state.mode, "source");
      assert.equal(page.renders(), 2);
    });
  }
}

test("the explicit form can retry a failed root save without losing the draft or blocking cancellation", async () => {
  const page = await goals({
    postHook: (attempt) => {
      if (attempt === 1) throw Error("Save unavailable");
    },
  });
  const draft = page.start("2026-11-08");
  draft.input.value = "111";
  draft.input.oninput();
  await draft.form.onsubmit(event());
  assert.equal(page.state.saving, false);
  assert.equal(page.state.dirty, true);
  assert.equal(page.status(), "Save unavailable");
  assert.equal(page.editor().input.value, "111");
  assert.equal(page.editor().cancel.type, "button");
  await page.editor().form.onsubmit(event());
  assert.equal(page.posts.length, 2);
  assert.equal(page.posts[1].payload.path, "profiles/goals/2026/11/08/111.md");
  assert.equal(page.state.dirty, false);
  assert.equal(page.state.saving, false);
  assert.equal(page.canLeave(), true);
  assert.deepEqual(page.loads, [[true]]);
});

test("submitting a child draft uses the source-edit action for that goal", async () => {
  const page = await goals(),
    draft = page.start("Existing goal");
  draft.input.value = " 111 ";
  draft.input.oninput();
  await draft.form.onsubmit(event());
  assert.equal(page.saves.length, 1);
  assert.equal(page.saves[0].path, "profiles/goals/2026/11/08/existing.md");
  assert.match(page.saves[0].text, /## \[ \] 111\n/);
  assert.equal(page.state.dirty, false);
  assert.equal(page.posts.length, 0);
});
