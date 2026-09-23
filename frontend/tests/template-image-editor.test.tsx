import { fireEvent, render } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, expect, it, vi } from "vitest";

import TemplateImageEditor from "@/components/preview/template-image-editor";
import { createTemplateImageElement } from "@/lib/templates";

const pixelsPerMm = 96 / 25.4;

beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockImplementation(
    function (this: HTMLElement) {
      return Number.parseFloat(this.style.width) || 800;
    },
  );
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockImplementation(
    function (this: HTMLElement) {
      return Number.parseFloat(this.style.height) || 1100;
    },
  );
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
    function (this: HTMLElement) {
      return new DOMRect(
        0,
        0,
        this.hasAttribute("data-export-root")
          ? 210 * pixelsPerMm
          : this.offsetWidth,
        this.offsetHeight,
      );
    },
  );
});

function imageEditor() {
  const change = vi.fn();
  function Editor() {
    const [image, setImage] = useState(() =>
      createTemplateImageElement(1, "Image"),
    );
    return (
      <article data-export-root="resume-page">
        <TemplateImageEditor
          image={image}
          onChange={(_id, geometry) => {
            change(geometry);
            setImage((current) => ({ ...current, ...geometry }));
          }}
        >
          <span>Image</span>
        </TemplateImageEditor>
      </article>
    );
  }
  const view = render(<Editor />);
  const frame = view.container.querySelector<HTMLElement>(
    "[data-template-image-frame]",
  )!;
  const handle = frame.querySelector<HTMLElement>(
    '[data-template-image-resize-handle="right"]',
  )!;
  const capture = vi.fn();
  const release = vi.fn();
  Object.assign(frame, {
    setPointerCapture: capture,
    releasePointerCapture: release,
  });
  return { ...view, change, frame, handle, capture, release };
}

function pointer(target: Element, type: string, clientX = 0) {
  const event = new MouseEvent(type, { bubbles: true, clientX, button: 0 });
  Object.defineProperty(event, "pointerId", { value: 7 });
  fireEvent(target, event);
}

it.each(["touchcancel", "pointercancel"])(
  "ends image resizing on %s without committing later movement",
  (cancel) => {
    const { change, frame, handle } = imageEditor();
    fireEvent.touchStart(handle, { touches: [{ clientX: 0, clientY: 0 }] });
    fireEvent.touchMove(window, {
      touches: [{ clientX: 10 * pixelsPerMm, clientY: 0 }],
    });
    expect(change).toHaveBeenLastCalledWith({
      x: 166,
      y: 18,
      width: 40,
      height: 20,
    });
    expect(frame.getAttribute("data-resizing")).toBe("true");
    change.mockClear();

    if (cancel === "touchcancel")
      fireEvent.touchCancel(handle, { touches: [] });
    else pointer(handle, "pointercancel");
    expect(frame.hasAttribute("data-resizing")).toBe(false);
    fireEvent.touchMove(window, {
      touches: [{ clientX: 20 * pixelsPerMm, clientY: 0 }],
    });
    fireEvent.mouseMove(window, { clientX: 30 * pixelsPerMm, clientY: 0 });
    fireEvent.touchEnd(window, { touches: [] });
    expect(change).not.toHaveBeenCalled();
    expect(frame.style.width).toBe("40mm");

    fireEvent.touchStart(handle, { touches: [{ clientX: 0, clientY: 0 }] });
    fireEvent.touchMove(window, {
      touches: [{ clientX: -5 * pixelsPerMm, clientY: 0 }],
    });
    expect(change).toHaveBeenLastCalledWith({
      x: 166,
      y: 18,
      width: 35,
      height: 20,
    });
    change.mockClear();
    fireEvent.touchEnd(window, { touches: [] });
    expect(frame.hasAttribute("data-resizing")).toBe(false);
    expect(change).not.toHaveBeenCalled();
  },
);

it("cancels a resize before movement without changing image geometry", () => {
  const { change, frame, handle } = imageEditor();
  fireEvent.mouseDown(handle, { button: 0, clientX: 0, clientY: 0 });
  pointer(handle, "pointercancel");
  fireEvent.mouseMove(window, { clientX: 10 * pixelsPerMm, clientY: 0 });
  fireEvent.mouseUp(window);
  expect(frame.hasAttribute("data-resizing")).toBe(false);
  expect(change).not.toHaveBeenCalled();
  expect(frame.style.width).toBe("30mm");
});

it("ends a cancelled image drag without applying later pointer movement", () => {
  const { change, frame, capture, release } = imageEditor();
  pointer(frame, "pointerdown");
  pointer(frame, "pointermove", -10 * pixelsPerMm);
  expect(change).toHaveBeenLastCalledWith({
    x: 156,
    y: 18,
    width: 30,
    height: 20,
  });
  change.mockClear();
  pointer(frame, "pointercancel", -10 * pixelsPerMm);
  pointer(frame, "pointermove", -20 * pixelsPerMm);
  pointer(frame, "pointerup", -20 * pixelsPerMm);
  expect(capture).toHaveBeenCalledWith(7);
  expect(release).toHaveBeenCalledOnce();
  expect(change).not.toHaveBeenCalled();
});

it("removes active resize listeners on unmount without another geometry update", () => {
  const { change, handle, unmount } = imageEditor();
  fireEvent.touchStart(handle, { touches: [{ clientX: 0, clientY: 0 }] });
  fireEvent.touchMove(window, {
    touches: [{ clientX: 5 * pixelsPerMm, clientY: 0 }],
  });
  expect(change).toHaveBeenCalled();
  change.mockClear();
  unmount();
  fireEvent.touchMove(window, {
    touches: [{ clientX: 10 * pixelsPerMm, clientY: 0 }],
  });
  fireEvent.mouseMove(window, { clientX: 15 * pixelsPerMm, clientY: 0 });
  fireEvent.touchEnd(window, { touches: [] });
  fireEvent.mouseUp(window);
  expect(change).not.toHaveBeenCalled();
});
