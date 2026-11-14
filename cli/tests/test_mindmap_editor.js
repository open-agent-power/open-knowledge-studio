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
      if ([".mindmap-inline-editor input", ".mindmap-inline-editor"].includes(selector)) {
        const form = all(this).find(
          (node) => node.className === "mindmap-inline-editor",
        );
        return selector === ".mindmap-inline-editor"
          ? form
          : form ? all(form).find((node) => node.tagName === "input") : null;
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
  assert.deepEqual(page.form.scrollOptions, { block: "nearest", inline: "nearest" });
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
async function goals({
  postHook,
  saveHook,
  loadHook,
  refreshAfterSave = true,
  writable = true,
  empty = false,
  history = false,
  mode = "list",
} = {}) {
  const { dom } = editorDom(),
    posts = [],
    saves = [],
    loads = [],
    state = goalState();
  state.mode = mode;
  state.context.local_edit = writable;
  if (empty) state.view = { entries: [], files: {}, timeline: [] };
  if (history) state.view.timeline = [
    { id: "old", at: "2026-11-08T10:00:00Z" },
    { id: "current", at: "2026-11-08T11:00:00Z" },
  ];
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
      writable: () => writable,
      status: (text) => {
        status = text;
      },
      render,
      async loadView(...args) {
        loads.push(args);
        await loadHook?.();
        status = "";
        render();
      },
      async saveDocument(at, text) {
        saves.push({ path: at.path, text });
        state.saving = true;
        try {
          await saveHook?.(saves.length);
        } catch (error) {
          state.saving = false;
          state.dirty = true;
          status = error.message;
          return false;
        }
        state.saving = false;
        state.dirty = false;
        status = "";
        state.view.files[at.path] = { ...at, text, sha256: "saved-sha" };
        if (refreshAfterSave) render();
        return true;
      },
    },
    api: {
      async request() {
        return { ...state.view, revision: { id: "old", at: "2026-11-08T10:00:00Z" } };
      },
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
    view,
    canLeave,
    status: () => status,
    renders: () => renders,
    button: (label) =>
      all(dom.$("content")).find(
        (node) => node.tagName === "button" && node.textContent === label,
      ),
    start(title) {
      all(dom.$("content"))
        .find((node) => ["新增子目标：" + title, "新增目标：" + title].includes(node["aria-label"]))
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

test("an empty goal view exposes creation and describes zoom separately", async () => {
  const page = await goals({ empty: true });
  assert.equal(typeof page.view.startCreate, "function");
  assert.ok(page.button("新建第一个目标"));
  assert.equal(page.button("−").getAttribute?.("aria-label") || page.button("−")["aria-label"], "缩小目标图");
  assert.equal(page.button("＋").title, "放大目标图");
  page.button("新建第一个目标").onclick();
  const draft = page.editor();
  assert.equal(draft.input["aria-label"], "新目标标题");
  assert.equal(page.state.dirty, true);
  draft.cancel.onclick();
  assert.equal(page.state.dirty, false);
  assert.equal(page.posts.length, 0);
});

test("the shared create action opens the goal form and root selection does not show an empty inspector", async () => {
  const page = await goals({ empty: true, mode: "source" });
  page.view.startCreate();
  assert.equal(page.state.mode, "list");
  assert.equal(page.editor().input["aria-label"], "新目标标题");
  page.editor().cancel.onclick();
  all(page.dom.$("content"))
    .find((node) => node.tagName === "g" && node["aria-label"] === page.state.date)
    .onclick();
  assert.ok(page.editor().save);
});

test("read-only goals explain why creation is unavailable without opening a draft", async () => {
  const page = await goals({ empty: true, writable: false });
  assert.equal(typeof page.view.startCreate, "function");
  page.view.startCreate();
  assert.match(page.status(), /只读/);
  assert.equal(page.state.dirty, false);
  assert.equal(all(page.dom.$("content")).some((n) => n.className === "mindmap-inline-editor"), false);
  assert.match(all(page.dom.$("content")).map((n) => n.textContent || "").join(" "), /只读/);
  assert.equal(page.posts.length, 0);
});

test("root creation blocks duplicate saves and cancellation until the request settles", async () => {
  let release;
  const waiting = new Promise((resolve) => { release = resolve; });
  const page = await goals({ empty: true, postHook: () => waiting });
  const draft = page.start(page.state.date);
  draft.input.value = "First goal";
  draft.input.oninput();
  const pending = draft.form.onsubmit(event());
  assert.equal(page.state.saving, true);
  assert.equal(page.editor().input.disabled, true);
  assert.ok(all(page.dom.$("content")).find((node) => node.textContent === "保存中…").disabled);
  page.editor().cancel.onclick();
  await page.editor().form.onsubmit(event());
  assert.equal(page.posts.length, 1);
  assert.equal(page.state.dirty, true);
  release();
  await pending;
  assert.equal(page.state.saving, false);
  assert.equal(page.state.dirty, false);
  assert.equal(page.state.scope, "profiles/goals/2026/11/08/First goal.md");
});

test("source editing has an explicit cancellation and zoom cannot discard unsaved Markdown", async () => {
  const page = await goals({ mode: "source" });
  const original = page.dom.$("editor").value;
  const cancel = page.button("取消");
  assert.ok(cancel);
  page.dom.$("editor").value = "# Draft edits";
  page.dom.$("editor").oninput();
  page.button("＋").onclick();
  assert.equal(page.dom.$("editor").value, "# Draft edits");
  assert.equal(page.state.dirty, true);
  cancel.onclick();
  assert.equal(page.dom.$("editor").value, original);
  assert.equal(page.state.dirty, false);
  assert.equal(page.saves.length, 0);
});

test("node title editing can be cancelled with Escape and preserves a failed save for retry", async () => {
  const page = await goals({ saveHook: () => { throw Error("Title conflict"); } });
  all(page.dom.$("content"))
    .find((node) => node.tagName === "g" && node["aria-label"] === "Existing goal")
    .onclick();
  const input = all(page.dom.$("content")).find((node) => node["aria-label"] === "节点标题");
  input.value = "Revised child";
  input.oninput();
  await page.button("保存").onclick();
  assert.equal(page.state.dirty, true);
  assert.equal(input.value, "Revised child");
  assert.equal(page.status(), "Title conflict");
  input.onkeydown(event("Escape"));
  assert.equal(page.state.dirty, false);
  assert.equal(page.saves.length, 1);
  assert.equal(page.canLeave(), true);
});

test("a failed child save retains its draft and explicit cancellation", async () => {
  const page = await goals({ saveHook: () => { throw Error("Changed on disk"); } });
  const draft = page.start("Existing goal");
  draft.input.value = "Keep this child";
  draft.input.oninput();
  await draft.form.onsubmit(event());
  assert.equal(page.editor().input.value, "Keep this child");
  assert.notEqual(page.editor().input.disabled, true);
  assert.equal(page.state.dirty, true);
  assert.equal(page.status(), "Changed on disk");
  page.editor().cancel.onclick();
  assert.equal(page.state.dirty, false);
  assert.equal(page.posts.length, 0);
  assert.equal(page.saves.length, 1);
});

test("a saved goal is not offered as an unsaved draft when refreshing the view fails", async () => {
  const page = await goals({ empty: true, loadHook: () => { throw Error("Refresh unavailable"); } });
  const draft = page.start(page.state.date);
  draft.input.value = "Saved goal";
  draft.input.oninput();
  await draft.form.onsubmit(event());
  assert.equal(page.posts.length, 1);
  assert.equal(page.state.dirty, false);
  assert.equal(page.state.saving, false);
  assert.equal(all(page.dom.$("content")).some((n) => n.className === "mindmap-inline-editor"), false);
  assert.match(page.status(), /目标已保存.*刷新失败/);
});

test("history remains read-only for create, node additions and Markdown editing", async () => {
  const page = await goals({ history: true });
  const range = all(page.dom.$("content")).find((node) => node.type === "range");
  range.value = "0";
  range.oninput();
  await new Promise((resolve) => setImmediate(resolve));
  page.view.startCreate();
  assert.match(page.status(), /历史快照.*只读/);
  assert.equal(all(page.dom.$("content")).some((n) => n.class === "mindmap-add"), false);
  page.button("原文").onclick();
  assert.equal(page.dom.$("editor").readOnly, true);
  assert.equal(page.button("保存").disabled, true);
  assert.equal(page.button("取消").disabled, true);
  assert.equal(page.posts.length + page.saves.length, 0);
});

test("a successful source save stays editable when the server's later view refresh is unavailable", async () => {
  const page = await goals({ mode: "source", refreshAfterSave: false });
  const editor = page.dom.$("editor");
  editor.value = "# Updated source\n";
  editor.oninput();
  await page.button("保存").onclick();
  assert.equal(page.dom.$("editor").value, "# Updated source\n");
  assert.equal(page.dom.$("editor").readOnly, false);
  assert.equal(page.button("保存").disabled, false);
  assert.equal(page.state.dirty, false);
  assert.equal(page.state.view.files[page.state.selected].sha256, "saved-sha");
});


test("a saved child leaves no disabled draft in the mounted goal canvas", async () => {
  const page = await goals();
  const draft = page.start("Existing goal");
  draft.input.value = "Saved child";
  draft.input.oninput();
  await draft.form.onsubmit(event());
  assert.equal(page.saves.length, 1);
  assert.equal(page.state.dirty, false);
  assert.equal(all(page.dom.$("content")).some((node) => node.className === "mindmap-inline-editor"), false);
});
