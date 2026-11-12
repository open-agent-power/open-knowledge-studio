"use strict";
const { test, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const {
  source,
  moduleUrl,
  deferred,
  Element,
} = require("./studio_test_helpers.cjs");
const all = (node) => [node, ...(node.children?.flatMap(all) || [])];
let cleanup;
afterEach(() => cleanup?.());

class Node extends Element {
  constructor(tag) {
    super(tag);
    this.scrollTop = 0;
  }
  prepend(...children) {
    this.children.unshift(...children);
  }
  scrollIntoView() {}
  focus() {
    globalThis.document.activeElement = this;
  }
  querySelectorAll(selector) {
    return all(this)
      .slice(1)
      .filter((node) =>
        selector.startsWith(".")
          ? (node.className || "").split(" ").includes(selector.slice(1))
          : selector === "details[open]"
            ? node.tagName === "details" && node.open
            : node.tagName === selector,
      );
  }
  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }
}
function response(root, path) {
  return {
    knowledge_base: root,
    path,
    kind: "drafts",
    title: path,
    sha256: "version",
    anchor_id: "section:5",
    body_html: "<p>Draft body</p>",
    sources: [],
    steps: [],
    changes: "",
    warnings: [],
    review_status: "draft",
    promotable: true,
    discussion: {
      comments: [],
      agents: [],
      agent: { id: "@codex", connected: true, label: "Codex" },
    },
  };
}
async function fixture(requestHook, options = {}) {
  const previous = {
    document: globalThis.document,
    location: globalThis.location,
    setTimeout: globalThis.setTimeout,
    clearTimeout: globalThis.clearTimeout,
    FileReader: globalThis.FileReader,
  };
  let timer = 0;
  const timers = new Map(),
    reads = [],
    posts = [];
  globalThis.document = { hidden: false, activeElement: new Node("button") };
  globalThis.location = {
    hash: "#tab=discuss",
    href: "http://local/#tab=discuss",
    origin: "http://local",
  };
  globalThis.setTimeout = (fn) => {
    timers.set(++timer, fn);
    return timer;
  };
  globalThis.clearTimeout = (id) => timers.delete(id);
  globalThis.FileReader = class {
    readAsDataURL() {
      this.result = "data:image/png;base64,YWJj";
      this.onload();
    }
  };
  const state = {
    context: { knowledge_base: "/kb-A", local_edit: true, local_review: true },
    commentDraft: null,
  };
  const dom = {
    el: (tag, className, text) =>
      Object.assign(new Node(tag), { className, textContent: text }),
    button: (text, onclick, className) =>
      Object.assign(new Node("button"), {
        textContent: text,
        onclick,
        className,
      }),
  };
  const { createDraftReader } = await import(
    moduleUrl(source("studio/draft-reader.js"))
  );
  const host = new Node("aside");
  const api = {
    async request(route, requestOptions) {
      if (requestOptions) {
        posts.push({
          route,
          payload: JSON.parse(requestOptions.body),
          root: state.context.knowledge_base,
        });
        return {};
      }
      reads.push(route);
      const result = requestHook?.(route, reads.length);
      return result === undefined
        ? response(
            state.context.knowledge_base,
            new URL("http://local" + route).searchParams.get("path"),
          )
        : result;
    },
    async post(route, payload) {
      posts.push({ route, payload, root: state.context.knowledge_base });
      if (api.error) throw Error(api.error);
    },
  };
  const reader = createDraftReader({ dom, state, actions: {}, api, ...options });
  cleanup = () => {
    reader.close();
    Object.assign(globalThis, previous);
    cleanup = null;
  };
  return {
    host,
    state,
    reader,
    reads,
    posts,
    api,
    timers,
    text: () => host.querySelector("textarea"),
    send: () =>
      all(host).find(
        (node) => node.tagName === "button" && node.textContent === "留言",
      ),
    async type(text, image = false) {
      this.text().value = text;
      this.text().oninput();
      if (image)
        await all(host)
          .find((node) => node.type === "file")
          .onchange({
            target: {
              files: [{ name: "from-A.png", type: "image/png", size: 3 }],
              value: "x",
            },
          });
    },
  };
}

