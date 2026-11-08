"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const { source, moduleUrl } = require("./studio_test_helpers.cjs");

test("local graph includes both incoming and outgoing direct links, never distant nodes", async () => {
  const { documentNeighborhood } = await import(
    moduleUrl(source("studio/knowledge-model.js"))
  );
  const projection = {
    nodes: ["a", "b", "c", "d", "isolated"].map((id) => ({ id })),
    edges: [
      { from: "a", to: "b" },
      { from: "c", to: "a" },
      { from: "b", to: "d" },
    ],
  };
  const local = documentNeighborhood(projection, "a");
  assert.deepEqual(
    local.nodes.map((n) => n.id),
    ["a", "b", "c"],
  );
  assert.equal(local.edges.length, 2);
  assert.equal(documentNeighborhood(projection, "isolated").nodes.length, 1);
  assert.equal(documentNeighborhood(projection, null), projection);
});

test("document projection deduplicates leaves while preserving different relation types and provenance", async () => {
  const { projectDocuments } = await import(
    moduleUrl(source("studio/knowledge-model.js"))
  );
  const a = { id: "a", title: "Alpha", path: "wiki/a.md", pending: true };
  const b = { id: "b", title: "Beta", path: "wiki/b.md", tags: ["Research"] };
  const roots = [
    { id: "r", children: [a, b] },
    { id: "other", children: [a] },
  ];
  const relations = [
    { a: "a", b: "b", type: "supports", sources: ["frontmatter"] },
    { a: "a", b: "b", type: "internal_link", declared_by: ["a"] },
    { a: "a", b: "missing", type: "cites" },
  ];
  const graph = projectDocuments(roots, relations);
  assert.deepEqual(graph.nodes, [
    { ...a, linkCount: 2 },
    { ...b, linkCount: 2 },
  ]);
  assert.equal(a.linkCount, undefined);
  assert.equal(b.linkCount, undefined);
  assert.deepEqual(
    graph.edges.map((edge) => edge.type),
    ["supports", "internal_link"],
  );
  assert.deepEqual(graph.edges[0].sources, ["frontmatter"]);
  assert.equal(graph.edges[1].pending, true);
  assert.deepEqual(projectDocuments(roots, relations, "research").nodes, [
    { ...b, linkCount: 0 },
  ]);
  assert.deepEqual(
    projectDocuments(roots, relations, "", new Set(["a"])).nodes,
    [{ ...a, linkCount: 0 }],
  );
});

test("shared-tag relationships remain distinct from declarations, document links and material evidence", async () => {
  const { knowledgeRelations, knowledgeTree } = await import(
    moduleUrl(source("studio/knowledge-model.js"))
  );
  const map = {
    domains: [],
    materials: [
      { id: "m", path: "wiki/source.md", content_role: "source_material" },
    ],
    edges: [],
    explicit_edges: [{ a: "a", b: "b", type: "related" }],
    shared_tag_edges: [
      { a: "a", b: "b", type: "related", sources: ["共同标签"] },
    ],
    internal_links: [{ a: "b", b: "c", type: "internal_link" }],
    material_edges: [{ a: "c", b: "m", type: "supports" }],
  };
  const relations = knowledgeRelations(map, {
    edges: [{ a: "g", b: "a", type: "cites" }],
  });
  assert.deepEqual(
    relations.map((edge) => edge.type),
    ["related", "shared_tag", "internal_link", "supports", "cites"],
  );
  assert.equal(relations[1].relationType, "related");
  assert.equal(relations[1].dashed, true);
  assert.deepEqual(relations[1].sources, ["共同标签"]);
  const tree = knowledgeTree(map, { entries: [] }, { skills: [] });
  assert.equal(tree[0].children[0].type, "raw");
});
