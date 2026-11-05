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

  function branchEnd(text, row) {
    const lines = text.match(/[^\r\n]*(?:\r\n|\r|\n|$)/g) || [];
    const following = [];
    let fence = false;
    for (let i = row.line + 1; i < lines.length; i++) {
      const line = lines[i];
      if (/^\s*(```|~~~)/.test(line)) {
        fence = !fence;
        continue;
      }
      if (fence) continue;
      const heading = line.match(/^(#{1,6})\s/);
      const task = line.match(/^(\s*)[-*+]\s+\[[ xX]\]/);
      if (row.kind === "heading" && heading && heading[1].length <= row.level)
        return i;
      if (
        row.kind === "task" &&
        (heading ||
          (task &&
            task[1].length <= (lines[row.line].match(/^\s*/)?.[0].length || 0)))
      )
        return i;
    }
    return lines.length;
  }
  function addChild(text, row, title) {
    if (!title.trim() || /[\r\n]/.test(title)) throw Error("标题必须为一行");
    const lines = text.match(/[^\r\n]*(?:\r\n|\r|\n|$)/g) || [];
    const end = branchEnd(text, row),
      newline = text.includes("\r\n") ? "\r\n" : "\n";
    const prefix =
      row.kind === "heading" && row.level < 6
        ? "#".repeat(row.level + 1) + " [ ] "
        : (lines[row.line].match(/^\s*/)?.[0] || "") + "  - [ ] ";
    if (end > 0 && !/[\r\n]$/.test(lines[end - 1])) lines[end - 1] += newline;
    lines.splice(end, 0, prefix + title.trim() + newline);
    return lines.join("");
  }
  function removeBranch(text, row) {
    const lines = text.match(/[^\r\n]*(?:\r\n|\r|\n|$)/g) || [];
    lines.splice(row.line, branchEnd(text, row) - row.line);
    return lines.join("");
  }
  const api = { replaceLine, toggle, rename, graph, addChild, removeBranch };
  root.OksStudioModel = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
