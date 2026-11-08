// Build dependencies live in the temporary directory passed as the argument.
import { readFile, writeFile, readdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
if (!process.argv[2]) throw new Error("Usage: node build.mjs <temporary-build-directory>");
const buildRoot = resolve(process.argv[2]);
const require = createRequire(join(buildRoot, "package.json"));
const esbuild = require("esbuild");
const options = {
  bundle: true, minify: true, format: "iife", platform: "browser",
  target: "es2020", legalComments: "inline", metafile: true,
  nodePaths: [join(buildRoot, "node_modules")],
};
const worker = await esbuild.build({
  ...options, entryPoints: [join(root, "src/layout.worker.js")],
  outfile: join(root, "layout.worker.js"),
});
const pixi = await esbuild.build({
  ...options, entryPoints: [join(root, "src/pixi.js")],
  outfile: join(root, "pixi.min.js"),
});
for (const [input, output] of [["edge-mesh.ts", "edge-mesh.js"], ["position-smoothing.ts", "position-smoothing.js"]]) {
  let source = await readFile(join(root, "src", input), "utf8");
  if (input === "edge-mesh.ts") {
    source = source.replace(/^import .* from "pixi.js";\r?\n/m, "");
    source = source.replace(
      "constructor(edgePairs: Uint32Array, color: number, alpha: number) {",
      "constructor(edgePairs: Uint32Array, color: number, alpha: number) {\nconst { Mesh, MeshGeometry, Texture } = globalThis.PIXI;",
    );
  }
  const result = await esbuild.transform(source, { loader: "ts", target: "es2020", format: "esm" });
  await writeFile(join(root, output), "// Advanced Graph View, MIT, copyright (c) 2026 n23eos. See LICENSE.\n" + result.code);
}

const packages = new Map();
for (const input of [...Object.keys(worker.metafile.inputs), ...Object.keys(pixi.metafile.inputs)]) {
  if (!input.includes("node_modules")) continue;
  let directory = dirname(resolve(input));
  while (directory !== dirname(directory)) {
    try {
      const data = JSON.parse(await readFile(join(directory, "package.json"), "utf8"));
      if (data.name) { packages.set(data.name, { directory, data }); break; }
    } catch { /* Continue up from a library's nested directory. */ }
    directory = dirname(directory);
  }
}
let notices = "Bundled runtime dependencies. License texts from the exact npm packages used by build.mjs.\n";
for (const [name, { directory, data }] of [...packages].sort(([a], [b]) => a.localeCompare(b))) {
  const files = await readdir(directory);
  const license = files.find((file) => /^licen[sc]e(?:\.(?:txt|md))?$/i.test(file));
  const licensePath = license ? join(directory, license) :
    name === "@pixi/colord" ? join(root, "licenses/colord-LICENSE.md") : null;
  if (!licensePath) throw new Error("License file missing for " + name);
  notices += `\n${"=".repeat(72)}\n${name} ${data.version} (${data.license})\n`;
  notices += `Package source https://registry.npmjs.org/${name}/-/${name.split("/").at(-1)}-${data.version}.tgz\n\n`;
  if (!license) notices += "License source https://github.com/omgovich/colord/blob/5344fbf77b736f81cd33c21050021bc09bc9dd1d/LICENSE.md\n\n";
  notices += await readFile(licensePath, "utf8");
  notices += "\n";
}
await writeFile(join(root, "THIRD-PARTY-NOTICES"), notices);
console.log("Built same-origin layout worker, CSP-safe Pixi and renderer helpers.");
