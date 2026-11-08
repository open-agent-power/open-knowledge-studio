// Same-origin Worker adapter for the Advanced Graph View 2D layout engine.
export function createLayout({ onPositions, onSettled, onError }) {
  let worker = null,
    dead = false,
    failed = false,
    paused = false,
    revision = 0;
  let indices = new Map(),
    positions = new Float32Array(0),
    dragging = null;
  const params = {};

  function fail(reason) {
    if (dead || failed) return;
    failed = true;
    stopWorker();
    onError(reason);
  }
  function stopWorker() {
    if (!worker) return;
    worker.onmessage = null;
    worker.onerror = null;
    worker.onmessageerror = null;
    worker.terminate();
    worker = null;
  }
  function ensureWorker() {
    if (worker) return worker;
    const current = new Worker("/vendor/graph-engine/layout.worker.js");
    worker = current;
    current.onmessage = ({ data }) => {
      if (dead || worker !== current || data.revision !== revision) return;
      positions = data.positions;
      if (data.type === "tick") onPositions(positions, data.alpha);
      else if (data.type === "end") onSettled(positions);
    };
    current.onerror = (event) => {
      if (worker === current)
        fail(event.message || "Graph layout worker failed");
    };
    current.onmessageerror = () => {
      if (worker === current) fail("Graph layout worker message failed");
    };
    return current;
  }
  function post(message, transfer = []) {
    if (dead || failed) return;
    try {
      ensureWorker().postMessage({ ...message, revision }, transfer);
    } catch (error) {
      fail(error.message || "Graph layout worker failed to start");
    }
  }
  function update(nodes, edges) {
    if (dead || failed) return;
    const seed = new Float32Array(nodes.length * 3);
    const anchors = new Float32Array(nodes.length * 2);
    nodes.forEach((node, index) => {
      const previous = indices.get(node.id);
      seed[index * 3] =
        previous === undefined ? (node.x ?? NaN) : positions[previous * 3];
      seed[index * 3 + 1] =
        previous === undefined ? (node.y ?? NaN) : positions[previous * 3 + 1];
      anchors[index * 2] = node.anchor?.x || 0;
      anchors[index * 2 + 1] = node.anchor?.y || 0;
    });
    indices = new Map(nodes.map((node, index) => [node.id, index]));
    positions = seed.slice();
    dragging = null;
    revision++;
    const visible = edges.filter(
      (edge) =>
        indices.has(edge.from) && indices.has(edge.to) && edge.from !== edge.to,
    );
    const pairs = new Uint32Array(visible.length * 2);
    visible.forEach((edge, index) => {
      pairs[index * 2] = indices.get(edge.from);
      pairs[index * 2 + 1] = indices.get(edge.to);
    });
    post(
      {
        type: "init",
        nodeCount: nodes.length,
        edges: pairs,
        positions: seed,
        anchors,
        params,
        paused,
      },
      [pairs.buffer, seed.buffer, anchors.buffer],
    );
  }
  function dragStart(id) {
    if (!indices.has(id)) return;
    dragging = id;
    post({ type: "drag-start", id: indices.get(id) });
  }
  function dragMove(id, x, y) {
    const index = indices.get(id);
    if (id !== dragging || index === undefined) return;
    positions[index * 3] = x;
    positions[index * 3 + 1] = y;
    post({ type: "drag-move", id: index, x, y });
  }
  function dragEnd() {
    if (dragging === null) return;
    dragging = null;
    post({ type: "drag-end" });
  }
  function setParams(next) {
    Object.assign(params, next);
    if (worker) post({ type: "params", params });
  }
  function pause() {
    paused = true;
    if (worker) post({ type: "pause" });
  }
  function resume() {
    paused = false;
    if (worker) post({ type: "resume" });
  }
  function destroy() {
    if (dead) return;
    dead = true;
    stopWorker();
    indices.clear();
    positions = new Float32Array(0);
  }
  return {
    update,
    dragStart,
    dragMove,
    dragEnd,
    setParams,
    pause,
    resume,
    destroy,
  };
}
