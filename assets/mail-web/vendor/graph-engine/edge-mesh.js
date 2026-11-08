// Advanced Graph View, MIT, copyright (c) 2026 n23eos. See LICENSE.
var __defProp = Object.defineProperty;
var __defNormalProp = (obj, key, value) => key in obj ? __defProp(obj, key, { enumerable: true, configurable: true, writable: true, value }) : obj[key] = value;
var __publicField = (obj, key, value) => __defNormalProp(obj, typeof key !== "symbol" ? key + "" : key, value);
class EdgeMesh {
  constructor(edgePairs, color, alpha) {
    __publicField(this, "mesh");
    __publicField(this, "vertices");
    __publicField(this, "positionBuffer");
    __publicField(this, "geometry");
    __publicField(this, "destroyed", false);
    /** Flat [source0, target0, source1, target1, ...] node id pairs. */
    __publicField(this, "edgePairs");
    __publicField(this, "width", 1);
    /** 1 = node hidden; its edges collapse to zero-area (invisible). */
    __publicField(this, "hiddenNodes", null);
    const { Mesh, MeshGeometry, Texture } = globalThis.PIXI;
    this.edgePairs = edgePairs;
    const edgeCount = edgePairs.length / 2;
    this.vertices = new Float32Array(edgeCount * 8);
    const indices = new Uint32Array(edgeCount * 6);
    for (let e = 0; e < edgeCount; e++) {
      const v = e * 4;
      const i = e * 6;
      indices[i] = v;
      indices[i + 1] = v + 1;
      indices[i + 2] = v + 2;
      indices[i + 3] = v + 2;
      indices[i + 4] = v + 1;
      indices[i + 5] = v + 3;
    }
    this.geometry = new MeshGeometry({
      positions: this.vertices,
      uvs: new Float32Array(edgeCount * 8),
      indices,
      topology: "triangle-list"
    });
    this.positionBuffer = this.geometry.getBuffer("aPosition");
    this.mesh = new Mesh({ geometry: this.geometry, texture: Texture.WHITE });
    this.mesh.tint = color;
    this.mesh.alpha = alpha;
  }
  setAlpha(alpha) {
    this.mesh.alpha = alpha;
  }
  setColor(color) {
    this.mesh.tint = color;
  }
  setVisible(visible) {
    this.mesh.visible = visible;
  }
  /** World-units line width, applied by the next updatePositions call. */
  setWidth(width) {
    this.width = width;
  }
  setHiddenNodes(mask) {
    this.hiddenNodes = mask;
  }
  updatePositions(nodePositions, depthScales) {
    const pairs = this.edgePairs;
    const vertices = this.vertices;
    const hidden = this.hiddenNodes;
    const baseHalf = this.width / 2;
    for (let e = 0; e < pairs.length / 2; e++) {
      const source = pairs[e * 2];
      const target = pairs[e * 2 + 1];
      const base = e * 8;
      if (hidden !== null && (hidden[source] === 1 || hidden[target] === 1)) {
        vertices.fill(0, base, base + 8);
        continue;
      }
      const x1 = nodePositions[source * 2];
      const y1 = nodePositions[source * 2 + 1];
      const x2 = nodePositions[target * 2];
      const y2 = nodePositions[target * 2 + 1];
      const dx = x2 - x1;
      const dy = y2 - y1;
      const length = Math.hypot(dx, dy) || 1;
      const half = depthScales ? baseHalf * (depthScales[source] + depthScales[target]) * 0.5 : baseHalf;
      const px = -dy / length * half;
      const py = dx / length * half;
      vertices[base] = x1 + px;
      vertices[base + 1] = y1 + py;
      vertices[base + 2] = x1 - px;
      vertices[base + 3] = y1 - py;
      vertices[base + 4] = x2 + px;
      vertices[base + 5] = y2 + py;
      vertices[base + 6] = x2 - px;
      vertices[base + 7] = y2 - py;
    }
    this.positionBuffer.update();
  }
  destroy() {
    if (this.destroyed) return;
    this.destroyed = true;
    const buffers = [...this.geometry.buffers];
    const indexBuffer = this.geometry.indexBuffer;
    this.mesh.destroy({ texture: false, textureSource: false });
    this.geometry.destroy(false);
    for (const buffer of buffers) {
      if (buffer !== indexBuffer) buffer.destroy();
    }
  }
}
export {
  EdgeMesh
};
