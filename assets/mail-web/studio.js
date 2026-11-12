import { createLibrariesView } from "./studio/libraries.js";
import { renderOnboarding } from "./studio/onboarding.js";
import { createStudioState, shiftDate } from "./studio/state.js";
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
    if (state.commentDraft) {
      status("请先发送或放弃未发送留言");
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
    updateRoute,
    setDiscussionMode,
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
    if (state.tab === "discuss") {
      if (state.discuss === "history") p.set("view", "history");
      if (state.discuss === "graph" && state.scope) p.set("scope", state.scope);
    }
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
    state.discuss = params.get("view") === "history" ? "history" : "graph";
    state.date =
      params.get("date") ||
      state.scope
        .match(/(\d{4})\/(\d{2})\/(\d{2})/)
        ?.slice(1)
        .join("-") ||
      state.date;
    state.selected = params.get("file") || "";
    if (state.tab === "learning")
      state.learn = params.get("view") ||
        { messages: "mail", agents: "members" }[raw] || "graph";
  }
  async function selectDate() {
    if (state.tab === "discuss" && state.discuss === "graph") {
      if (!state.date) state.date = localDate();
      if (state.scope && !state.scope.startsWith("drafts/") && !state.scope.startsWith("raw/"))
        state.scope = "";
      return;
    }
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
    if (!state.scope && !(state.tab === "discuss" && state.discuss === "graph")) {
      state.view = null;
      render();
      return;
    }
    const ticket = ++state.loading,
      at = state.scope,
      tab = state.tab,
      date = state.date,
      discuss = state.discuss,
      context = state.context;
    const current = () => ticket === state.loading && at === state.scope &&
      tab === state.tab && date === state.date && discuss === state.discuss &&
      context === state.context;
    state.viewLoading = true;
    let next;
    try {
      next = await request(
        tab === "discuss" && discuss === "graph" ? "/api/studio/drafts" :
        "/api/studio/view?" +
          new URLSearchParams({
            kind: state.tab === "discuss" ? "discuss" : "goal",
            date: state.date,
          }),
      );
    } finally {
      if (ticket === state.loading) state.viewLoading = false;
    }
    if (!current()) return;
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
      const updateDiscussion = tab === "discuss" && discuss === "graph" &&
        state.view?.scope === next.scope;
      state.view = next;
      if (
        !state.view.files?.[state.selected] ||
        state.view.files[state.selected].kind !== "goal"
      )
        state.selected = state.view.entry;
      if (updateDiscussion && discussionView.update()) updateRoute();
      else if (state.tab !== "learning") render();
    }
    if (!state.settingsDirty && !state.dirty)
      status(next.warnings?.length ? next.warnings.join("；") : "");
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
  async function setDiscussionMode(mode) {
    if (!canLeave() || state.discuss === mode) return;
    state.discuss = mode;
    state.scope = state.selected = "";
    state.view = null;
    await selectDate();
    await loadView(true);
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
    const dated = state.tab === "goals" ||
      (state.tab === "discuss" && state.discuss === "history");
    $("scope").hidden = !dated;
    document.querySelector('label[for="scope"]').hidden = !dated;
    $("scope").setAttribute("aria-label", "日期");
    $("newGoal").setAttribute(
      "aria-label",
      state.tab === "discuss" ? "新增讨论 Markdown" : "新增目标 Markdown",
    );
    $("newGoal").hidden = state.tab !== "discuss";
    $("newGoal").disabled = !writable();
    $("newGoal").title = writable() ? "当天新增讨论文件（同一天可有多个主题）" : "只读模式";
    $("previousDay").hidden = $("nextDay").hidden = state.tab === "learning";
    document.title =
      "OKS · " +
      { discuss: "讨论", goals: "目标", learning: "学习" }[state.tab];
    if (!writable()) $("newGoal").title = "当前只读，请使用启用本地编辑的连接";
    if (state.tab === "discuss")
      $("previousDay").hidden = $("nextDay").hidden = state.discuss !== "history";
    $("content").replaceChildren();
    renderOnboarding({ dom, state, actions, api });
    updateRoute();
    if (state.tab === "learning") {
      renderLearning();
      return;
    }
    if (state.tab === "discuss") {
      const tabs = el("div", "discussion-view-tabs");
      for (const [mode, label] of [["graph", "待审草稿"], ["history", "讨论记录"]]) {
        const tab = button(label, () => {
          void setDiscussionMode(mode).catch((e) => status(e.message));
        });
        tab.setAttribute("aria-pressed", String(state.discuss === mode));
        tabs.append(tab);
      }
      $("content").append(tabs);
    }
    if (!state.view || (state.tab === "discuss" && state.discuss === "history" && !state.view.entries?.length)) {
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
  const closeNew = () => { if (!state.saving) $("newDialog").close(); };
  $("closeNew").onclick = closeNew;
  $("cancelNew").onclick = closeNew;
  $("newDialog").oncancel = (event) => { if (state.saving) event.preventDefault(); };
  $("closeFile").onclick = () => $("fileDialog").close();
  $("newForm").onsubmit = async (event) => {
    event.preventDefault();
    if (state.saving || !writable()) return;
    const title = $("newPath").value.trim();
    if (!title || /[/\\\r\n]/.test(title)) {
      $("newError").textContent = "标题不能含路径分隔符";
      return;
    }
    const path = `profiles/${state.tab === "discuss" ? "discuss" : "goals"}/${state.date.replaceAll("-", "/")}/${title}.md`;
    state.saving = true;
    $("createNew").disabled = true;
    $("cancelNew").disabled = true;
    $("closeNew").disabled = true;
    let committed = false;
    try {
      await post("/api/studio/file", {
        path,
        text: $("newText").value,
        create: true,
        expected_sha256: null,
      });
      committed = true;
      $("newDialog").close();
      state.selected = path;
      state.scope = path;
      state.tab = path.startsWith("profiles/discuss/") ? "discuss" : "goals";
      if (state.tab === "discuss") state.discuss = "history";
      await selectDate();
      state.saving = false;
      await loadView(true);
    } catch (e) {
      if (committed) status("已保存，刷新失败：" + e.message);
      else $("newError").textContent = e.message;
    } finally {
      state.saving = false;
      $("createNew").disabled = false;
      $("cancelNew").disabled = false;
      $("closeNew").disabled = false;
    }
  };
  document.querySelectorAll("[data-tab]").forEach(
    (b) =>
      (b.onclick = () => {
        void navigate(b.dataset.tab).catch((e) => status(e.message));
      }),
  );
  async function changeDate(date) {
    if (!canLeave()) { $("scope").value = state.date; return; }
    if (!date) { $("scope").value = state.date; return; }
    state.date = date;
    await selectDate();
    state.selected = "";
    state.view = null;
    try {
      if (state.tab === "learning") render();
      else await loadView(true);
    } catch (e) { status(e.message); render(); }
  }
  $("scope").onchange = event => { void changeDate(event.target.value); };
  for (const [id, step] of [["previousDay", -1], ["nextDay", 1]]) {
    $(id).onclick = () => { void changeDate(shiftDate(state.date || localDate(), step)); };
  }
  window.addEventListener("beforeunload", (event) => {
    if (state.dirty || state.settingsDirty) {
      event.preventDefault();
      event.returnValue = "";
    }
    if (state.commentDraft) {
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
      if (state.scope || (state.tab === "discuss" && state.discuss === "graph"))
        await loadView(true);
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
      state.commentDraft = null;
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
    if (state.scope || (state.tab === "discuss" && state.discuss === "graph")) await loadView(true);
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
      if (state.scope || (state.tab === "discuss" && state.discuss === "graph")) await loadView();
    })().catch((e) => status(e.message));
  }, 2000);
})();