test("unsent text and images are isolated by knowledge base and document path", async () => {
  const page = await fixture();
  await page.reader.open(page.host, "drafts/same.md");
  await page.type("A-only opinion", true);
  page.state.context = { ...page.state.context, knowledge_base: "/kb-B" };
  await page.reader.open(page.host, "drafts/same.md");
  assert.equal(page.text().value, "");
  assert.equal(page.host.querySelector(".draft-uploads").children.length, 0);
  await page.type("B-only opinion");
  await page.send().onclick();
  await new Promise(setImmediate);
  assert.equal(page.posts[0].root, "/kb-B");
  assert.equal(page.posts[0].payload.text, "B-only opinion");
  assert.deepEqual(page.posts[0].payload.images, []);
  page.state.context = { ...page.state.context, knowledge_base: "/kb-A" };
  await page.reader.open(page.host, "drafts/same.md");
  assert.equal(page.text().value, "A-only opinion");
  assert.equal(page.host.querySelector(".draft-uploads").children.length, 1);
});

test("unsent opinions protect leaving and can be explicitly discarded", async () => {
  const page = await fixture();
  await page.reader.open(page.host, "drafts/a.md");
  await page.type("Not sent yet", true);
  assert.ok(page.state.commentDraft);
  assert.equal(page.reader.ownsDraft(), true);
  assert.equal(
    all(page.host).find((node) => node.textContent === "确认入库").disabled,
    true,
  );
  all(page.host)
    .find((node) => node.textContent === "放弃未发送留言")
    .onclick();
  assert.equal(page.state.commentDraft, null);
  assert.equal(page.text().value, "");
  assert.equal(page.host.querySelector(".draft-uploads").children.length, 0);
});

test("opening a source preserves its draft opinion and offers a return path", async () => {
  const page = await fixture((route) => {
    const path = new URL("http://local" + route).searchParams.get("path");
    return {
      ...response("/kb-A", path),
      kind: path.startsWith("raw/") ? "raw" : "drafts",
      sources: path.startsWith("drafts/")
        ? [{ path: "raw/source.md", title: "Original source" }]
        : [],
    };
  });
  await page.reader.open(page.host, "drafts/a.md");
  await page.type("Preserve while reading", true);
  all(page.host).find((node) => node.textContent === "Original source").onclick();
  await new Promise(setImmediate);
  assert.ok(page.state.commentDraft);
  all(page.host).find((node) => node.textContent === "返回草稿").onclick();
  await new Promise(setImmediate);
  assert.equal(page.text().value, "Preserve while reading");
  assert.equal(page.host.querySelector(".draft-uploads").children.length, 1);
});

test("comments request replies by default and edit permission requires an explicit choice", async () => {
  const page = await fixture();
  await page.reader.open(page.host, "drafts/a.md");
  await page.type("Please explain");
  await page.send().onclick();
  await new Promise(setImmediate);
  assert.equal(page.posts[0].payload.allow_edit, false);
  await page.type("Please revise");
  const permission = all(page.host).find((node) => node.type === "checkbox");
  permission.checked = true;
  permission.onchange();
  await page.send().onclick();
  await new Promise(setImmediate);
  assert.equal(page.posts[1].payload.allow_edit, true);
});

test("read-only capability and Agent failure explain why actions are unavailable", async () => {
  const page = await fixture(() => ({
    ...response("/kb-A", "drafts/a.md"),
    discussion: {
      comments: [],
      agents: [],
      agent: {
        id: "@codex",
        label: "Codex",
        connected: true,
        state: "error",
        error: "CLI exited",
      },
    },
  }));
  page.state.context.local_edit = false;
  await page.reader.open(page.host, "drafts/a.md");
  assert.equal(page.text().disabled, true);
  assert.match(
    page.host.querySelector(".draft-agent-status").textContent,
    /未启用本地编辑/,
  );
  page.state.context.local_edit = true;
  await page.reader.refresh();
  assert.match(page.host.querySelector(".draft-agent-status").textContent, /CLI exited/);
});

test("Agent result states remain visible instead of becoming a generic reply", async () => {
  const cases = [
    ["updated", "已修改"],
    ["answered", "已回复"],
    ["needs_info", "需补充"],
    ["failed", "处理失败"],
  ];
  for (const [status, label] of cases) {
    const page = await fixture(() => ({
      ...response("/kb-A", "drafts/a.md"),
      discussion: {
        agent: { id: "@codex" },
        comments: [{
          text: "Opinion",
          source_sha256: "version",
          replies: [{
            from: "@codex",
            body: "JSON transport",
            result: { status, reply: "Readable reply" },
          }],
        }],
      },
    }));
    try {
      await page.reader.open(page.host, "drafts/a.md");
      assert.ok(all(page.host).some((node) => node.textContent === label));
      assert.ok(all(page.host).some((node) => node.textContent === "Readable reply"));
    } finally {
      cleanup();
    }
  }
});

