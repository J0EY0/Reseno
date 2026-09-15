import { act, cleanup, fireEvent, render } from "@testing-library/react";
import { useCallback } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  A4_WIDTH_PX,
  getFitWidthScale,
} from "@/components/preview/document-canvas-model";
import { useDocumentCanvas } from "@/components/preview/use-document-canvas";

const storageKey = "reseno-document-canvas-scale-v1";
const resizeObservers: TestResizeObserver[] = [];

class TestResizeObserver implements ResizeObserver {
  readonly callback: ResizeObserverCallback;
  observe = vi.fn<(target: Element) => void>();
  unobserve = vi.fn<(target: Element) => void>();
  disconnect = vi.fn<() => void>();

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
    resizeObservers.push(this);
  }
}

function Canvas({ dimensions }: { dimensions: { width: number } }) {
  const canvas = useDocumentCanvas();
  const { viewportRef } = canvas;
  const attachViewport = useCallback(
    (viewport: HTMLDivElement | null) => {
      viewportRef.current = viewport;
      if (!viewport) return;
      Object.defineProperty(viewport, "clientWidth", {
        configurable: true,
        get: () => dimensions.width,
      });
      viewport.getBoundingClientRect = () =>
        new DOMRect(0, 0, dimensions.width, 800);
      viewport.scrollBy = vi.fn();
      const paper = viewport.querySelector<HTMLElement>(
        "[data-document-canvas-paper]",
      )!;
      paper.getBoundingClientRect = () => {
        const scale = Number(viewport.style.getPropertyValue("--canvas-scale"));
        return new DOMRect(0, 0, A4_WIDTH_PX * scale, 1122 * scale);
      };
    },
    [dimensions, viewportRef],
  );

  return (
    <div
      ref={attachViewport}
      data-testid="viewport"
      onKeyDown={canvas.onKeyDown}
    >
      <div data-document-canvas-paper />
      <input
        aria-label="Zoom scale"
        type="number"
        value={canvas.scale}
        onChange={(event) => canvas.setScale(Number(event.target.value))}
      />
      <output aria-label="Zoom mode">
        {canvas.isFitToWidth ? "fit" : "manual"}
      </output>
      <button onClick={() => canvas.setScale(null)}>Fit width</button>
    </div>
  );
}

function createCanvas(savedScale = "1.2") {
  window.localStorage.setItem(storageKey, savedScale);
  const writes = vi.spyOn(Storage.prototype, "setItem");
  writes.mockClear();
  const dimensions = { width: A4_WIDTH_PX + 48 };
  const view = render(<Canvas dimensions={dimensions} />);
  const viewport = view.getByTestId("viewport");
  const scaleChanges = vi.spyOn(viewport.style, "setProperty");
  const resizeObserver = resizeObservers.at(-1)!;
  expect(resizeObserver.observe).toHaveBeenCalledExactlyOnceWith(viewport);

  return {
    ...view,
    dimensions,
    viewport,
    writes,
    resizeObserver,
    scaleChanges,
    get scale() {
      return Number(
        (view.getByLabelText("Zoom scale") as HTMLInputElement).value,
      );
    },
    get mode() {
      return view.getByLabelText("Zoom mode").textContent;
    },
    zoom(scale: number) {
      fireEvent.change(view.getByLabelText("Zoom scale"), {
        target: { value: String(scale) },
      });
    },
    fit() {
      fireEvent.click(view.getByRole("button", { name: "Fit width" }));
    },
    resize() {
      act(() => resizeObserver.callback([], resizeObserver));
    },
  };
}

function advance(milliseconds: number) {
  act(() => vi.advanceTimersByTime(milliseconds));
}

function frame() {
  act(() => vi.advanceTimersToNextFrame());
}

