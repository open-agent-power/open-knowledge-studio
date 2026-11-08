// Adapted from Advanced Graph View, MIT, copyright (c) 2026 n23eos.
// Worker scheduling/seeds from Advanced Graph View, force balance from Graphs Plus,
// and degree-based collision from Quartz Graph. All MIT; see ../README.md.
// 2D subset of layoutEngine.ts, layoutSeed.ts,
// repulsionAccuracy.ts and tickPacing.ts. See ../README.md for attribution.
import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
} from "d3-force-3d";

const ALPHA_MIN = 0.01;
const FRAME_INTERVAL_MS = 33;
const DRAG_INTERVAL_MS = 16;

function scatterSeed(count) {
  const seed = new Float32Array(count * 3);
  const extent = 40 * Math.sqrt(count);
  function hash01(value) {
    let hash = value | 0;
    hash = hash ^ 61 ^ (hash >>> 16);
    hash += hash << 3;
    hash ^= hash >>> 4;
    hash = Math.imul(hash, 0x27d4eb2d);
    hash ^= hash >>> 15;
    return (hash >>> 0) / 4294967296;
  }
  for (let i = 0; i < count; i++) {
    seed[i * 3] = (hash01(i * 2 + 1) - 0.5) * extent;
    seed[i * 3 + 1] = (hash01(i * 2 + 2) - 0.5) * extent;
  }
  return seed;
}

export function createLayoutEngine(post) {
  const params = {
    repel: 1000,
    linkDistance: 250,
    centering: 0.1,
    linkStrength: 1,
    velocityDecay: 0.4,
    collideRadius: 0,
  };
  let simulation = null,
    nodes = [],
    revision = 0;
  let timer = null,
    interval = FRAME_INTERVAL_MS,
    paused = false,
    dragging = null;
  const collision = forceCollide().strength(0.7).iterations(3);

  function snapshot(type = "tick") {
    const positions = new Float32Array(nodes.length * 3);
    for (let i = 0; i < nodes.length; i++) {
      positions[i * 3] = nodes[i].x;
      positions[i * 3 + 1] = nodes[i].y;
    }
    post({ type, revision, positions, alpha: simulation?.alpha() ?? 0 }, [
      positions.buffer,
    ]);
  }
  function stopTimer() {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  }
  function schedule(delay = interval) {
    if (!paused && timer === null) timer = setTimeout(pacedStep, delay);
  }
  function step() {
    if (!simulation || paused) return;
    const alpha = simulation.alpha();
    simulation
      .force("charge")
      .theta(alpha > 0.15 ? 1.2 : alpha > 0.05 ? 0.9 : 0.6);
    simulation.tick();
    snapshot();
    if (simulation.alpha() < ALPHA_MIN) {
      stopTimer();
      snapshot("end");
    }
  }
  function pacedStep() {
    timer = null;
    const startedAt = performance.now();
    step();
    if (simulation && simulation.alpha() >= ALPHA_MIN) {
      schedule(Math.max(8, interval - (performance.now() - startedAt)));
    }
  }
  function applyParams() {
    if (!simulation) return;
    simulation.force("charge").strength(-params.repel);
    simulation
      .force("link")
      .distance(params.linkDistance)
      .strength(
        (edge) =>
          params.linkStrength /
          Math.max(1, Math.min(edge.source.degree, edge.target.degree)),
      );
    // Graphs Plus balances an uncapped -1000 charge with 250-unit links and
    // 0.1 centering. One degree-weighted spring keeps hubs from over-pulling.
    simulation.force("x").strength(params.centering);
    simulation.force("y").strength(params.centering);
    simulation.velocityDecay(
      dragging === null
        ? params.velocityDecay
        : Math.min(params.velocityDecay, 0.35),
    );
    collision.radius((node) =>
      Math.max(params.collideRadius, 2 + Math.sqrt(node.degree)),
    );
  }
  function init(message) {
    stopTimer();
    simulation?.stop();
    revision = message.revision;
    paused = message.paused;
    dragging = null;
    interval = FRAME_INTERVAL_MS;
    Object.assign(params, message.params);
    const seed = scatterSeed(message.nodeCount);
    nodes = Array.from({ length: message.nodeCount }, (_, id) => ({
      id,
      x: Number.isFinite(message.positions[id * 3])
        ? message.positions[id * 3]
        : seed[id * 3],
      y: Number.isFinite(message.positions[id * 3 + 1])
        ? message.positions[id * 3 + 1]
        : seed[id * 3 + 1],
      degree: 0,
      anchorX: message.anchors?.[id * 2] || 0,
      anchorY: message.anchors?.[id * 2 + 1] || 0,
    }));
    const links = [];
    for (let i = 0; i < message.edges.length; i += 2) {
      const source = message.edges[i],
        target = message.edges[i + 1];
      links.push({ source, target });
      nodes[source].degree++;
      nodes[target].degree++;
    }
    simulation = forceSimulation(nodes, 2)
      .force("charge", forceManyBody())
      .force(
        "link",
        forceLink(links).id((node) => node.id),
      )
      .force(
        "x",
        forceX((node) => node.anchorX),
      )
      .force(
        "y",
        forceY((node) => node.anchorY),
      )
      .force("collide", collision)
      .alphaMin(ALPHA_MIN)
      .stop();
    applyParams();
    snapshot();
    if (!nodes.length) snapshot("end");
    else schedule();
  }
  function reheat(alpha = 0.3) {
    if (!simulation) return;
    simulation.alpha(Math.max(simulation.alpha(), alpha));
    schedule();
  }
  function dragStart(id) {
    const node = nodes[id];
    if (!node || !simulation) return;
    dragging = id;
    node.fx = node.x;
    node.fy = node.y;
    simulation.alphaTarget(0.3);
    interval = DRAG_INTERVAL_MS;
    applyParams();
    stopTimer();
    reheat(0.12);
  }
  function dragEnd() {
    const node = nodes[dragging];
    if (node) {
      node.fx = null;
      node.fy = null;
    }
    dragging = null;
    simulation?.alphaTarget(0);
    interval = FRAME_INTERVAL_MS;
    applyParams();
  }
  return {
    handle(message) {
      if (message.type === "init") {
        init(message);
        return;
      }
      if (message.revision !== revision) return;
      switch (message.type) {
        case "params":
          Object.assign(params, message.params);
          applyParams();
          reheat();
          break;
        case "drag-start":
          dragStart(message.id);
          break;
        case "drag-move": {
          const node = nodes[message.id];
          if (!node || dragging !== message.id) break;
          node.fx = message.x;
          node.fy = message.y;
          node.x = message.x;
          node.y = message.y;
          snapshot();
          break;
        }
        case "drag-end":
          dragEnd();
          break;
        case "pause":
          paused = true;
          stopTimer();
          break;
        case "resume":
          paused = false;
          if (simulation?.alpha() >= ALPHA_MIN) schedule();
          break;
        case "step":
          step();
          break;
        case "stop":
          paused = true;
          stopTimer();
          simulation?.stop();
          break;
      }
    },
  };
}
