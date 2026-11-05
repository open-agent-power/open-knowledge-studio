"use strict";
const { test, beforeEach, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const { source, moduleUrl, settle, deferred, Element } = require("./studio_test_helpers.cjs");
const sha = "a".repeat(64), nextSha = "b".repeat(64);
let previousDocument;
beforeEach(() => {
  previousDocument = globalThis.document;
  globalThis.document = {
    createElement: (tag) => new Element(tag),
    createTextNode: (text) => ({ textContent: text }),
  };
});
afterEach(() => { globalThis.document = previousDocument; });

function all(node) {
  return [node, ...(node.children?.flatMap(all) || [])];
}
function text(node) {
  return all(node).map((item) => item.textContent || item.innerHTML || "").join(" ");
}
function find(host, label) {
  return all(host).find((node) => node.tagName === "button" && node.textContent === label);
}
function draft(values = {}) {
  return {
    knowledge_base: "/kb", path: "drafts/one.md", sha256: sha,
    text: "---\ntitle: One\n---\nOriginal proposal", body_html: "<p>Original proposal</p>",
    review_status: "draft", ...values,
  };
}
async function fixture({ localReview = true, hook } = {}) {
  const module = source("studio/draft-review.js").replace(
    '"./dom.js"', JSON.stringify(moduleUrl(source("studio/dom.js"))),
  );
  const { createDraftReview } = await import(moduleUrl(module));
  const host = new Element("div"), calls = [], busy = [], decisions = [];
  let context = { knowledge_base: "/kb", local_edit: false, local_review: localReview };
  let current = draft();
  const history = new Map();
  const view = createDraftReview({
    getContext: () => context,
    onBusy: (value) => busy.push(value),
    onDecision: (decision) => decisions.push(decision),
    api: {
      async request(url, options) {
        calls.push({ url, options });
        const custom = hook?.(url, options);
        if (custom !== undefined) return custom;
        if (!options) {
          const revision = new URL("http://local" + url).searchParams.get("revision");
          return revision ? history.get(revision) : current;
        }
        const body = JSON.parse(options.body);
        assert.equal(body.expected_knowledge_base, context.knowledge_base);
        assert.equal(body.expected_sha256, current.sha256);
        const approved = url.endsWith("promote");
        current = { ...current, review_status: approved ? "promoted" : "rejected", original_available: true, snapshot_status: "preserved_original" };
        history.set(current.sha256, current);
        return { status: current.review_status };
      },
    },
  });
  return {
    view, host, calls, busy, decisions,
    context: (value) => { context = value; },
    current: (value) => { current = value; },
    render: (selection = { path: "drafts/one.md" }) => view.render(host, selection),
    confirm() {
      const checkbox = all(host).find((node) => node.tagName === "input");
      checkbox.checked = true;
      checkbox.onchange();
    },
  };
}

test("local-review approval uses explicit confirmation, captured instance and exact source SHA", async () => {
  const page = await fixture();
  await page.render();
  assert.equal(find(page.host, "加入知识库").disabled, true);
  await find(page.host, "加入知识库").onclick();
  assert.equal(page.calls.length, 1);
  page.confirm();
  assert.equal(find(page.host, "加入知识库").disabled, false);
  await find(page.host, "加入知识库").onclick();
  const sent = JSON.parse(page.calls[1].options.body);
  assert.equal(sent.confirm_review, true);
  assert.equal(sent.expected_sha256, sha);
  assert.equal(sent.expected_knowledge_base, "/kb");
  assert.ok(page.calls[2].url.includes("revision=" + sha));
  assert.deepEqual(page.busy, [true, false]);
  assert.equal(find(page.host, "加入知识库").disabled, true);
  assert.ok(text(page.host).includes("原始审核稿已保存"));
});

test("read-only and terminal states cannot approve or reject", async () => {
  const reader = await fixture({ localReview: false });
  await reader.render();
  reader.confirm();
  assert.equal(find(reader.host, "加入知识库").disabled, true);
  await find(reader.host, "不收录").onclick();
  assert.equal(reader.calls.length, 1);
  for (const status of ["promoted", "rejected", "not_proposed"]) {
    const page = await fixture();
    page.current(draft({ review_status: status }));
    await page.render();
    page.confirm();
    await find(page.host, "加入知识库").onclick();
    await find(page.host, "不收录").onclick();
    assert.equal(page.calls.length, 1);
  }
});

test("changed workflow sources remain visible without enabling decisions", async () => {
  const page = await fixture();
  page.current(draft({ workflow_context: { source_status: "changed", warning: "Source changed" } }));
  await page.render();
  page.confirm();
  assert.equal(find(page.host, "加入知识库").disabled, true);
  await find(page.host, "不收录").onclick();
  assert.equal(page.calls.length, 1);
  assert.ok(text(page.host).includes("Source changed"));
});

test("duplicate clicks share one write and destroying the view discards late completion", async () => {
  const pending = deferred();
  const page = await fixture({ hook: (url, options) => options ? pending.promise : undefined });
  await page.render();
  const reject = find(page.host, "不收录");
  const first = reject.onclick();
  await reject.onclick();
  assert.equal(page.calls.length, 2);
  assert.equal(find(page.host, "加入知识库").disabled, true);
  assert.deepEqual(page.busy, [true]);
  page.view.destroy();
  pending.resolve({ status: "rejected" });
  await first;
  assert.deepEqual(page.busy, [true, false]);
  assert.deepEqual(page.decisions, []);
});

test("destroyed or switched-instance responses do not replace the current view", async () => {
  const pending = deferred();
  const page = await fixture({ hook: () => pending.promise });
  const reading = page.render();
  page.view.destroy();
  pending.resolve(draft());
  await reading;
  assert.ok(!text(page.host).includes("Original proposal"));

  const wrong = await fixture({ hook: () => draft({ knowledge_base: "/other" }) });
  await wrong.render();
  assert.ok(text(wrong.host).includes("知识库已切换"));
  wrong.confirm();
  await find(wrong.host, "加入知识库").onclick();
  assert.equal(wrong.calls.length, 1);

  const switched = await fixture();
  await switched.render();
  switched.confirm();
  switched.context({ knowledge_base: "/other", local_review: true });
  await find(switched.host, "加入知识库").onclick();
  assert.equal(switched.calls.length, 1);
});

test("a late read cannot overwrite another selected Draft", async () => {
  const pending = deferred();
  const page = await fixture({ hook: (url) => {
    const path = new URL("http://local" + url).searchParams.get("path");
    return path === "drafts/one.md" ? pending.promise
      : draft({ path: "drafts/two.md", text: "Second proposal", body_html: "Second proposal" });
  } });
  const first = page.render();
  await page.render({ path: "drafts/two.md" });
  pending.resolve(draft());
  await first;
  assert.ok(text(page.host).includes("Second proposal"));
  assert.ok(!text(page.host).includes("Original proposal"));
});

test("new source content stays pending while the prior snapshot remains historical", async () => {
  const page = await fixture();
  await page.render();
  await find(page.host, "不收录").onclick();
  const sent = JSON.parse(page.calls[1].options.body);
  assert.equal(sent.confirm_reject, true);
  assert.ok(text(page.host).includes("已拒绝"));
  page.current(draft({ sha256: nextSha, text: "New proposal", body_html: "<p>New proposal</p>" }));
  await page.render();
  assert.equal(find(page.host, "不收录").disabled, false);
  assert.ok(text(page.host).includes("New proposal"));
  await page.render({ path: "drafts/one.md", revision: sha });
  assert.equal(find(page.host, "不收录").disabled, true);
  assert.ok(!text(page.host).includes("New proposal"));
});

test("a saved decision with an unavailable receipt cannot be submitted again", async () => {
  let saved = false;
  const page = await fixture({ hook: (url, options) => {
    if (options) { saved = true; return { status: "rejected" }; }
    if (saved) throw Error("Receipt unavailable");
  } });
  await page.render();
  await find(page.host, "不收录").onclick();
  assert.ok(text(page.host).includes("决定已保存"));
  await find(page.host, "不收录").onclick();
  assert.equal(page.calls.length, 3);
});

test("retained current-Wiki fallbacks are labelled separately from original review snapshots", async () => {
  const page = await fixture();
  page.current(draft({ review_status: "promoted", original_available: false, text_role: "current_wiki" }));
  await page.render();
  assert.ok(text(page.host).includes("当前知识原文与校验信息"));
  assert.ok(text(page.host).includes("原始审核稿未保存或无法校验"));
  assert.ok(!text(page.host).includes("字节校验一致"));
  await settle();
});

test("only an identical first body heading is removed while the exact original remains available", async () => {
  const createElement = document.createElement;
  for (const headingText of ["One", "Different title", "one"]) {
    let removed = false;
    const heading = new Element("h2");
    heading.textContent = headingText;
    heading.remove = () => {
      removed = true;
    };
    document.createElement = (tag) => {
      const node = createElement(tag);
      if (tag === "article") node.querySelector = () => heading;
      return node;
    };
    const page = await fixture();
    const original = `---\ntitle: One\n---\n## ${headingText}\nFull original`;
    page.current(draft({
      text: original,
      body_html: `<h2>${headingText}</h2><p>Full original</p>`,
    }));
    await page.render();
    assert.equal(removed, headingText === "One");
    assert.ok(all(page.host).some(
      (node) => node.tagName === "pre" && node.textContent === original,
    ));
    assert.ok(text(page.host).includes(sha));
  }
});
