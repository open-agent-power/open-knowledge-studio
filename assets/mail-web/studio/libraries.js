// Connection configuration belongs to the shell, not a fourth navigation tab.
export function createLibrariesView({ dom, actions, api }) {
  const { $, el, button } = dom;
  let current;
  let rows = [];
  let busy = false;
  const error = (message = "") => {
    $("libraryError").textContent = message;
  };
  function renderSources() {
    const list = $("teamLibraries");
    list.replaceChildren();
    rows.forEach((row, index) => {
      const line = el("div", "library-source");
      const folder = (value) =>
        value
          .trim()
          .replace(/[\\/]+$/, "")
          .split(/[\\/]/)
          .pop() || "团队知识库";
      const name = el("span", "library-folder", folder(row.path));
      name.title = folder(row.path);
      const path = el("input");
      path.value = row.path;
      path.placeholder = "目录路径";
      path.setAttribute("aria-label", `团队 ${index + 1} 路径`);
      path.oninput = () => {
        row.path = path.value;
        name.textContent = name.title = folder(row.path);
        remove.setAttribute("aria-label", `解除关联 ${folder(row.path)}`);
      };
      const remove = button("×", () => {
        rows.splice(index, 1);
        renderSources();
      });
      remove.setAttribute("aria-label", `解除关联 ${folder(row.path)}`);
      line.append(name, path, remove);
      list.append(line);
    });
  }
  async function save(payload) {
    if (busy || !actions.canLeave()) return;
    busy = true;
    error();
    $("libraryDialog")
      .querySelectorAll("button,input")
      .forEach((n) => {
        n.disabled = true;
      });
    try {
      await api.post("/api/studio/libraries", payload);
      // Discard all instance-bound caches and reconnect to the selected root.
      location.reload();
    } catch (e) {
      error(e.message);
    } finally {
      busy = false;
      $("libraryDialog")
        .querySelectorAll("button,input")
        .forEach((n) => {
          n.disabled = false;
        });
    }
  }
  $("libraryDialog").addEventListener("cancel", (event) => {
    if (busy) event.preventDefault();
  });
  $("closeLibraries").onclick = () => {
    if (!busy) $("libraryDialog").close();
  };
  $("switchLibrary").onclick = () =>
    save({ action: "switch", personal_path: $("personalLibrary").value });
  $("addTeamLibrary").onclick = () => {
    rows.push({ path: "", revision: "HEAD" });
    renderSources();
    $("teamLibraries")
      .lastElementChild?.querySelector('input[placeholder="目录路径"]')
      ?.focus();
  };
  $("saveTeamLibraries").onclick = () =>
    save({
      action: "sources",
      sources_version: current.sources_version,
      sources: rows.map((row) => ({
        path: row.path.trim(),
        revision: row.path === row.originalPath ? row.revision : "HEAD",
      })),
    });
  return {
    async open() {
      if (!actions.canLeave()) return;
      try {
        current = await api.request("/api/studio/libraries");
        $("personalLibrary").value = current.personal_path;
        rows = current.sources.map((row) => ({
          ...row,
          originalPath: row.path,
        }));
        renderSources();
        error();
        $("libraryDialog")
          .querySelectorAll("button,input")
          .forEach((n) => {
            n.disabled = !actions.writable();
          });
        $("closeLibraries").disabled = false;
        $("libraryDialog").showModal();
      } catch (e) {
        actions.status(e.message);
      }
    },
  };
}
