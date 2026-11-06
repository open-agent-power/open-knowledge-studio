import { createLibrariesView } from "./studio/libraries.js";
import { renderOnboarding } from "./studio/onboarding.js";
import { createStudioState } from "./studio/state.js";
import { $, el, button } from "./studio/dom.js";
import { createStudioApi } from "./studio/api.js";
import { createDiscussionView } from "./studio/discussion.js";
import { createGoalsView } from "./studio/goals.js";
import { createLearningView } from "./studio/learning.js";
import { createSettingsView } from "./studio/settings.js";
/* The Studio owns navigation and file selection. Existing feature pages own
   knowledge reading, review, execution records, versions and telemetry. */
(() => {
  const M = window.OksStudioModel;
  const state = createStudioState();
  const status = (text) => ($("status").textContent = text || "");
  const writable = () => state.context?.local_edit === true;
  const canLeave = () => {
    if (state.saving) {
      status("保存中…");
      return false;
    }
    if (state.dirty || state.settingsDirty) {
      status("请先保存修改");
      return false;
    }
    return true;
  };
  const api = createStudioApi(window.OksWorkspace, () => state.context);
  const { request, post } = api;
  const dom = { $, el, button };
  const actions = {
    canLeave,
    render,
    saveDocument,
    loadView,
    status,
    writable,
    scopeFile,
    inspect,
    navigate,
  };
  const librariesView = createLibrariesView({ dom, actions, api });
  $("instance").onclick = () => librariesView.open();
  const settingsView = createSettingsView({
    dom,
    state,
    actions,
    api,
  });
  const discussionView = createDiscussionView({
    dom,
    state,
    actions,
    model: M,
    api,
  });
  const goalsView = createGoalsView({
    dom,
    state,
    actions,
    model: M,
    api,
  });
  const learningView = createLearningView({
    dom,
    state,
    actions,
    api,
    settingsView,
  });
  const renderDiscussion = () => discussionView.render();
  const renderGoals = () => goalsView.render();
  const renderLearning = () => learningView.render();
  function localDate() {
    const n = new Date();
    return [
      n.getFullYear(),
      String(n.getMonth() + 1).padStart(2, "0"),
      String(n.getDate()).padStart(2, "0"),
    ].join("-");
  }
  function updateRoute() {
    const p = new URLSearchParams({ tab: state.tab });
    if (state.date) p.set("date", state.date);
    if (state.selected && state.tab === "goals") p.set("file", state.selected);
    if (state.tab === "learning") p.set("view", state.learn);
    history.replaceState(null, "", "#" + p);
  }
  function restore() {
    state.legacyPanelHash = null;
    const raw = location.hash.slice(1),
      params = new URLSearchParams(raw),
      name = raw.split("&")[0];
    if (
      !params.has("tab") &&
      (name.startsWith("wiki") ||
        ["collaboration", "messages", "agents"].includes(name) ||
        params.has("view"))
    ) {
      state.legacyPanelHash = raw;
      state.tab = "learning";
      // Legacy reader scope is a knowledge domain/tag, not a Goal path.
      state.scope = "";
      state.learn =
        name === "agents"
          ? "members"
          : ["collaboration", "messages"].includes(name)
            ? "mail"
            : "graph";
      return;
    }
    state.tab =
      params.get("tab") ||
      {
        wiki: "learning",
        "wiki-overview": "learning",
        messages: "learning",
        agents: "learning",
        goals: "goals",
      }[raw] ||
      "discuss";
    if (!["discuss", "goals", "learning"].includes(state.tab))
      state.tab = "discuss";
    state.scope = params.get("scope") || "";
    state.date =
      params.get("date") ||
      state.scope
        .match(/(\d{4})\/(\d{2})\/(\d{2})/)
        ?.slice(1)
        .join("-") ||
      state.date;
    state.selected = params.get("file") || "";
    state.learn =
      params.get("view") ||
      { messages: "mail", agents: "members" }[raw] ||
      "graph";
  }
  async function selectDate() {
    if (state.tab === "learning") {
      $("scope").value = state.date || (state.date = localDate());
      state.scope = "";
      return;
    }
    const kind = state.tab === "discuss" ? "discuss" : "goal";
    if (!state.date) state.date = localDate();
    $("scope").value = state.date;
    state.scope =
      (kind === "discuss" ? "profiles/discuss/" : "profiles/goals/") +
      state.date.replaceAll("-", "/");
  }
  async function loadView(force = false) {
    if (state.viewLoading && !force) return;
    if (!state.scope) {
      state.view = null;
      render();
      return;
    }
    const ticket = ++state.loading,
      at = state.scope;
    state.viewLoading = true;
    let next;
    try {
      next = await request(
        "/api/studio/view?" +
          new URLSearchParams({
            kind: state.tab === "discuss" ? "discuss" : "goal",
            date: state.date,
          }),
      );
    } finally {
      if (ticket === state.loading) state.viewLoading = false;
    }
    if (ticket !== state.loading || at !== state.scope) return;
    if (next.knowledge_base !== state.context.knowledge_base) {
      window.OksWorkspace.recovery();
      status("知识库已切换，请重新连接");
      return;
    }
    if ($("connectionRecovery")) $("connectionRecovery").hidden = true;
    if (state.dirty || state.saving) {
      if (state.view && next.version !== state.view.version)
        status("文件已有更新，请先保存或重新读取");
      return;
    }
    if (
      force ||
      !state.view ||
      state.view.version !== next.version ||
      state.view.scope !== next.scope
    ) {
      state.view = next;
      if (
        !state.view.files[state.selected] ||
        state.view.files[state.selected].kind !== "goal"
      )
        state.selected = state.view.entry;
      if (state.tab !== "learning") render();
    }
    if (!state.settingsDirty && !state.dirty)
      status(next.warnings.length ? next.warnings.join("；") : "");
  }
  async function navigate(tab) {
    if (!canLeave()) return;
    state.tab = tab;
    state.scope = "";
    state.selected = "";
    await selectDate();
    if (tab !== "learning") await loadView(true);
    else render();
  }
  function render() {
    discussionView.destroy();
    goalsView.destroy();
    learningView.destroy();
    document.querySelectorAll("[data-tab]").forEach((b) => {
      if (b.dataset.tab === state.tab) b.setAttribute("aria-current", "page");
      else b.removeAttribute("aria-current");
    });
    $("scopeBar").hidden = false;
    $("scope").setAttribute("aria-label", "日期");
    $("newGoal").setAttribute(
      "aria-label",
      state.tab === "discuss" ? "新增讨论 Markdown" : "新增目标 Markdown",
    );
    $("newGoal").hidden = state.tab !== "discuss";
    $("newGoal").disabled = !writable();
    $("newGoal").title = writable() ? "新增 Markdown" : "只读模式";
    document.title =
      "OKS · " +
      { discuss: "讨论", goals: "目标", learning: "学习" }[state.tab];
    $("content").replaceChildren();
    renderOnboarding({ dom, state, actions, api });
    updateRoute();
    if (state.tab === "learning") {
      renderLearning();
      return;
    }
    if (!state.view || (state.tab !== "goals" && !state.view.entries?.length)) {
      $("content").append(
        el("div", "empty", state.tab === "discuss" ? "暂无讨论" : "暂无目标"),
      );
      return;
    }
    if (state.tab === "discuss") renderDiscussion();
    else renderGoals();
  }
  function scopeFile(path) {
    if (state.view?.files[path]?.kind === "goal") {
      if (!canLeave()) return;
      state.selected = path;
      state.mode = "list";
      state.tab = "goals";
      render();
    } else void inspect(path);
  }
  async function inspect(path) {
    try {
      const item =
        state.view?.files[path] ||
        (await request("/api/studio/file?" + new URLSearchParams({ path })));
      $("fileTitle").textContent = path;
      $("fileText").textContent = item.text;
      $("fileDialog").showModal();
    } catch (e) {
      status(e.message);
    }
  }
  async function saveDocument(file, text) {
    if (state.saving) return;
    status("保存中…");
    state.saving = true;
    try {
      await post("/api/studio/file", {
        path: file.path,
        text,
        expected_sha256: file.sha256,
        actor: "studio-user",
      });
      state.dirty = false;
      state.saving = false;
      await loadView(true);
      status("");
    } catch (e) {
      state.saving = false;
      state.dirty = true;
      status(e.message);
    }
  }
  function openNew() {
    if (!writable()) return;
    const now = new Date(),
      bucket = state.tab === "discuss" ? "discuss" : "goals";
    const date = state.date.replaceAll("-", "/");
    const title = bucket === "discuss" ? "新讨论" : "新目标";
    $("newPath").value = title;
    $("newText").value =
      bucket === "discuss"
        ? `# ${title}\n\n## 人的判断\n\n## AI 理解\n\n## 待确认\n`
        : `---\ntype: goal\nstatus: active\n---\n\n# ${title}\n\n## [ ] 下一步\n`;
    $("newError").textContent = "";
    $("newDialog").showModal();
  }
  $("newGoal").onclick = () => {
    if (canLeave()) openNew();
  };
  $("closeNew").onclick = () => $("newDialog").close();
  $("closeFile").onclick = () => $("fileDialog").close();
  $("newForm").onsubmit = async (event) => {
    event.preventDefault();
    const title = $("newPath").value.trim();
    if (!title || /[/\\\r\n]/.test(title)) {
      $("newError").textContent = "标题不能含路径分隔符";
      return;
    }
    const path = `profiles/${state.tab === "discuss" ? "discuss" : "goals"}/${state.date.replaceAll("-", "/")}/${title}.md`;
    try {
      await post("/api/studio/file", {
        path,
        text: $("newText").value,
        create: true,
        expected_sha256: null,
      });
      $("newDialog").close();
      state.selected = path;
      state.scope = path;
      state.tab = path.startsWith("profiles/discuss/") ? "discuss" : "goals";
      await selectDate();
      await loadView(true);
    } catch (e) {
      $("newError").textContent = e.message;
    }
  };
  document.querySelectorAll("[data-tab]").forEach(
    (b) =>
      (b.onclick = () => {
        void navigate(b.dataset.tab).catch((e) => status(e.message));
      }),
  );
  $("scope").onchange = async (event) => {
    if (!canLeave()) {
      $("scope").value = state.date;
      return;
    }
    state.date = event.target.value;
    await selectDate();
    state.selected = "";
    state.view = null;
    try {
      if (state.tab === "learning") render();
      else await loadView(true);
    } catch (e) {
      status(e.message);
      render();
    }
  };
  window.addEventListener("beforeunload", (event) => {
    if (state.dirty || state.settingsDirty) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
  window.addEventListener("hashchange", () => {
    if (!canLeave()) {
      updateRoute();
      return;
    }
    restore();
    void (async () => {
      await selectDate();
      if (state.scope) await loadView(true);
      else render();
      if (state.tab === "learning") render();
    })().catch((e) => status(e.message));
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && state.tab !== "learning")
      void loadView().catch((e) => status(e.message));
  });
  document.addEventListener("oks:reconnected", async (event) => {
    state.context = event.detail.context;
    if (event.detail.changedRoot) {
      state.dirty = state.settingsDirty = false;
      state.view = null;
      state.scope = state.selected = "";
      await selectDate();
    }
    await loadView(true);
  });
  $("showGuide").onclick = async () => {
    if (!canLeave()) return;
    state.onboarding = writable()
      ? await post("/api/studio/onboarding", { action: "reset" })
      : {
          status: "not_started",
          steps: { discuss: false, goals: false, learning: false },
        };
    render();
  };
  restore();
  void (async () => {
    state.context = await window.OksWorkspace.ready;
    if (!state.context) return;
    $("instance").textContent = state.context.knowledge_base
      .split(/[\\/]/)
      .pop();
    $("instance").title = state.context.knowledge_base;
    state.onboarding = await request("/api/studio/onboarding");
    await selectDate();
    if (state.scope) await loadView(true);
    else render();
    if (state.tab === "learning") render();
  })().catch((e) => status(e.message));
  let listingTick = 0;
  setInterval(() => {
    if (document.hidden || state.settingsDirty) return;
    void (async () => {
      if (
        !state.dirty &&
        !state.saving &&
        (++listingTick % 5 === 0 || !state.scope)
      )
        await selectDate();
      if (state.scope) await loadView();
    })().catch((e) => status(e.message));
  }, 2000);
})();
