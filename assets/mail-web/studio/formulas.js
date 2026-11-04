// Preview calculations mirror store.compute_score and the injection budget cap.
// They do not estimate retrieval quality or mutate runtime configuration.
export function memoryScore({
  importance,
  lambda,
  days,
  access,
  pinned = false,
  active = true,
  pinBonus = 0.5,
}) {
  return (
    (importance * Math.exp(-lambda * days) +
      0.5 * Math.log1p(access) +
      (pinned ? pinBonus : 0)) *
    (active ? 1.2 : 1)
  );
}
export function budgetCap({ topn, perPage, budget }) {
  return Math.min(budget, topn * perPage);
}
export function changeLabel(before, after, unit = "") {
  const delta = after - before;
  return delta === 0
    ? "—"
    : `${delta > 0 ? "↑" : "↓"} ${Math.abs(delta).toLocaleString("zh-CN", { maximumFractionDigits: 3 })}${unit}`;
}
