import { act } from "@testing-library/react";
import { vi } from "vitest";

export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

export function installFrames() {
  let nextId = 0;
  const pending = new Map<number, FrameRequestCallback>();
  vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
    pending.set(++nextId, callback);
    return nextId;
  });
  vi.spyOn(window, "cancelAnimationFrame").mockImplementation((id) => {
    pending.delete(id);
  });
  return {
    pending,
    async frame() {
      await act(async () => {
        const callbacks = [...pending.values()];
        pending.clear();
        callbacks.forEach((callback) => callback(performance.now()));
      });
    },
  };
}

export function installFonts(ready: Promise<unknown>) {
  const original = Object.getOwnPropertyDescriptor(document, "fonts");
  Object.defineProperty(document, "fonts", {
    configurable: true,
    value: { ready },
  });
  return () => {
    if (original) Object.defineProperty(document, "fonts", original);
    else Reflect.deleteProperty(document, "fonts");
  };
}

export function installPreviewGeometry() {
  const geometry = {
    contentHeight: 500,
    lineRects: [new DOMRect(0, 260, 100, 20)],
  };
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
    function (this: HTMLElement) {
      if (this.className.includes("--measure"))
        return new DOMRect(0, 0, 186, geometry.contentHeight);
      if (this.dataset.resumeFlowContent === "true")
        return new DOMRect(0, 0, 186, geometry.contentHeight);
      return new DOMRect();
    },
  );
  const createRange = document.createRange.bind(document);
  vi.spyOn(document, "createRange").mockImplementation(() => {
    const range = createRange();
    Object.defineProperty(range, "getClientRects", {
      value: () => geometry.lineRects,
    });
    return range;
  });
  return geometry;
}
