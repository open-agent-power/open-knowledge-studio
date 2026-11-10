import { goalTree, drawMindmap } from "./mindmap.js";
import { createTimeline } from "./timeline.js";
export function createGoalsView({ dom, state, actions, model: M, api }) {
  const { $, el, button } = dom;
  let revision = null,
    day = "",
    destroyTimeline = () => {},
    initialized = false;
  let pendingAdd = null;
  const collapsed = new Set();
  let zoom = 1;
  function destroy() {
    destroyTimeline();
    destroyTimeline = () => {};
  }
  function render() {
    destroy();
    if (day !== state.date) {
      revision = null;
      day = state.date;
      collapsed.clear();
      initialized = false;
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
    toolbar.append(
      info,
      el("span", "spacer"),
      button("−", () => {
        zoom = Math.max(0.4, zoom - 0.1);
        paint();
      }),
      button("＋", () => {
        zoom = Math.min(2, zoom + 0.1);
        paint();
      }),
    );
    wrap.append(toolbar, stage);
    $("content").append(wrap);
    const data = () => revision || state.view;
    function paint() {
      panel.hidden = true;
      info.textContent = revision
        ? "历史 · " +
          new Date(revision.revision.at).toLocaleTimeString([], {
            hour12: false,
          })
        : "";
      const view = data();
      if (state.mode === "source") {
        const file = view.files[state.selected] || view.files[view.entry];
        if (!file) {
          canvas.replaceChildren();
          return;
        }
        const editor = el("textarea");
        editor.id = "editor";
        editor.value = file.text;
        editor.readOnly = !!revision || !actions.writable();
        editor.setAttribute("aria-label", "目标 Markdown");
        editor.oninput = () => {
          state.dirty = true;
        };
        const save = button(
          "保存",
          () => actions.saveDocument(file, editor.value),
          "soft",
        );
        save.disabled = editor.readOnly;
        canvas.replaceChildren(save, editor);
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
        onCancel: () => {
          pendingAdd = null;
          state.dirty = false;
          actions.status("");
          paint();
        },
        onCommit: commitChild,
      });
    }
    function startAdd(node) {
      if (!actions.canLeave()) return;
      state.dirty = true;
      collapsed.delete(node.id);
      pendingAdd = { id: node.id, title: "" };
      paint();
    }
    async function commitChild(node, title) {
      if (revision || !actions.writable() || !pendingAdd) return;
      const captured = pendingAdd;
      pendingAdd = null;
      if (!node.file) {
        try {
          if (
            /[/\\:\r\n\0]/.test(title) ||
            new TextEncoder().encode(title).length > 240
          )
            throw Error("请使用较短的单行目标标题，不含路径分隔符");
          const path = `profiles/goals/${state.date.replaceAll("-", "/")}/${title}.md`;
          await api.post("/api/studio/file", {
            path,
            text: `---\ntype: goal\nstatus: active\n---\n\n# ${title}\n`,
            create: true,
            expected_sha256: null,
            actor: "studio-client",
          });
          state.dirty = false;
          state.selected = path;
          await actions.loadView(true);
        } catch (error) {
          state.dirty = true;
          pendingAdd = captured;
          actions.status(error.message);
        }
      } else {
        const text = node.row
          ? M.addChild(node.file.text, node.row, title)
          : node.file.text.trimEnd() + "\n\n## [ ] " + title + "\n";
        await actions.saveDocument(node.file, text);
        if (state.dirty) pendingAdd = captured;
      }
    }
    function select(node) {
      if (pendingAdd) {
        canvas.querySelector(".mindmap-inline-editor input")?.focus();
        return;
      }
      if (!actions.canLeave()) return;
      panel.replaceChildren();
      panel.hidden = false;
      panel.append(
        button(
          "×",
          () => {
            state.dirty = false;
            panel.hidden = true;
          },
          "close-node",
        ),
      );
      if (!node.file) {
        panel.append(el("strong", null, node.title));
        return;
      }
      state.selected = node.file.path;
      const input = el("input");
      input.value = node.title;
      input.setAttribute("aria-label", "节点标题");
      input.disabled = !!revision || !actions.writable();
      input.oninput = () => {
        state.dirty = input.value !== node.title;
      };
      const save = button(
        "保存",
        () => {
          if (node.row)
            void actions.saveDocument(
              node.file,
              M.rename(node.file.text, node.row, input.value),
            );
        },
        "soft",
      );
      save.disabled = input.disabled || !node.row;
      panel.append(input, save);
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
    paint();
  }
  return { render, destroy };
}
