// Orbit projection is independent of SVG: x/y/z remain world coordinates.
const TAU = Math.PI * 2;
const PITCH_LIMIT = Math.PI / 2 - 0.015;

export function createOrbit({ yaw = -0.32, pitch = 0.22, distance = 1400,
  target = { x: 0, y: 0, z: 0 }, fov = Math.PI / 4, near = 1 } = {}) {
  return { yaw, pitch: Math.max(-PITCH_LIMIT, Math.min(PITCH_LIMIT, pitch)),
    distance: Math.max(near * 2, distance), target: { ...target }, fov, near };
}

export function rotateOrbit(camera, dx, dy) {
  return createOrbit({ ...camera,
    yaw: ((camera.yaw + dx * 0.006 + Math.PI) % TAU + TAU) % TAU - Math.PI,
    pitch: camera.pitch + dy * 0.006 });
}

// Fit in world space before projecting: a near-plane crossing otherwise makes
// the 2D fit chase enormous perspective coordinates and lose the whole graph.
export function fitOrbit(camera, points) {
  if (!points.length) return camera;
  const bounds = { min: { x: Infinity, y: Infinity, z: Infinity },
    max: { x: -Infinity, y: -Infinity, z: -Infinity } };
  for (const point of points) for (const axis of ['x', 'y', 'z']) {
    const value = point[axis] ?? 0;
    bounds.min[axis] = Math.min(bounds.min[axis], value);
    bounds.max[axis] = Math.max(bounds.max[axis], value);
  }
  const target = Object.fromEntries(['x', 'y', 'z'].map(axis =>
    [axis, (bounds.min[axis] + bounds.max[axis]) / 2]));
  const radius = Math.max(...points.map(point => Math.hypot(
    point.x - target.x, point.y - target.y, (point.z ?? 0) - target.z)));
  return createOrbit({ ...camera, target,
    distance: Math.max(1400, radius / Math.sin(camera.fov / 2) * 1.1) });
}

// Positive depth is closer to the camera. Paint ascending depth (far first).
// fov is vertical, in radians; scale is pixels per world unit at this depth.
export function project3D(point, camera, width, height) {
  const cy = Math.cos(camera.yaw), sy = Math.sin(camera.yaw);
  const cp = Math.cos(camera.pitch), sp = Math.sin(camera.pitch);
  const x = point.x - camera.target.x, y = point.y - camera.target.y;
  const z = (point.z ?? 0) - camera.target.z;
  const rx = cy * x + sy * z, rz = -sy * x + cy * z;
  const ry = cp * y - sp * rz, depth = sp * y + cp * rz;
  const distance = camera.distance - depth;
  const scale = height / (2 * Math.tan(camera.fov / 2) * Math.max(camera.near, distance));
  return { x: width / 2 + rx * scale, y: height / 2 + ry * scale,
    depth, scale, visible: distance > camera.near };
}

// Inverse on the camera-facing plane passing through the original node.
// Keep project3D(node).depth from pointerdown; dragging then preserves that plane.
export function unproject3D(screen, camera, width, height, depth) {
  const scale = height / (2 * Math.tan(camera.fov / 2) * (camera.distance - depth));
  const rx = (screen.x - width / 2) / scale, ry = (screen.y - height / 2) / scale;
  const cy = Math.cos(camera.yaw), sy = Math.sin(camera.yaw);
  const cp = Math.cos(camera.pitch), sp = Math.sin(camera.pitch);
  const y = cp * ry + sp * depth, rz = -sp * ry + cp * depth;
  return { x: camera.target.x + cy * rx - sy * rz,
    y: camera.target.y + y, z: camera.target.z + sy * rx + cy * rz };
}

export function depthOrder(a, b) { return a.depth - b.depth; }

// d3-force-3d runs off the main thread. The caller paints projected snapshots.
export function create3DLayout(items, links, options = {}) {
  const extent = Math.max(100, 32 * Math.sqrt(items.length));
  const nodes = items.map((item, i) => {
    const z = 1 - 2 * (i + 0.5) / items.length, angle = i * 2.399963;
    const radius = Math.sqrt(1 - z * z) * extent;
    return { ...item, x: item.x ?? Math.cos(angle) * radius,
      y: item.y ?? Math.sin(angle) * radius, z: item.z ?? z * extent };
  });
  const indices = new Map(nodes.map((node, i) => [node.id, i]));
  const edges = links.filter(edge => indices.has(edge.from) && indices.has(edge.to) && edge.from !== edge.to)
    .map(edge => ({ ...edge, source: nodes[indices.get(edge.from)], target: nodes[indices.get(edge.to)] }));
  const params = { repel: options.repel ?? 3300, linkDistance: options.distance ?? 160,
    centering: options.center ?? 0.003, linkStrength: 1, velocityDecay: 0.4 };
  let alpha = 1, dead = false, dragging = null;
  const worker = new Worker(options.workerUrl || new URL('../vendor/graph-engine/graph-3d.worker.js', import.meta.url));
  const post = message => { if (!dead) worker.postMessage({ ...message, revision: 1 }); };
  worker.onmessage = ({ data }) => {
    if (dead || data.revision !== 1) return;
    nodes.forEach((node, i) => {
      if (i === dragging) return;
      node.x = data.positions[i * 3]; node.y = data.positions[i * 3 + 1]; node.z = data.positions[i * 3 + 2];
    });
    alpha = data.type === 'end' ? 0 : data.alpha;
    options.onTick?.(data.type);
  };
  const destroy = () => {
    if (dead) return;
    dead = true; alpha = 0; worker.onmessage = null; worker.onerror = null;
    worker.onmessageerror = null; worker.terminate();
  };
  const fail = event => { destroy(); options.onError?.(event.message || 'Graph 3D worker failed'); };
  worker.onerror = fail;
  worker.onmessageerror = fail;
  post({ type: 'init', nodeCount: nodes.length,
    positions: Float32Array.from(nodes.flatMap(node => [node.x, node.y, node.z])),
    anchors: Float32Array.from(nodes.flatMap(node => {
      const anchor = options.anchor?.(node); return [anchor?.x || 0, anchor?.y || 0, anchor?.z || 0];
    })),
    edges: Uint32Array.from(edges.flatMap(edge => [indices.get(edge.from), indices.get(edge.to)])),
    params, paused: false });
  return { nodes, edges, get alpha() { return alpha; }, step: () => !dead && alpha > 0.01,
    reheat() { if (!dead) { alpha = 0.3; post({ type: 'params', params }); } },
    dragStart(id) { dragging = indices.get(id); if (dragging !== undefined) post({ type: 'drag-start', id: dragging }); },
    dragMove(id, x, y, z) {
      const index = indices.get(id);
      if (index === undefined || index !== dragging) return;
      Object.assign(nodes[index], { x, y, z }); post({ type: 'drag-move', id: index, x, y, z });
    },
    dragEnd() { dragging = null; post({ type: 'drag-end' }); }, destroy };
}
