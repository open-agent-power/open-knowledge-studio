// Advanced Graph View, MIT, copyright (c) 2026 n23eos. See LICENSE.
const SMOOTH_FACTOR = 0.35;
const SMOOTH_SNAP_EPSILON = 0.05;
function easePositions(current, target, factor) {
  if (current.length !== target.length) return false;
  let moving = false;
  for (let i = 0; i < current.length; i++) {
    const gap = target[i] - current[i];
    if (gap > -SMOOTH_SNAP_EPSILON && gap < SMOOTH_SNAP_EPSILON) {
      current[i] = target[i];
      continue;
    }
    current[i] += gap * factor;
    moving = true;
  }
  return moving;
}
export {
  SMOOTH_FACTOR,
  SMOOTH_SNAP_EPSILON,
  easePositions
};
