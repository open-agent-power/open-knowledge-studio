// A scrubber over retained stages; the endpoint always returns to live files.
export function createTimeline({ dom, api, events = [], onSelect, onCurrent,
  canLeave = () => true, selectedId = null }) {
  const { el, button } = dom;
  const rows = events.filter(e => (!e.status || e.status === "complete") && Number.isFinite(Date.parse(e.at)))
    .slice().sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  const last = Math.max(0, rows.length - 1);
  const host = el("div", "day-timeline"), controls = el("div", "timeline-controls");
  const play = button("▶", () => {}), speed = el("select");
  const track = el("div", "timeline-track"), range = el("input", "timeline-range");
  const marks = el("div", "timeline-marks"), clock = el("span", "timeline-clock");
  const caption = el("div", "timeline-caption"), stages = el("div", "timeline-stages");
  stages.setAttribute("aria-label", "时间轴阶段");
  let position = Math.max(0, rows.findIndex(e => e.id === selectedId));
  if (!selectedId || !rows.some(e => e.id === selectedId)) position = last;
  let applied = Math.floor(position), requested = applied, pending = null;
  let playing = false, starting = false, alive = true, timer = null, generation = 0, playTicket = 0, previous = 0;
  range.type = "range"; range.min = "0"; range.max = String(Math.max(1, last) * 1000); range.step = "1";
  range.setAttribute("aria-label", "时间轴进度");
  range.disabled = rows.length < 2;
  play.disabled = rows.length < 2;
  play.setAttribute("aria-label", "播放时间轴");
  speed.setAttribute("aria-label", "时间轴回放倍速");
  speed.title = "按记录间隔回放，压缩长空档";
  for (const n of [1, 2, 4, 8]) speed.append(new Option(n + "×", n));
  speed.value = "1";
  const time = e => new Date(e.at).toLocaleTimeString([], { hour12: false });
  const label = e => {
    const action = { baseline: "开始记录已有内容", observed_change: "观察到修改", create: "新增", edit: "编辑" }[e.action] || e.action || "";
    const name = (e.path || "").split("/").pop().replace(/\.md$/, "");
    const change = e.changes?.[0];
    const kind = { added: "新增", removed: "移除", completed: "完成", reopened: "重新打开" }[change?.type];
    const summary = ["baseline", "create"].includes(e.action) ? name : change && kind ? `${name} · ${kind} ${change.title}` : name;
    return `${action} · ${summary}`;
  };
  function scrollSelected() {
    const node = stages.children[Math.min(last, Math.floor(position))];
    if (node && Number.isFinite(node.offsetLeft))
      stages.scrollLeft = Math.max(0, node.offsetLeft - stages.offsetLeft - (stages.clientWidth - node.offsetWidth) / 2);
  }
  function paint() {
    const i = Math.min(last, Math.floor(position));
    const percent = rows.length < 2 ? 100 : position / last * 100;
    range.value = String(rows.length < 2 ? Number(range.max) : Math.round(position * 1000));
    range.style.setProperty("--progress", percent + "%");
    clock.textContent = rows[i] ? time(rows[i]) : "";
    caption.textContent = rows[i] ? `${i + 1}/${rows.length} · ${label(rows[i])}` : "暂无记录";
    caption.hidden = !!rows.length;
    caption.title = rows[i] ? `${time(rows[i])} · ${label(rows[i])}` : "";
    range.setAttribute("aria-valuetext", caption.title);
    [...marks.children].forEach((mark, index) => mark.setAttribute("aria-pressed", String(index === i)));
    [...stages.children].forEach((stage, index) => stage.setAttribute("aria-pressed", String(index === i)));
    scrollSelected();
  }
  function pause() {
    playTicket++; starting = false; playing = false; clearTimeout(timer); timer = null;
    play.textContent = "▶"; play.setAttribute("aria-label", "播放时间轴");
  }
  async function select(i) {
    if (i === requested) return pending || true;
    requested = i;
    const ticket = ++generation;
    if (i === last) {
      applied = i; pending = null; onCurrent(); return true;
    }
    pending = (async () => {
      try {
        const frame = await api.request("/api/studio/revision?" + new URLSearchParams({ id: rows[i].id }));
        if (!alive || ticket !== generation) return false;
        if (!canLeave()) { requested = applied; position = applied; paint(); return false; }
        await onSelect(frame);
        applied = i;
        return true;
      } catch (error) {
        if (!alive || ticket !== generation) return false;
        pause(); requested = applied; position = applied; paint();
        caption.hidden = false; caption.textContent = "读取失败：" + error.message;
        return false;
      } finally {
        if (ticket === generation) pending = null;
      }
    })();
    return pending;
  }
  async function seek(value) {
    if (!alive) return false;
    if (!canLeave()) { paint(); return false; }
    position = Math.max(0, Math.min(last, value)); paint();
    return select(Math.floor(position));
  }
  async function tick() {
    if (!playing || !alive) return;
    if (!canLeave()) { pause(); return; }
    const epoch = playTicket;
    const now = Date.now(), i = Math.floor(position);
    // The display is stage-based; timestamps determine the compressed dwell.
    const gap = rows[i + 1] ? Date.parse(rows[i + 1].at) - Date.parse(rows[i].at) : 0;
    const duration = Math.max(250, Math.min(5000, gap / 60));
    const next = Math.min(i + 1, position + (now - previous) * Number(speed.value) / duration);
    previous = now;
    const shown = await seek(next);
    if (epoch !== playTicket) return;
    if (!shown || !playing || !alive) { pause(); return; }
    if (position >= last) { pause(); return; }
    previous = Date.now();
    timer = setTimeout(tick, 40);
  }
  range.oninput = () => { pause(); void seek(Number(range.value) / 1000); };
  range.onkeydown = e => {
    const target = { ArrowLeft: Math.ceil(position) - 1, ArrowRight: Math.floor(position) + 1, Home: 0, End: last }[e.key];
    if (target === undefined) return;
    e.preventDefault(); pause(); void seek(target);
  };
  play.onclick = async () => {
    if (!canLeave()) return;
    if (playing || starting) { pause(); return; }
    const epoch = ++playTicket;
    starting = true;
    const ready = position < last || await seek(0);
    if (epoch !== playTicket) return;
    starting = false;
    if (!ready || !alive || rows.length < 2 || !canLeave()) return;
    playing = true; play.textContent = "Ⅱ"; play.setAttribute("aria-label", "暂停时间轴");
    previous = Date.now(); timer = setTimeout(tick, 40);
  };
  for (let i = 0; i < rows.length; i++) {
    const mark = button("", () => { pause(); void seek(i); }, "timeline-marker");
    mark.style.left = (rows.length < 2 ? 100 : i / last * 100) + "%";
    mark.title = `${time(rows[i])} · ${label(rows[i])}`;
    mark.setAttribute("aria-label", `阶段 ${i + 1}：${mark.title}`);
    marks.append(mark);
    const stage = button(`${time(rows[i])} · ${label(rows[i])}`, () => { pause(); void seek(i); }, "timeline-event");
    stage.title = rows[i].path || "";
    stages.append(stage);
  }
  track.append(range, marks); controls.append(play, speed, track, clock);
  host.append(controls, stages, caption); paint();
  const layoutTimer = setTimeout(() => { if (alive) scrollSelected(); }, 0);
  return { element: host, destroy() { alive = false; generation++; clearTimeout(layoutTimer); pause(); } };
}
