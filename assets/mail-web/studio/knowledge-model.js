// Read-only projection of the existing knowledge map and explicit use counters.
export function knowledgeTree(map, usage, skills, contexts = { entries: [] }) {
  const counts = new Map(usage.entries.map((item) => [item.slug, item.count]));
  const leaf = (point) => ({
    ...point,
    type: point.kind === "candidate" ? "drafts" : "wiki",
    uses: counts.get(point.path.split("/").pop().replace(/\.md$/, "")) || 0,
    pending: point.kind === "candidate",
  });
  const group = (id, title, children, level, family = "wiki") => ({
    id,
    title,
    type: "group",
    level,
    family,
    children,
    uses: children.reduce((sum, item) => sum + item.uses, 0),
    pending: children.length > 0 && children.every((item) => item.pending),
    has_pending: children.some((item) => item.pending || item.has_pending),
  });
  const roots = map.domains.map((domain) =>
    group(
      "domain:" + domain.id,
      domain.label,
      domain.clusters.map((cluster) =>
        group(
          "cluster:" + JSON.stringify([domain.id, cluster.id]),
          cluster.label,
          cluster.points.map((point) => leaf({ ...point, family: domain.id })),
          2,
          domain.id,
        ),
      ),
      1,
      domain.id,
    ),
  );
  if (map.materials?.length)
    roots.push(group("materials", "来源资料", map.materials.map(leaf), 1));
  if (skills.skills.length)
    roots.push(
      group(
        "skills",
        "技能",
        skills.skills.map((skill) => ({
          ...skill,
          id: skill.path,
          type: "skill",
          family: "skill",
          uses: 0,
          pending: false,
        })),
        1,
        "skill",
      ),
    );
  for (const [kind, title] of [
    ["profile", "画像"],
    ["project", "项目"],
    ["goal", "目标"],
    ["discuss", "讨论"],
    ["team", "团队"],
    ["mail", "交接"],
  ]) {
    const entries = contexts.entries.filter((e) => e.type === kind);
    if (!entries.length) continue;
    const grouped = new Map();
    for (const item of entries) {
      const key =
        item.date ||
        (["goal", "discuss"].includes(kind) ? "历史未归档" : item.group);
      if (!grouped.has(key)) grouped.set(key, []);
      grouped.get(key).push({ ...item, uses: 0, pending: item.pending || false, family: kind });
    }
    roots.push(
      group(
        "context:" + kind,
        title,
        [...grouped].map(([key, items]) =>
          group(
            "context-group:" + JSON.stringify([kind, key]),
            key,
            items,
            2,
            kind,
          ),
        ),
        1,
        kind,
      ),
    );
  }
  return roots;
}
export function projectKnowledge(
  roots,
  expanded = new Set(),
  depth = 1,
  query = "",
  relations = [],
) {
  const nodes = [],
    edges = [],
    matches = new Set(),
    q = query.trim().toLocaleLowerCase();
  function matchesBelow(node) {
    const match =
      !!q &&
      [node.title, node.path, ...(node.tags || [])].some((v) =>
        String(v || "")
          .toLocaleLowerCase()
          .includes(q),
      );
    if (match) matches.add(node.id);
    return match || !!node.children?.map(matchesBelow).some(Boolean);
  }
  function visit(node, level, parent, force = false) {
    const match = q ? matchesBelow(node) : true;
    if (!match && !force) return;
    nodes.push(node);
    if (parent)
      edges.push({
        from: parent.id,
        to: node.id,
        type: "contains",
        pending: node.pending,
      });
    if (node.children && (q || level < depth || expanded.has(node.id) || force))
      for (const child of node.children)
        visit(child, level + 1, node, force || matches.has(node.id));
  }
  for (const root of roots) visit(root, 1, null);
  const ids = new Set(nodes.map((node) => node.id));
  for (const edge of relations)
    if (ids.has(edge.a) && ids.has(edge.b))
      edges.push({
        from: edge.a,
        to: edge.b,
        type: edge.type || "related",
        pending: nodes.some(
          (n) => (n.id === edge.a || n.id === edge.b) && n.pending,
        ),
      });
  return { nodes, edges };
}
export function usageColor(uses, maxUses, pending = false, hue = 220) {
  if (pending) return "#e3e6ec";
  if (!uses) return `hsl(${hue} 42% 86%)`;
  const lightness =
    82 - (35 * Math.log1p(uses)) / Math.log1p(Math.max(maxUses, 1));
  return `hsl(${hue} 42% ${lightness}%)`;
}

export function nodeHue(node) {
  const hues = {
    profile: 36,
    project: 155,
    goal: 335,
    discuss: 278,
    skill: 263,
    team: 175,
    mail: 25,
    computing: 220,
    engineering: 166,
    management: 38,
  };
  const key = node.family || node.type;
  if (key in hues) return hues[key];
  return [220, 160, 275, 35, 330][
    [...key].reduce((s, c) => s + c.charCodeAt(0), 0) % 5
  ];
}
export function findNode(roots, id) {
  for (const node of roots) {
    if (node.id === id) return node;
    const found = node.children && findNode(node.children, id);
    if (found) return found;
  }
}
export function revealNode(roots, id, expanded) {
  for (const node of roots) {
    if (node.id === id) return true;
    if (node.children && revealNode(node.children, id, expanded)) {
      expanded.add(node.id);
      return true;
    }
  }
  return false;
}
export function mapQueryHits(roots, knowledge) {
  const leaves = [];
  const walk = (items) =>
    items.forEach((n) => (n.children ? walk(n.children) : leaves.push(n)));
  walk(roots);
  return knowledge.map((hit) => {
    const path =
      hit.source_path ||
      (hit.uri?.startsWith("oks://")
        ? decodeURIComponent(hit.uri.slice(6))
        : "");
    const candidates = hit.channel === 'team'
      ? leaves.filter(n => n.id === hit.id || n.id === hit.slug)
      : path
      ? leaves.filter((n) => n.path === path)
      : leaves.filter(
          (n) => n.path?.split("/").pop().replace(/\.md$/, "") === hit.slug,
        );
    return {
      ...hit,
      nodeId: candidates.length === 1 ? candidates[0].id : null,
    };
  });
}

// Query inspection shows exact hits and ancestor paths; unrelated branches stay collapsed.
export function projectQuery(roots, hits, relations = []) {
  const ids = new Set(hits.map((hit) => hit.nodeId).filter(Boolean)),
    expanded = new Set();
  function prune(items) {
    return items.flatMap((node) => {
      const children = node.children ? prune(node.children) : null;
      if (!ids.has(node.id) && !children?.length) return [];
      if (children) {
        expanded.add(node.id);
        return [{ ...node, children }];
      }
      return [node];
    });
  }
  return projectKnowledge(prune(roots), expanded, 1, "", relations);
}
