// Retained revisions, with actual event timestamps. Playback scales idle time.
export function createTimeline({
  dom,
  api,
  events = [],
  onSelect,
  onCurrent,
  canLeave = () => true,
}) {
  const { el, button } = dom,
    host = el("div", "day-timeline"),
    play = button("▶", () => {}),
    speed = el("select"),
    seek = el("input"),
    clock = el("span", "tiny");
  let timer = null,
    index = -1,
    playing = false,
    alive = true,
    generation = 0;
  const rows = events.filter((e) => !e.status || e.status === "complete");
  for (const n of [1, 2, 4, 8]) speed.append(new Option(n + "×", n));
  speed.title = "1×：每秒推进一分钟";
  speed.setAttribute("aria-label", "时间轴回放倍速");
  seek.type = "range";
  seek.min = 0;
  seek.max = Math.max(0, rows.length - 1);
  seek.value = seek.max;
  seek.disabled = !rows.length;
  seek.setAttribute("aria-label", "时间轴");
  function pause() {
    generation++;
    playing = false;
    clearTimeout(timer);
    play.textContent = "▶";
  }
  async function show(i) {
    const requested = generation;
    if (!canLeave()) return false;
    const event = rows[i];
    if (!event) return false;
    try {
      const frame = await api.request(
        "/api/studio/revision?" + new URLSearchParams({ id: event.id }),
      );
      if (!alive || requested !== generation || !canLeave()) return false;
      index = i;
      seek.value = i;
      clock.textContent = new Date(event.at).toLocaleTimeString([], {
        hour12: false,
      });
      await onSelect(frame);
      return true;
    } catch (error) {
      if (requested !== generation) return false;
      pause();
      host.title = error.message;
      return false;
    }
  }
  async function tick() {
    const requested = generation;
    if (!playing) return;
    if (index >= rows.length - 1) {
      pause();
      return;
    }
    const shown = await show(index + 1);
    if (requested !== generation) return;
    if (!shown) {
      pause();
      return;
    }
    const next = rows[index + 1];
    if (!next) {
      pause();
      return;
    }
    timer = setTimeout(
      tick,
      Math.max(
        150,
        (Date.parse(next.at) - Date.parse(rows[index].at)) /
          60 /
          Number(speed.value),
      ),
    );
  }
  play.setAttribute("aria-label", "回放记录");
  play.disabled = !rows.length;
  play.onclick = () => {
    if (!canLeave()) return;
    if (playing) {
      pause();
      return;
    }
    index = -1;
    playing = true;
    play.textContent = "Ⅱ";
    void tick();
  };
  seek.oninput = () => {
    pause();
    void show(Number(seek.value)).then((ok) => {
      if (!ok) seek.value = index < 0 ? seek.max : index;
    });
  };
  host.append(
    play,
    speed,
    seek,
    clock,
    button(
      "当前",
      () => {
        if (!canLeave()) return;
        pause();
        clock.textContent = "";
        onCurrent();
      },
      "soft",
    ),
  );
  for (let i = 0; i < rows.length; i++) {
    const event = rows[i],
      time = new Date(event.at).toLocaleTimeString([], { hour12: false });
    const action =
      {
        baseline: "开始记录已有内容",
        observed_change: "观察到修改",
        create: "新增",
        edit: "编辑",
      }[event.action] || event.action;
    const name = event.path.split("/").pop().replace(/\.md$/, "");
    const first = event.changes?.[0],
      kinds = {
        added: "新增",
        removed: "移除",
        completed: "完成",
        reopened: "重新打开",
      };
    const summary = ["baseline", "create"].includes(event.action)
      ? name
      : first
        ? kinds[first.type] +
          " " +
          first.title +
          (event.changes.length > 1 ? " ＋" + (event.changes.length - 1) : "")
        : name;
    const b = button(
      `${time} · ${action} · ${summary}`,
      () => {
        pause();
        void show(i);
      },
      "timeline-event",
    );
    b.title = event.path;
    host.append(b);
  }
  return {
    element: host,
    destroy: () => {
      alive = false;
      pause();
    },
  };
}
