/* Pure document operations: source lines and explicit references remain authoritative. */
(function (root) {
  "use strict";
  function replaceLine(text, line, transform) {
    const parts = text.match(/[^\r\n]*(?:\r\n|\r|\n|$)/g) || [];
    if (!Number.isInteger(line) || line < 0 || line >= parts.length)
      throw Error("目标行已变化，请重新读取");
    const ending = parts[line].match(/(?:\r\n|\r|\n)$/)?.[0] || "";
    parts[line] =
      transform(parts[line].slice(0, ending ? -ending.length : undefined)) +
      ending;
    return parts.join("");
  }
  function toggle(text, row, checked) {
    if (!["heading", "task"].includes(row.kind)) throw Error("该记录不是目标");
    return replaceLine(text, row.line, (line) => {
      const pattern =
        row.kind === "heading"
          ? /^(#{1,6}\s+)(?:\[[ xX]\]\s*)?(.*)$/
          : /^(\s*[-*+]\s+)(?:\[[ xX]\]\s*)(.*)$/;
      const match = line.match(pattern);
      if (!match) throw Error("目标结构已变化，请重新读取");
      return match[1] + (checked ? "[x] " : "[ ] ") + match[2];
    });
  }
  function rename(text, row, title) {
    if (!title.trim() || /[\r\n]/.test(title)) throw Error("标题必须为一行");
    return replaceLine(text, row.line, (line) => {
      const pattern =
        row.kind === "heading"
          ? /^(#{1,6}\s+(?:\[[ xX]\]\s*)?).*$/
          : /^(\s*[-*+]\s+\[[ xX]\]\s*).*$/;
      if (!pattern.test(line)) throw Error("目标结构已变化，请重新读取");
      return line.replace(pattern, (_, prefix) => prefix + title.trim());
    });
  }
  function graph(view, expanded = false) {
    const nodes = view.nodes.map((n) => ({ ...n })),
      edges = view.edges.map((e) => ({ ...e }));
    if (expanded)
      for (const [path, file] of Object.entries(view.files)) {
        if (file.kind !== "goal") continue;
        const byLine = new Map();
        for (const row of file.outline) {
          if (
            !["heading", "task"].includes(row.kind) ||
            (row.kind === "heading" && row.level === 1)
          )
            continue;
          const id = path + "#line-" + row.line,
            parent = byLine.get(row.parent) || path;
          nodes.push({
            id,
            path,
            title: row.text,
            type: "todo",
            checked: row.checked,
            line: row.line,
          });
          edges.push({
            from: parent,
            to: id,
            type: "contains",
            origin: "markdown_structure",
            evidence: path,
          });
          byLine.set(row.line, id);
        }
      }
    return { nodes, edges };
  }
  const api = { replaceLine, toggle, rename, graph };
  root.OksStudioModel = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
