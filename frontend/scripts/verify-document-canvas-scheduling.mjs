import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import * as canvasModel from "../src/components/preview/document-canvas-model.ts";
import { evaluateTypeScript } from "./typescript-module.mjs";

const source = readFileSync(
  new URL("../src/components/preview/use-document-canvas.ts", import.meta.url),
  "utf8",
);

function createCanvas(savedScale = "1.2") {
  const frames = new Map();
  const timers = new Map();
  const effects = [];
  const windowListeners = new Map();
  const writes = [];
  const scaleChanges = [];
  let now = 0;
  let nextId = 0;
  let resize;
  let disconnected = false;
  const viewport = {
    clientWidth: canvasModel.A4_WIDTH_PX + 48,
    style: {
      setProperty(_name, scale) {
        scaleChanges.push(Number(scale));
      },
    },
    addEventListener() {},
    removeEventListener() {},
    scrollBy() {},
    getBoundingClientRect: () => ({
      left: 0,
      top: 0,
      width: viewport.clientWidth,
      height: 800,
    }),
    querySelector: () => ({
      getBoundingClientRect: () => ({
        left: 0,
        top: 0,
        width: canvasModel.A4_WIDTH_PX * scaleChanges.at(-1),
        height: 1122 * scaleChanges.at(-1),
      }),
    }),
  };
  const module = evaluateTypeScript(source, {
    imports: {
      react: {
        useCallback: (callback) => callback,
        useRef: (current) => ({ current }),
        useState: (initial) => [
          typeof initial === "function" ? initial() : initial,
          () => {},
        ],
        useLayoutEffect: (effect) => effects.push(effect),
      },
      "@/components/preview/document-canvas-model": canvasModel,
    },
    globals: {
      window: {
        addEventListener: (type, listener) =>
          windowListeners.set(type, listener),
        removeEventListener(type, listener) {
          assert.equal(windowListeners.get(type), listener);
          windowListeners.delete(type);
        },
        localStorage: {
          getItem: () => savedScale,
          setItem(key, value) {
            writes.push({ key, value });
            savedScale = value;
          },
        },
        requestAnimationFrame(callback) {
          frames.set(++nextId, callback);
          return nextId;
        },
        cancelAnimationFrame: (id) => frames.delete(id),
        setTimeout(callback, delay) {
          timers.set(++nextId, { callback, at: now + delay });
          return nextId;
        },
        clearTimeout: (id) => timers.delete(id),
      },
      ResizeObserver: class {
        constructor(callback) {
          resize = callback;
        }
        observe(element) {
          assert.equal(element, viewport);
        }
        disconnect() {
          disconnected = true;
        }
      },
    },
  });
  const hook = module.useDocumentCanvas();
  hook.viewportRef.current = viewport;
  const cleanups = effects.map((effect) => effect());
  return {
    hook,
    frames,
    timers,
    writes,
    scaleChanges,
    viewport,
    resize: () => resize(),
    pagehide: () => windowListeners.get("pagehide")(),
    frame() {
      const callbacks = [...frames.values()];
      frames.clear();
      callbacks.forEach((callback) => callback());
    },
    advance(milliseconds) {
      now += milliseconds;
      for (const [id, timer] of timers) {
        if (timer.at <= now) {
          timers.delete(id);
          timer.callback();
        }
      }
    },
    unmount() {
      cleanups.forEach((cleanup) => cleanup?.());
      assert(disconnected);
      assert.equal(windowListeners.size, 0);
    },
  };
}

test("manual zoom restores immediately and ignores viewport resize", () => {
  const canvas = createCanvas("1.4");
  assert.equal(canvas.hook.scale, 1.4);
  assert.equal(canvas.hook.isFitToWidth, false);
  canvas.resize();
  assert.equal(canvas.frames.size, 0);
  assert.deepEqual(canvas.scaleChanges, [1.4]);
  canvas.unmount();
  assert.deepEqual(canvas.writes, []);
});

test("fit resize coalesces a frame and uses the latest viewport width", () => {
  const canvas = createCanvas();
  canvas.hook.setScale(null);
  assert.equal(canvas.scaleChanges.at(-1), 1);
  for (const width of [800, 1000, 1200]) {
    canvas.viewport.clientWidth = width;
    canvas.resize();
  }
  assert.equal(canvas.frames.size, 1);
  assert.deepEqual(canvas.scaleChanges, [1.2, 1]);
  canvas.frame();
  const fittedScale = canvasModel.getFitWidthScale(1200);
  assert.deepEqual(canvas.scaleChanges, [1.2, 1, fittedScale]);
  canvas.resize();
  canvas.frame();
  assert.equal(canvas.scaleChanges.length, 3);
  canvas.advance(149);
  assert.deepEqual(canvas.writes, []);
  canvas.advance(1);
  assert.deepEqual(canvas.writes, [
    { key: "reseno-document-canvas-scale-v1", value: String(fittedScale) },
  ]);
  canvas.unmount();
  assert.equal(canvas.writes.length, 1);
});

test("continuous zoom remains immediate and saves the latest idle scale once", () => {
  const canvas = createCanvas();
  canvas.hook.setScale(1.3);
  canvas.advance(100);
  canvas.hook.setScale(1.6);
  assert.deepEqual(canvas.scaleChanges, [1.2, 1.3, 1.6]);
  canvas.advance(149);
  assert.deepEqual(canvas.writes, []);
  canvas.advance(1);
  assert.equal(canvas.writes.length, 1);
  assert.equal(canvas.writes[0].value, "1.6");
  const restored = createCanvas(canvas.writes[0].value);
  assert.equal(restored.hook.scale, 1.6);
  assert.equal(restored.hook.isFitToWidth, false);
  restored.unmount();
  canvas.unmount();
});

test("queued fit resize cannot override a newer manual zoom choice", () => {
  const canvas = createCanvas();
  canvas.hook.setScale(null);
  canvas.viewport.clientWidth = 600;
  canvas.resize();
  canvas.hook.setScale(1.5);
  canvas.frame();
  assert.deepEqual(canvas.scaleChanges, [1.2, 1, 1.5]);
  canvas.unmount();
  assert.equal(canvas.writes[0].value, "1.5");
});

test("unmount cancels pending work and flushes the latest scale once", () => {
  const canvas = createCanvas();
  canvas.hook.setScale(null);
  canvas.viewport.clientWidth = 600;
  canvas.resize();
  canvas.hook.setScale(1.7);
  canvas.unmount();
  assert.equal(canvas.frames.size, 0);
  assert.equal(canvas.timers.size, 0);
  assert.equal(canvas.writes.length, 1);
  assert.equal(canvas.writes[0].value, "1.7");
  canvas.advance(500);
  assert.equal(canvas.writes.length, 1);
});

test("pagehide saves pending zoom before refresh without duplicate writes", () => {
  const canvas = createCanvas();
  canvas.hook.setScale(1.8);
  canvas.pagehide();
  assert.equal(canvas.writes.length, 1);
  assert.equal(canvas.writes[0].value, "1.8");
  assert.equal(canvas.timers.size, 0);
  canvas.advance(500);
  canvas.pagehide();
  canvas.unmount();
  assert.equal(canvas.writes.length, 1);
});
