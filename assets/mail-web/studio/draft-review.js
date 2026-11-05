import { el, button } from "./dom.js";

// Shared Draft decisions. Private feedback scopes remain owned by review.js.
export function createDraftReview({
  api, getContext, onBusy, onDecision, onState,
}) {
  let ticket = 0,
    pending = false,
    record = null;

  function destroy() {
    ticket++;
    record = null;
    if (pending) {
      pending = false;
      onBusy?.(false);
    }
  }

  async function render(host, { path, revision = null }) {
    destroy();
    const current = ticket,
      root = getContext()?.knowledge_base,
      shell = el("section", "draft-review"),
      content = el("div", "draft-review-content"),
      status = el("p", "draft-review-status"),
      controls = el("div", "draft-review-controls"),
      label = el("label", "draft-review-confirm"),
      confirm = el("input");
    confirm.type = "checkbox";
    confirm.setAttribute("aria-label", "确认已阅读全文并同意加入知识库");
    label.append(
      confirm,
      document.createTextNode("我已阅读草稿全文，确认内容可以加入知识库。"),
    );
    const approve = button("加入知识库", () => decide("promoted")),
      reject = button("不收录", () => decide("rejected"));
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    controls.append(label, approve, reject);
    shell.append(content, controls, status);
    host.replaceChildren(shell);
    const unchanged = () =>
      current === ticket && root === getContext()?.knowledge_base;
    const reviewable = () =>
      record?.review_status === "draft" &&
      (!record.workflow_context || record.workflow_context.source_status === "current");
    function updateControls() {
      const writable =
        unchanged() && getContext()?.local_review === true && reviewable();
      controls.hidden = !!record && record.review_status !== "draft";
      confirm.disabled = !writable || pending;
      approve.disabled = !writable || !confirm.checked || pending;
      reject.disabled = !writable || pending;
    }
    confirm.onchange = updateControls;

    async function load(selectedRevision) {
      const query = new URLSearchParams({ path, expected_knowledge_base: root });
      if (selectedRevision) query.set("revision", selectedRevision);
      const data = await api.request("/api/learning/draft?" + query);
      if (!unchanged()) return false;
      if (data.knowledge_base !== root)
        throw Error("知识库已切换，请重新连接后读取草稿");
      if (
        typeof data.text !== "string" ||
        !/^[0-9a-f]{64}$/.test(data.sha256) ||
        data.path !== path
      )
        throw Error("草稿无法完整读取，请核对路径后重试");
      record = data;
      confirm.checked = false;
      const title = renderContent(content, data);
      status.textContent = statusText(data, getContext()?.local_review === true);
      status.dataset.state = "";
      updateControls();
      onState?.({ ...data, title });
      return true;
    }

    async function decide(decision) {
      if (
        pending ||
        !unchanged() ||
        !reviewable() ||
        getContext()?.local_review !== true
      )
        return;
      if (decision === "promoted" && !confirm.checked) return;
      const selected = record,
        approved = decision === "promoted";
      pending = true;
      onBusy?.(true);
      updateControls();
      status.textContent = approved ? "正在加入知识库…" : "正在保存不收录决定…";
      status.dataset.state = "";
      let saved = false;
      try {
        await api.request(
          approved ? "/api/learning/promote" : "/api/learning/reject",
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              path: selected.path,
              expected_sha256: selected.sha256,
              expected_knowledge_base: root,
              ...(approved ? { confirm_review: true } : { confirm_reject: true }),
            }),
          },
        );
        if (!unchanged()) return;
        saved = true;
        record = { ...selected, review_status: decision };
        confirm.checked = false;
        // Read the decided revision even if another writer already made a new Draft.
        await load(selected.sha256);
      } catch (error) {
        if (unchanged()) {
          status.textContent = saved
            ? "决定已保存，审核记录暂时无法读取，请重新打开。" + error.message
            : error.message;
          status.dataset.state = "error";
        }
      } finally {
        if (current === ticket) {
          pending = false;
          onBusy?.(false);
          updateControls();
          if (saved && unchanged())
            onDecision?.({ path, revision: selected.sha256, status: decision });
        }
      }
    }

    updateControls();
    status.textContent = "正在读取完整草稿…";
    try {
      if (!root) throw Error("知识库尚未连接，请恢复连接后重试");
      await load(revision);
    } catch (error) {
      if (unchanged()) {
        status.textContent = error.message;
        status.dataset.state = "error";
      }
    }
  }

  return { render, destroy };
}

function statusText(data, localReview) {
  if (data.review_status === "promoted")
    return "已加入知识库。当前查看的是审核记录。";
  if (data.review_status === "rejected")
    return "本版本已拒绝，原稿保留供追溯。新内容需要重新审核。";
  if (data.review_status === "not_proposed")
    return "原记录没有学习建议，保留原文供回看。";
  if (data.workflow_context && data.workflow_context.source_status !== "current")
    return "依据已变化，请核对后重新提出建议。";
  return localReview
    ? "草稿已完整读取。请检查内容和来源，再勾选确认。"
    : "当前为只读模式，启用本地审核后可批准或拒绝。";
}

