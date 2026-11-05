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
    selected: "",
    mode: "list",
    dirty: false,
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
