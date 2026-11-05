export function renderOnboarding({ dom, state, actions, api }) {
  const { el, button } = dom,
    host = document.getElementById("onboarding");
  host.replaceChildren();
  const data = state.onboarding;
  if (!data || ["completed", "skipped"].includes(data.status)) {
    host.hidden = true;
    return;
  }
  host.hidden = false;
  const steps = [
    ["discuss", "讨论", "留下问题、判断与待确认事项"],
    ["goals", "目标", "用分支拆解目标，记录每天的推进"],
    ["learning", "学习", "查阅知识、复核经验与调整方法"],
  ];
  const step = steps.find(([id]) => !data.steps[id]) || steps[0];
  for (const [id, title] of steps)
    host.append(
      button(
        (data.steps[id] ? "✓ " : "") + title,
        () => actions.navigate(id),
        id === step[0] ? "active" : "",
      ),
    );
  host.append(el("span", "guide-hint", step[2]));
  async function update(payload) {
    try {
      if (actions.writable())
        state.onboarding = await api.post("/api/studio/onboarding", payload);
      else state.onboarding = { ...data, status: "skipped" };
      actions.render();
    } catch (error) {
      actions.status(error.message);
    }
  }
  host.append(
    button(
      "下一步",
      async () => {
        await update({ action: "complete_step", step: step[0] });
        const next = steps.find(([id]) => !state.onboarding.steps[id]);
        if (next) await actions.navigate(next[0]);
      },
      "soft",
    ),
    button("跳过", () => update({ action: "skip" }), "soft"),
  );
}
