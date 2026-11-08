"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const { source, moduleUrl, Element } = require("./studio_test_helpers.cjs");
test("graph controls route zoom, display and partial force values and reset their defaults", async () => {
  const saved = global.document;
  global.document = {
    createElement: (tag) => new Element(tag),
    createElementNS: (_namespace, tag) => new Element(tag),
  };
  try {
    const calls = [];
    const actions = Object.fromEntries(
      ["zoom", "fit", "display", "physics"].map((name) => [
        name,
        (...args) => calls.push([name, ...args]),
      ]),
    );
    const { createGraphControls } = await import(
      moduleUrl(source("studio/graph-controls.js"))
    );
    const host = new Element("div");
    const controls = createGraphControls(host, actions);
    const walk = (element) => [element, ...element.children.flatMap(walk)];
    const all = walk(host);
    const find = (label) =>
      all.find((element) => element["aria-label"] === label);
    find("\u653e\u5927").onclick();
    find("\u7f29\u5c0f").onclick();
    find("\u9002\u5e94\u753b\u5e03").onclick();
    assert.deepEqual(calls.slice(0, 3), [
      ["zoom", 1.3],
      ["zoom", 1 / 1.3],
      ["fit"],
    ]);
    const labels = find("\u663e\u793a\u540d\u79f0");
    labels.checked = false;
    labels.oninput();
    assert.equal(calls.at(-1)[1].labels, false);
    const distance = find("\u8fde\u7ebf\u8ddd\u79bb");
    distance.value = "110";
    distance.oninput();
    assert.deepEqual(calls.at(-1), [
      "physics",
      { repel: 1000, linkDistance: 110, centering: 0.1 },
    ]);
    all
      .find((element) => element.textContent === "\u6062\u590d\u9ed8\u8ba4")
      .onclick();
    assert.equal(labels.checked, true);
    assert.equal(Number(distance.value), 250);
    assert.deepEqual(calls.at(-1), [
      "physics",
      { repel: 1000, linkDistance: 250, centering: 0.1 },
    ]);
    controls.destroy();
  } finally {
    if (saved === undefined) delete global.document;
    else global.document = saved;
  }
});