test("not collecting a draft requires confirmation and sends the exact reviewed revision", async () => {
  const page = await fixture();
  await page.reader.open(page.host, "drafts/a.md");
  const reject = all(page.host).find((node) => node.textContent === "不收录");
  assert.ok(reject);
  reject.onclick();
  assert.equal(page.posts.length, 0);
  await all(page.host).find((node) => node.textContent === "确认不收录").onclick();
  await new Promise(setImmediate);
  assert.equal(page.posts[0].route, "/api/learning/reject");
  assert.equal(page.posts[0].payload.expected_sha256, "version");
  assert.equal(page.posts[0].payload.confirm_reject, true);
  assert.equal(page.posts[0].payload.expected_knowledge_base, "/kb-A");
});

test("opening a reader enters its controls and closing returns keyboard focus", async () => {
  const page = await fixture();
  const trigger = globalThis.document.activeElement;
  await page.reader.open(page.host, "drafts/a.md");
  assert.equal(globalThis.document.activeElement["aria-label"], "关闭审阅侧栏");
  page.reader.close();
  assert.equal(globalThis.document.activeElement, trigger);
});

test("a manifest-backed legacy source alias opens inside the reader", async () => {
  const page = await fixture((route) => {
    const path = new URL("http://local" + route).searchParams.get("path");
    return {
      ...response("/kb-A", path),
      kind: path.startsWith("raw/") ? "raw" : "drafts",
      sources: [{
        path: "raw/bundle/raw.md",
        title: "Source",
        aliases: ["raw/bundle/source/excerpt.txt"],
      }],
    };
  });
  await page.reader.open(page.host, "drafts/a.md");
  await page.type("Keep my opinion");
  let prevented = false;
  page.host.querySelector(".draft-article").onclick({
    target: {
      closest: () => ({
        getAttribute: () => "/#collaboration&entry=raw%2Fbundle%2Fsource%2Fexcerpt.txt",
      }),
    },
    preventDefault() {
      prevented = true;
    },
  });
  await new Promise(setImmediate);
  assert.equal(prevented, true);
  assert.equal(
    new URL("http://local" + page.reads.at(-1)).searchParams.get("path"),
    "raw/bundle/raw.md",
  );
  assert.ok(all(page.host).some((node) => node.textContent === "返回草稿"));
  assert.ok(page.state.commentDraft);
});

test("an unlisted source alias keeps normal link navigation", async () => {
  const page = await fixture();
  await page.reader.open(page.host, "drafts/a.md");
  let prevented = false;
  page.host.querySelector(".draft-article").onclick({
    target: {
      closest: () => ({getAttribute: () => "/#collaboration&entry=raw%2Funrelated.md"}),
    },
    preventDefault() {
      prevented = true;
    },
  });
  assert.equal(prevented, false);
  assert.equal(page.reads.length, 1);
});

test("a capture ID resolves only within the draft's explicitly referenced sources", async () => {
  const captureId = "capture-11111111111111111111111111111111";
  const sourcePath = `raw/2026/11/02/daily/${captureId}/raw.md`;
  const page = await fixture((route) => {
    const path = new URL("http://local" + route).searchParams.get("path");
    return {
      ...response("/kb-A", path),
      kind: path.startsWith("raw/") ? "raw" : "drafts",
      sources: [{
        path: sourcePath,
        title: "Original source",
        aliases: [`raw/2026/11/02/daily/${captureId}/source/excerpt.txt`],
      }],
    };
  });
  await page.reader.open(page.host, "drafts/a.md");
  await page.type("Retain this opinion");
  let prevented = false;
  page.host.querySelector(".draft-article").onclick({
    target: {
      closest: () => ({ getAttribute: () => `/#collaboration&entry=${captureId}` }),
    },
    preventDefault() { prevented = true; },
  });
  await new Promise(setImmediate);
  assert.equal(prevented, true);
  assert.equal(
    new URL("http://local" + page.reads.at(-1)).searchParams.get("path"),
    sourcePath,
  );
  all(page.host).find((node) => node.textContent === "返回草稿").onclick();
  await new Promise(setImmediate);
  assert.equal(page.text().value, "Retain this opinion");
});

