// A document reader with recorded history and one Mail conversation per Draft.
export function createDraftReader({
  dom,
  state,
  actions,
  api,
  onClose,
  onOpen,
  onChange,
}) {
  const { el, button } = dom;
  const buffers = new Map();
  const owner = Symbol("draft-reader-opinion");
  let host = null,
    path = "",
    data = null,
    serial = 0,
    timer = null,
    loading = false;
  let body,
    title,
    status,
    history,
    article,
    comments,
    composer,
    input,
    send,
    attach,
    uploads,
    feedback,
    discard,
    allowEdit;
  let diffOpen = false,
    backPath = "",
    busy = false,
    confirmDecision = "",
    returnFocus = null;
  const resultLabels = {
    updated: "已修改",
    answered: "已回复",
    needs_info: "需补充",
    failed: "处理失败",
  };
  const labels = {
    draft: "待审阅",
    promoted: "已入库",
    rejected: "不收录",
    not_proposed: "仅保留记录",
  };
  const stepStates = {
    partial: "部分完成",
    failed: "失败",
    skipped: "已跳过",
    running: "处理中",
    queued: "排队中",
    cancelled: "已取消",
  };
  const active = (ticket, at, context) =>
    serial === ticket && path === at && state.context === context;
  const buffer = () => {
    const key = JSON.stringify([state.context?.knowledge_base, path]);
    if (!buffers.has(key))
      buffers.set(key, {
        text: "",
        images: [],
        reading: 0,
        attachmentSerial: 0,
        allow_edit: false,
        sha256: null,
        anchor_id: null,
      });
    return buffers.get(key);
  };
  const ownsDraft = () => state.commentDraft === owner;
  function markDraft() {
    const root = state.context?.knowledge_base;
    const pending = [...buffers].some(
      ([key, draft]) =>
        JSON.parse(key)[0] === root &&
        Boolean(draft.text.trim() || draft.images.length || draft.reading),
    );
    if (pending && (!state.commentDraft || ownsDraft()))
      state.commentDraft = owner;
    else if (!pending && ownsDraft()) state.commentDraft = null;
  }
  function discardOpinion() {
    if (busy) return;
    const root = state.context?.knowledge_base;
    for (const [key, draft] of buffers) {
      if (JSON.parse(key)[0] !== root) continue;
      Object.assign(draft, {
        text: "",
        images: [],
        reading: 0,
        allow_edit: false,
        sha256: null,
        anchor_id: null,
      });
      draft.attachmentSerial++;
    }
    input.value = "";
    allowEdit.checked = false;
    feedback.textContent = "未发送留言已放弃。";
    markDraft();
    renderUploads();
    controls();
    renderStatus();
  }
  function bindDraft(draft) {
    if (!draft.sha256 && data) {
      draft.sha256 = data.sha256;
      draft.anchor_id = data.anchor_id;
    }
  }
  function changedDraft() {
    feedback.replaceChildren(
      el("span", null, "草稿已更新，你的留言仍保留。请核对当前正文。"),
      button(
        "按当前版本发送",
        () => {
          const draft = buffer();
          draft.sha256 = data.sha256;
          draft.anchor_id = data.anchor_id;
          void submit();
        },
        "draft-link",
      ),
    );
  }
  function close(restoreFocus = true) {
    serial++;
    clearTimeout(timer);
    timer = null;
    loading = false;
    host = null;
    path = "";
    data = null;
    if (ownsDraft()) markDraft();
    if (restoreFocus && returnFocus?.isConnected !== false)
      returnFocus?.focus?.();
  }
  function html(markup, className = "markdown-body") {
    const node = el("div", className);
    node.innerHTML = markup || ""; // Server-rendered and sanitized Markdown.
    return node;
  }
  function openSource(target) {
    if (busy) return;
    if (data?.kind === "drafts") backPath = path;
    const container = host;
    onOpen?.(target);
    void open(container, target, true);
  }
  function renderSteps() {
    const expanded = new Set(
      [...history.querySelectorAll("details[open]")].map(
        (item) => item.dataset.id,
      ),
    );
    history.replaceChildren();
    history.hidden = data.kind !== "drafts";
    if (history.hidden) return;
    history.append(el("h3", null, "处理经过"));
    if (!data.steps.length) {
      history.append(el("p", "draft-muted", "暂无处理记录"));
      return;
    }
    const list = el("ol", "draft-process");
    for (const step of data.steps) {
      const row = el("li"),
        detail = el("details"),
        summary = el("summary"),
        content = el("div", "draft-process-content");
      detail.dataset.id = step.id;
      detail.open = expanded.has(step.id);
      const actor = step.extractor?.tool || step.agent;
      summary.append(
        el(
          "span",
          "draft-process-title",
          step.kind === "extraction" ? "提取材料" : step.title,
        ),
      );
      if (actor && actor !== "unspecified")
        summary.append(
          el(
            "span",
            "draft-process-actor",
            actor + (step.simulated ? " · 模拟" : ""),
          ),
        );
      if (stepStates[step.status])
        summary.append(
          el("span", "draft-process-state", stepStates[step.status]),
        );
      if (step.at) {
        const time = el(
          "time",
          null,
          new Date(step.at).toLocaleTimeString("zh-CN", {
            hour: "2-digit",
            minute: "2-digit",
          }),
        );
        time.dateTime = step.at;
        time.title = new Date(step.at).toLocaleString("zh-CN");
        summary.append(time);
      }
      if (step.detail) content.append(el("p", null, step.detail));
      for (const [key, name] of [
        ["inputs", "用了什么"],
        ["outputs", "得到了什么"],
      ]) {
        const items = step[key] || [];
        if (!items.length) continue;
        content.append(el("h4", null, name));
        for (const item of items) {
          const part = el("details", "draft-artifact"),
            label = el("summary", null, item.title || item.path || item.uri);
          part.append(label);
          if (item.html) part.append(html(item.html));
          else if (item.text) part.append(el("pre", null, item.text));
          else
            part.append(
              el("p", "draft-muted", item.path || item.uri || "记录未保留正文"),
            );
          if (["changed", "unavailable"].includes(item.verification))
            part.append(
              el(
                "p",
                "draft-notice",
                item.verification === "changed"
                  ? "当前文件已与记录版本不同"
                  : "文件暂时无法读取",
              ),
            );
          content.append(part);
        }
      }
      detail.append(summary, content);
      row.append(detail);
      list.append(row);
    }
    history.append(list);
  }
  function renderComments() {
    const open = comments.querySelector("details")?.open;
    const rows = data.discussion?.comments || [];
    comments.replaceChildren();
    comments.hidden = data.kind !== "drafts";
    if (comments.hidden) return;
    const disclosure = el("details"),
      list = el("div", "draft-comment-list");
    disclosure.open = open ?? rows.length > 0;
    disclosure.append(
      el("summary", null, rows.length ? `留言 · ${rows.length}` : "留言"),
    );
    if (!rows.length) list.append(el("p", "draft-muted", "还没有留言"));
    for (const comment of rows) {
      const row = el("section", "draft-comment"),
        meta = el("div", "draft-comment-meta");
      const result = [...comment.replies]
        .reverse()
        .find((reply) => reply.result)?.result;
      const delivery =
        resultLabels[result?.status] ||
        (comment.replies.length
          ? "已回复"
          : comment.processing
            ? "处理中"
            : comment.received
              ? "已接收"
              : "等待 Agent 接收");
      meta.append(el("strong", null, "你"), el("span", null, delivery));
      row.append(meta, el("p", "draft-comment-text", comment.text));
      for (const image of comment.images || []) {
        const link = el("a"),
          img = el("img");
        link.href = image.url;
        link.target = "_blank";
        link.rel = "noopener";
        img.src = image.url;
        img.alt = image.name;
        link.append(img);
        row.append(link);
      }
      if (comment.source_sha256 !== data.sha256)
        row.append(el("span", "draft-muted", "针对先前版本的留言"));
      for (const reply of comment.replies) {
        const answer = el("div", "draft-reply");
        answer.append(
          el("strong", null, reply.from),
          el(
            "span",
            "draft-muted",
            resultLabels[reply.result?.status] || "已回复",
          ),
          el("p", "draft-comment-text", reply.result?.reply || reply.body),
        );
        row.append(answer);
      }
      list.append(row);
    }
    disclosure.append(list);
    comments.append(disclosure);
  }
  function agentId() {
    const discussion = data?.discussion;
    return discussion?.agent?.id || discussion?.agents?.[0]?.id || "";
  }
  function controls() {
    if (!input) return;
    markDraft();
    discard.hidden = !ownsDraft();
    discard.disabled = busy || Boolean(state.saving);
    if (!data) return;
    const writable =
      state.context?.local_edit === true && data.kind === "drafts";
    const blocked = busy || Boolean(state.saving);
    input.disabled = !writable || blocked;
    allowEdit.disabled = !writable || blocked;
    attach.disabled = !writable || blocked || buffer().reading > 0;
    send.disabled =
      !writable ||
      blocked ||
      buffer().reading > 0 ||
      !agentId() ||
      !(buffer().text.trim() || buffer().images.length) ||
      Boolean(state.commentDraft && !ownsDraft());
    for (const remove of uploads.querySelectorAll("button"))
      remove.disabled = blocked;
    composer.hidden = data.kind !== "drafts";
    const agent = data.discussion?.agent;
    const connection = composer.querySelector(".draft-agent-status");
    connection.textContent = !writable
      ? "当前服务未启用本地编辑，暂时无法留言。需使用 oks mail serve --local-edit 启用。"
      : agent?.connected
        ? {
            running: `${agent.label} 正在处理留言`,
            listening: `${agent.label} 已连接，等待留言`,
            stopped: `${agent.label} 会话已停止，留言将等待接手`,
            error: `${agent.label} 处理失败。${agent.error || "请检查 Agent 连接后重试。"}`,
          }[agent.state] || `${agent.label} 已连接`
        : agentId()
          ? "负责 Agent 未连接，留言将保存并等待接手"
          : "尚未登记负责 Agent，暂时无法发送留言";
    connection.title = agent?.error || "";
  }
  function renderUploads() {
    uploads.replaceChildren();
    for (const [index, image] of buffer().images.entries()) {
      const item = el("span", "draft-upload");
      item.append(
        el("span", null, image.name),
        button("移除", () => {
          buffer().images.splice(index, 1);
          renderUploads();
          controls();
          renderStatus();
        }),
      );
      uploads.append(item);
    }
  }
  async function addImages(event) {
    const files = [...event.target.files],
      draft = buffer();
    const imageTicket = draft.attachmentSerial;
    if (!files.length) return;
    const showing = () => host && buffer() === draft;
    bindDraft(draft);
    draft.reading++;
    controls();
    renderStatus();
    feedback.textContent = "正在读取图片…";
    try {
      if (files.length + draft.images.length > 2)
        throw Error("一次最多附两张图片");
      const images = [];
      for (const file of files) {
        if (
          !/^image\/(png|jpeg|gif|webp|bmp)$/.test(file.type) ||
          file.size > 4 * 1024 * 1024
        )
          throw Error("请选择 4 MiB 以内的 PNG、JPEG、GIF、WebP 或 BMP 图片");
        const encoded = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result).split(",")[1]);
          reader.onerror = () => reject(Error("图片读取失败，请重试"));
          reader.readAsDataURL(file);
        });
        images.push({ name: file.name, data_base64: encoded });
      }
      if (imageTicket !== draft.attachmentSerial) return;
      draft.images.push(...images);
      if (showing()) {
        renderUploads();
        feedback.textContent = "";
      }
    } catch (error) {
      if (showing()) feedback.textContent = error.message;
    } finally {
      if (imageTicket === draft.attachmentSerial) draft.reading--;
      event.target.value = "";
      markDraft();
      if (showing()) {
        controls();
        renderStatus();
      }
    }
  }
  async function submit() {
    if (busy || state.saving || send.disabled) return;
    const ticket = serial,
      at = path,
      context = state.context,
      draft = buffer();
    bindDraft(draft);
    if (draft.sha256 !== data.sha256) {
      changedDraft();
      return;
    }
    const savingOwner = {};
    busy = true;
    state.saving = savingOwner;
    controls();
    feedback.textContent = "发送中…";
    try {
      await api.post("/api/studio/discussion-comments", {
        path,
        expected_sha256: draft.sha256,
        anchor_id: draft.anchor_id,
        agent: agentId(),
        text: draft.text.trim(),
        images: draft.images,
        allow_edit: draft.allow_edit,
      });
      draft.text = "";
      draft.images = [];
      draft.sha256 = draft.anchor_id = null;
      draft.allow_edit = false;
      markDraft();
      if (!active(ticket, at, context)) return;
      input.value = "";
      allowEdit.checked = false;
      renderUploads();
      feedback.textContent = "留言已保存，等待 Agent 接收";
      await refresh();
      comments.querySelector("details").open = true;
      comments.scrollIntoView({ block: "nearest", behavior: "smooth" });
    } catch (error) {
      if (active(ticket, at, context)) {
        feedback.textContent = error.message;
        if (/Discussion changed/i.test(error.message)) await refresh();
      }
    } finally {
      busy = false;
      if (state.saving === savingOwner) state.saving = false;
      if (active(ticket, at, context)) {
        controls();
        renderStatus();
      }
    }
  }
  async function decide(decision) {
    if (
      busy ||
      state.saving ||
      state.commentDraft ||
      !reviewable() ||
      !["promoted", "rejected"].includes(decision) ||
      confirmDecision !== decision
    )
      return;
    const ticket = serial,
      at = path,
      context = state.context,
      savingOwner = {};
    busy = true;
    state.saving = savingOwner;
    renderStatus();
    controls();
    try {
      await api.request(
        decision === "promoted" ? "/api/learning/promote" : "/api/learning/reject",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            path,
            expected_sha256: data.sha256,
            expected_knowledge_base: context.knowledge_base,
            ...(decision === "promoted"
              ? { confirm_review: true }
              : { confirm_reject: true }),
          }),
        },
      );
      if (!active(ticket, at, context)) return;
      confirmDecision = "";
      feedback.textContent =
        decision === "promoted"
          ? "这份草稿已入库"
          : "已保存不收录决定，原稿与来源保留。";
      await refresh();
      onChange?.();
    } catch (error) {
      if (active(ticket, at, context)) feedback.textContent = error.message;
    } finally {
      busy = false;
      if (state.saving === savingOwner) state.saving = false;
      if (active(ticket, at, context)) {
        renderStatus();
        controls();
      }
    }
  }
  function reviewable() {
    return (
      data?.kind === "drafts" &&
      data.review_status === "draft" &&
      data.promotable &&
      state.context?.local_review === true &&
      (!data.workflow_context || data.workflow_context.source_status === "current")
    );
  }
  function renderStatus() {
    if (!data) return;
    status.replaceChildren(
      el("span", "draft-muted", labels[data.review_status] || "来源资料"),
    );
    if (data.kind !== "drafts") {
      if (data.processing_status)
        status.append(
          el(
            "span",
            "draft-muted",
            data.processing_status === "complete"
              ? "提取完成"
              : `提取状态 · ${stepStates[data.processing_status] || data.processing_status}`,
          ),
        );
      return;
    }
    if (data.changes)
      status.append(
        button(
          diffOpen ? "返回正文" : "查看修改",
          () => {
            diffOpen = !diffOpen;
            renderArticle();
            renderStatus();
          },
          "draft-link",
        ),
      );
    if (data.review_status === "promoted" && data.wiki_path) {
      const link = el("a", "draft-promote", "阅读 Wiki");
      link.href =
        "/wiki-page?" +
        new URLSearchParams({
          path: data.wiki_path,
          return_to: location.hash ? "/" + location.hash : "/",
        });
      status.append(link);
    } else if (data.review_status === "draft" && data.promotable) {
      const promoteButton = button(
        "确认入库",
        () => {
          confirmDecision = confirmDecision === "promoted" ? "" : "promoted";
          renderStatus();
        },
        "draft-promote draft-primary",
      );
      promoteButton.disabled =
        busy || Boolean(state.saving) || Boolean(state.commentDraft) || !reviewable();
      promoteButton.title = state.context?.local_review
        ? "仅入库这份草稿"
        : "当前未启用本地审核";
      const rejectButton = button(
        "不收录",
        () => {
          confirmDecision = confirmDecision === "rejected" ? "" : "rejected";
          renderStatus();
        },
        "draft-link",
      );
      rejectButton.disabled = promoteButton.disabled;
      status.append(promoteButton, rejectButton);
      if (state.commentDraft)
        status.append(
          el("span", "draft-muted", "请先发送或放弃未发送留言，再审核当前版本。"),
        );
      if (confirmDecision) {
        const decision = confirmDecision;
        const confirmation = el("div", "draft-promotion-confirm");
        const yes = button(
          busy
            ? "正在保存…"
            : confirmDecision === "promoted"
              ? "入库这份草稿"
              : "确认不收录",
          () => void decide(decision),
          "draft-primary",
        );
        yes.disabled = promoteButton.disabled;
        confirmation.append(
          el(
            "p",
            null,
            confirmDecision === "promoted"
              ? "已阅读全文与来源，确认将当前版本加入 Wiki。来源、留言与处理记录保留。"
              : "确认当前版本不收录到 Wiki，原稿、来源与处理记录保留。",
          ),
          yes,
          button("取消", () => {
            confirmDecision = "";
            renderStatus();
          }),
        );
        status.append(confirmation);
      }
    }
  }
  function renderArticle() {
    article.replaceChildren();
    if (diffOpen && data.changes) {
      article.append(
        el("h3", null, "最近一次修改"),
        el("pre", "draft-diff", data.changes),
      );
      return;
    }
    article.innerHTML = data.body_html;
    const first = article.firstElementChild;
    if (
      first &&
      /^H[1-6]$/.test(first.tagName) &&
      first.textContent.trim() === data.title.trim()
    )
      first.remove();
  }
  function paint() {
    const position = body.scrollTop;
    title.textContent = data.title.replace(/\.md$/i, "") + ".md";
    renderStatus();
    renderSteps();
    renderArticle();
    renderComments();
    controls();
    if (
      feedback.textContent === "留言已保存，等待 Agent 接收" &&
      data.discussion?.comments.at(-1)?.received
    )
      feedback.textContent = "";
    if (
      data.kind === "drafts" &&
      buffer().sha256 &&
      buffer().sha256 !== data.sha256 &&
      (buffer().text.trim() || buffer().images.length)
    )
      changedDraft();
    let sources = body.querySelector(".draft-sources");
    sources.replaceChildren();
    sources.hidden = !data.sources.length;
    if (data.sources.length)
      sources.append(el("span", "draft-muted", "引用来源"));
    for (const source of data.sources)
      sources.append(
        button(source.title, () => openSource(source.path), "draft-link"),
      );
    const warning = body.querySelector(".draft-warning");
    warning.replaceChildren();
    warning.hidden = !data.warnings.length;
    if (data.warnings.length) {
      warning.append(
        el("summary", null, "部分记录无法读取"),
        el("p", null, data.warnings.join("；")),
      );
    }
    body.scrollTop = position;
  }
  async function refresh() {
    if (!host || loading) return;
    const ticket = serial,
      at = path,
      context = state.context;
    loading = true;
    try {
      const next = await api.request(
        "/api/studio/draft-reader?" + new URLSearchParams({ path: at }),
      );
      if (!active(ticket, at, context)) return;
      if (next.knowledge_base !== context.knowledge_base)
        throw Error("知识库已切换，请重新打开");
      if (JSON.stringify(next) !== JSON.stringify(data)) {
        if (
          data &&
          (next.sha256 !== data.sha256 || next.review_status !== data.review_status)
        )
          confirmDecision = "";
        data = next;
        paint();
      }
    } catch (error) {
      if (active(ticket, at, context)) {
        feedback.textContent = error.message;
        if (!data)
          article.replaceChildren(
            el("p", null, "读取失败"),
            button("重新读取", () => void refresh()),
          );
      }
    } finally {
      if (serial === ticket && path === at && host) {
        loading = false;
        if (data) controls();
        clearTimeout(timer);
        timer = setTimeout(() => {
          if (!document.hidden) void refresh();
          else schedule();
        }, 3000);
      }
    }
  }
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(() => void refresh(), 3000);
  }
  async function open(container, relative, fromSource = false) {
    if (!fromSource) returnFocus = document.activeElement;
    close(false);
    host = container;
    path = relative;
    diffOpen = false;
    confirmDecision = "";
    if (!fromSource) backPath = "";
    host.replaceChildren();
    const header = el("header", "draft-reader-header"),
      heading = el("div", "draft-reader-title");
    title = el("h2", null, "正在读取…");
    const closeButton = button("关闭", () => onClose?.(), "draft-close");
    closeButton.setAttribute("aria-label", "关闭审阅侧栏");
    discard = button("放弃未发送留言", discardOpinion, "draft-link draft-discard");
    discard.hidden = !ownsDraft();
    heading.append(title, closeButton);
    status = el("div", "draft-reader-status");
    header.append(heading, status, discard);
    if (backPath)
      header.prepend(
        button(
          "返回草稿",
          () => {
            const target = backPath;
            backPath = "";
            openSource(target);
          },
          "draft-link draft-back",
        ),
      );
    body = el("div", "draft-reader-scroll");
    history = el("section", "draft-history");
    article = el("article", "draft-article markdown-body");
    comments = el("section", "draft-comments");
    body.append(
      el("div", "draft-sources"),
      history,
      el("details", "draft-warning"),
      article,
      comments,
    );
    composer = el("footer", "draft-composer");
    input = el("textarea");
    input.rows = 2;
    input.placeholder = "对这份草稿有什么意见？";
    input.setAttribute("aria-label", "给草稿留言");
    input.value = buffer().text;
    input.oninput = () => {
      const draft = buffer();
      draft.text = input.value;
      if (!draft.text && !draft.images.length)
        draft.sha256 = draft.anchor_id = null;
      else bindDraft(draft);
      controls();
      renderStatus();
    };
    uploads = el("div", "draft-uploads");
    const row = el("div", "draft-composer-actions"),
      picker = el("input");
    const permission = el("label", "draft-edit-permission");
    allowEdit = el("input");
    allowEdit.type = "checkbox";
    allowEdit.checked = buffer().allow_edit;
    allowEdit.onchange = () => {
      buffer().allow_edit = allowEdit.checked;
    };
    permission.append(allowEdit, el("span", null, "允许 Agent 修改这份草稿"));
    picker.type = "file";
    picker.accept = "image/png,image/jpeg,image/gif,image/webp,image/bmp";
    picker.multiple = true;
    picker.hidden = true;
    picker.onchange = addImages;
    attach = button("附图", () => picker.click(), "draft-link");
    send = button("留言", () => void submit(), "draft-primary");
    row.append(attach, el("span", "draft-agent-status"), send);
    feedback = el("p", "draft-feedback");
    feedback.setAttribute("role", "status");
    composer.append(input, uploads, permission, picker, row);
    host.append(header, body, feedback, composer);
    article.onclick = (event) => {
      const link = event.target.closest?.("a[href]");
      if (
        !link || event.ctrlKey || event.metaKey ||
        event.shiftKey || event.altKey || event.button
      )
        return;
      const url = new URL(link.getAttribute("href"), location.href);
      if (url.origin !== location.origin) return;
      const reference =
        new URLSearchParams(url.hash.slice(1)).get("entry") ||
        url.searchParams.get("path");
      const matches = data?.sources.filter(
        (item) =>
          item.path === reference || item.aliases?.includes(reference) ||
          (reference?.startsWith("capture-") && item.path.startsWith("raw/") &&
            item.path.split("/").at(-2) === reference),
      );
      if (!matches?.length) return;
      event.preventDefault();
      if (matches.length !== 1) {
        feedback.textContent = "此标识对应多个已引用来源，无法唯一定位。请从“引用来源”选择原文。";
        return;
      }
      openSource(matches[0].path);
    };
    host.onkeydown = (event) => {
      if (event.key === "Escape" && !busy) {
        event.stopPropagation();
        onClose?.();
      }
    };
    renderUploads();
    input.disabled = attach.disabled = send.disabled = true;
    composer.hidden = !path.startsWith("drafts/");
    closeButton.focus();
    await refresh();
  }
  return { open, close, refresh, ownsDraft };
}