function link(text, href, className) {
  const node = el("a", className, text);
  node.href = href;
  return node;
}

function renderContent(host, data) {
  const raw = data.text.replace(/^\uFEFF/, ""),
    front = raw.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/),
    title = front?.[1].match(/^title:\s*(.+)$/m)?.[1].trim()
      .replace(/^(['"])(.*)\1$/, "$2") || "待审核草稿",
    reviewed = data.review_status === "promoted",
    heading = el("header"),
    body = el("article", "draft-review-body markdown-body"),
    integrity = el("details", "draft-review-integrity");
  heading.append(el("h2", null, title));
  if (typeof data.body_html === "string") body.innerHTML = data.body_html;
  else body.textContent = front ? raw.slice(front[0].length).trim() : raw;
  const firstHeading = body.querySelector("h1, h2, h3, h4, h5, h6");
  if (firstHeading?.textContent.trim() === title.trim()) firstHeading.remove();
  if (typeof data.evidence_html === "string") {
    const evidence = el("details"),
      reading = el("article", "draft-review-body markdown-body");
    reading.innerHTML = data.evidence_html;
    evidence.append(el("summary", null, "查看本次依据"), reading);
    body.append(evidence);
  }
  if (reviewed) {
    heading.append(el(
      "p", null,
      "已人工审核 · " + (data.reviewed_at
        ? new Date(data.reviewed_at).toLocaleString("zh-CN")
        : "时间未记录"),
    ));
    if (data.wiki_path)
      heading.append(link(
        "阅读已入库的知识",
        "/?panel=1#wiki-reader&path=" + encodeURIComponent(data.wiki_path),
      ));
    renderReuse(heading, data.reuse);
  }
  if (data.review_status === "rejected")
    heading.append(el("p", null, "这条建议已拒绝，原稿保留供追溯。"));
  if (data.review_status === "not_proposed")
    heading.append(el("p", null, "原记录明确表示没有学习建议。"));
  renderOrigins(
    heading, data.workflow_context, reviewed || data.review_status === "rejected",
  );
  integrity.append(
    el("summary", null, reviewed && !data.original_available
      ? "当前知识原文与校验信息" : "完整原文与来源校验"),
    el("p", null, data.path),
    el("code", null, data.sha256),
    el("pre", null, data.text),
  );
  if (reviewed) {
    const history = el("details"),
      notice = el("p", "draft-review-note", data.original_available
        ? "原始审核稿已保存，字节校验一致。"
        : "原始审核稿未保存或无法校验。下方内容为当前知识正文。");
    history.append(
      el("summary", null, data.original_available
        ? "查看审核时的完整提案" : "查看当前知识正文"),
      body,
    );
    host.replaceChildren(heading, notice, history, integrity);
  } else host.replaceChildren(heading, body, integrity);
  return title.replace(/^任务经验\s*·\s*/, "");
}

function renderOrigins(host, source, historical) {
  if (!source) return;
  if (source.task_id)
    host.append(link("查看本次目标", "/tasks?id=" + encodeURIComponent(source.task_id)));
  host.append(el("p", null, historical
    ? "以下链接追溯任务与产物，后续变化不改写原审核决定。"
    : source.source_status === "current"
      ? "任务依据与产物版本一致。" : source.warning || "来源已变化，请重新整理候选。"));
  for (const item of source.artifacts || []) {
    if (typeof item.path !== "string") continue;
    host.append(link(
      item.path.split("/").pop(),
      "/tasks?" + new URLSearchParams({ id: source.task_id, artifact: item.path }),
      "review-output",
    ));
  }
}

function renderReuse(host, reuse) {
  const section = el("section", "learning-followup");
  section.append(el("h3", null, "后续任务中的记录"));
  if (reuse?.status === "ok") {
    section.append(el("p", null, reuse.tasks.length
      ? `${reuse.tasks.length} 项后续任务 · ${reuse.read_count} 条读取 · ${reuse.citation_count} 份产物引用`
      : "尚未记录到其他任务读取这份知识。"));
    for (const item of reuse.tasks) {
      const row = el("p");
      row.append(
        link(item.title || item.task_id, "/tasks?id=" + encodeURIComponent(item.task_id)),
        document.createTextNode(` · 读取 ${item.read_count} 次 · 产物引用 ${item.citation_count} 份`),
      );
      section.append(row);
    }
    section.append(el("p", "draft-review-note", "仅统计当前知识版本保留的记录，引用不代表内容已验收。"));
  } else section.append(el("p", "draft-review-note", "后续使用记录暂时不可用。"));
  host.append(section);
}
