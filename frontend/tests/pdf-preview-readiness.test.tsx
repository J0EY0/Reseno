import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ResumePreview } from "@/components/preview/resume-preview";
import { defaultMessages } from "@/i18n";
import {
  createResumeDetailItem,
  createResumeDetailTemplate,
} from "./helpers/resume-detail-fixtures";
import {
  deferred,
  installFonts,
  installFrames,
  installPreviewGeometry,
} from "./helpers/pdf-browser-fixtures";

let restoreFonts: () => void;
beforeEach(() => {
  vi.stubGlobal("ResizeObserver", undefined);
});
afterEach(() => {
  cleanup();
  restoreFonts?.();
  vi.unstubAllGlobals();
});

it("measures visible page slices before fonts settle, then needs two matching frames before reporting readiness", async () => {
  const fonts = deferred<void>();
  restoreFonts = installFonts(fonts.promise);
  const frames = installFrames();
  const geometry = installPreviewGeometry();
  const onReady = vi.fn();
  const item = createResumeDetailItem();
  const template = createResumeDetailTemplate("minimal");
  const { container, rerender, unmount } = render(
    <ResumePreview
      fontFamily="inter"
      fontSize={16}
      resume={item.resume}
      template={template}
      t={defaultMessages}
      onPaginationReadyChange={onReady}
    />,
  );
  const stack = () => container.querySelector(".resume-page-stack");
  expect(stack()?.getAttribute("data-resume-page-count")).toBe("2");
  expect(stack()?.getAttribute("data-resume-pagination-ready")).toBe("false");
  expect(onReady).toHaveBeenLastCalledWith(false, 2);
  await act(() => vi.dynamicImportSettled());
  await frames.frame();
  expect(stack()?.getAttribute("data-resume-pagination-ready")).toBe("false");
  await act(async () => fonts.resolve());
  await frames.frame();
  expect(stack()?.getAttribute("data-resume-pagination-ready")).toBe("false");
  geometry.contentHeight = 800;
  await frames.frame();
  expect(stack()?.getAttribute("data-resume-page-count")).toBe("3");
  expect(stack()?.getAttribute("data-resume-pagination-ready")).toBe("false");
  await frames.frame();
  expect(onReady).toHaveBeenLastCalledWith(true, 3);
  expect(stack()?.getAttribute("data-resume-pagination-ready")).toBe("true");
  const updated = {
    ...item.resume,
    basic: { ...item.resume.basic, name: "Updated" },
  };
  rerender(
    <ResumePreview
      fontFamily="inter"
      fontSize={16}
      resume={updated}
      template={template}
      t={defaultMessages}
      onPaginationReadyChange={onReady}
    />,
  );
  expect(onReady).toHaveBeenLastCalledWith(false, 3);
  await act(() => vi.dynamicImportSettled());
  await frames.frame();
  await frames.frame();
  expect(onReady).toHaveBeenLastCalledWith(false, 3);
  await frames.frame();
  expect(onReady).toHaveBeenLastCalledWith(true, 3);
  rerender(
    <ResumePreview
      fontFamily="inter"
      fontSize={16}
      resume={item.resume}
      template={template}
      t={defaultMessages}
      onPaginationReadyChange={onReady}
    />,
  );
  await act(() => vi.dynamicImportSettled());
  const callsBeforeUnmount = onReady.mock.calls.length;
  unmount();
  await frames.frame();
  expect(onReady).toHaveBeenCalledTimes(callsBeforeUnmount);
  expect(frames.pending.size).toBe(0);
});

it("uses measured text line boxes to avoid splitting a line at a page boundary", async () => {
  restoreFonts = installFonts(Promise.resolve());
  const frames = installFrames();
  const geometry = installPreviewGeometry();
  geometry.lineRects = [new DOMRect(0, 260, 100, 30)];
  const item = createResumeDetailItem();
  const template = createResumeDetailTemplate("minimal");
  const { container } = render(
    <ResumePreview
      fontFamily="inter"
      fontSize={16}
      resume={item.resume}
      template={template}
      t={defaultMessages}
    />,
  );
  const viewport = container.querySelector<HTMLElement>(
    ".resume-page-content-viewport",
  );
  expect(viewport?.style.height).toBe("260mm");
  const next = container.querySelectorAll<HTMLElement>(
    ".resume-page-content-fragment",
  )[1];
  expect(next.style.transform).toBe("translateY(-260mm)");
  await act(() => vi.dynamicImportSettled());
  await frames.frame();
});