test("an ambiguous capture ID stays in the reader and reports how to choose its source", async () => {
  const captureId = "capture-11111111111111111111111111111111";
  const page = await fixture(() => ({
    ...response("/kb-A", "drafts/a.md"),
    sources: [
      { path: `raw/2026/11/02/daily/${captureId}/raw.md`, title: "Source one" },
      { path: `raw/2026/11/03/daily/${captureId}/raw.md`, title: "Source two" },
    ],
  }));
  await page.reader.open(page.host, "drafts/a.md");
  let prevented = false;
  page.host.querySelector(".draft-article").onclick({
    target: {
      closest: () => ({ getAttribute: () => `/#collaboration&entry=${captureId}` }),
    },
    preventDefault() { prevented = true; },
  });
  assert.equal(prevented, true);
  assert.equal(page.reads.length, 1);
  assert.match(page.host.querySelector(".draft-feedback").textContent, /无法唯一定位/);
});

test("an unknown capture ID preserves normal navigation without searching the knowledge base", async () => {
  const page = await fixture();
  await page.reader.open(page.host, "drafts/a.md");
  let prevented = false;
  page.host.querySelector(".draft-article").onclick({
    target: {
      closest: () => ({
        getAttribute: () => "/#collaboration&entry=capture-22222222222222222222222222222222",
      }),
    },
    preventDefault() { prevented = true; },
  });
  assert.equal(prevented, false);
  assert.equal(page.reads.length, 1);
});

test("discarding an opinion cancels an unfinished image attachment", async () => {
  const page = await fixture();
  let finish;
  globalThis.FileReader = class {
    readAsDataURL() {
      finish = () => {
        this.result = "data:image/png;base64,YWJj";
        this.onload();
      };
    }
  };
  await page.reader.open(page.host, "drafts/a.md");
  const reading = page.type("Discard this", true);
  all(page.host).find((node) => node.textContent === "放弃未发送留言").onclick();
  finish();
  await reading;
  assert.equal(page.state.commentDraft, null);
  assert.equal(page.host.querySelector(".draft-uploads").children.length, 0);
  assert.equal(page.send().disabled, true);
});

test("a new revision invalidates rejection confirmation and review permission is rechecked", async () => {
  let version = "v1";
  const page = await fixture(() => ({
    ...response("/kb-A", "drafts/a.md"),
    sha256: version,
  }));
  await page.reader.open(page.host, "drafts/a.md");
  all(page.host).find((node) => node.textContent === "不收录").onclick();
  const confirmation = all(page.host).find((node) => node.textContent === "确认不收录");
  version = "v2";
  await page.reader.refresh();
  await confirmation.onclick();
  assert.equal(page.posts.length, 0);
  all(page.host).find((node) => node.textContent === "不收录").onclick();
  page.state.context.local_review = false;
  await all(page.host).find((node) => node.textContent === "确认不收录").onclick();
  assert.equal(page.posts.length, 0);
});

test("switching knowledge bases releases a hidden opinion owner without losing its buffer", async () => {
  const page = await fixture();
  await page.reader.open(page.host, "drafts/a.md");
  await page.type("Opinion belongs to A");
  assert.ok(page.state.commentDraft);
  page.state.context = { ...page.state.context, knowledge_base: "/kb-B" };
  page.reader.close();
  assert.equal(page.state.commentDraft, null);
  page.state.context = { ...page.state.context, knowledge_base: "/kb-A" };
  page.reader.close();
  assert.equal(page.state.commentDraft, null);
  await page.reader.open(page.host, "drafts/a.md");
  assert.equal(page.text().value, "Opinion belongs to A");
  assert.ok(page.state.commentDraft);
});

test("an opinion can be discarded after its source fails to load", async () => {
  const page = await fixture((route) => {
    const path = new URL("http://local" + route).searchParams.get("path");
    if (path.startsWith("raw/")) throw Error("Source unavailable");
    return {
      ...response("/kb-A", path),
      sources: [{ path: "raw/source.md", title: "Source" }],
    };
  });
  await page.reader.open(page.host, "drafts/a.md");
  await page.type("Keep until discarded");
  all(page.host).find((node) => node.textContent === "Source").onclick();
  await new Promise(setImmediate);
  assert.ok(page.state.commentDraft);
  const discard = all(page.host).find((node) => node.textContent === "放弃未发送留言");
  assert.doesNotThrow(() => discard.onclick());
  assert.equal(page.state.commentDraft, null);
  assert.equal(discard.hidden, true);
});

