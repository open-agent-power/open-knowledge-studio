// View module. State and side effects are supplied explicitly by the controller.
export function createGoalsView({ dom, state, actions, model: M }) {
  const { $, el, button } = dom;
  const { canLeave, render, saveDocument, loadView, status, writable } =
    actions;
  function renderGoals() {
    const layout = el("div", "goal-single"),
      doc = el("div", "document"),
      file =
        state.view.files[state.selected] || state.view.files[state.view.entry];
    layout.append(doc);
    doc.id = "goalDocument";
    doc.inert = state.saving;
    if (state.saving) doc.setAttribute("aria-busy", "true");
    const toolbar = el("div", "toolbar"),
      modes = el("div", "seg");
    for (const [id, label] of [
      ["list", "清单"],
      ["source", "原文"],
    ])
      modes.append(
        button(
          label,
          () => {
            if (!canLeave()) return;
            state.mode = id;
            render();
          },
          state.mode === id ? "active" : "",
        ),
      );
    toolbar.append(modes, el("span", "spacer"));
    if (!writable()) toolbar.append(el("span", "tiny", "只读"));
    const save = button(
      "保存",
      () => {
        const editor = $("editor");
        if (editor) void saveDocument(file, editor.value);
      },
      "soft",
    );
    save.disabled = !writable() || state.mode !== "source";
    if (state.mode === "source") toolbar.append(save);
    if (writable() && state.mode === "source")
      toolbar.append(
        button(
          "还原",
          () => {
            state.dirty = false;
            void loadView(true).catch((e) => status(e.message));
          },
          "soft",
        ),
      );
    doc.append(toolbar);
    const paper = el("div", "paper");
    doc.append(paper);
    if (state.mode === "source") {
      const editor = el("textarea");
      editor.id = "editor";
      editor.setAttribute("aria-label", "目标 Markdown");
      editor.value = file.text;
      editor.readOnly = !writable();
      editor.oninput = () => {
        state.dirty = true;
        status("未保存");
      };
      paper.append(editor);
    } else {
      let hidden = null;
      const rows = file.outline.filter((row) =>
        ["heading", "task"].includes(row.kind),
      );
      for (const row of rows) {
        if (hidden !== null) {
          if (["heading", "metadata"].includes(row.kind) && row.level <= hidden)
            hidden = null;
          else continue;
        }
        const level = Math.min(12, row.level),
          isTask = ["heading", "task"].includes(row.kind),
          n = el(
            "div",
            isTask
              ? "outline-row " + row.kind + (row.checked ? " done" : "")
              : "outline-note " + row.kind,
          );
        n.style.paddingLeft = 12 + (level - 1) * 17 + "px";
        if (isTask) {
          const children = rows.some((r) => r.parent === row.line);
          const fold = button(
            children ? (state.folds.has(row.line) ? "▸" : "▾") : "",
            () => {
              if (!canLeave()) return;
              state.folds.has(row.line)
                ? state.folds.delete(row.line)
                : state.folds.add(row.line);
              render();
            },
            "fold",
          );
          fold.disabled = !children;
          fold.setAttribute("aria-label", "展开或收起 " + row.text);
          const check = el("input");
          check.type = "checkbox";
          check.checked = row.checked;
          check.disabled = !writable();
          check.setAttribute("aria-label", "完成：" + row.text);
          check.onchange = () => {
            try {
              void saveDocument(file, M.toggle(file.text, row, check.checked));
            } catch (e) {
              status(e.message);
            }
          };
          const text = el("span", "outline-title", row.text);
          text.contentEditable = String(writable());
          text.setAttribute("role", "textbox");
          text.setAttribute("aria-label", "编辑：" + row.text);
          text.oninput = () => {
            state.dirty = true;
            status("未保存");
          };
          text.onblur = () => {
            if (state.saving) return;
            if (text.textContent !== row.text) {
              try {
                void saveDocument(
                  file,
                  M.rename(file.text, row, text.textContent),
                );
              } catch (e) {
                status(e.message);
              }
            } else {
              state.dirty = false;
              status("");
            }
          };
          n.append(fold, check, text);
          if (state.folds.has(row.line)) hidden = row.level;
        }
        paper.append(n);
      }
      if (writable()) {
        const form = el("form", "add-task"),
          input = el("input"),
          add = el("button", null, "＋");
        input.placeholder = "添加目标";
        input.setAttribute("aria-label", "新增清单项");
        input.required = true;
        add.type = "submit";
        form.append(input, add);
        form.onsubmit = (e) => {
          e.preventDefault();
          if (!canLeave()) return;
          if (input.value.trim())
            void saveDocument(
              file,
              file.text.trimEnd() + "\n\n- [ ] " + input.value.trim() + "\n",
            );
        };
        paper.append(form);
      }
    }
    paper.title = file.path;
    $("content").append(layout);
  }
  return { render: renderGoals };
}
