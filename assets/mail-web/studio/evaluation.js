import {
  qualityChart,
  latencyChart,
  pairedChart,
} from "./evaluation-charts.js";

export function createEvaluationView({ dom, state, actions, api }) {
  const { $, el, button } = dom;
  let ticket = 0,
    timer = null,
    selectedDataset = "",
    selectedRun = "",
    baselineRun = "",
    catalog = null,
    jobId = "",
    method = "fts5",
    configurationExperiment = false;
  function destroy() {
    ticket++;
    clearTimeout(timer);
  }
  function jsonPost(route, payload) {
    return api.request(route, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...payload,
        expected_knowledge_base: state.context.knowledge_base,
      }),
    });
  }
  async function render() {
    destroy();
    const current = ticket,
      host = el("div", "evaluation-workspace");
    $("content").append(host);
    try {
      catalog = await api.request("/api/evaluation/catalog");
      if (current !== ticket) return;
      const controls = el("div", "evaluation-controls"),
        datasets = el("select"),
        methods = el("select"),
        split = el("select");
      datasets.setAttribute("aria-label", "评测数据集");
      methods.setAttribute("aria-label", "评测方法");
      split.setAttribute("aria-label", "评测拆分");
      for (const d of catalog.datasets)
        datasets.append(
          new Option(`${d.title} · ${d.case_count ?? "—"}`, d.id),
        );
      if (!catalog.datasets.some((d) => d.id === selectedDataset))
        selectedDataset = catalog.datasets[0]?.id || "";
      datasets.value = selectedDataset;
      for (const item of catalog.methods)
        methods.append(new Option(item, item));
      methods.value = method;
      const upload = button("上传", () => file.click(), "soft"),
        file = el("input");
      file.type = "file";
      file.accept = ".yaml,.yml,.json";
      upload.title =
        "recall-case/v1 或 v2 · YAML / JSON，可携带 corpus · 最大 8 MiB";
      file.hidden = true;
      upload.disabled = state.context?.local_edit !== true;
      file.onchange = async () => {
        const chosen = file.files[0];
        if (!chosen) return;
        upload.disabled = true;
        try {
          if (chosen.size > 8 * 1024 * 1024) throw Error("数据集上限 8 MiB");
          const result = await jsonPost("/api/evaluation/import", {
            filename: chosen.name,
            text: await chosen.text(),
          });
          selectedDataset = result.id;
          await render();
        } catch (error) {
          actions.status(error.message);
          upload.disabled = false;
        }
      };
      const start = button(
        "运行全部",
        async () => {
          start.disabled = true;
          try {
            const result = await jsonPost("/api/evaluation/start", {
              dataset: selectedDataset,
              method: methods.value,
              split: split.hidden ? null : split.value,
            });
            jobId = result.id;
            poll();
          } catch (error) {
            actions.status(error.message);
            start.disabled = false;
          }
        },
        "soft",
      );
      const status = el("span", "eval-status"),
        progress = el("progress");
      progress.hidden = true;
      progress.setAttribute("aria-label", "评测进度");
      status.setAttribute("role", "status");
      const coverage = el("div", "eval-warning");
      coverage.hidden = true;
      controls.append(
        datasets,
        methods,
        split,
        start,
        upload,
        file,
        status,
        progress,
      );
      host.append(controls, coverage);
      const history = el("div", "evaluation-controls"),
        mainSelect = el("select"),
        baselineSelect = el("select");
      mainSelect.setAttribute("aria-label", "历史评测记录");
      baselineSelect.setAttribute("aria-label", "对比基线");
      const experimentLabel = el("label"),
        experiment = el("input");
      experiment.type = "checkbox";
      experiment.checked = configurationExperiment;
      experimentLabel.hidden = !baselineRun;
      experimentLabel.title =
        "同一数据与语料快照下，显式允许设置和有效参数变化";
      experimentLabel.append(experiment, document.createTextNode("配置实验"));
      experiment.onchange = () => {
        configurationExperiment = experiment.checked;
        void showReport();
      };
      history.append(mainSelect, baselineSelect, experimentLabel);
      host.append(history);
      const report = el("section");
      host.append(report);
      function configure() {
        const d = catalog.datasets.find((item) => item.id === selectedDataset);
        split.replaceChildren();
        for (const s of d?.splits || []) split.append(new Option(s, s));
        split.hidden = !d?.splits?.length;
        const missing = d?.coverage?.missing_count || 0;
        coverage.hidden = !missing && !d?.error;
        coverage.textContent =
          d?.error ||
          `缺少 ${missing} 份目标语料；恢复语料后可重跑。历史记录仍可查看。`;
        start.disabled =
          !d ||
          !!missing ||
          !!d.error ||
          state.context?.local_edit !== true ||
          catalog.jobs.some((j) => ["queued", "running"].includes(j.status));
        const latestJob = catalog.jobs.find(
          (j) => j.dataset === selectedDataset,
        );
        progress.hidden = !latestJob;
        if (latestJob) {
          progress.max = latestJob.total;
          progress.value = latestJob.completed;
          status.textContent = `${latestJob.method} · ${{ queued: "排队", running: "运行中", completed: "已完成", failed: "失败" }[latestJob.status] || latestJob.status} · ${latestJob.completed}/${latestJob.total}`;
        } else status.textContent = "";
        const runs = catalog.runs.filter(
          (r) =>
            r.manifest.dataset_id === d?.dataset_id ||
            r.studio?.dataset === selectedDataset,
        );
        const name = (r) =>
          `${r.id.startsWith("historical-") ? "历史 · " : ""}${r.studio?.method || r.manifest.comparison_context?.backend || r.id.replace("historical-", "")} · ${r.generated_at?.slice(0, 19).replace("T", " ")}`;
        mainSelect.replaceChildren();
        baselineSelect.replaceChildren(new Option("不对比", ""));
        for (const run of runs) {
          mainSelect.append(new Option(name(run), run.id));
          baselineSelect.append(new Option(name(run), run.id));
        }
        const attempts = catalog.jobs.filter(
          (j) => j.dataset === selectedDataset && j.status !== "completed",
        );
        for (const job of attempts)
          mainSelect.append(
            new Option(
              `${job.method} · ${job.status} · ${job.created_at.slice(0, 19)}`,
              job.id,
            ),
          );
        if (
          !runs.some((r) => r.id === selectedRun) &&
          !attempts.some((j) => j.id === selectedRun)
        )
          selectedRun = runs[0]?.id || attempts[0]?.id || "";
        if (
          !runs.some((r) => r.id === baselineRun) ||
          baselineRun === selectedRun
        )
          baselineRun = "";
        mainSelect.value = selectedRun;
        baselineSelect.value = baselineRun;
        experimentLabel.hidden = !baselineRun;
        void showReport();
      }
      datasets.onchange = () => {
        selectedDataset = datasets.value;
        selectedRun = "";
        baselineRun = "";
        configure();
      };
      methods.onchange = () => {
        method = methods.value;
      };
      mainSelect.onchange = () => {
        selectedRun = mainSelect.value;
        void showReport();
      };
      baselineSelect.onchange = () => {
        baselineRun = baselineSelect.value;
        experimentLabel.hidden = !baselineRun;
        void showReport();
      };
      let reportTicket = 0;
      async function showReport() {
        const reportVersion = ++reportTicket;
        report.replaceChildren();
        if (!selectedRun) {
          report.append(el("p", "empty", "暂无运行记录"));
          return;
        }
        const attempt = catalog.jobs.find(
          (j) => j.id === selectedRun && j.status !== "completed",
        );
        if (attempt) {
          const item = await api.request(
            "/api/evaluation/job?id=" + encodeURIComponent(attempt.id),
          );
          if (current !== ticket || reportVersion !== reportTicket) return;
          report.append(
            el(
              "p",
              "eval-status",
              `${item.method} · ${item.status} · ${item.completed}/${item.total}`,
            ),
          );
          if (item.error) report.append(el("p", "eval-warning", item.error));
          const trace = el("details", "eval-manifest");
          trace.append(
            el("summary", null, "运行记录"),
            el("pre", null, JSON.stringify(item, null, 2)),
          );
          report.append(trace);
          return;
        }
        try {
          const right = await api.request(
            "/api/evaluation/run?id=" + encodeURIComponent(selectedRun),
          );
          const left = baselineRun
            ? await api.request(
                "/api/evaluation/run?id=" + encodeURIComponent(baselineRun),
              )
            : null;
          if (current !== ticket || reportVersion !== reportTicket) return;
          let comparison = null,
            comparisonError = "";
          if (left) {
            try {
              comparison = await jsonPost("/api/evaluation/compare", {
                baseline: baselineRun,
                candidate: selectedRun,
                configuration_experiment: configurationExperiment,
              });
            } catch (error) {
              comparisonError = error.message;
            }
          }
          if (current !== ticket || reportVersion !== reportTicket) return;
          if (comparisonError)
            report.append(
              el("div", "eval-warning", "不可受控对比：" + comparisonError),
            );
          if (comparison?.comparability?.warnings.length)
            report.append(
              el(
                "div",
                "eval-warning",
                comparison.comparability.warnings.join("；"),
              ),
            );
          const cards = el("div", "eval-metrics");
          for (const [key, title] of [
            ["recall_at_1", "R@1"],
            ["recall_at_5", "R@5"],
            ["mrr", "MRR"],
            ["latency_p50_ms", "P50 · ms"],
            ["latency_p95_ms", "P95 · ms"],
          ]) {
            const card = el("div"),
              value = right.metrics[key];
            card.append(
              el("span", null, title),
              el(
                "strong",
                null,
                value == null ? "—" : Number(value).toFixed(3),
              ),
            );
            if (comparison?.deltas[key] != null)
              card.append(
                el(
                  "small",
                  null,
                  `Δ ${comparison.deltas[key] >= 0 ? "+" : ""}${comparison.deltas[key].toFixed(3)}`,
                ),
              );
            cards.append(card);
          }
          report.append(cards);
          const sameCases =
            left &&
            left.manifest.dataset_sha256 === right.manifest.dataset_sha256 &&
            JSON.stringify(
              left.cases.map((c) => [c.case_id, c.query, c.relevant]),
            ) ===
              JSON.stringify(
                right.cases.map((c) => [c.case_id, c.query, c.relevant]),
              );
          const showBoth = !!comparison || !!sameCases;
          const runs = showBoth ? [left, right] : [right],
            charts = el("div", "eval-charts");
          for (const [title, chart] of [
            ["Recall / Ranking", qualityChart(runs)],
            ["Latency · ECDF", latencyChart(runs)],
          ]) {
            const figure = el("figure");
            figure.append(el("figcaption", null, title), chart);
            charts.append(figure);
          }
          const audits = [
            ["scope_leakage", "Scope leak"],
            ["future_leakage", "Future leak"],
            ["version_leakage", "Version leak"],
            ["abstention_correct", "Abstain"],
          ].filter(([key]) => key in right.metrics);
          if (audits.length) {
            const figure = el("figure");
            figure.append(
              el("figcaption", null, "Scope / Version / Abstention"),
              qualityChart(runs, audits),
            );
            charts.append(figure);
          }
          if (showBoth) {
            const figure = el("figure");
            figure.append(
              el("figcaption", null, "Paired RR"),
              pairedChart(left, right),
            );
            charts.append(figure);
          }
          report.append(charts);
          const legend = el(
            "div",
            "eval-legend" + (showBoth ? " comparing" : ""),
          );
          legend.append(el("span", "candidate", "● 当前记录"));
          if (showBoth) legend.prepend(el("span", "baseline", "● 基线"));
          report.append(legend);
          const source = el("details", "eval-manifest");
          source.append(
            el("summary", null, "快照与配置"),
            el("pre", null, JSON.stringify(right.manifest, null, 2)),
          );
          report.append(source);
          if (comparison) {
            const evidence = el("details", "eval-manifest");
            evidence.append(
              el("summary", null, "对比依据"),
              el(
                "pre",
                null,
                JSON.stringify(comparison.comparability, null, 2),
              ),
            );
            report.append(evidence);
          }
          renderCases(right, report);
          if (catalog.references.length) {
            const references = el("details", "eval-manifest");
            references.append(el("summary", null, "外部参考 · 不同评测口径"));
            for (const ref of catalog.references) {
              const link = el(
                "a",
                null,
                `${ref.title} · ${ref.metric} ${(ref.value * 100).toFixed(2)}%`,
              );
              link.href = ref.source;
              link.target = "_blank";
              link.rel = "noopener noreferrer";
              references.append(
                link,
                el(
                  "p",
                  null,
                  ref.scope + " · 文献报告，未在本机重跑；不与召回率计算差值。",
                ),
              );
            }
            report.append(references);
          }
        } catch (error) {
          if (current === ticket) actions.status(error.message);
        }
      }
      async function poll() {
        try {
          const job = await api.request(
            "/api/evaluation/job?id=" + encodeURIComponent(jobId),
          );
          if (current !== ticket) return;
          progress.hidden = false;
          progress.max = job.total;
          progress.value = job.completed;
          status.textContent = `${job.method} · ${{ queued: "排队", running: "运行中", completed: "已完成", failed: "失败" }[job.status] || job.status} · ${job.completed}/${job.total}`;
          if (["queued", "running"].includes(job.status)) {
            start.disabled = true;
            timer = setTimeout(poll, 1500);
          } else if (job.status === "completed") {
            catalog = await api.request("/api/evaluation/catalog");
            if (current !== ticket) return;
            selectedRun = job.id;
            configure();
          } else {
            actions.status(job.error || "运行失败");
            configure();
          }
        } catch (error) {
          if (current === ticket) actions.status(error.message);
        }
      }
      configure();
      const active = catalog.jobs.find((j) =>
        ["queued", "running"].includes(j.status),
      );
      if (active) {
        jobId = active.id;
        void poll();
      }
      if (catalog.warnings.length) actions.status(catalog.warnings.join("；"));
    } catch (error) {
      if (current === ticket) actions.status(error.message);
    }
  }
  function renderCases(run, parent) {
    const section = el("section", "eval-cases"),
      tools = el("div", "evaluation-controls"),
      search = el("input"),
      failed = el("input"),
      label = el("label"),
      table = el("table"),
      pager = el("div", "eval-pager");
    let page = 0;
    search.type = "search";
    search.placeholder = "筛选 query";
    search.setAttribute("aria-label", "筛选评测题目");
    failed.type = "checkbox";
    label.append(failed, document.createTextNode("仅失败"));
    tools.append(search, label);
    section.append(tools, table, pager);
    parent.append(section);
    function draw() {
      const cases = run.cases.filter(
        (c) =>
          (!failed.checked ||
            (c.metrics.recall_at_1 == null
              ? c.metrics.abstention_correct === 0
              : c.metrics.recall_at_1 < 1)) &&
          (!search.value ||
            [c.query, c.case_id]
              .join(" ")
              .toLowerCase()
              .includes(search.value.toLowerCase())),
      );
      table.replaceChildren();
      const head = el("tr");
      for (const title of ["Case / Query", "R@1", "RR", "ms"])
        head.append(el("th", null, title));
      table.append(head);
      for (const c of cases.slice(page * 40, (page + 1) * 40)) {
        const row = el("tr"),
          cell = el("td"),
          detail = el("details");
        detail.append(
          el("summary", null, c.query),
          el(
            "pre",
            null,
            JSON.stringify(
              {
                case_id: c.case_id,
                relevant: c.relevant,
                retrieved: c.retrieved,
                metrics: c.metrics,
              },
              null,
              2,
            ),
          ),
        );
        cell.append(detail);
        row.append(
          cell,
          ...["recall_at_1", "mrr", "latency_ms"].map((key) =>
            el(
              "td",
              null,
              (key === "latency_ms" ? c[key] : c.metrics[key])?.toFixed(3) ??
                "—",
            ),
          ),
        );
        table.append(row);
      }
      pager.replaceChildren();
      if (cases.length > 40) {
        const back = button("←", () => {
            page--;
            draw();
          }),
          next = button("→", () => {
            page++;
            draw();
          });
        back.disabled = page === 0;
        next.disabled = (page + 1) * 40 >= cases.length;
        pager.append(
          back,
          el("span", null, `${page + 1} / ${Math.ceil(cases.length / 40)}`),
          next,
        );
      }
    }
    search.oninput = failed.onchange = () => {
      page = 0;
      draw();
    };
    draw();
  }
  return { render, destroy };
}
