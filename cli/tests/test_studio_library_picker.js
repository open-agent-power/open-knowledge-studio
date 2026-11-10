"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const { source, moduleUrl, domFixture, deferred } = require("./studio_test_helpers.cjs");
const all = node => [node, ...node.children.flatMap(all)];
async function fixture(editable = true) {
  const dom = domFixture(), posts = [], errors = [];
  dom.$("libraryDialog").addEventListener = () => {};
  dom.$("libraryDialog").showModal = () => {};
  dom.$("libraryDialog").querySelectorAll = () => [...dom.ids.values()].flatMap(all);
  const current = { personal_path: "/knowledge/个人库", sources: [{ path: "/knowledge/团队库", revision: "HEAD" }], sources_version: "v1" };
  let result = { cancelled: false, path: "/knowledge/新的个人库" };
  const { createLibrariesView } = await import(moduleUrl(source("studio/libraries.js")));
  const view = createLibrariesView({ dom, actions: { canLeave: () => true, writable: () => editable, status: m => errors.push(m) },
    api: { request: async () => current, post: async (route, payload) => { posts.push({ route, payload }); return result; } } });
  await view.open();
  return { dom, posts, errors, setResult: value => result = value };
}
test("personal folder label follows typing and native selection fills without switching", async () => {
  const t = await fixture();
  assert.equal(t.dom.$("personalLibraryName").textContent, "个人库");
  t.dom.$("personalLibrary").value = "C:\\knowledge\\another\\";
  t.dom.$("personalLibrary").oninput();
  assert.equal(t.dom.$("personalLibraryName").textContent, "another");
  await t.dom.$("choosePersonalLibrary").onclick();
  assert.equal(t.dom.$("personalLibrary").value, "/knowledge/新的个人库");
  assert.equal(t.dom.$("personalLibraryName").textContent, "新的个人库");
  assert.deepEqual(t.posts.map(p => p.payload.action), ["choose_folder"]);
});
test("cancel preserves paths, and pending selection cannot open a second dialog", async () => {
  const t = await fixture();
  t.setResult({ cancelled: true, path: null });
  await t.dom.$("choosePersonalLibrary").onclick();
  assert.equal(t.dom.$("personalLibrary").value, "/knowledge/个人库");
  const pending = deferred(); t.setResult(pending.promise);
  const first = t.dom.$("choosePersonalLibrary").onclick();
  await t.dom.$("choosePersonalLibrary").onclick();
  assert.equal(t.posts.length, 2);
  pending.resolve({ cancelled: true }); await first;
  assert.equal(t.dom.$("closeLibraries").disabled, false);
});
test("team selection uses the same folder naming and reader mode cannot invoke a chooser", async () => {
  const t = await fixture();
  t.setResult({ cancelled: false, path: "/knowledge/新团队" });
  const pick = all(t.dom.$("teamLibraries")).find(n => n["aria-label"] === "选择团队 1 文件夹");
  await pick.onclick();
  assert.ok(all(t.dom.$("teamLibraries")).some(n => n.textContent === "新团队"));
  assert.ok(all(t.dom.$("teamLibraries")).some(n => n.value === "/knowledge/新团队"));
  const reader = await fixture(false);
  await reader.dom.$("choosePersonalLibrary").onclick();
  assert.equal(reader.posts.length, 0);
});