for (const [processingStatus, label] of [
  ["partial", "提取状态 · 部分完成"],
  ["failed", "提取状态 · 失败"],
  ["skipped", "提取状态 · 已跳过"],
  ["complete", "提取完成"],
]) {
  test(`source extraction ${processingStatus} remains visible in its reading header`, async () => {
    const page = await fixture(() => ({
      ...response("/kb-A", "raw/source.md"),
      kind: "raw",
      review_status: undefined,
      processing_status: processingStatus,
    }));
    await page.reader.open(page.host, "raw/source.md");
    const labels = all(page.host.querySelector(".draft-reader-status"))
      .map((node) => node.textContent);
    assert.ok(labels.includes("来源资料"));
    assert.ok(labels.includes(label));
  });
}

test("same-library reconnect during a request releases loading and allows a fresh read", async () => {
  const first = deferred();
  const page = await fixture((route, count) =>
    count === 1 ? first.promise : undefined,
  );
  const opening = page.reader.open(page.host, "drafts/a.md");
  page.state.context = { ...page.state.context };
  first.resolve(response("/kb-A", "drafts/a.md"));
  await opening;
  await page.reader.refresh();
  assert.equal(page.reads.length, 2);
  assert.equal(page.text().disabled, false);
});

test("late reads cannot replace a newer selected draft or create a second polling loop", async () => {
  const first = deferred();
  const page = await fixture((route, count) =>
    count === 1 ? first.promise : undefined,
  );
  const opening = page.reader.open(page.host, "drafts/a.md");
  await page.reader.open(page.host, "drafts/b.md");
  first.resolve(response("/kb-A", "drafts/a.md"));
  await opening;
  assert.equal(page.host.querySelector("h2").textContent, "drafts/b.md");
  assert.equal(page.timers.size, 1);
  page.reader.close();
  assert.equal(page.timers.size, 0);
});

test("a failed send preserves the user's text and attachment for retry", async () => {
  const page = await fixture();
  await page.reader.open(page.host, "drafts/a.md");
  await page.type("Keep this opinion", true);
  page.api.error = "Connection failed";
  await page.send().onclick();
  await new Promise(setImmediate);
  assert.equal(page.text().value, "Keep this opinion");
  assert.equal(page.host.querySelector(".draft-uploads").children.length, 1);
  assert.equal(
    page.host.querySelector(".draft-feedback").textContent,
    "Connection failed",
  );
  assert.equal(page.state.saving, false);
  assert.equal(page.send().disabled, false);
});

test("a comment stays bound to the version the user read until explicitly rebound", async () => {
  let version = "v1";
  const page = await fixture(() => ({
    ...response("/kb-A", "drafts/a.md"),
    sha256: version,
  }));
  await page.reader.open(page.host, "drafts/a.md");
  await page.type("Opinion on version one");
  version = "v2";
  await page.reader.refresh();
  await page.send().onclick();
  assert.equal(page.posts.length, 0);
  assert.equal(page.text().value, "Opinion on version one");
  const rebind = all(page.host).find(
    (node) => node.textContent === "按当前版本发送",
  );
  assert.ok(rebind);
  rebind.onclick();
  await new Promise(setImmediate);
  assert.equal(page.posts[0].payload.expected_sha256, "v2");
});

test("a newly read revision invalidates an open Wiki promotion confirmation", async () => {
  let version = "v1";
  const page = await fixture(() => ({
    ...response("/kb-A", "drafts/a.md"),
    sha256: version,
  }));
  await page.reader.open(page.host, "drafts/a.md");
  all(page.host)
    .find((node) => node.textContent === "确认入库")
    .onclick();
  assert.ok(all(page.host).some((node) => node.textContent === "入库这份草稿"));
  version = "v2";
  await page.reader.refresh();
  assert.equal(
    all(page.host).some((node) => node.textContent === "入库这份草稿"),
    false,
  );
});

test("submission waits for selected images to finish reading", async () => {
  const page = await fixture();
  let finish;
  globalThis.FileReader = class {
    readAsDataURL() {
      finish = () => {
        this.result = "data:image/png;base64,YWJj";
        this.onload();
      };
    }
  };
  await page.reader.open(page.host, "drafts/a.md");
  const reading = page.type("Opinion with image", true);
  assert.equal(page.send().disabled, true);
  page.send().onclick();
  assert.equal(page.posts.length, 0);
  finish();
  await reading;
  assert.equal(page.send().disabled, false);
  page.send().onclick();
  await new Promise(setImmediate);
  assert.equal(page.posts[0].payload.images.length, 1);
});
