// Build the checked-in graph runtime using the pinned build-package lock.
// Usage: node build.mjs <build-directory-with-node_modules>
import { readFile, writeFile, readdir } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
if (!process.argv[2]) throw new Error('Pass a build directory installed from build-package-lock.json.');
const cache = resolve(process.argv[2]);
const require = createRequire(join(cache, 'package.json'));
const { build, transform } = require('esbuild');
const vendor = here;
let source = (await readFile(join(vendor, 'src/layout-engine.js'), 'utf8')).replace(/\r\n/g, '\n');
const changes = [
  ['// 2D subset of layoutEngine.ts, layoutSeed.ts,', '// 3D adaptation of layoutEngine.ts, layoutSeed.ts,'],
  ['  forceY,', '  forceY,\n  forceZ,'],
  ['    seed[i * 3 + 1] = (hash01(i * 2 + 2) - 0.5) * extent;',
    '    seed[i * 3 + 1] = (hash01(i * 2 + 2) - 0.5) * extent;\n    seed[i * 3 + 2] = (hash01(i * 3 + 3) - 0.5) * extent;'],
  ['      positions[i * 3 + 1] = nodes[i].y;',
    '      positions[i * 3 + 1] = nodes[i].y;\n      positions[i * 3 + 2] = nodes[i].z;'],
  ['    simulation.force("y").strength(params.centering);',
    '    simulation.force("y").strength(params.centering);\n    simulation.force("z").strength(params.centering);'],
  ['      degree: 0,',
    '      z: Number.isFinite(message.positions[id * 3 + 2]) ? message.positions[id * 3 + 2] : seed[id * 3 + 2],\n      degree: 0,'],
  ['      anchorX: message.anchors?.[id * 2] || 0,', '      anchorX: message.anchors?.[id * 3] || 0,'],
  ['      anchorY: message.anchors?.[id * 2 + 1] || 0,',
    '      anchorY: message.anchors?.[id * 3 + 1] || 0,\n      anchorZ: message.anchors?.[id * 3 + 2] || 0,'],
  ['forceSimulation(nodes, 2)', 'forceSimulation(nodes, 3)'],
  ['      .force("collide", collision)', '      .force("z", forceZ((node) => node.anchorZ))\n      .force("collide", collision)'],
  ['    node.fy = node.y;', '    node.fy = node.y;\n    node.fz = node.z;'],
  ['      node.fy = null;', '      node.fy = null;\n      node.fz = null;'],
  ['          node.fy = message.y;', '          node.fy = message.y;\n          node.fz = message.z;'],
  ['          node.y = message.y;', '          node.y = message.y;\n          node.z = message.z;'],
];
for (const [before, after] of changes) {
  if (!source.includes(before)) throw new Error('Upstream source changed: ' + before);
  source = source.replace(before, after);
}
source += '\nconst engine = createLayoutEngine((message, transfer) => self.postMessage(message, transfer));\nself.onmessage = event => engine.handle(event.data);\n';
const result = await build({
  stdin: { contents: source, resolveDir: join(vendor, 'src'), sourcefile: 'graph-3d.worker-source.js', loader: 'js' },
  bundle: true, minify: true, format: 'iife', platform: 'browser', target: 'es2020', metafile: true,
  nodePaths: [join(cache, 'node_modules')], legalComments: 'inline',
  banner: { js: '// Advanced Graph View 3D adaptation, MIT. d3-force-3d 3.0.6.\n// See LICENSE, NOTICE, licenses/ and THIRD-PARTY-NOTICES.\n// Rebuild with build.mjs and build-package-lock.json.' },
  outfile: join(here, 'graph-3d.worker.js'),
});
const smoothing = await transform(await readFile(join(here, 'src/position-smoothing.ts'), 'utf8'), {
  loader: 'ts', target: 'es2020', format: 'esm',
});
await writeFile(join(here, 'position-smoothing.js'), '// Advanced Graph View, MIT, copyright (c) 2026 n23eos. See LICENSE.\n'+smoothing.code);

const packages = new Map();
for (const input of Object.keys(result.metafile.inputs)) {
  if (!input.includes('node_modules')) continue;
  let directory = dirname(resolve(input));
  while (directory !== dirname(directory)) {
    try {
      const data = JSON.parse(await readFile(join(directory, 'package.json'), 'utf8'));
      if (data.name) { packages.set(data.name, {directory, data}); break; }
    } catch { /* Walk from nested source directories to their package. */ }
    directory = dirname(directory);
  }
}
let notices = 'Runtime dependencies bundled into graph-3d.worker.js.\n';
for (const [name, {directory, data}] of [...packages].sort(([a],[b])=>a.localeCompare(b))) {
  const license = (await readdir(directory)).find(file=>/^licen[sc]e(?:\.(?:txt|md))?$/i.test(file));
  if (!license) throw new Error('Missing runtime license: '+name);
  notices += `\n${'='.repeat(72)}\n${name} ${data.version} (${data.license})\n`;
  notices += `Package source https://registry.npmjs.org/${name}/-/${name.split('/').at(-1)}-${data.version}.tgz\n\n`;
  notices += await readFile(join(directory, license), 'utf8');
  notices += '\n';
}
await writeFile(join(here, 'THIRD-PARTY-NOTICES'), notices.trimEnd()+'\n');
console.log('Built the 3D worker, smoothing runtime and runtime notices.');
