const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../../assets/mail-web/studio/graph-3d.js'), 'utf8');
const modulePromise = import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const near = (a, b, label) => assert.ok(Math.abs(a - b) < 1e-8, `${label}: ${a} != ${b}`);

test('perspective provides depth scaling, parallax, and far-to-near ordering', async () => {
  const { createOrbit, project3D, rotateOrbit, depthOrder } = await modulePromise;
  const camera = createOrbit({ yaw: 0, pitch: 0, distance: 1000 });
  const far = project3D({ x: 100, y: 0, z: -300 }, camera, 900, 600);
  const close = project3D({ x: 100, y: 0, z: 300 }, camera, 900, 600);
  assert.ok(close.scale > far.scale);
  assert.ok(close.x > far.x);
  assert.deepEqual([close, far].sort(depthOrder), [far, close]);
  const turned = rotateOrbit(camera, 100, 0);
  const front = project3D({ x: 0, y: 0, z: 300 }, turned, 900, 600);
  const back = project3D({ x: 0, y: 0, z: -300 }, turned, 900, 600);
  assert.ok(front.x > 450 && back.x < 450);
  assert.ok(Math.abs(front.x - back.x) > 100);
});

test('projection and same-depth inverse agree through orbit and nonzero target', async () => {
  const { createOrbit, project3D, unproject3D } = await modulePromise;
  for (const yaw of [-2.7, -0.4, 0, 1.9]) for (const pitch of [-1.2, 0, 0.8]) {
    const camera = createOrbit({ yaw, pitch, distance: 1500, target: { x: 74, y: -90, z: 33 } });
    for (const point of [{ x: 230, y: -180, z: 311 }, { x: -400, y: 80, z: -70 }]) {
      const projected = project3D(point, camera, 1100, 700);
      const result = unproject3D(projected, camera, 1100, 700, projected.depth);
      for (const key of ['x', 'y', 'z']) near(result[key], point[key], key);
      const moved = { x: projected.x + 70, y: projected.y - 40 };
      const dragged = unproject3D(moved, camera, 1100, 700, projected.depth);
      const reprojection = project3D(dragged, camera, 1100, 700);
      near(reprojection.x, moved.x, 'drag x'); near(reprojection.y, moved.y, 'drag y');
      near(reprojection.depth, projected.depth, 'drag depth');
    }
  }
});

test('orbit rotation leaves input unchanged and clips points at the near plane', async () => {
  const { createOrbit, project3D, rotateOrbit } = await modulePromise;
  const camera = createOrbit({ yaw: 0, pitch: 0, distance: 100 });
  const turned = rotateOrbit(camera, 100000, 100000);
  assert.equal(camera.yaw, 0); assert.equal(camera.pitch, 0);
  assert.ok(turned.yaw >= -Math.PI && turned.yaw <= Math.PI);
  assert.ok(turned.pitch < Math.PI / 2 && turned.pitch > -Math.PI / 2);
  for (const z of [99, 100, 120]) {
    const point = project3D({ x: 10, y: 20, z }, camera, 800, 600);
    assert.equal(point.visible, false);
    assert.ok([point.x, point.y, point.scale].every(Number.isFinite));
  }
});

test('world-space fit keeps a large off-center graph in front of every orbit angle', async () => {
  const {createOrbit, fitOrbit, project3D, rotateOrbit} = await modulePromise;
  const points = Array.from({length:106}, (_,i) => ({
    x: 5000 + Math.cos(i*2.4)*3000,
    y: -3500 + Math.sin(i*2.4)*2400,
    z: (i/105-.5)*6000,
  }));
  const original = createOrbit();
  assert.ok(points.some(point => !project3D(point,original,1200,1200).visible));
  const fitted = fitOrbit(original,points);
  assert.equal(original.distance,1400);
  for(const [dx,dy] of [[0,0],[180,90],[-300,-160]]) {
    const orbit=rotateOrbit(fitted,dx,dy);
    for(const point of points) {
      const p=project3D(point,orbit,1200,1200);
      assert.equal(p.visible,true);
      assert.ok([p.x,p.y,p.scale].every(Number.isFinite));
      assert.ok(p.scale<2,'near-plane coordinates must not dominate the screen fit');
    }
  }
});

function workerFixture() {
  const output = [], self = { postMessage: message => output.push(message) };
  const context = vm.createContext({ self, performance: { now: () => 0 },
    Float32Array, Uint32Array, Int32Array,
    setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {} });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../../assets/mail-web/vendor/graph-engine/graph-3d.worker.js'), 'utf8'), context);
  const send = message => self.onmessage({ data: { revision: 1, ...message } });
  const init = (positions, params, anchors = positions.map(() => 0)) => send({ type: 'init',
    nodeCount: positions.length / 3, positions: Float32Array.from(positions),
    edges: new Uint32Array(), anchors: Float32Array.from(anchors), paused: false, params });
  return { output, send, init };
}