beforeEach(() => {
  window.localStorage.clear();
  resizeObservers.length = 0;
  vi.useFakeTimers({
    toFake: [
      "setTimeout",
      "clearTimeout",
      "requestAnimationFrame",
      "cancelAnimationFrame",
    ],
  });
  vi.stubGlobal("ResizeObserver", TestResizeObserver);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it.each(["plain", "ctrl", "meta"])(
  "only consumes %s wheel gestures when they request canvas zoom",
  (modifier) => {
    const canvas = createCanvas("1");
    const event = new WheelEvent("wheel", {
      bubbles: true,
      cancelable: true,
      deltaY: -100,
      ctrlKey: modifier === "ctrl",
      metaKey: modifier === "meta",
    });
    act(() => canvas.viewport.dispatchEvent(event));
    frame();
    expect(event.defaultPrevented).toBe(modifier !== "plain");
    if (modifier === "plain") expect(canvas.scale).toBe(1);
    else expect(canvas.scale).toBeGreaterThan(1);
    fireEvent.keyDown(window, { ctrlKey: true, key: "-" });
    const scale = canvas.scale;
    frame();
    expect(canvas.scale).toBe(scale);
  },
);

describe("Document canvas zoom scheduling", () => {
  it("restores manual zoom immediately and ignores viewport resize", () => {
    const canvas = createCanvas("1.4");
    const requestFrame = vi.spyOn(window, "requestAnimationFrame");
    expect(canvas.scale).toBe(1.4);
    expect(canvas.mode).toBe("manual");
    expect(canvas.viewport.style.getPropertyValue("--canvas-scale")).toBe(
      "1.4",
    );
    canvas.resize();
    expect(requestFrame).not.toHaveBeenCalled();
    expect(canvas.scaleChanges).not.toHaveBeenCalled();
    canvas.unmount();
    expect(canvas.writes).not.toHaveBeenCalled();
    expect(canvas.resizeObserver.disconnect).toHaveBeenCalledOnce();
  });

  it("coalesces fit resizes into one frame using the latest viewport width", () => {
    const canvas = createCanvas();
    const requestFrame = vi.spyOn(window, "requestAnimationFrame");
    canvas.fit();
    expect(canvas.scale).toBe(1);
    expect(canvas.mode).toBe("fit");
    for (const width of [800, 1000, 1200]) {
      canvas.dimensions.width = width;
      canvas.resize();
    }
    expect(requestFrame).toHaveBeenCalledOnce();
    expect(canvas.scaleChanges).toHaveBeenCalledExactlyOnceWith(
      "--canvas-scale",
      "1",
    );
    frame();
    const fittedScale = getFitWidthScale(1200);
    expect(canvas.scale).toBe(fittedScale);
    expect(canvas.scaleChanges).toHaveBeenLastCalledWith(
      "--canvas-scale",
      String(fittedScale),
    );
    canvas.resize();
    advance(149);
    expect(canvas.scaleChanges).toHaveBeenCalledTimes(2);
    expect(canvas.writes).not.toHaveBeenCalled();
    advance(1);
    expect(canvas.writes).toHaveBeenCalledExactlyOnceWith(
      storageKey,
      String(fittedScale),
    );
    canvas.unmount();
    expect(canvas.writes).toHaveBeenCalledOnce();
  });

  it("updates consecutive zooms immediately and saves only the latest idle scale", () => {
    const canvas = createCanvas();
    canvas.zoom(1.3);
    expect(canvas.scale).toBe(1.3);
    advance(100);
    canvas.zoom(1.6);
    expect(canvas.scale).toBe(1.6);
    expect(canvas.scaleChanges.mock.calls).toEqual([
      ["--canvas-scale", "1.3"],
      ["--canvas-scale", "1.6"],
    ]);
    advance(149);
    expect(canvas.writes).not.toHaveBeenCalled();
    advance(1);
    expect(canvas.writes).toHaveBeenCalledExactlyOnceWith(storageKey, "1.6");
    canvas.unmount();
    const restored = createCanvas(window.localStorage.getItem(storageKey)!);
    expect(restored.scale).toBe(1.6);
    expect(restored.mode).toBe("manual");
  });

  it("does not let a queued fit resize override a newer manual zoom", () => {
    const canvas = createCanvas();
    canvas.fit();
    canvas.dimensions.width = 600;
    canvas.resize();
    canvas.zoom(1.5);
    frame();
    expect(canvas.scale).toBe(1.5);
    expect(canvas.mode).toBe("manual");
    expect(canvas.scaleChanges.mock.calls).toEqual([
      ["--canvas-scale", "1"],
      ["--canvas-scale", "1.5"],
    ]);
    canvas.unmount();
    expect(canvas.writes).toHaveBeenCalledExactlyOnceWith(storageKey, "1.5");
  });

  it("cancels pending work and removes listeners on unmount, flushing scale once", () => {
    const addWindowListener = vi.spyOn(window, "addEventListener");
    const removeWindowListener = vi.spyOn(window, "removeEventListener");
    const canvas = createCanvas();
    const requestFrame = vi.spyOn(window, "requestAnimationFrame");
    const cancelFrame = vi.spyOn(window, "cancelAnimationFrame");
    const setTimeout = vi.spyOn(window, "setTimeout");
    const clearTimeout = vi.spyOn(window, "clearTimeout");
    canvas.fit();
    canvas.dimensions.width = 600;
    canvas.resize();
    canvas.zoom(1.7);
    const pendingFrame = requestFrame.mock.results.at(-1)!.value;
    const pendingSave = setTimeout.mock.results.at(-1)!.value;
    canvas.unmount();
    expect(canvas.resizeObserver.disconnect).toHaveBeenCalledOnce();
    const pagehideListener = addWindowListener.mock.calls.find(
      ([name]) => name === "pagehide",
    )![1];
    expect(removeWindowListener).toHaveBeenCalledWith(
      "pagehide",
      pagehideListener,
    );
    expect(cancelFrame).toHaveBeenCalledWith(pendingFrame);
    expect(clearTimeout).toHaveBeenCalledWith(pendingSave);
    expect(canvas.writes).toHaveBeenCalledExactlyOnceWith(storageKey, "1.7");
    const detachedWheel = new WheelEvent("wheel", {
      cancelable: true,
      ctrlKey: true,
      deltaY: -30,
    });
    canvas.viewport.dispatchEvent(detachedWheel);
    expect(detachedWheel.defaultPrevented).toBe(false);
    window.dispatchEvent(new Event("pagehide"));
    advance(500);
    expect(canvas.writes).toHaveBeenCalledOnce();
  });

  it("flushes pending zoom on pagehide without duplicate writes", () => {
    const canvas = createCanvas();
    const setTimeout = vi.spyOn(window, "setTimeout");
    const clearTimeout = vi.spyOn(window, "clearTimeout");
    canvas.zoom(1.8);
    const pendingSave = setTimeout.mock.results.at(-1)!.value;
    window.dispatchEvent(new Event("pagehide"));
    expect(canvas.writes).toHaveBeenCalledExactlyOnceWith(storageKey, "1.8");
    expect(clearTimeout).toHaveBeenCalledWith(pendingSave);
    advance(500);
    window.dispatchEvent(new Event("pagehide"));
    canvas.unmount();
    expect(canvas.writes).toHaveBeenCalledOnce();
  });

  it("keeps wheel and keyboard zoom bound to the latest rendered scale", () => {
    const canvas = createCanvas("1");
    fireEvent.wheel(canvas.viewport, { ctrlKey: true, deltaY: -300 });
    expect(canvas.scale).toBe(2);
    fireEvent.keyDown(canvas.viewport, { ctrlKey: true, key: "-" });
    expect(canvas.scale).toBe(1.9);
    fireEvent.keyDown(canvas.viewport, { metaKey: true, key: "0" });
    expect(canvas.scale).toBe(1);
    advance(150);
    expect(canvas.writes).toHaveBeenCalledExactlyOnceWith(storageKey, "1");
    expect(canvas.resizeObserver.observe).toHaveBeenCalledOnce();
  });
});
