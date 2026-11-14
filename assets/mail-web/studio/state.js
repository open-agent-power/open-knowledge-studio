// Session-only UI state. Markdown remains on disk; no knowledge is cached here.
export function createStudioState() {
  return {
    context: null,
    date: "",
    onboarding: null,
    scopes: [],
    scope: "",
    view: null,
    tab: "discuss",
    discuss: "history",
    selected: "",
    mode: "list",
    dirty: false,
    commentDraft: null,
    saving: false,
    loading: 0,
    learn: "graph",
    folds: new Set(),
    settingsDirty: false,
    legacyPanelHash: null,
    viewLoading: false,
    statisticsMode: "usage",
  };
}

// Calendar arithmetic in UTC avoids DST changing the selected local date.
export function shiftDate(value, days) {
  const date = new Date(value + "T12:00:00Z");
  if (!Number.isFinite(date.getTime())) throw Error("日期无效");
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}
