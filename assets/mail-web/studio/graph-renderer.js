import { EdgeMesh } from "../vendor/graph-engine/edge-mesh.js";
import { easePositions } from "../vendor/graph-engine/position-smoothing.js";
import {
  createCamera,
  fitCamera,
  panBy,
  screenPoint,
  setCamera as restoreCamera,
  stepCamera,
  stopCamera,
  worldPoint,
  zoomAt,
} from "./graph-camera.js";

// Camera gestures and label fading adapted from Graphs Plus (MIT).
// EdgeMesh and position interpolation are reused from Advanced Graph View (MIT).
const FRAME_MS = 1000 / 60;
const EDGE_COLORS = {
  contains: 0x9aacc3,
  cites: 0x879fc3,
  states: 0x91afa4,
  source: 0xa294b8,
  shared_tag: 0xb6a583,
};
const dashed = (edge) =>
  edge.pending || edge.dashed || edge.type === "shared_tag";
const EDGE_LABELS = {
  contains: "包含",
  cites: "引用",
  states: "记录",
  source: "来源",
};

// The grid bounds the collision work to nearby labels and visible node dots.
export function createCollisionGrid(cellSize = 64) {
  const cells = new Map();
  function visit(box, callback) {
    for (
      let y = Math.floor(box.top / cellSize);
      y <= Math.floor(box.bottom / cellSize);
      y++
    ) {
      for (
        let x = Math.floor(box.left / cellSize);
        x <= Math.floor(box.right / cellSize);
        x++
      ) {
        if (callback(x, y)) return true;
      }
    }
    return false;
  }
  return {
    add(box) {
      visit(box, (x, y) => {
        if (!cells.has(y)) cells.set(y, new Map());
        const row = cells.get(y);
        if (!row.has(x)) row.set(x, []);
        row.get(x).push(box);
      });
    },
    overlaps(box) {
      return visit(box, (x, y) =>
        (cells.get(y)?.get(x) || []).some(
          (other) =>
            box.left < other.right &&
            box.right > other.left &&
            box.top < other.bottom &&
            box.bottom > other.top,
        ),
      );
    },
  };
}

