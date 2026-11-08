// Pixi's official CSP-safe implementation replaces generated Function bodies.
import * as PIXI from "pixi.js";
import "pixi.js/unsafe-eval";

globalThis.PIXI = PIXI;
