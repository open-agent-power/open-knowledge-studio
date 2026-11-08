# Graph engine

OKS Studio loads the checked-in runtime files locally. Graph layout runs in a
same-origin classic Worker. Pixi includes its official CSP-safe implementation.

## Runtime files

| File | Purpose |
| --- | --- |
| `pixi.min.js` | PixiJS 8.19.0 browser global `PIXI`, including `pixi.js/unsafe-eval` |
| `layout.worker.js` | Bundled 2D layout with d3-force-3d 3.0.6 |
| `edge-mesh.js` | ESM `EdgeMesh`, using the loaded `PIXI` global |
| `position-smoothing.js` | ESM `easePositions`, `SMOOTH_FACTOR`, `SMOOTH_SNAP_EPSILON` |

`pixi.js/unsafe-eval` installs Pixi's static shader/uniform implementations so
the renderer works with `script-src 'self'`. The Worker URL is
`/vendor/graph-engine/layout.worker.js` and needs `worker-src 'self'`, or the
equivalent default-source policy.

## Source attribution

Studio's `studio/graph-camera.js` and `studio/graph-renderer.js` adapt camera
gestures, inertial panning, zoom easing, fit and label fading from Graphs Plus.
The Worker adapts `src/forceSim.ts`'s force balance: -1000 repulsion without a
distance cutoff, 250-unit links, 0.1 centering and degree-weighted link strength.
These keep linked branches readable alongside disconnected source documents.
The source is pinned to
commit `55733d905900bf668c689141d461e75bdaa1afc0`, copyright 2026 John Morabito,
MIT. The full license is retained in `licenses/graphs-plus-LICENSE` and is
preserved when rebuilding the runtime bundles.
[Graphs Plus source](https://github.com/jsmorabito/obsidian-graphs-plus/tree/55733d905900bf668c689141d461e75bdaa1afc0/src)

The layout and renderer helpers derive from Advanced Graph View commit
`17e3eb1fd0e64d4d13d9a130c4bd77b2f287b48d`, copyright 2026 n23eos, MIT.
Its full license is retained in `LICENSE`.
[Advanced Graph View source](https://github.com/n23eos/advanced_graph_view/tree/17e3eb1fd0e64d4d13d9a130c4bd77b2f287b48d/src)

`src/layout-engine.js` consolidates the 2D portions of `workers/layoutEngine.ts`,
`layoutSeed.ts`, `repulsionAccuracy.ts` and `tickPacing.ts`.
It retains alpha-dependent Barnes-Hut accuracy, paced ticks and deterministic
scatter seeds. Graphs Plus's single degree-weighted link force replaces the
previous combination of D3 links and additional Hooke springs. OKS uses
revision-scoped messages, explicit pause/resume, partial parameter updates,
and releases the temporary node pin after a drag.

Degree-based collision radii and three collision iterations follow Quartz Graph
commit `e647019c05ab2a3279c9cddd7bc2f18acb9858b8`, copyright 2026 Quartz
Community, MIT. The full license is retained in `licenses/quartz-graph-LICENSE`.
Document sizes also reflect their actual link counts; focused labels remain
visible over nearby dots, while other labels avoid collisions.
[Quartz Graph source](https://github.com/quartz-community/graph/blob/e647019c05ab2a3279c9cddd7bc2f18acb9858b8/src/components/scripts/graph.inline.ts)

`src/edge-mesh.ts` and `src/position-smoothing.ts` retain upstream source.
The build translates them to ESM. `EdgeMesh` resolves Pixi classes in its
constructor in place of the package import. Numeric edge indices and typed
position arrays stay separate from OKS node IDs and relationship metadata.
`setWidth` applies on the next `updatePositions` call so zooming updates each
edge buffer once per frame.

`THIRD-PARTY-NOTICES` contains the exact bundled runtime dependency licenses.
The `@pixi/colord` npm package omits its license file, so its MIT text is retained
under `licenses/` from the package's published Git commit.
[colord license source](https://github.com/omgovich/colord/blob/5344fbf77b736f81cd33c21050021bc09bc9dd1d/LICENSE.md)

## Rebuild

Run from this directory in PowerShell. Build dependencies are installed into a
temporary directory using the checked-in build dependency lock.

```powershell
$graphBuildRoot = Join-Path $env:TEMP 'oks-graph-engine-build'
New-Item -ItemType Directory -Force -Path $graphBuildRoot | Out-Null
Copy-Item -LiteralPath build-package.json -Destination (Join-Path $graphBuildRoot 'package.json')
Copy-Item -LiteralPath build-package-lock.json -Destination (Join-Path $graphBuildRoot 'package-lock.json')
npm ci --ignore-scripts --no-audit --no-fund --prefix $graphBuildRoot
node build.mjs $graphBuildRoot
```

The build regenerates the four runtime files and third-party notices.
`cli/tests/test_graph_layout.js` exercises the shipped Worker bundle and Studio
adapter through coordinate remapping, settling, drag release, pause/resume,
stale revisions, error handling and teardown.
