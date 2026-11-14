import { goalTree, drawMindmap } from "./mindmap.js";
import { createTimeline } from "./timeline.js";
export function createGoalsView({ dom, state, actions, model: M, api }) {
  const { $, el, button } = dom;
  let revision = null,
    day = "",
    destroyTimeline = () => {},
    initialized = false;
  let pendingAdd = null;
  let draftSaving = false,
    createGoal = () => {};
  const collapsed = new Set();
  let zoom = 1;
  function destroy() {
    destroyTimeline();
    destroyTimeline = () => {};
  }
  function readOnlyReason() {
    return revision
      ? "历史快照为只读，回到当前目标后可编辑"
      : "当前为只读模式，启用本地编辑后可新增或修改目标";
  }
  function startCreate() {
    if (!actions.canLeave()) return;
    if (revision || !actions.writable()) {
      actions.status(readOnlyReason());
      return;
    }
    if (state.mode !== "list") {
      state.mode = "list";
      render();
    }
    createGoal();
  }
  function render() {
    destroy();
    if (day !== state.date) {
      revision = null;
      day = state.date;
      collapsed.clear();
      initialized = false;
      pendingAdd = null;
    }
    const wrap = el("div", "goal-single"),
      toolbar = el("div", "toolbar"),
      stage = el("div", "mindmap-stage"),
      canvas = el("div", "mindmap-canvas"),
      panel = el("aside", "mindmap-editor");
    panel.hidden = true;
    stage.append(canvas, panel);
    const info = el("span", "tiny");
    for (const [id, title] of [
      ["list", "思维图"],
      ["source", "原文"],
    ])
      toolbar.append(
        button(
          title,
          () => {
            if (actions.canLeave()) {
              state.mode = id;
              actions.render();
            }
          },
          state.mode === id ? "active" : "",
        ),
      );
    const zoomOut = button("−", () => {
        if (!actions.canLeave()) return;
        zoom = Math.max(0.4, zoom - 0.1);
        paint();
      }),
      zoomIn = button("＋", () => {
        if (!actions.canLeave()) return;
        zoom = Math.min(2, zoom + 0.1);
        paint();
      });
    zoomOut.title = "缩小目标图";
    zoomOut.setAttribute("aria-label", "缩小目标图");
    zoomIn.title = "放大目标图";
    zoomIn.setAttribute("aria-label", "放大目标图");
    toolbar.append(info, el("span", "spacer"), zoomOut, zoomIn);
    wrap.append(toolbar, stage);
    $("content").append(wrap);
    const data = () => revision || state.view;
    function paint() {
      panel.hidden = true;
      info.textContent = revision
        ? "历史 · " +
          new Date(revision.revision.at).toLocaleTimeString([], {
            hour12: false,
          }) + " · 只读"
        : actions.writable() ? "" : readOnlyReason();
      const view = data();
      if (state.mode === "source") {
        const file = view.files[state.selected] || view.files[view.entry];
        if (!file) {
          canvas.replaceChildren();
          if (!revision && actions.writable())
            canvas.append(button("新建第一个目标", startCreate, "soft"));
          return;
        }
        const editor = el("textarea");
        editor.id = "editor";
        editor.value = file.text;
        editor.readOnly = !!revision || !actions.writable();
        editor.setAttribute("aria-label", "目标 Markdown");
        editor.oninput = () => {
          state.dirty = editor.value !== file.text;
        };
        const cancel = button("取消", () => {
          if (editor.readOnly || state.saving) return;
          editor.value = file.text;
          state.dirty = false;
          actions.status("");
          editor.focus();
        }, "soft");
        const save = button(
          "保存",
          async () => {
            if (editor.readOnly || state.saving) return;
            save.disabled = cancel.disabled = editor.readOnly = true;
            const saved = await actions.saveDocument(file, editor.value);
            if (saved) {
              paint();
            } else {
              save.disabled = cancel.disabled = editor.readOnly = false;
              editor.focus();
            }
          },
          "soft",
        );
        save.disabled = editor.readOnly;
        cancel.disabled = editor.readOnly;
        editor.onkeydown = (event) => {
          if (event.isComposing) return;
          if (event.key === "Escape") {
            event.preventDefault();
            cancel.onclick();
          } else if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
            event.preventDefault();
            return save.onclick();
          }
        };
        const controls = el("div", "goal-editor-actions");
        controls.append(save, cancel);
        canvas.replaceChildren(controls, editor);
        return;
      }
      const tree = goalTree(view, state.date);
      if (!initialized) {
        const fold = (n) => {
          if (n.children.length) collapsed.add(n.id);
          n.children.forEach(fold);
        };
        tree.children.forEach(fold);
        initialized = true;
      }
      drawMindmap({
        dom,
        host: canvas,
        tree,
        collapsed,
        zoom,
        onSelect: select,
        onAdd: !revision && actions.writable() ? startAdd : null,
        pendingAdd: !revision ? pendingAdd : null,
        onDraft: (title) => {
          if (pendingAdd) pendingAdd.title = title;
        },
        onCancel: cancelAdd,
        onCommit: commitChild,
      });
      if (!tree.children.length && !pendingAdd) {
        const empty = el("div", "goal-empty");
        empty.append(!revision && actions.writable()
          ? button("新建第一个目标", () => startAdd(tree), "soft")
          : el("p", null, revision ? "此版本没有目标" : "当天还没有目标"));
        canvas.append(empty);
      }
    }
    function cancelAdd() {
      if (draftSaving || state.saving) return;
      pendingAdd = null;
      state.dirty = false;
      actions.status("");
      paint();
    }
    function startAdd(node) {
      if (revision || !actions.writable()) {
        actions.status(readOnlyReason());
        return;
      }
      if (!actions.canLeave()) return;
      state.dirty = true;
      collapsed.delete(node.id);
      pendingAdd = { id: node.id, title: "" };
      paint();
    }
    async function commitChild(node, title) {
      if (revision || !actions.writable() || !pendingAdd || draftSaving || state.saving) return;
      const captured = pendingAdd;
      draftSaving = true;
      captured.saving = true;
      paint();
      if (!node.file) {
        state.saving = true;
        const path = `profiles/goals/${state.date.replaceAll("-", "/")}/${title}.md`;
        try {
          if (
            /[/\\:\r\n\0]/.test(title) ||
            new TextEncoder().encode(title).length > 240
          )
            throw Error("请使用较短的单行目标标题，不含路径分隔符");
          await api.post("/api/studio/file", {
            path,
            text: `---\ntype: goal\nstatus: active\n---\n\n# ${title}\n`,
            create: true,
            expected_sha256: null,
            actor: "studio-client",
          });
        } catch (error) {
          state.saving = draftSaving = captured.saving = false;
          state.dirty = true;
          pendingAdd = captured;
          actions.status(error.message);
          paint();
          return;
        }
        pendingAdd = null;
        state.saving = draftSaving = false;
        state.dirty = false;
        state.selected = state.scope = path;
        paint();
        try {
          await actions.loadView(true);
        } catch (error) {
          actions.status("目标已保存，刷新失败：" + error.message);
        }
      } else {
        const text = node.row
          ? M.addChild(node.file.text, node.row, title)
          : node.file.text.trimEnd() + "\n\n## [ ] " + title + "\n";
        const saved = await actions.saveDocument(node.file, text);
        draftSaving = captured.saving = false;
        pendingAdd = saved ? null : captured;
        actions.render();
      }
    }
    function select(node) {
      if (pendingAdd) {
        canvas.querySelector(".mindmap-inline-editor input")?.focus();
        return;
      }
      if (!actions.canLeave()) return;
      if (!node.file && !revision && actions.writable()) {
        startAdd(node);
        return;
      }
      panel.replaceChildren();
      panel.hidden = false;
      const returnFocus = document.activeElement;
      const cancelEdit = () => {
        if (state.saving) return;
        state.dirty = false;
        panel.hidden = true;
        actions.status("");
        returnFocus?.focus?.();
      };
      panel.append(
        button(
          "×",
          cancelEdit,
          "close-node",
        ),
      );
      if (!node.file) {
        panel.append(el("strong", null, node.title), el("p", "goal-readonly", readOnlyReason()));
        return;
      }
      state.selected = node.file.path;
      const input = el("input");
      input.value = node.title;
      input.setAttribute("aria-label", "节点标题");
      input.disabled = !!revision || !actions.writable() || !node.row;
      input.oninput = () => {
        state.dirty = input.value !== node.title;
      };
      const save = button(
        "保存",
        async () => {
          if (input.disabled || state.saving) return;
          if (!input.value.trim()) {
            actions.status("请输入目标标题");
            input.focus();
            return;
          }
          input.disabled = save.disabled = cancel.disabled = true;
          const saved = await actions.saveDocument(
            node.file,
            M.rename(node.file.text, node.row, input.value.trim()),
          );
          if (saved) {
            paint();
          } else {
            input.disabled = save.disabled = cancel.disabled = false;
            input.focus();
          }
        },
        "soft",
      );
      save.disabled = input.disabled || !node.row;
      const cancel = button("取消", cancelEdit, "soft");
      cancel.disabled = input.disabled;
      input.onkeydown = (event) => {
        if (event.isComposing && event.key === "Enter") {
          event.preventDefault();
        } else if (event.key === "Escape" && !event.isComposing) {
          event.preventDefault();
          cancelEdit();
        } else if (event.key === "Enter") {
          event.preventDefault();
          return save.onclick();
        }
      };
      panel.append(input, save, cancel);
      if (revision || !actions.writable()) panel.append(el("p", "goal-readonly", readOnlyReason()));
      if (!node.row) panel.append(button("编辑原文", () => {
        if (!actions.canLeave()) return;
        state.mode = "source";
        actions.render();
      }, "soft"));
      input.focus?.();
      if (node.row) {
        const label = el("label"),
          check = el("input");
        check.type = "checkbox";
        check.checked = !!node.checked;
        check.disabled = input.disabled;
        check.onchange = () => {
          if (!actions.canLeave()) {
            check.checked = !!node.checked;
            return;
          }
          return actions.saveDocument(
            node.file,
            M.toggle(node.file.text, node.row, check.checked),
          );
        };
        label.append(check, document.createTextNode("完成"));
        panel.append(label);
      }
      if (node.children.length)
        panel.append(
          button(
            collapsed.has(node.id) ? "展开" : "收起",
            () => {
              if (!actions.canLeave()) return;
              collapsed.has(node.id)
                ? collapsed.delete(node.id)
                : collapsed.add(node.id);
              paint();
            },
            "soft",
          ),
        );
      if (node.row && node.id !== node.file.path) {
        const remove = button(
          "删除分支",
          () =>
            actions.canLeave() &&
            actions.saveDocument(
              node.file,
              M.removeBranch(node.file.text, node.row),
            ),
          "soft",
        );
        remove.disabled = input.disabled;
        panel.append(remove);
      }
    }
    const timeline = createTimeline({
      dom,
      api,
      canLeave: actions.canLeave,
      events: state.view.timeline,
      selectedId: revision?.revision?.id,
      onSelect: (view) => {
        revision = view;
        paint();
      },
      onCurrent: () => {
        revision = null;
        paint();
      },
    });
    wrap.append(timeline.element);
    destroyTimeline = timeline.destroy;
    createGoal = () => startAdd(goalTree(data(), state.date));
    paint();
  }
  return { render, destroy, startCreate };
}
