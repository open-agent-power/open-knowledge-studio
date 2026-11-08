"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const { source, moduleUrl } = require("./studio_test_helpers.cjs");
const load = () => import(moduleUrl(source("studio/graph-camera.js")));
const near = (actual, expected, tolerance = 0.001) =>
  assert.ok(
    Math.abs(actual - expected) < tolerance,
    `${actual} should be close to ${expected}`,
  );

test("camera screen/world conversions preserve points", async () => {
  const { createCamera, setCamera, screenPoint, worldPoint } = await load();
  const camera = createCamera();
  setCamera(camera, { x: 240, y: -80, scale: 0.4 });
  const screen = screenPoint(camera, 650, 190, 900, 600);
  const world = worldPoint(camera, screen.x, screen.y, 900, 600);
  near(world.x, 650);
  near(world.y, 190);
});

test("fit centers finite positions and fits a narrow canvas", async () => {
  const { fitCamera } = await load();
  const nodes = [
    { x: -300, y: 20, radius: 10 },
    { x: 500, y: 180, radius: 10 },
    { x: NaN, y: NaN },
  ];
  const camera = fitCamera(nodes, 300, 600);
  near(camera.x, 100);
  near(camera.y, 100);
  assert.ok(camera.scale * 820 <= 300 - 128);
  assert.equal(fitCamera(nodes, 0, 600), null);
  assert.equal(fitCamera([], 300, 600), null);
});

test("zoom keeps its world anchor under the same screen pixel", async () => {
  const { createCamera, zoomAt, worldPoint, stepCamera } = await load();
  const camera = createCamera();
  const point = { x: 130, y: 170 };
  const before = worldPoint(camera, point.x, point.y, 900, 600);
  zoomAt(camera, 2, point, 900, 600);
  for (let i = 0; i < 90; i++)
    stepCamera(camera, 1000 / 60, false, false, 900, 600);
  const after = worldPoint(camera, point.x, point.y, 900, 600);
  near(after.x, before.x);
  near(after.y, before.y);
  near(camera.scale, 2);
});

test("zoom and inertia take the same time at 60 and 120 Hz", async () => {
  const { createCamera, zoomAt, stepCamera } = await load();
  const run = (frames, dt, zoom) => {
    const camera = createCamera();
    if (zoom) zoomAt(camera, 3, null, 900, 600);
    else {
      camera.vx = -0.8;
      camera.vy = 0.3;
    }
    for (let i = 0; i < frames; i++)
      stepCamera(camera, dt, false, false, 900, 600);
    return camera;
  };
  near(run(30, 1000 / 60, true).scale, run(60, 1000 / 120, true).scale);
  near(run(30, 1000 / 60, false).x, run(60, 1000 / 120, false).x);
});

test("pan cancels a flight and reduced motion ends inertia", async () => {
  const { createCamera, panBy, stepCamera, stopCamera } = await load();
  const camera = createCamera();
  camera.flight = { x: 200, y: 100 };
  panBy(camera, 20, 10, 16);
  near(camera.x, -20);
  near(camera.y, -10);
  assert.equal(camera.flight, null);
  assert.ok(camera.vx < 0);
  stepCamera(camera, 16, true);
  assert.equal(camera.vx, 0);
  stopCamera(camera);
  assert.equal(stepCamera(camera, 16), false);
});

test("saved camera restores exactly and clamps supported zoom", async () => {
  const { createCamera, setCamera } = await load();
  const camera = createCamera();
  setCamera(camera, { x: 123, y: 456, scale: 300 });
  assert.equal(camera.scale, 6);
  assert.equal(camera.targetScale, 6);
  near(camera.x, 123);
  near(camera.y, 456);
});

test("small graphs use the canvas while a single node keeps its readable zoom", async () => {
  const { fitCamera } = await load();
  const nodes = [
    { x: -60, y: -60, radius: 7 },
    { x: 60, y: 60, radius: 7 },
  ];
  assert.equal(fitCamera(nodes, 1390, 700).scale, 3);
  assert.equal(fitCamera([nodes[0]], 1390, 700).scale, 1.2);
});
