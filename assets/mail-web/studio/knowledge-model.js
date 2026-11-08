// Read-only projection of the existing knowledge map and explicit use counters.
export function knowledgeTree(map, usage, skills, contexts = { entries: [] }) {
  const counts = new Map(usage.entries.map((item) => [item.slug, item.count]));
  const leaf = (point) => ({
    ...point,
    type:
      point.content_role === "source_material" || point.path?.startsWith("raw/")
        ? "raw"
        : point.kind === "candidate"
          ? "drafts"
          : "wiki",
    uses:
      point.kind === "wiki" && point.content_role !== "source_material"
        ? counts.get(point.path.split("/").pop().replace(/\.md$/, "")) || 0
        : 0,
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
    const entries = contexts.entries.filter(
      (e) => e.type === kind && !/(?:^|\/)_template\.md$/i.test(e.path || ""),
    );
    if (!entries.length) continue;
    const grouped = new Map();
    for (const item of entries) {
      const key =
        item.date ||
        (["goal", "discuss"].includes(kind) ? "历史未归档" : item.group);
      if (!grouped.has(key)) grouped.set(key, []);
      grouped.get(key).push({
        ...item,
        uses: 0,
        pending: item.pending || false,
        family: kind,
      });
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
        ...edge,
        from: edge.a,
        to: edge.b,
        type: edge.type || "related",
        pending: nodes.some(
          (n) => (n.id === edge.a || n.id === edge.b) && n.pending,
        ),
      });
  return { nodes, edges };
}

export function knowledgeRelations(map, contexts = { edges: [] }) {
  return [
    ...(map.explicit_edges ?? map.edges),
    ...(map.shared_tag_edges || []).map((edge) => ({
      ...edge,
      type: "shared_tag",
      relationType: edge.type,
      dashed: true,
    })),
    ...(map.internal_links || []),
    ...(map.material_edges || []),
    ...(contexts.edges || []),
  ];
}

export function projectDocuments(
  roots,
  relations = [],
  query = "",
  hitIds = null,
) {
  const documents = new Map();
  const q = query.trim().toLocaleLowerCase();
  function visit(items) {
    for (const node of items) {
      if (node.children) visit(node.children);
      else if (
        (!hitIds || hitIds.has(node.id)) &&
        (!q ||
          [node.title, node.path, ...(node.tags || [])].some((value) =>
            String(value || "")
              .toLocaleLowerCase()
              .includes(q),
          ))
      )
        documents.set(node.id, node);
    }
  }
  visit(roots);
  const edges = relations
    .filter((edge) => documents.has(edge.a) && documents.has(edge.b))
    .map((edge) => ({
      ...edge,
      from: edge.a,
      to: edge.b,
      type: edge.type || "related",
      pending: documents.get(edge.a).pending || documents.get(edge.b).pending,
    }));
  const degrees = new Map();
  for (const edge of edges) {
    degrees.set(edge.from, (degrees.get(edge.from) || 0) + 1);
    degrees.set(edge.to, (degrees.get(edge.to) || 0) + 1);
  }
  const nodes = [...documents.values()].map((node) => ({
    ...node,
    linkCount: degrees.get(node.id) || 0,
  }));
  return { nodes, edges };
}
export function usageColor(uses, maxUses, pending = false, hue = 220) {
  if (pending) return "#e3e6ec";
  if (!uses) return `hsl(${hue} 42% 56%)`;
  const lightness =
    56 -
    16 *
      Math.min(
        1,
        Math.log1p(Math.max(0, uses)) / Math.log1p(Math.max(maxUses, 1)),
      );
  return `hsl(${hue} 54% ${lightness}%)`;
}

export function documentNeighborhood(projection, id) {
  if (!id) return projection;
  const ids = new Set([id]);
  for (const edge of projection.edges) {
    if (edge.from === id) ids.add(edge.to);
    if (edge.to === id) ids.add(edge.from);
  }
  return {
    nodes: projection.nodes.filter((node) => ids.has(node.id)),
    edges: projection.edges.filter(
      (edge) => ids.has(edge.from) && ids.has(edge.to),
    ),
  };
}

export function nodeHue(node) {
  const hues = {
    profile: 174,
    project: 195,
    goal: 145,
    discuss: 30,
    skill: 263,
    team: 325,
    mail: 15,
    wiki: 220,
    raw: 210,
    drafts: 43,
  };
  return hues[nodeCategory(node)] ?? hues.wiki;
}

export const categoryLabels = {
  wiki: "知识",
  drafts: "待审核",
  raw: "来源",
  skill: "技能",
  profile: "画像",
  project: "项目",
  goal: "目标",
  discuss: "讨论",
  team: "团队",
  mail: "交接",
};
export function knowledgeOverview(roots) {
  const domains = roots.filter((n) => nodeCategory(n) === "wiki");
  if (!domains.length) return roots;
  return [
    {
      id: "overview:wiki",
      title: "知识",
      type: "group",
      family: "wiki",
      children: domains,
      uses: domains.reduce((sum, n) => sum + n.uses, 0),
      has_pending: domains.some((n) => n.pending || n.has_pending),
    },
    ...roots.filter((n) => nodeCategory(n) !== "wiki"),
  ];
}
export function nodeCategory(node) {
  if (node.type !== "group") return node.type;
  if (node.id === "materials") return "raw";
  return node.family in categoryLabels ? node.family : "wiki";
}
export function nodeSize(node) {
  // Quartz sizes documents by their real link degree, not by usage or title.
  if (!node.children) return 4 + Math.min(7, Math.sqrt(node.linkCount || 0));
  const count = (n) =>
    n.children ? n.children.reduce((sum, child) => sum + count(child), 0) : 1;
  return 13 + Math.min(9, Math.log2(1 + count(node)) * 1.5);
}
// View filters preserve ancestor paths, but never turn a hidden item into evidence.
export function filterKnowledge(
  roots,
  { categories = null, state = "all", hidden = new Set(), only = null } = {},
) {
  const visit = (node) => {
    if (hidden.has(node.id)) return [];
    if (node.children) {
      const children = node.children.flatMap(visit);
      return children.length
        ? [
            {
              ...node,
              children,
              uses: children.reduce((sum, child) => sum + (child.uses || 0), 0),
              pending: children.every((child) => child.pending),
              has_pending: children.some(
                (child) => child.pending || child.has_pending,
              ),
            },
          ]
        : [];
    }
    if (categories && !categories.has(nodeCategory(node))) return [];
    if (
      (state === "pending" && !node.pending) ||
      (state === "used" && !node.uses)
    )
      return [];
    if (only && !only.has(node.id)) return [];
    return [node];
  };
  return roots.flatMap(visit);
}
export function subtreeIds(node) {
  return [node.id, ...(node.children || []).flatMap(subtreeIds)];
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
    const candidates =
      hit.channel === "team"
        ? leaves.filter((n) => n.id === hit.id || n.id === hit.slug)
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
