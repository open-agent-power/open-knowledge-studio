// Advanced Graph View layout engine adaptation. See ../LICENSE.
import { createLayoutEngine } from "./layout-engine.js";

const engine = createLayoutEngine((message, transfer) => self.postMessage(message, transfer));
self.onmessage = (event) => engine.handle(event.data);
