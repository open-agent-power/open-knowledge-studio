"use strict";
const fs = require("node:fs");
const path = require("node:path");
const root = path.join(__dirname, "../../assets/mail-web");
const source = (name) => fs.readFileSync(path.join(root, name), "utf8");
const moduleUrl = (text) =>
  "data:text/javascript;base64," + Buffer.from(text).toString("base64");
const settle = () => new Promise((resolve) => setImmediate(resolve));
function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
class Element {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.dataset = {};
    this.style = { setProperty(key, value) { this[key] = value; } };
    this.classList = { add() {} };
    this.value = "";
  }
  append(...children) {
    this.children.push(...children);
  }
  replaceChildren(...children) {
    this.children = children;
  }
  setAttribute(key, value) {
    this[key] = value;
  }
  removeAttribute(key) {
    delete this[key];
  }
  querySelectorAll() {
    return [];
  }
  querySelector() {
    return null;
  }
  remove() {}
}
function domFixture() {
  const ids = new Map();
  const $ = (id) => {
    if (!ids.has(id)) ids.set(id, new Element("div"));
    return ids.get(id);
  };
  return {
    $,
    ids,
    el: (tag, className, text) =>
      Object.assign(new Element(tag), { className, textContent: text }),
    button: (text, onclick) =>
      Object.assign(new Element("button"), { textContent: text, onclick }),
  };
}

module.exports = { source, moduleUrl, settle, deferred, Element, domFixture };
