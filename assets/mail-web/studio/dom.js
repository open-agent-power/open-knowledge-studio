// Shared safe DOM constructors. Source Markdown is always inserted as text.
export const $ = (id) => document.getElementById(id);
export function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}
export function button(text, action, cls = "") {
  const node = el("button", cls, text);
  node.type = "button";
  node.onclick = action;
  return node;
}
