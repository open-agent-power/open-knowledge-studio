// Camera easing and fit adapted from Graphs Plus (MIT, John Morabito).
// Velocities and easing are time-normalized so displays share the same motion.
const MIN_SCALE = 0.03;
const MAX_SCALE = 6;
const FRAME_MS = 1000 / 60;
const clampScale = (scale) => Math.max(MIN_SCALE, Math.min(MAX_SCALE, scale));

export function createCamera() {
  return {
    x: 0,
    y: 0,
    scale: 1,
    targetScale: 1,
    vx: 0,
    vy: 0,
    anchor: null,
    flight: null,
  };
}

export function screenPoint(camera, x, y, width, height) {
  return {
    x: width / 2 + (x - camera.x) * camera.scale,
    y: height / 2 + (y - camera.y) * camera.scale,
  };
}

export function worldPoint(camera, x, y, width, height) {
  return {
    x: camera.x + (x - width / 2) / camera.scale,
    y: camera.y + (y - height / 2) / camera.scale,
  };
}

export function setCamera(camera, next) {
  camera.x = next.x;
  camera.y = next.y;
  camera.scale = camera.targetScale = clampScale(next.scale);
  camera.vx = camera.vy = 0;
  camera.anchor = camera.flight = null;
}

export function fitCamera(nodes, width, height, padding = 64) {
  const placed = nodes.filter(
    (node) => Number.isFinite(node.x) && Number.isFinite(node.y),
  );
  if (!placed.length || width <= 0 || height <= 0) return null;
  let left = Infinity,
    top = Infinity,
    right = -Infinity,
    bottom = -Infinity;
  for (const node of placed) {
    const radius = node.radius || 7;
    left = Math.min(left, node.x - radius);
    right = Math.max(right, node.x + radius);
    top = Math.min(top, node.y - radius);
    bottom = Math.max(bottom, node.y + radius);
  }
  const margin = Math.min(padding, width / 4, height / 4);
  const maximum = placed.length > 1 && placed.length <= 80 ? 3 : 1.2;
  return {
    x: (left + right) / 2,
    y: (top + bottom) / 2,
    scale: Math.min(
      maximum,
      clampScale(
        Math.min(
          (width - margin * 2) / Math.max(1, right - left),
          (height - margin * 2) / Math.max(1, bottom - top),
        ),
      ),
    ),
  };
}

export function zoomAt(camera, factor, point, width, height) {
  const next = clampScale(camera.targetScale * factor);
  const anchor = point || { x: width / 2, y: height / 2 };
  camera.anchor = {
    ...anchor,
    world: worldPoint(camera, anchor.x, anchor.y, width, height),
  };
  camera.targetScale = next;
  camera.flight = null;
  camera.vx = camera.vy = 0;
}

export function panBy(camera, dx, dy, elapsed = FRAME_MS) {
  camera.x -= dx / camera.scale;
  camera.y -= dy / camera.scale;
  camera.vx =
    camera.vx * 0.8 - (dx / Math.max(1, elapsed) / camera.scale) * 0.2;
  camera.vy =
    camera.vy * 0.8 - (dy / Math.max(1, elapsed) / camera.scale) * 0.2;
  camera.anchor = camera.flight = null;
  camera.targetScale = camera.scale;
}

export function stopCamera(camera) {
  camera.vx = camera.vy = 0;
  camera.anchor = camera.flight = null;
  camera.targetScale = camera.scale;
}

export function stepCamera(
  camera,
  elapsed,
  reducedMotion = false,
  panning = false,
  width = 0,
  height = 0,
) {
  const dt = Math.max(1, Math.min(64, elapsed));
  const keep = reducedMotion ? 0 : Math.pow(0.85, dt / FRAME_MS);
  let moving = false;
  if (camera.flight) {
    camera.x = camera.flight.x + (camera.x - camera.flight.x) * keep;
    camera.y = camera.flight.y + (camera.y - camera.flight.y) * keep;
    moving =
      Math.hypot(camera.x - camera.flight.x, camera.y - camera.flight.y) *
        camera.scale >
      0.2;
    if (!moving) {
      camera.x = camera.flight.x;
      camera.y = camera.flight.y;
      camera.flight = null;
    }
  }
  if (Math.abs(camera.scale - camera.targetScale) > 0.0001) {
    camera.scale =
      camera.targetScale + (camera.scale - camera.targetScale) * keep;
    if (Math.abs(camera.scale - camera.targetScale) <= 0.0001)
      camera.scale = camera.targetScale;
    if (camera.anchor) {
      camera.x =
        camera.anchor.world.x - (camera.anchor.x - width / 2) / camera.scale;
      camera.y =
        camera.anchor.world.y - (camera.anchor.y - height / 2) / camera.scale;
    }
    moving = true;
  }
  if (!panning && (camera.vx || camera.vy)) {
    const decay = reducedMotion ? 0 : Math.pow(0.9, dt / FRAME_MS);
    const distance = reducedMotion
      ? 0
      : (1 - decay) / (-Math.log(0.9) / FRAME_MS);
    camera.x += camera.vx * distance;
    camera.y += camera.vy * distance;
    camera.vx *= decay;
    camera.vy *= decay;
    if (Math.hypot(camera.vx, camera.vy) * camera.scale < 0.002)
      camera.vx = camera.vy = 0;
    moving ||= Boolean(camera.vx || camera.vy);
  }
  return moving;
}
