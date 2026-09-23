import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { TemplateWorkspaceColumns } from "@/components/workspace/template-workspace-columns";
import WorkspacePanelResizer from "@/components/workspace/workspace-panel-resizer";

let changeViewport: (desktop: boolean) => void;

beforeEach(() => {
  localStorage.clear();
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockImplementation(
    function (this: HTMLElement) {
      return Number.parseFloat(this.style.width) || 1440;
    },
  );
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(800);
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  const media = {
    matches: true,
    addEventListener: (_: string, callback: () => void) => {
      changeViewport = (desktop) => {
        media.matches = desktop;
        callback();
      };
    },
    removeEventListener: vi.fn(),
  };
  vi.stubGlobal("matchMedia", () => media);
});

afterEach(() => vi.unstubAllGlobals());

it("finishes a cancelled touch resize once and permits a fresh gesture", () => {
  const onCommit = vi.fn();
  const onResize = vi.fn();
  render(
    <WorkspacePanelResizer
      width={400}
      min={340}
      max={560}
      direction="right"
      label="Editor width"
      onResizeStart={vi.fn()}
      onResize={onResize}
      onCommit={onCommit}
      onReset={vi.fn()}
    />,
  );
  const handle = screen.getByRole("separator");
  fireEvent.touchStart(handle, { touches: [{ clientX: 400, clientY: 20 }] });
  fireEvent.touchMove(window, { touches: [{ clientX: 448, clientY: 20 }] });
  expect(onResize).toHaveBeenLastCalledWith(448);
  fireEvent.touchCancel(handle, {
    changedTouches: [{ clientX: 448, clientY: 20 }],
  });
  expect(onCommit).toHaveBeenCalledExactlyOnceWith(448);
  onResize.mockClear();
  fireEvent.touchMove(window, { touches: [{ clientX: 480, clientY: 20 }] });
  fireEvent.touchEnd(window);
  expect(onResize).not.toHaveBeenCalled();
  expect(onCommit).toHaveBeenCalledOnce();

  fireEvent.touchStart(handle, { touches: [{ clientX: 400, clientY: 20 }] });
  fireEvent.touchMove(window, { touches: [{ clientX: 432, clientY: 20 }] });
  fireEvent.touchEnd(window);
  expect(onCommit).toHaveBeenLastCalledWith(432);
  expect(onCommit).toHaveBeenCalledTimes(2);
});

it("clears the live resize state and remembers the width when the desktop handle unmounts", async () => {
  const { container } = render(
    <TemplateWorkspaceColumns locale="en" editor={<input aria-label="Name" />}>
      <div>Preview</div>
    </TemplateWorkspaceColumns>,
  );
  const handle = await screen.findByRole("separator");
  const workspace = container.firstElementChild!;
  fireEvent.mouseDown(handle, { clientX: 400, clientY: 20 });
  fireEvent.mouseMove(window, { clientX: 448, clientY: 20 });
  expect(workspace.getAttribute("data-resizing")).toBe("true");
  act(() => changeViewport(false));
  expect(screen.queryByRole("separator")).toBeNull();
  expect(workspace.hasAttribute("data-resizing")).toBe(false);
  expect(localStorage.getItem("reseno-template-editor-width-v1")).toBe("448");
  fireEvent.mouseUp(window);
  act(() => changeViewport(true));
  expect(screen.getByRole("separator").getAttribute("aria-valuenow")).toBe(
    "448",
  );
});