test('bundled d3-force-3d worker repels nodes along z and snapshots nonzero z', () => {
  const { output, send, init } = workerFixture();
  init([0, 0, -80, 0, 0, 80], { repel: 1200, centering: 0, linkStrength: 0 });
  for (let i = 0; i < 30; i++) send({ type: 'step' });
  const positions = output.at(-1).positions;
  assert.ok(positions[2] < -80 && positions[5] > 80);
  assert.ok([...positions].every(Number.isFinite));
  send({ type: 'stop' });
});

test('worker z anchors and release after a three-axis drag affect actual simulation', () => {
  const { output, send, init } = workerFixture();
  init([0, 0, 0, 0, 0, 0], { repel: 0, centering: 0.1, linkStrength: 0 },
    [0, 0, -300, 0, 0, 300]);
  for (let i = 0; i < 250; i++) send({ type: 'step' });
  assert.ok(output.at(-1).positions[2] < -280);
  assert.ok(output.at(-1).positions[5] > 280);
  send({ type: 'drag-start', id: 0 });
  send({ type: 'drag-move', id: 0, x: 140, y: 80, z: 220 });
  for (let i = 0; i < 4; i++) send({ type: 'step' });
  assert.deepEqual([...output.at(-1).positions].slice(0, 3), [140, 80, 220]);
  send({ type: 'drag-end' });
  for (let i = 0; i < 10; i++) send({ type: 'step' });
  assert.ok(output.at(-1).positions[2] < 220);
  const count = output.length;
  send({ type: 'drag-move', revision: 0, id: 0, x: 0, y: 0, z: 999 });
  assert.equal(output.length, count);
  send({ type: 'stop' });
});

test('3D adapter retains real topology, consumes xyz and terminates on disposal', async () => {
  const { create3DLayout } = await modulePromise;
  const previous = global.Worker, instances = [], ticks = [], errors = [];
  global.Worker = class {
    constructor(url) { this.url = url; this.sent = []; this.terminated = 0; instances.push(this); }
    postMessage(message) { this.sent.push(message); }
    terminate() { this.terminated++; }
  };
  try {
    const items = [{ id: 'a' }, { id: 'b' }], before = JSON.stringify(items);
    const layout = create3DLayout(items, [{ from: 'a', to: 'b', type: 'cites' },
      { from: 'a', to: 'missing' }, { from: 'a', to: 'a' }],
    { workerUrl: '/graph-3d.worker.js', onTick: type => ticks.push(type), onError: error => errors.push(error) });
    const worker = instances[0], first = worker.sent[0];
    assert.equal(JSON.stringify(items), before);
    assert.notEqual(layout.nodes[0].z, layout.nodes[1].z);
    assert.equal(layout.edges.length, 1); assert.equal(layout.edges[0].type, 'cites');
    assert.equal(layout.edges[0].source, layout.nodes[0]);
    assert.deepEqual([...first.edges], [0, 1]);
    worker.onmessage({ data: { revision: 1, type: 'tick', alpha: 0.6,
      positions: Float32Array.from([10, 20, 30, 40, 50, 60]) } });
    assert.equal(layout.nodes[0].z, 30); assert.equal(layout.nodes[1].z, 60);
    layout.dragStart('a'); layout.dragMove('a', 110, 120, 130);
    worker.onmessage({ data: { revision: 1, type: 'tick', alpha: 0.4,
      positions: Float32Array.from([11, 21, 31, 41, 51, 61]) } });
    assert.equal(layout.nodes[0].z, 130); assert.equal(layout.nodes[1].z, 61);
    assert.equal(worker.sent.at(-1).z, 130);
    layout.dragEnd();
    worker.onmessage({ data: { revision: 1, type: 'end', alpha: 0.009,
      positions: Float32Array.from([110, 120, 130, 41, 51, 61]) } });
    assert.equal(layout.step(), false); assert.deepEqual(ticks, ['tick', 'tick', 'end']);
    assert.deepEqual(errors, []);
    const staleCallback = worker.onmessage, count = worker.sent.length;
    layout.destroy(); layout.destroy(); layout.reheat();
    staleCallback({ data: { revision: 1, type: 'tick', positions: new Float32Array(6), alpha: 1 } });
    assert.equal(layout.nodes[0].z, 130); assert.equal(worker.terminated, 1);
    assert.equal(worker.sent.length, count); assert.equal(layout.alpha, 0);
  } finally { global.Worker = previous; }
});