export function createRenderer(host, callbacks = {}, options = {}) {
  const PIXI = window.PIXI;
  const camera = createCamera();
  const config = {
    labels: true,
    nodeScale: 1,
    edgeWidth: 1,
    arrows: false,
    reducedMotion: Boolean(options.reducedMotion),
  };
  const sprites = new Map(),
    ringSprites = new Map(),
    labels = new Map(),
    labelLayouts = new Map(),
    held = new Map(),
    positioned = new Set();
  const measurement = document.createElement("canvas").getContext("2d");
  let nodes = [],
    edges = [],
    byId = new Map(),
    orderedLabels = [],
    neighbors = new Set();
  let focusState = { selected: null, hover: null, keyboard: null };
  let current = new Float32Array(),
    targets = new Float32Array();
  let width = host.clientWidth,
    height = host.clientHeight;
  let app,
    world,
    edgeLayer,
    nodeLayer,
    labelLayer,
    regionLayer,
    lassoShape,
    rings,
    pendingLines,
    circleTexture,
    solidRingTexture,
    dashedRingTexture,
    dashTexture,
    dashSource;
  let initPending = true,
    appReady = false,
    resourcesDisposed = false;
  const temporaryGraphics = new Set();
  let meshes = [],
    edgeViews = [],
    focusedViews = [],
    edgeTexts = [],
    structure = [],
    frame = 0,
    previousTime = 0,
    focusRevision = 0;
  let textBudget = 4,
    labelFrame = 0,
    edgeGeometryDirty = true,
    renderedScale = NaN;
  let dead = false,
    paused = false,
    initialized = false,
    fitted = false,
    interacted = false,
    fitAfterSettled = false;
  let drag = null,
    pinch = null,
    lasso = false,
    lassoGesture = null;
  const lassoSelected = new Set();
  const degrees = new Map();
  const pointers = new Map(),
    events = new AbortController();
  const activeId = () =>
    drag?.id && drag.moved
      ? drag.id
      : (focusState.hover ?? focusState.keyboard ?? focusState.selected);
  const placed = (node) => Number.isFinite(node.x) && Number.isFinite(node.y);
  const insetTop = Math.max(0, Number(options.insetTop) || 0);
  const fitPadding = options.fitPadding ?? 64;
  const viewportHeight = () =>
    Math.max(
      1,
      height - insetTop - Math.max(0, Number(options.insetBottom) || 0),
    );
  const screenRadius = (node) =>
    options.screenSize
      ? Math.max(
          node.data?.children ? 12 : 3,
          (node.radius || 7) *
            config.nodeScale *
            (node.data?.children
              ? camera.scale
              : Math.min(1, Math.sqrt(camera.scale))),
        )
      : (node.radius || 7) * config.nodeScale * Math.sqrt(camera.scale);
  const point = (x, y) => {
    const p = screenPoint(camera, x, y, width, viewportHeight());
    p.y += insetTop;
    return p;
  };
  const unproject = (p) =>
    worldPoint(camera, p.x, p.y - insetTop, width, viewportHeight());
  const viewportPoint = (p) => ({ ...p, y: p.y - insetTop });
  const nodeTitle = (node) => String(node.title || node.data?.title || node.id);

  function schedule() {
    if (!frame && initialized && !dead && !paused && !document.hidden)
      frame = requestAnimationFrame(draw);
  }

  function refreshFocus(topology = false) {
    focusRevision++;
    neighbors = new Set();
    if (topology) degrees.clear();
    const focus = activeId();
    for (const edge of edges) {
      if (topology) {
        degrees.set(edge.from, (degrees.get(edge.from) || 0) + 1);
        degrees.set(edge.to, (degrees.get(edge.to) || 0) + 1);
      }
      if (edge.from !== focus && edge.to !== focus) continue;
      neighbors.add(edge.from);
      neighbors.add(edge.to);
    }
    orderedLabels = [...nodes].sort((a, b) => priority(b) - priority(a));
    if (topology) rebuildEdges();
    else updateEdgeFocus();
    schedule();
  }

  function priority(node) {
    if (node.id === activeId()) return 100;
    if (node.id === focusState.selected || node.id === focusState.keyboard)
      return 90;
    if (node.queryHit) return 80;
    if (node.data?.children) return 60;
    return neighbors.has(node.id)
      ? 40
      : Math.min(30, degrees.get(node.id) || 0);
  }

  function clearMeshes() {
    for (const group of meshes) group.mesh.destroy();
    meshes = [];
  }

  function rebuildEdges() {
    if (!initialized) return;
    clearMeshes();
    const parallel = new Map(),
      groups = new Map(),
      focus = activeId();
    edgeViews = [];
    for (const [index, edge] of edges.entries()) {
      const source = byId.get(edge.from),
        target = byId.get(edge.to);
      if (!source || !target) continue;
      const key =
        edge.from < edge.to
          ? `${edge.from}\0${edge.to}`
          : `${edge.to}\0${edge.from}`;
      if (!parallel.has(key)) parallel.set(key, []);
      const adjacent =
        focus !== null && (edge.from === focus || edge.to === focus);
      const view = {
        index,
        edge,
        source,
        target,
        adjacent,
        offset: 0,
        points: {},
      };
      parallel.get(key).push(view);
      edgeViews.push(view);
      const groupKey = `${edge.type || "cites"}|${Boolean(dashed(edge))}|${Boolean(edge.pending)}`;
      if (!groups.has(groupKey)) groups.set(groupKey, []);
      groups.get(groupKey).push(view);
    }
    for (const views of parallel.values())
      views.forEach((view, index) => {
        view.offset = (index - (views.length - 1) / 2) * 5;
      });
    for (const views of groups.values()) {
      const color = views[0].edge.pending
        ? 0xa88b58
        : EDGE_COLORS[views[0].edge.type] || 0xa6b7cc;
      addMesh(views, color, focus === null ? 0.7 : 0.12, false);
    }
    edgeGeometryDirty = true;
    updateEdgeFocus();
  }

  function addMesh(views, color, alpha, highlight) {
    const pairs = Uint32Array.from(
      views.flatMap((_, index) => [index * 2, index * 2 + 1]),
    );
    const mesh = new EdgeMesh(pairs, color, highlight ? 0 : alpha);
    edgeLayer.addChild(mesh.mesh);
    const isDashed = Boolean(dashed(views[0].edge));
    let uvBuffer = null;
    if (isDashed) {
      mesh.mesh.texture = dashTexture;
      uvBuffer = mesh.mesh.geometry.getBuffer("aUV");
    }
    meshes.push({
      views,
      mesh,
      highlight,
      dashed: isDashed,
      uvBuffer,
      dirty: true,
      alpha: highlight ? 0 : alpha,
      targetAlpha: alpha,
      positions: new Float32Array(views.length * 4),
    });
  }

  function updateEdgeFocus() {
    if (!initialized) return;
    const focus = activeId();
    meshes = meshes.filter((group) => {
      if (group.highlight) {
        group.mesh.destroy();
        return false;
      }
      group.targetAlpha = focus === null ? 0.7 : 0.12;
      return true;
    });
    for (const view of edgeViews)
      view.adjacent =
        focus !== null && (view.edge.from === focus || view.edge.to === focus);
    focusedViews = edgeViews.filter((view) => view.adjacent);
    const solid = focusedViews.filter((view) => !dashed(view.edge));
    const broken = focusedViews.filter((view) => dashed(view.edge));
    if (solid.length) addMesh(solid, 0x6588be, 0.85, true);
    if (broken.length) addMesh(broken, 0x6588be, 0.85, true);
  }

  function edgePoints(view) {
    const p = view.points;
    p.x1 = view.source.x;
    p.y1 = view.source.y;
    p.x2 = view.target.x;
    p.y2 = view.target.y;
    if (!placed(view.source) || !placed(view.target)) {
      p.x1 = p.y1 = p.x2 = p.y2 = 0;
      return p;
    }
    if (!view.offset) return p;
    const dx = p.x2 - p.x1,
      dy = p.y2 - p.y1,
      distance = Math.hypot(dx, dy) || 1;
    const direction = view.edge.from < view.edge.to ? 1 : -1;
    const offset = (view.offset / camera.scale) * direction;
    const ox = (-dy / distance) * offset,
      oy = (dx / distance) * offset;
    p.x1 += ox;
    p.y1 += oy;
    p.x2 += ox;
    p.y2 += oy;
    return p;
  }

  function updateMesh(group) {
    group.views.forEach((view, index) => {
      const p = view.points,
        base = index * 4;
      group.positions[base] = p.x1;
      group.positions[base + 1] = p.y1;
      group.positions[base + 2] = p.x2;
      group.positions[base + 3] = p.y2;
      if (group.uvBuffer) {
        const uvs = group.uvBuffer.data,
          uv = index * 8;
        const repeat =
          (Math.hypot(p.x2 - p.x1, p.y2 - p.y1) * camera.scale) / 10;
        uvs[uv] = 0;
        uvs[uv + 1] = 0;
        uvs[uv + 2] = 0;
        uvs[uv + 3] = 1;
        uvs[uv + 4] = repeat;
        uvs[uv + 5] = 0;
        uvs[uv + 6] = repeat;
        uvs[uv + 7] = 1;
      }
    });
    const lineWidth = config.edgeWidth / camera.scale;
    if (group.width !== lineWidth) {
      group.mesh.setWidth(lineWidth);
      group.width = lineWidth;
    }
    group.mesh.updatePositions(group.positions);
    group.uvBuffer?.update();
    group.dirty = false;
  }

  function paintEdges(elapsed) {
    let moving = false;
    const fade = config.reducedMotion
      ? 1
      : 1 - Math.pow(0.9, elapsed / FRAME_MS);
    if (edgeGeometryDirty) for (const view of edgeViews) edgePoints(view);
    for (const group of meshes) {
      group.alpha += (group.targetAlpha - group.alpha) * fade;
      group.mesh.setAlpha(group.alpha);
      if (Math.abs(group.targetAlpha - group.alpha) > 0.005) moving = true;
      if (edgeGeometryDirty || group.dirty) updateMesh(group);
    }
    edgeGeometryDirty = false;
    pendingLines.clear();
    let labelCount = 0;
    for (const view of focusedViews) {
      if (
        !config.arrows &&
        (options.showEdgeLabels === false || labelCount >= 12)
      )
        break;
      if (!placed(view.source) || !placed(view.target)) continue;
      const p = view.points,
        a = point(p.x1, p.y1),
        b = point(p.x2, p.y2);
      const dx = b.x - a.x,
        dy = b.y - a.y,
        length = Math.hypot(dx, dy) || 1;
      if (config.arrows && view.adjacent && length > 20) {
        const distance = screenRadius(view.target) + 3;
        const x = b.x - (dx / length) * distance,
          y = b.y - (dy / length) * distance;
        pendingLines
          .moveTo(x, y)
          .lineTo(
            x - (dx / length) * 7 - (dy / length) * 3,
            y - (dy / length) * 7 + (dx / length) * 3,
          )
          .lineTo(
            x - (dx / length) * 7 + (dy / length) * 3,
            y - (dy / length) * 7 - (dx / length) * 3,
          )
          .closePath()
          .fill({ color: 0x6588be, alpha: 0.8 });
      }
      if (
        !view.adjacent ||
        options.showEdgeLabels === false ||
        camera.scale < 0.3 ||
        labelCount >= 12
      )
        continue;
      let label = edgeTexts[labelCount];
      const text =
        view.edge.label ||
        view.edge.type_label ||
        EDGE_LABELS[view.edge.type] ||
        view.edge.type ||
        "关联";
      if (!label || label.text !== text) {
        if (!textBudget) {
          moving = true;
          continue;
        }
        textBudget--;
        if (!label) {
          label = new PIXI.Text({
            text,
            style: {
              fontFamily: "Segoe UI, Microsoft YaHei, sans-serif",
              fontSize: 10,
              fill: 0x566d8b,
            },
          });
          label.visible = false;
          label.anchor.set(0.5, 1);
          labelLayer.addChild(label);
          edgeTexts.push(label);
        } else label.text = text;
      }
      labelCount++;
      label.position.set((a.x + b.x) / 2, (a.y + b.y) / 2 - 3);
      label.visible = true;
    }
    for (let index = labelCount; index < edgeTexts.length; index++)
      edgeTexts[index].visible = false;
    return moving;
  }

  function labelLayout(node) {
    const title = nodeTitle(node),
      maxWidth =
        priority(node) >= 80
          ? Math.min(320, width - 40)
          : nodes.length >= 80
            ? 120
            : width < 500
              ? 150
              : 200;
    let layout = labelLayouts.get(node.id);
    if (layout?.title === title && layout.maxWidth === maxWidth) return layout;
    measurement.font = "13px Segoe UI, Microsoft YaHei, sans-serif";
    let text = title;
    if (measurement.measureText(title).width > maxWidth) {
      text = "";
      for (const character of title) {
        if (measurement.measureText(text + character + "…").width > maxWidth)
          break;
        text += character;
      }
      text += "…";
    }
    layout = {
      title,
      text,
      maxWidth,
      measuredWidth: measurement.measureText(text).width,
    };
    labelLayouts.set(node.id, layout);
    return layout;
  }

  function paintLabels(elapsed) {
    const focus = activeId();
    const occupied = createCollisionGrid();
    const occupiedLabels = createCollisionGrid();
    for (const node of nodes) {
      if (!placed(node)) continue;
      const p = point(node.x, node.y),
        radius = screenRadius(node) + 2;
      if (
        p.x + radius < 0 ||
        p.x - radius > width ||
        p.y + radius < 0 ||
        p.y - radius > height
      )
        continue;
      occupied.add({
        left: p.x - radius,
        right: p.x + radius,
        top: p.y - radius,
        bottom: p.y + radius,
      });
    }
    let moving = false,
      count = 0;
    const fade = 1 - Math.pow(0.9, elapsed / FRAME_MS);
    for (const item of labels.values()) item.text.visible = false;
    for (const node of orderedLabels) {
      if (count >= 160) break;
      if (!placed(node)) continue;
      const p = point(node.x, node.y),
        important = priority(node) >= 40 || (degrees.get(node.id) || 0) >= 2;
      const zoomAlpha =
        nodes.length < 80 || important
          ? 1
          : Math.max(0.65, Math.min(1, Math.log2(camera.scale) + 1));
      const targetAlpha =
        config.labels === false
          ? 0
          : zoomAlpha *
            (focus === null || node.id === focus || neighbors.has(node.id)
              ? 1
              : 0.2);
      if (
        targetAlpha < 0.01 ||
        p.x < -100 ||
        p.x > width + 100 ||
        p.y < -30 ||
        p.y > height + 30
      )
        continue;
      const layout = labelLayout(node),
        offset = screenRadius(node) + 7;
      let placement = null;
      for (const [candidateX, candidateY] of [
        [p.x, p.y + offset],
        [p.x, p.y - offset - 18],
        [p.x + offset + layout.measuredWidth / 2, p.y - 8],
        [p.x - offset - layout.measuredWidth / 2, p.y - 8],
      ]) {
        const box = {
          left: candidateX - layout.measuredWidth / 2 - 4,
          right: candidateX + layout.measuredWidth / 2 + 4,
          top: candidateY - 2,
          bottom: candidateY + 18,
        };
        if (
          box.left < 4 ||
          box.right > width - 4 ||
          box.top < 4 ||
          box.bottom > height - 4
        )
          continue;
        // Keep focused/connected names readable in dense clusters. White text
        // outlines separate them from dots; ordinary names avoid both dots and text.
        if ((important ? occupiedLabels : occupied).overlaps(box)) continue;
        placement = { x: candidateX, y: candidateY, box };
        break;
      }
      if (!placement) continue;
      let item = labels.get(node.id);
      if (!item || item.text.text !== layout.text) {
        if (!textBudget) {
          moving = true;
          continue;
        }
        textBudget--;
        if (!item) {
          const label = new PIXI.Text({
            text: layout.text,
            style: {
              fontFamily: "Segoe UI, Microsoft YaHei, sans-serif",
              fontSize: 13,
              fill: 0x4e627e,
              stroke: { color: 0xffffff, width: 3 },
            },
          });
          label.visible = false;
          label.anchor.set(0.5, 0);
          labelLayer.addChild(label);
          item = {
            text: label,
            alpha: config.reducedMotion ? targetAlpha : 0,
            lastVisible: labelFrame,
          };
          labels.set(node.id, item);
        } else item.text.text = layout.text;
      }
      occupied.add(placement.box);
      occupiedLabels.add(placement.box);
      count++;
      item.alpha +=
        (targetAlpha - item.alpha) * (config.reducedMotion ? 1 : fade);
      if (Math.abs(item.alpha - targetAlpha) > 0.005) moving = true;
      item.lastVisible = labelFrame;
      item.text.alpha = item.alpha;
      item.text.position.set(placement.x, placement.y);
      item.text.visible = true;
    }
    if (labels.size > 320) {
      const hidden = [...labels.entries()]
        .filter(([, item]) => !item.text.visible)
        .sort((a, b) => a[1].lastVisible - b[1].lastVisible);
      for (const [id, item] of hidden) {
        item.text.destroy();
        labels.delete(id);
        if (labels.size <= 320) break;
      }
    }
    return moving;
  }

  function paintNodes(elapsed) {
    const focus = activeId();
    for (const ring of ringSprites.values()) ring.visible = false;
    let moving = false;
    const fade = config.reducedMotion
      ? 1
      : 1 - Math.pow(0.9, elapsed / FRAME_MS);
    for (const node of nodes) {
      const sprite = sprites.get(node.id);
      sprite.visible = placed(node);
      if (!sprite.visible) continue;
      sprite.position.set(node.x, node.y);
      sprite.width = sprite.height = (screenRadius(node) * 2) / camera.scale;
      const alpha =
        focus === null || node.id === focus || neighbors.has(node.id)
          ? 1
          : 0.22;
      sprite.alpha += (alpha - sprite.alpha) * fade;
      if (Math.abs(sprite.alpha - alpha) > 0.005) moving = true;
      const active =
        node.id === focusState.selected ||
        node.id === focusState.hover ||
        node.id === focusState.keyboard ||
        lassoSelected.has(node.id);
      if (!active && !node.pending && !node.queryHit && !node.dayActive)
        continue;
      const p = point(node.x, node.y),
        radius = screenRadius(node) + 3;
      const color = active
        ? 0x526fae
        : node.queryHit
          ? 0xe49a47
          : node.dayActive
            ? 0x7d9bce
            : 0xa88b58;
      let ring = ringSprites.get(node.id);
      if (!ring) {
        ring = new PIXI.Sprite(solidRingTexture);
        ring.anchor.set(0.5);
        rings.addChild(ring);
        ringSprites.set(node.id, ring);
      }
      ring.texture =
        node.pending && !active && !node.queryHit && !node.dayActive
          ? dashedRingTexture
          : solidRingTexture;
      ring.position.set(p.x, p.y);
      ring.width = ring.height = radius * 2;
      ring.tint = color;
      ring.alpha = 0.9;
      ring.visible = true;
    }
    return moving;
  }

  function paintRegions() {
    regionLayer.clear();
    const grouped = new Map();
    for (const node of nodes) {
      if (!node.region || !placed(node)) continue;
      if (!grouped.has(node.region)) grouped.set(node.region, []);
      grouped.get(node.region).push(node);
    }
    for (const items of grouped.values()) {
      if (items.length < 2) continue;
      const left = Math.min(...items.map((node) => node.x)) - 75;
      const right = Math.max(...items.map((node) => node.x)) + 75;
      const top = Math.min(...items.map((node) => node.y)) - 60;
      const bottom = Math.max(...items.map((node) => node.y)) + 60;
      regionLayer
        .ellipse(
          (left + right) / 2,
          (top + bottom) / 2,
          (right - left) / 2,
          (bottom - top) / 2,
        )
        .fill({ color: items[0].regionColor || "#dae4f3", alpha: 0.18 });
    }
  }

  function interpolate(elapsed) {
    const now = performance.now();
    nodes.forEach((node, index) => {
      let local =
        drag?.id === node.id && drag.moved ? drag.position : held.get(node.id);
      if (local?.until && local.until < now) {
        held.delete(node.id);
        local = null;
      }
      const x =
        local?.x ?? (Number.isFinite(node.targetX) ? node.targetX : node.x);
      const y =
        local?.y ?? (Number.isFinite(node.targetY) ? node.targetY : node.y);
      if (!Number.isFinite(x) || !Number.isFinite(y)) {
        current[index * 2] =
          current[index * 2 + 1] =
          targets[index * 2] =
          targets[index * 2 + 1] =
            0;
        return;
      }
      targets[index * 2] = x;
      targets[index * 2 + 1] = y;
      if (
        !positioned.has(node.id) ||
        !Number.isFinite(current[index * 2]) ||
        local
      ) {
        positioned.add(node.id);
        current[index * 2] = targets[index * 2];
        current[index * 2 + 1] = targets[index * 2 + 1];
      }
    });
    const moving = easePositions(
      current,
      targets,
      config.reducedMotion ? 1 : 1 - Math.pow(0.65, elapsed / FRAME_MS),
    );
    nodes.forEach((node, index) => {
      node.x = positioned.has(node.id) ? current[index * 2] : NaN;
      node.y = positioned.has(node.id) ? current[index * 2 + 1] : NaN;
    });
    return moving;
  }

  function draw(now) {
    frame = 0;
    if (dead || paused || document.hidden || !initialized) return;
    const elapsed = previousTime ? Math.min(64, now - previousTime) : FRAME_MS;
    previousTime = now;
    const layoutMoving = interpolate(elapsed);
    if (!interacted && (!fitted || layoutMoving) && nodes.some(placed)) {
      const bounds = nodes.map((node) => ({
        ...node,
        x: Number.isFinite(node.targetX) ? node.targetX : node.x,
        y: Number.isFinite(node.targetY) ? node.targetY : node.y,
      }));
      const initial = fitCamera(bounds, width, viewportHeight(), fitPadding);
      if (initial) {
        if (!fitted || config.reducedMotion) restoreCamera(camera, initial);
        else {
          camera.flight = { x: initial.x, y: initial.y };
          camera.targetScale = initial.scale;
        }
        fitted = true;
      }
    }
    const cameraMoving = stepCamera(
      camera,
      elapsed,
      config.reducedMotion,
      Boolean(drag && !drag.id),
      width,
      viewportHeight(),
    );
    world.position.set(
      width / 2 - camera.x * camera.scale,
      insetTop + viewportHeight() / 2 - camera.y * camera.scale,
    );
    world.scale.set(camera.scale);
    paintRegions();
    edgeGeometryDirty ||= layoutMoving || renderedScale !== camera.scale;
    textBudget = 4;
    labelFrame++;
    const edgesMoving = paintEdges(elapsed),
      nodesMoving = paintNodes(elapsed);
    renderedScale = camera.scale;
    const labelsMoving = paintLabels(elapsed);
    app.render();
    if (
      layoutMoving ||
      cameraMoving ||
      edgesMoving ||
      nodesMoving ||
      labelsMoving ||
      held.size
    )
      schedule();
  }

  function hitNode(p) {
    const location = unproject(p);
    let best = null,
      distance = Infinity;
    for (const node of nodes) {
      if (!placed(node)) continue;
      const reach = Math.max(8, screenRadius(node)) / camera.scale;
      const value = (node.x - location.x) ** 2 + (node.y - location.y) ** 2;
      if (value <= reach * reach && value < distance) {
        best = node;
        distance = value;
      }
    }
    return best;
  }

  function hover(p) {
    const id = p ? (hitNode(p)?.id ?? null) : null;
    if (focusState.hover === id) return;
    focusState.hover = id;
    app.canvas.style.cursor = id ? "pointer" : "grab";
    app.canvas.title = id ? nodeTitle(byId.get(id)) : "";
    const before = focusRevision;
    callbacks.onHover?.(id);
    if (focusRevision === before) refreshFocus();
  }

  function eventPoint(event) {
    const bounds = app.canvas.getBoundingClientRect();
    return { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
  }

  function pinchState() {
    const [a, b] = [...pointers.values()];
    return a && b
      ? {
          distance: Math.hypot(a.x - b.x, a.y - b.y),
          x: (a.x + b.x) / 2,
          y: (a.y + b.y) / 2,
        }
      : null;
  }

  function release(event) {
    if (lassoGesture?.id === event.pointerId) {
      const polygon = lassoGesture.points;
      lassoGesture = null;
      lasso = false;
      lassoShape.clear();
      app.canvas.style.cursor = "grab";
      if (event.type === "pointerup" && polygon.length > 2) {
        const ids = nodes
          .filter(
            (node) =>
              placed(node) &&
              options.insidePolygon(point(node.x, node.y), polygon),
          )
          .map((node) => node.id);
        lassoSelected.clear();
        ids.forEach((id) => lassoSelected.add(id));
        callbacks.onLasso?.(ids);
      } else callbacks.onLasso?.([]);
      schedule();
      return;
    }
    pointers.delete(event.pointerId);
    if (pinch) {
      if (pointers.size < 2) pinch = null;
      return;
    }
    if (!drag) return;
    const released = drag;
    drag = null;
    app.canvas.style.cursor = focusState.hover ? "pointer" : "grab";
    if (released.id && released.moved) {
      held.set(released.id, {
        ...released.position,
        until: performance.now() + 220,
      });
      callbacks.onDragEnd?.(released.id);
    } else if (!released.moved && event.type === "pointerup") {
      if (released.id) callbacks.onSelect?.(released.id);
      else callbacks.onBackground?.();
    }
    if (config.reducedMotion || performance.now() - released.time > 100)
      stopCamera(camera);
    refreshFocus();
  }

  function bindEvents() {
    const canvas = app.canvas,
      listen = (type, handler, settings = {}) =>
        canvas.addEventListener(type, handler, {
          ...settings,
          signal: events.signal,
        });
    listen(
      "wheel",
      (event) => {
        event.preventDefault();
        interacted = true;
        const delta =
          event.deltaY *
          (event.deltaMode === 1 ? 40 : event.deltaMode === 2 ? 800 : 1);
        zoomAt(
          camera,
          Math.pow(1.5, -delta / 120),
          delta < 0 ? viewportPoint(eventPoint(event)) : null,
          width,
          viewportHeight(),
        );
        callbacks.onCameraChange?.();
        schedule();
      },
      { passive: false },
    );
    listen("pointerdown", (event) => {
      if (event.button !== 0 && event.button !== 1) return;
      const p = eventPoint(event);
      if (lasso && event.button === 0) {
        if (lassoGesture) return;
        stopCamera(camera);
        lassoGesture = { id: event.pointerId, points: [p] };
        canvas.setPointerCapture(event.pointerId);
        event.preventDefault();
        return;
      }
      pointers.set(event.pointerId, p);
      canvas.setPointerCapture(event.pointerId);
      interacted = true;
      if (pointers.size === 2) {
        if (drag?.id && drag.moved) callbacks.onDragEnd?.(drag.id);
        drag = null;
        pinch = pinchState();
        stopCamera(camera);
        return;
      }
      const node = hitNode(p);
      stopCamera(camera);
      drag = {
        id: node?.id ?? null,
        start: p,
        last: p,
        time: performance.now(),
        moved: false,
      };
      canvas.style.cursor = "grabbing";
    });
    listen("pointermove", (event) => {
      const p = eventPoint(event),
        now = performance.now();
      if (lassoGesture) {
        if (lassoGesture.id !== event.pointerId) return;
        const points = lassoGesture.points,
          last = points.at(-1);
        if (Math.hypot(p.x - last.x, p.y - last.y) > 3) points.push(p);
        lassoShape.clear().moveTo(points[0].x, points[0].y);
        for (const next of points.slice(1)) lassoShape.lineTo(next.x, next.y);
        lassoShape
          .closePath()
          .fill({ color: 0x6386c5, alpha: 0.1 })
          .stroke({ color: 0x6386c5, width: 1.5 });
        schedule();
        return;
      }
      if (pointers.has(event.pointerId)) pointers.set(event.pointerId, p);
      if (pinch) {
        const next = pinchState();
        if (next && pinch.distance > 0) {
          camera.x -= (next.x - pinch.x) / camera.scale;
          camera.y -= (next.y - pinch.y) / camera.scale;
          zoomAt(
            camera,
            next.distance / pinch.distance,
            viewportPoint(next),
            width,
            viewportHeight(),
          );
          pinch = next;
          callbacks.onCameraChange?.();
          schedule();
        }
        return;
      }
      if (!drag) {
        hover(p);
        return;
      }
      if (
        !drag.moved &&
        Math.hypot(p.x - drag.start.x, p.y - drag.start.y) > 5
      ) {
        drag.moved = true;
        if (drag.id) {
          callbacks.onDragStart?.(drag.id);
          refreshFocus();
        }
      }
      if (drag.moved && drag.id) {
        drag.position = unproject(p);
        const node = byId.get(drag.id);
        if (node) {
          node.x = node.targetX = drag.position.x;
          node.y = node.targetY = drag.position.y;
        }
        edgeGeometryDirty = true;
        callbacks.onDragMove?.(drag.id, drag.position.x, drag.position.y);
      } else if (drag.moved) {
        panBy(camera, p.x - drag.last.x, p.y - drag.last.y, now - drag.time);
        callbacks.onCameraChange?.();
      }
      drag.last = p;
      drag.time = now;
      schedule();
    });
    listen("pointerup", release);
    listen("pointercancel", release);
    listen("lostpointercapture", (event) => {
      if (drag || lassoGesture)
        release({ pointerId: event.pointerId, type: "pointercancel" });
    });
    listen("pointerleave", () => {
      if (!drag) hover(null);
    });
    listen("mousedown", (event) => {
      if (event.button === 1) event.preventDefault();
    });
  }

  function update(nextNodes, nextEdges) {
    if (dead) return;
    const topologyChanged =
      nodes.length !== nextNodes.length ||
      nodes.some((node, index) => node !== nextNodes[index]) ||
      structure.length !== nextEdges.length ||
      structure.some((edge, index) => {
        const next = nextEdges[index];
        return (
          edge.from !== next.from ||
          edge.to !== next.to ||
          edge.type !== next.type ||
          edge.pending !== next.pending ||
          edge.dashed !== next.dashed
        );
      });
    structure = nextEdges.map(({ from, to, type, pending, dashed }) => ({
      from,
      to,
      type,
      pending,
      dashed,
    }));
    nodes = nextNodes;
    edges = nextEdges;
    byId = new Map(nodes.map((node) => [node.id, node]));
    current = Float32Array.from(nodes.flatMap((node) => [node.x, node.y]));
    targets = new Float32Array(current);
    for (const [id, sprite] of sprites)
      if (!byId.has(id)) {
        sprite.destroy();
        sprites.delete(id);
        held.delete(id);
        positioned.delete(id);
      }
    for (const [id, label] of labels)
      if (!byId.has(id)) {
        label.text.destroy();
        labels.delete(id);
        labelLayouts.delete(id);
      }
    for (const [id, ring] of ringSprites)
      if (!byId.has(id)) {
        ring.destroy();
        ringSprites.delete(id);
      }
    for (const id of labelLayouts.keys())
      if (!byId.has(id)) labelLayouts.delete(id);
    if (initialized) syncSprites();
    if (topologyChanged) refreshFocus(true);
    else {
      for (const view of edgeViews) view.edge = edges[view.index];
      orderedLabels = [...nodes].sort((a, b) => priority(b) - priority(a));
      schedule();
    }
  }

  function syncSprites() {
    for (const node of nodes) {
      let sprite = sprites.get(node.id);
      if (!sprite) {
        sprite = new PIXI.Sprite(circleTexture);
        sprite.anchor.set(0.5);
        sprite.eventMode = "none";
        nodeLayer.addChild(sprite);
        sprites.set(node.id, sprite);
      }
      sprite.tint = node.color ?? 0xaab8d1;
    }
  }

  function fit() {
    if (dead) return;
    const next = fitCamera(nodes, width, viewportHeight(), fitPadding);
    if (!next) return;
    interacted = fitted = true;
    stopCamera(camera);
    if (config.reducedMotion) restoreCamera(camera, next);
    else {
      camera.flight = { x: next.x, y: next.y };
      camera.targetScale = next.scale;
    }
    callbacks.onCameraChange?.();
    schedule();
  }

  function settled() {
    if (dead || interacted) return;
    fitAfterSettled = true;
    if (!initialized) return;
    const finalNodes = nodes.map((node) => ({
      ...node,
      x: Number.isFinite(node.targetX) ? node.targetX : node.x,
      y: Number.isFinite(node.targetY) ? node.targetY : node.y,
    }));
    const next = fitCamera(finalNodes, width, viewportHeight(), fitPadding);
    if (!next) return;
    fitAfterSettled = false;
    fitted = true;
    stopCamera(camera);
    if (config.reducedMotion) restoreCamera(camera, next);
    else {
      camera.flight = { x: next.x, y: next.y };
      camera.targetScale = next.scale;
    }
    schedule();
  }

  function resize() {
    if (dead) return;
    width = host.clientWidth;
    height = host.clientHeight;
    if (initialized && width > 0 && height > 0)
      app.renderer.resize(width, height);
    schedule();
  }

  function pause() {
    paused = true;
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    previousTime = 0;
  }
  function resume() {
    if (dead) return;
    paused = false;
    previousTime = 0;
    schedule();
  }

  const ready = (async () => {
    app = new PIXI.Application();
    await app.init({
      width: Math.max(1, width),
      height: Math.max(1, height),
      preference: "webgl",
      backgroundAlpha: 0,
      antialias: true,
      autoStart: false,
      autoDensity: true,
      resolution: Math.min(2, window.devicePixelRatio || 1),
    });
    initPending = false;
    appReady = true;
    app.ticker.stop();
    if (dead) {
      disposeResources();
      return false;
    }
    world = new PIXI.Container();
    regionLayer = new PIXI.Graphics();
    edgeLayer = new PIXI.Container();
    nodeLayer = new PIXI.Container();
    world.addChild(regionLayer, edgeLayer, nodeLayer);
    pendingLines = new PIXI.Graphics();
    rings = new PIXI.Container();
    labelLayer = new PIXI.Container();
    lassoShape = new PIXI.Graphics();
    app.stage.addChild(world, pendingLines, rings, labelLayer, lassoShape);
    app.stage.eventMode = "none";
    const circle = new PIXI.Graphics();
    temporaryGraphics.add(circle);
    circle.circle(0, 0, 16).fill(0xffffff);
    circleTexture = app.renderer.generateTexture({
      target: circle,
      resolution: 2,
    });
    circle.destroy();
    temporaryGraphics.delete(circle);
    const ring = new PIXI.Graphics();
    temporaryGraphics.add(ring);
    ring.circle(0, 0, 16).stroke({ width: 2, color: 0xffffff });
    solidRingTexture = app.renderer.generateTexture({
      target: ring,
      resolution: 2,
    });
    ring.clear();
    for (let angle = 0; angle < Math.PI * 2; angle += Math.PI / 4) {
      ring
        .moveTo(Math.cos(angle) * 16, Math.sin(angle) * 16)
        .arc(0, 0, 16, angle, angle + Math.PI / 7);
    }
    ring.stroke({ width: 1.5, color: 0xffffff });
    dashedRingTexture = app.renderer.generateTexture({
      target: ring,
      resolution: 2,
    });
    ring.destroy();
    temporaryGraphics.delete(ring);
    const pattern = document.createElement("canvas");
    pattern.width = 8;
    pattern.height = 2;
    const context = pattern.getContext("2d");
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, 4, 2);
    dashSource = new PIXI.CanvasSource({
      resource: pattern,
      resolution: 1,
      addressMode: "repeat",
      scaleMode: "nearest",
      autoGenerateMipmaps: false,
    });
    dashTexture = new PIXI.Texture({ source: dashSource });
    app.canvas.style.touchAction = "none";
    app.canvas.style.cursor = "grab";
    host.append(app.canvas);
    initialized = true;
    bindEvents();
    syncSprites();
    rebuildEdges();
    resize();
    if (fitAfterSettled) settled();
    schedule();
    return true;
  })().catch((error) => {
    initPending = false;
    disposeResources();
    if (!dead) callbacks.onError?.(error.message || "图谱初始化失败");
    return false;
  });

  function disposeResources() {
    if (initPending || resourcesDisposed) return;
    resourcesDisposed = true;
    initialized = false;
    pause();
    events.abort();
    const failures = [],
      options = { children: true, texture: false, textureSource: false };
    const release = (resource, cleanup) => {
      if (!resource || resource.destroyed) return;
      try {
        cleanup();
      } catch (error) {
        failures.push(error);
      }
    };
    for (const group of meshes) release(group.mesh, () => group.mesh.destroy());
    meshes = [];
    for (const graphic of temporaryGraphics)
      release(graphic, () => graphic.destroy());
    temporaryGraphics.clear();
    const stage = app?.stage,
      renderer = app?.renderer;
    const orphans = [
      world,
      regionLayer,
      edgeLayer,
      nodeLayer,
      pendingLines,
      rings,
      labelLayer,
      lassoShape,
    ].filter((display) => display && !display.parent);
    let appDestroyed = false;
    if (appReady)
      release(app, () => {
        app.destroy(true, options);
        appDestroyed = true;
      });
    if (!appDestroyed) {
      release(app?.ticker, () => app.ticker.destroy());
      release(stage, () => stage.destroy(options));
      release(renderer, () => renderer.destroy(true));
    }
    for (const display of orphans)
      release(display, () => display.destroy(options));
    for (const texture of [
      circleTexture,
      solidRingTexture,
      dashedRingTexture,
      dashTexture,
    ])
      release(texture, () => texture.destroy(true));
    release(dashSource, () => dashSource.destroy());
    sprites.clear();
    ringSprites.clear();
    labels.clear();
    labelLayouts.clear();
    // Cleanup failures are secondary diagnostics. The original init error reaches onError.
    for (const failure of failures)
      console.warn("Graph resource cleanup failed", failure);
  }

  function destroy() {
    if (dead) return;
    dead = true;
    pause();
    events.abort();
    disposeResources();
    sprites.clear();
    ringSprites.clear();
    labels.clear();
    labelLayouts.clear();
    held.clear();
    positioned.clear();
    pointers.clear();
    lassoSelected.clear();
    lassoGesture = null;
    nodes = [];
    edges = [];
  }

  return {
    ready,
    update,
    fit,
    resize,
    pause,
    resume,
    destroy,
    settled,
    positionsChanged() {
      edgeGeometryDirty = true;
      schedule();
    },
    focus(state) {
      if (dead) return;
      const next = { ...focusState, ...state };
      if (
        next.selected === focusState.selected &&
        next.hover === focusState.hover &&
        next.keyboard === focusState.keyboard
      )
        return;
      focusState = next;
      refreshFocus();
    },
    configure(settings) {
      if (!dead) {
        Object.assign(config, settings);
        edgeGeometryDirty = true;
        if (config.reducedMotion) stopCamera(camera);
        schedule();
      }
    },
    zoomBy(factor) {
      if (!dead) {
        interacted = true;
        zoomAt(camera, factor, null, width, viewportHeight());
        callbacks.onCameraChange?.();
        schedule();
      }
    },
    getCamera() {
      return { x: camera.x, y: camera.y, scale: camera.scale };
    },
    setLasso(value) {
      if (dead) return;
      lasso = Boolean(value);
      lassoGesture = null;
      lassoShape?.clear();
      if (app?.canvas) app.canvas.style.cursor = lasso ? "crosshair" : "grab";
      schedule();
    },
    setCamera(next) {
      if (!dead) {
        interacted = fitted = true;
        restoreCamera(camera, next);
        schedule();
      }
    },
    focusNode(id) {
      const node = byId.get(id);
      if (dead || !node || !placed(node)) return;
      interacted = true;
      stopCamera(camera);
      if (config.reducedMotion) {
        camera.x = node.x;
        camera.y = node.y;
      } else camera.flight = { x: node.x, y: node.y };
      schedule();
    },
  };
}
