import { createStudioState } from "./studio/state.js";
import { $, el, button } from "./studio/dom.js";
import { createStudioApi } from "./studio/api.js";
import { createDiscussionView } from "./studio/discussion.js";
import { createGoalsView } from "./studio/goals.js";
import { createLearningView } from "./studio/learning.js";
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
  };
  const discussionView = createDiscussionView({
    dom,
    state,
    actions,
    model: M,
  });
  const goalsView = createGoalsView({
    dom,
    state,
    actions,
    model: M,
  });
  const learningView = createLearningView({
    dom,
    state,
    actions,
    api,
  });
  const renderDiscussion = () => discussionView.render();
  const renderGoals = () => goalsView.render();
  const renderLearning = () => learningView.render();
  let scopesRequest = null,
    navigation = 0,
    listingTick = 0,
    refreshing = false;
  function updateRoute() {
    const p = new URLSearchParams({ tab: state.tab });
    if (state.scope) p.set("scope", state.scope);
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
    state.selected = params.get("file") || "";
    state.learn =
      params.get("view") ||
      { messages: "mail", agents: "members" }[raw] ||
      "graph";
  }
  async function loadScopes() {
    if (state.tab === "learning") return;
    const tab = state.tab,
      context = state.context;
    const kind = state.tab === "discuss" ? "discuss" : "goal";
    if (scopesRequest?.tab !== tab || scopesRequest?.context !== context)
      scopesRequest = {
        tab,
        context,
        promise: request("/api/studio/scopes?kind=" + kind),
      };
    const pending = scopesRequest;
    let data;
    try {
      data = await pending.promise;
    } finally {
      if (scopesRequest === pending) scopesRequest = null;
    }
    if (tab !== state.tab || context !== state.context) return;
    state.scopes = data.scopes;
    const select = $("scope");
    select.replaceChildren(new Option("选择日期 / 文件", ""));
    const groups = new Map();
    const files = data.scopes
      .flatMap((s) => s.files)
      .sort((a, b) => (b.date || "").localeCompare(a.date || ""));
    for (const file of files) {
      const date = file.date || "历史未归档";
      if (!groups.has(date)) {
        const group = el("optgroup");
        group.label = date;
        groups.set(date, group);
        select.append(group);
      }
      groups.get(date).append(new Option(file.title, file.path));
    }
    const valid =
      files.some((f) => f.path === state.scope) ||
      data.scopes.some((s) => s.path === state.scope);
    if (!valid) state.scope = files[0]?.path || "";
    if (valid && !files.some((f) => f.path === state.scope))
      select.append(new Option(state.scope, state.scope));
    select.value = state.scope;
    if (data.warnings.length) status(data.warnings.join("；"));
  }
  async function loadView(force = false) {
    if (state.tab === "learning") return;
    if (state.viewLoading && !force) return;
    if (!state.scope) {
      state.view = null;
      render();
      return;
    }
    const ticket = ++state.loading,
      at = state.scope,
      tab = state.tab,
      context = state.context;
    state.viewLoading = true;
    let next;
    try {
      next = await request(
        "/api/studio/view?" + new URLSearchParams({ scope: at }),
      );
    } finally {
      if (ticket === state.loading) state.viewLoading = false;
    }
    if (
      ticket !== state.loading ||
      at !== state.scope ||
      tab !== state.tab ||
      context !== state.context
    )
      return;
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
      render();
    }
    if (!state.settingsDirty && !state.dirty)
      status(next.warnings.length ? next.warnings.join("；") : "");
  }
  async function loadCurrent() {
    const current = ++navigation;
    state.loading++;
    state.viewLoading = false;
    listingTick = 0;
    if (state.tab === "learning") {
      if (!state.settingsDirty) render();
      return;
    }
    if (!state.dirty && !state.saving) await loadScopes();
    if (current === navigation) await loadView(true);
  }
  function render() {
    discussionView.destroy();
    learningView.destroy();
    document.querySelectorAll("[data-tab]").forEach((b) => {
      if (b.dataset.tab === state.tab) b.setAttribute("aria-current", "page");
      else b.removeAttribute("aria-current");
    });
    $("scopeBar").hidden = state.tab === "learning";
    $("scope").setAttribute(
      "aria-label",
      state.tab === "discuss" ? "讨论日期与文件" : "目标日期与文件",
    );
    $("newGoal").setAttribute(
      "aria-label",
      state.tab === "discuss" ? "新增讨论 Markdown" : "新增目标 Markdown",
    );
    $("newGoal").disabled = !writable();
    $("newGoal").title = writable() ? "新增 Markdown" : "只读模式";
    document.title =
      "OKS · " +
      { discuss: "讨论", goals: "目标", learning: "学习" }[state.tab];
    $("content").replaceChildren();
    updateRoute();
    if (state.tab === "learning") {
      renderLearning();
      return;
    }
    if (!state.view) {
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
    const knowledgeBase = state.context.knowledge_base;
    try {
      await post("/api/studio/file", {
        path: file.path,
        text,
        expected_sha256: file.sha256,
      });
      if (knowledgeBase !== state.context.knowledge_base) return;
      state.dirty = false;
      state.saving = false;
      await loadView(true);
      status("");
    } catch (e) {
      if (knowledgeBase !== state.context.knowledge_base) return;
      state.saving = false;
      state.dirty = true;
      status(e.message);
    }
  }
  function openNew() {
    if (!writable()) return;
    const now = new Date(),
      bucket = state.tab === "discuss" ? "discuss" : "goal";
    const date = [
      now.getFullYear(),
      String(now.getMonth() + 1).padStart(2, "0"),
      String(now.getDate()).padStart(2, "0"),
    ].join("/");
    const title = bucket === "discuss" ? "新讨论" : "新目标";
    $("newPath").value = `${bucket}/${date}/${title}.md`;
    $("newText").value =
      bucket === "discuss"
        ? `# ${title}\n\n## 人的判断\n\n## AI 理解\n\n## 待确认\n`
        : `# ${title}\n\n- [ ] 下一步\n`;
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
    const path = $("newPath").value.trim(),
      knowledgeBase = state.context.knowledge_base;
    try {
      await post("/api/studio/file", {
        path,
        text: $("newText").value,
        create: true,
        expected_sha256: null,
      });
      if (knowledgeBase !== state.context.knowledge_base) return;
      $("newDialog").close();
      state.selected = path;
      state.scope = path;
      state.tab = path.startsWith("discuss/") ? "discuss" : "goals";
      await loadCurrent();
    } catch (e) {
      $("newError").textContent = e.message;
    }
  };
  document.querySelectorAll("[data-tab]").forEach(
    (b) =>
      (b.onclick = async () => {
        if (!canLeave()) return;
        state.tab = b.dataset.tab;
        if (state.tab !== "learning") {
          state.scope = "";
          state.selected = "";
          state.view = null;
        }
        await loadCurrent();
      }),
  );
  $("scope").onchange = async (event) => {
    if (!canLeave()) {
      $("scope").value = state.scope;
      return;
    }
    state.scope = event.target.value;
    state.selected = "";
    state.view = null;
    try {
      await loadView(true);
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
    void loadCurrent().catch((e) => status(e.message));
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && state.tab !== "learning")
      void loadView().catch((e) => status(e.message));
  });
  document.addEventListener("oks:reconnected", async (event) => {
    state.context = event.detail.context;
    if (event.detail.changedRoot) {
      state.dirty = state.settingsDirty = state.saving = false;
      state.view = null;
      state.scope = state.selected = "";
    }
    await loadCurrent();
  });
  restore();
  void (async () => {
    state.context = await window.OksWorkspace.ready;
    if (!state.context) return;
    $("instance").textContent = state.context.knowledge_base
      .split(/[\\/]/)
      .pop();
    $("instance").title = state.context.knowledge_base;
    await loadCurrent();
  })().catch((e) => status(e.message));
  setInterval(() => {
    if (
      document.hidden ||
      !state.context ||
      state.tab === "learning" ||
      state.settingsDirty ||
      refreshing
    )
      return;
    refreshing = true;
    void (async () => {
      if (!state.dirty && !state.saving && ++listingTick % 5 === 0)
        await loadScopes();
      if (state.scope || state.view) await loadView();
    })()
      .catch((e) => status(e.message))
      .finally(() => {
        refreshing = false;
      });
  }, 2000);
})();
