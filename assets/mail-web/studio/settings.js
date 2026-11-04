import { memoryScore, budgetCap, changeLabel } from "./formulas.js";

export function createSettingsView({ dom, state, actions, api }) {
  const { $, el, button } = dom;
  const { writable, status, render } = actions;
  const { request, post } = api;
  const names = {
    search_backend: "检索算法",
    recall_topn: "召回数量",
    recall_floor: "相关性阈值",
    recall_minlen: "最短查询",
    recall_cooldown: "冷却秒数",
    embedding_fallback: "向量补召回",
    inject_budget_chars: "总字符预算",
    inject_per_page_chars: "每页字符预算",
    inject_title_only_floor: "仅标题阈值",
    posttool_mode: "工具后提醒",
    posttool_signal_rel_floor: "提醒阈值",
    conflict_window: "冲突窗口秒数",
    mail_topn: "交接条数",
    debug_record: "诊断记录",
    memory_validity: "知识有效性",
  };
  function formula(tex) {
    const node = el("div", "algorithm-formula");
    node.title = tex;
    if (window.katex)
      window.katex.render(tex, node, {
        displayMode: true,
        throwOnError: false,
        trust: false,
      });
    else node.textContent = tex;
    return node;
  }
  function card(title, tex) {
    const section = el("section", "algorithm-card");
    section.append(el("h2", null, title));
    if (tex) section.append(formula(tex));
    return section;
  }
  function decayPreview(data) {
    const section = card(
      "Memory Curve · 预览",
      String.raw`S=\left(Ie^{-\lambda t}+0.5\ln(1+a)+b_{pin}\right)c_{active}`,
    );
    section.append(
      el(
        "small",
        "formula-note",
        "λ 固定 · 仅预览",
      ),
    );
    const controls = {};
    for (const [key, title, type, value, max] of [
      ["kind", "类型", "select", "strategy", 0],
      ["importance", "重要度", "range", 0.7, 1],
      ["days", "天数", "range", 30, 365],
      ["access", "引用次数", "range", 0, 100],
    ]) {
      const row = el("label", "param-row"),
        input = el(type === "select" ? "select" : "input"),
        out = el("output");
      input.setAttribute("aria-label", title + "预览");
      if (type === "select")
        for (const kind of Object.keys(data.fixed.decay_lambda))
          input.append(new Option(kind, kind));
      else {
        input.type = type;
        input.min = 0;
        input.max = max;
        input.step = key === "importance" ? 0.05 : 1;
      }
      input.value = value;
      controls[key] = input;
      row.append(el("span", null, title), input, out);
      section.append(row);
      input.oninput = () => {
        out.value = input.value;
        draw();
      };
      out.value = value;
    }
    const result = el("div", "formula-result"),
      plot = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    plot.setAttribute("viewBox", "0 0 500 130");
    plot.classList.add("formula-plot");
    plot.setAttribute("role", "img");
    plot.setAttribute("aria-label", "零至365天的衰减分数");
    const curve = document.createElementNS(plot.namespaceURI, "polyline");
    plot.append(curve);
    section.append(
      result,
      plot,
      el("small", "formula-note", "0 → 365 天 · active，未置顶"),
    );
    function draw() {
      const input = {
        importance: Number(controls.importance.value),
        lambda: data.fixed.decay_lambda[controls.kind.value],
        days: Number(controls.days.value),
        access: Number(controls.access.value),
      };
      const today = memoryScore(input),
        next = memoryScore({ ...input, days: input.days + 30 });
      result.textContent = `S = ${today.toFixed(3)}  ·  30 天后 ${next.toFixed(3)}  ${changeLabel(today, next)}  ·  λ = ${input.lambda}`;
      const max = Math.max(memoryScore({ ...input, days: 0 }), 0.01);
      curve.setAttribute(
        "points",
        Array.from({ length: 74 }, (_, i) => {
          const days = i * 5;
          return `${10 + (days / 365) * 480},${115 - (memoryScore({ ...input, days }) / max) * 105}`;
        }).join(" "),
      );
    }
    draw();
    return section;
  }
  async function renderSettings() {
    try {
      const data = await request("/api/studio/settings");
      if (state.tab !== "learning" || state.learn !== "settings") return;
      state.settingsDirty = false;
      const form = el("form", "algorithm-settings"),
        inputs = {},
        changes = {};
      function parameter(section, key) {
        const value = data.values[key],
          row = el("label", "param-row"),
          name = el("span", null, names[key]);
        name.title = key;
        let input;
        if (
          ["memory_validity", "posttool_mode", "search_backend"].includes(key)
        ) {
          input = el("select");
          const options =
            key === "memory_validity"
              ? ["shadow", "enforce"]
              : key === "posttool_mode"
                ? ["signal", "full"]
                : ["native", "fts5", "fusion", "code"];
          if (!options.includes(value)) options.push(value);
          for (const option of options)
            input.append(new Option(option, option));
          input.value = value;
        } else {
          input = el("input");
          input.type =
            typeof value === "boolean"
              ? "checkbox"
              : typeof value === "number"
                ? "number"
                : "text";
          if (input.type === "checkbox") input.checked = value;
          else input.value = value;
          if (input.type === "number") {
            input.step = Number.isInteger(value) ? "1" : "any";
            input.min = 0;
            input.max = 1000000;
          }
        }
        input.name = key;
        input.disabled = !writable();
        inputs[key] = input;
        const delta = el("output", "parameter-delta");
        changes[key] = delta;
        input.oninput = input.onchange = () => {
          state.settingsDirty = true;
          status("未保存");
          const current = read(input);
          delta.value =
            typeof value === "number"
              ? changeLabel(value, current)
              : current === value
                ? ""
                : "已更改";
          updateBudget();
        };
        row.append(name, input, delta);
        section.append(row);
      }
      const recall = card(
        "Node-BM25",
        String.raw`\operatorname{rank}(d)=-\sum_{q\in Q}\operatorname{IDF}(q)\frac{f(q,d)(k_1+1)}{f(q,d)+k_1(1-b+b\frac{|d|}{\mathrm{avgdl}})}`,
      );
      recall.append(
        el(
          "small",
          "formula-note",
          "FTS5 · k₁=1.2 · b=0.75 · rank 升序",
        ),
      );
      recall.append(
        formula(String.raw`f(q,d)=5f_{title}+f_{body}+3f_{tags}+0.5f_{code}`),
      );
      recall.append(el("small", "formula-note", "默认字段权重 · 只读"));
      for (const key of [
        "search_backend",
        "recall_topn",
        "recall_floor",
        "recall_minlen",
        "recall_cooldown",
        "embedding_fallback",
      ])
        parameter(recall, key);
      const inject = card(
        "注入预算",
        String.raw`C_{target}=\min\left(B,\;K\cdot P\right)`,
      );
      for (const key of [
        "inject_budget_chars",
        "inject_per_page_chars",
        "inject_title_only_floor",
      ])
        parameter(inject, key);
      const preview = el("output", "formula-result");
      inject.append(preview);
      inject.append(
        el(
          "small",
          "formula-note",
          "计划正文预算 · 非实际输出测量",
        ),
      );
      function updateBudget() {
        if (!inputs.inject_budget_chars) return;
        const cap = (values) =>
          budgetCap({
            topn: values.recall_topn,
            perPage: values.inject_per_page_chars,
            budget: values.inject_budget_chars,
          });
        const next = cap(
          Object.fromEntries(
            Object.entries(inputs).map(([key, input]) => [key, read(input)]),
          ),
        );
        preview.value = `${next.toLocaleString()} 字符  ${changeLabel(cap(data.values), next)}`;
      }
      const other = card("运行");
      for (const key of [
        "posttool_mode",
        "posttool_signal_rel_floor",
        "conflict_window",
        "mail_topn",
        "debug_record",
        "memory_validity",
      ])
        parameter(other, key);
      const toolbar = el("div", "toolbar"),
        save = el("button", "soft", "保存");
      save.type = "submit";
      save.disabled = !writable();
      toolbar.append(
        save,
        button(
          "还原",
          () => {
            state.settingsDirty = false;
            status("");
            render();
          },
          "soft",
        ),
      );
      form.append(recall, inject, decayPreview(data), other, toolbar);
      form.onsubmit = async (event) => {
        event.preventDefault();
        save.disabled = true;
        try {
          await post("/api/studio/settings", {
            values: Object.fromEntries(
              Object.entries(inputs).map(([key, input]) => [key, read(input)]),
            ),
            expected_sha256: data.sha256,
          });
          state.settingsDirty = false;
          status("");
          render();
        } catch (error) {
          status(error.message);
          save.disabled = false;
        }
      };
      $("content").append(form);
      updateBudget();
    } catch (error) {
      status(error.message);
    }
  }
  function read(input) {
    return input.type === "checkbox"
      ? input.checked
      : input.type === "number"
        ? Number(input.value)
        : input.value;
  }
  return { render: renderSettings };
}
