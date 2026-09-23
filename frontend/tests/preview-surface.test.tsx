import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { DocumentCanvas } from "@/components/preview/document-canvas";
import { ResumePreview } from "@/components/preview/resume-preview";
import { TemplateImages } from "@/components/preview/resume-preview-media";
import { ResumeThumbnail } from "@/components/preview/resume-thumbnail";
import { defaultMessages as t } from "@/i18n";
import { createResumeSection } from "@/lib/resume-sections";
import type { ResumeDraftDiff, ResumeTemplateLayout } from "@/types/resume";
import {
  installFonts,
  installFrames,
  installPreviewGeometry,
} from "./helpers/pdf-browser-fixtures";
import {
  createResumeDetailItem,
  createResumeDetailTemplate,
} from "./helpers/resume-detail-fixtures";
import { createTemplateImageElement } from "@/lib/templates";

let restoreFonts: () => void;
const capture = vi.fn();
const release = vi.fn();

it.each([false, true])(
  "keeps hidden template images absent (editable=%s)",
  (editable) => {
    const { container } = render(
      <TemplateImages
        editable={editable}
        onChangeImage={vi.fn()}
        showEmptyPlaceholders
        images={[{ ...createTemplateImageElement(1, "Image"), visible: false }]}
      />,
    );
    expect(container.querySelector("[data-template-image-frame]")).toBeNull();
    expect(
      container.querySelector("[data-template-image-resize-handle]"),
    ).toBeNull();
  },
);

beforeEach(() => {
  window.localStorage.clear();
  window.localStorage.setItem("reseno-document-canvas-scale-v1", "1");
  restoreFonts = installFonts(Promise.resolve());
  installFrames();
  installPreviewGeometry();
  const measure = vi
    .mocked(HTMLElement.prototype.getBoundingClientRect)
    .getMockImplementation()!;
  vi.mocked(HTMLElement.prototype.getBoundingClientRect).mockImplementation(
    function (this: HTMLElement) {
      if (this.dataset.slot === "document-canvas-viewport")
        return new DOMRect(0, 0, 1000, 800);
      if (this.hasAttribute("data-document-canvas-paper")) {
        const viewport = this.closest<HTMLElement>(
          '[data-slot="document-canvas-viewport"]',
        )!;
        const scale =
          Number(viewport.style.getPropertyValue("--canvas-scale")) || 1;
        return new DOMRect(24, 24, 210 * scale, 297 * scale);
      }
      if (
        this.dataset.exportRoot ||
        this.classList.contains("resume-page-content-viewport") ||
        this.classList.contains("resume-page-flow-viewport")
      )
        return new DOMRect(24, 24, 210, 500);
      if (this.dataset.resumeDiffPath) return new DOMRect(30, 40, 150, 20);
      return measure.call(this);
    },
  );
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: true,
      addEventListener() {},
      removeEventListener() {},
    })),
  );
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(1000);
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(800);
  vi.stubGlobal("PointerEvent", MouseEvent);
  Object.defineProperty(HTMLElement.prototype, "setPointerCapture", {
    configurable: true,
    value: capture,
  });
  Object.defineProperty(HTMLElement.prototype, "releasePointerCapture", {
    configurable: true,
    value: release,
  });
});
afterEach(() => {
  cleanup();
  restoreFonts();
  vi.unstubAllGlobals();
  Reflect.deleteProperty(HTMLElement.prototype, "setPointerCapture");
  Reflect.deleteProperty(HTMLElement.prototype, "releasePointerCapture");
});

function pointer(
  target: Element,
  type: string,
  overrides: Record<string, unknown> = {},
) {
  const event = new MouseEvent(type, {
    bubbles: true,
    cancelable: true,
    button: 0,
    clientX: 100,
    clientY: 100,
    ...overrides,
  });
  Object.assign(event, {
    pointerId: 7,
    pointerType: "mouse",
    ...Object.fromEntries(
      Object.entries(overrides).filter(([key]) => key.startsWith("pointer")),
    ),
  });
  fireEvent(target, event);
  return event;
}
function canvas(diffs?: ResumeDraftDiff[], onSelectReviewItem = vi.fn()) {
  const item = createResumeDetailItem();
  const template = createResumeDetailTemplate("custom");
  const view = render(
    <DocumentCanvas
      variant="resume"
      t={t}
      documentT={t}
      resume={item.resume}
      template={template}
      typography={item.typography}
      diffs={diffs}
      draftReview={{
        onSelectReviewItem,
        reviewItemIdByOperationId: { "edit-headline": "review-headline" },
      }}
    />,
  );
  const viewport = screen.getByRole("region", { name: t.preview });
  const scrollBy = vi.fn((x: number, y: number) => {
    viewport.scrollLeft += x;
    viewport.scrollTop += y;
  });
  Object.defineProperty(viewport, "scrollBy", {
    configurable: true,
    value: scrollBy,
  });
  return {
    ...view,
    viewport,
    scrollBy,
    paper: viewport.querySelector<HTMLElement>("[data-document-canvas-paper]")!,
  };
}

it("wires real canvas keyboard, wheel and toolbar zoom with bounded controls and anchored scrolling", () => {
  const { viewport, scrollBy } = canvas();
  expect(screen.queryByText(t.preview)).toBeNull();
  viewport.focus();
  fireEvent.keyDown(viewport, { ctrlKey: true, key: "+" });
  expect(screen.getByRole("button", { name: t.actualSize }).textContent).toBe(
    "110%",
  );
  fireEvent.keyDown(screen.getByRole("button", { name: t.zoomOut }), {
    metaKey: true,
    key: "-",
  });
  expect(viewport.style.getPropertyValue("--canvas-scale")).toBe("1");
  const wheel = new WheelEvent("wheel", {
    bubbles: true,
    cancelable: true,
    ctrlKey: true,
    deltaY: -300,
    clientX: 124,
    clientY: 124,
  });
  fireEvent(viewport, wheel);
  expect(wheel.defaultPrevented).toBe(true);
  expect(scrollBy).toHaveBeenLastCalledWith(100, 100);
  expect(
    (screen.getByRole("button", { name: t.zoomIn }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  fireEvent.keyDown(viewport, { metaKey: true, key: "0" });
  expect(screen.getByRole("button", { name: t.actualSize }).textContent).toBe(
    "100%",
  );
  fireEvent.wheel(viewport, { ctrlKey: true, deltaY: 3000 });
  expect(
    (screen.getByRole("button", { name: t.zoomOut }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  expect(viewport.style.getPropertyValue("--canvas-scale")).toBe("0.25");
  fireEvent.click(screen.getByRole("button", { name: t.fitToWidth }));
  expect(
    screen
      .getByRole("button", { name: t.fitToWidth })
      .getAttribute("aria-pressed"),
  ).toBe("true");
  fireEvent.click(screen.getByRole("button", { name: t.actualSize }));
  expect(
    screen
      .getByRole("button", { name: t.fitToWidth })
      .getAttribute("aria-pressed"),
  ).toBe("false");
  expect(
    screen.getByText(
      t.canvasPage.replace("{current}", "1").replace("{total}", "2"),
    ),
  ).toBeTruthy();
});

it.each([
  ["background", 0, "mouse", true],
  ["paper", 1, "mouse", true],
  ["paper", 0, "mouse", false],
  ["background", 0, "touch", false],
] as const)(
  "pans %s with button %s and %s only when allowed",
  (surface, button, pointerType, allowed) => {
    const { viewport, paper } = canvas();
    viewport.scrollLeft = 80;
    viewport.scrollTop = 90;
    const down = pointer(
      surface === "paper" ? paper : viewport,
      "pointerdown",
      { button, pointerType },
    );
    expect(down.defaultPrevented).toBe(allowed);
    expect(capture).toHaveBeenCalledTimes(allowed ? 1 : 0);
    if (!allowed) {
      pointer(viewport, "pointermove", { clientX: 130, clientY: 120 });
      expect([viewport.scrollLeft, viewport.scrollTop]).toEqual([80, 90]);
      return;
    }
    expect(capture).toHaveBeenCalledWith(7);
    expect(viewport.dataset.panning).toBe("true");
    pointer(viewport, "pointermove", { pointerId: 8, clientX: 120 });
    expect(viewport.scrollLeft).toBe(80);
    pointer(viewport, "pointermove", { clientX: 130, clientY: 120 });
    expect([viewport.scrollLeft, viewport.scrollTop]).toEqual([50, 70]);
    pointer(viewport, "lostpointercapture");
    expect(viewport.dataset.panning).toBe("false");
    pointer(viewport, "pointermove", { clientX: 150, clientY: 150 });
    expect([viewport.scrollLeft, viewport.scrollTop]).toEqual([50, 70]);
  },
);

it.each(["centered", "sidebar"] as const)(
  "keeps the %s measurement copy inert and hidden while rendering accessible pages",
  (basicInfo) => {
    const item = createResumeDetailItem();
    item.resume.basic.email = "ada@example.com";
    const template = createResumeDetailTemplate("custom");
    template.layout.basicInfo = basicInfo;
    const { container } = render(
      <ResumePreview
        t={t}
        resume={item.resume}
        template={template}
        fontFamily="inter"
        fontSize={16}
      />,
    );
    const hidden = container.querySelectorAll<HTMLElement>("[inert]");
    expect(hidden).toHaveLength(1);
    expect(hidden[0].getAttribute("aria-hidden")).toBe("true");
    expect(hidden[0].textContent).toContain("Ada");
    const pages = container.querySelectorAll<HTMLElement>(
      '[data-export-root="resume-page"]',
    );
    expect(pages.length).toBeGreaterThan(0);
    for (const page of pages) {
      expect(page.closest("[inert], [aria-hidden=true]")).toBeNull();
      expect(page.textContent).toContain("Ada");
      expect(
        within(page)
          .getByRole("link", { name: "ada@example.com" })
          .getAttribute("href"),
      ).toBe("mailto:ada@example.com");
    }
    expect(container.querySelector(".resume-page-label")).toBeNull();
  },
);

const headlineDiff: ResumeDraftDiff = {
  id: "diff-headline",
  operationId: "edit-headline",
  path: "basic.headline",
  kind: "modified",
  label: "Update headline",
  before: "<p><strong>Developer</strong></p>",
  after: "Engineer",
};
it.each(["click", "Enter", " "])(
  "opens one real delegated comparison through %s and selects the canonical review item",
  async (activation) => {
    const select = vi.fn();
    const { container, unmount } = canvas([headlineDiff], select);
    await act(() => vi.dynamicImportSettled());
    const target = await screen.findAllByRole("button", {
      name: t.agentDiffInspect.replace("{label}", headlineDiff.label),
    });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(
      container.querySelector(
        '[data-export-root="resume-page"] [data-resume-diff-badge]',
      )?.textContent,
    ).toBe(t.agentDiffModified);
    const hidden = container.querySelector<HTMLElement>(
      '[inert] [data-resume-diff-path="basic.headline"]',
    )!;
    fireEvent.click(hidden);
    expect(select).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
    if (activation === "click") fireEvent.click(target[0]);
    else fireEvent.keyDown(target[0], { key: activation });
    const dialog = await screen.findByRole("dialog");
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(within(dialog).getByText(headlineDiff.label)).toBeTruthy();
    expect(within(dialog).getByText(t.agentDiffBefore)).toBeTruthy();
    expect(within(dialog).getByText(t.agentDiffAfter)).toBeTruthy();
    expect(dialog.querySelector("strong")?.textContent).toBe("Developer");
    expect(within(dialog).getByText("Engineer")).toBeTruthy();
    expect(select).toHaveBeenCalledExactlyOnceWith("review-headline");
    expect(target[0].getAttribute("aria-expanded")).toBe("true");
    unmount();
    expect(screen.queryByRole("dialog")).toBeNull();
  },
);

it.each(["boxed", "band", "ruled"] satisfies ResumeTemplateLayout["section"][])(
  "renders %s section status and deleted item/section review anchors beside surviving content",
  async (sectionLayout) => {
    const item = createResumeDetailItem();
    const section = createResumeSection("experience");
    if (section.kind !== "experience")
      throw new Error("Expected experience fixture");
    section.id = "experience";
    section.title = "Experience";
    section.items[0].id = "survivor";
    section.items[0].company = "Surviving company";
    item.resume.sections = [section];
    const template = createResumeDetailTemplate("custom");
    template.layout.section = sectionLayout;
    const diffs: ResumeDraftDiff[] = [
      {
        id: "section",
        operationId: "move-section",
        path: "sections.experience",
        kind: "moved",
        label: "Move experience",
        sectionId: section.id,
        before: 1,
        after: 0,
      },
      {
        id: "item",
        operationId: "add-item",
        path: "sections.experience.items.survivor",
        kind: "added",
        label: "Add company",
        sectionId: section.id,
        itemId: "survivor",
        after: section.items[0],
      },
      {
        id: "deleted-item",
        operationId: "delete-item",
        path: "sections.experience.items.removed",
        kind: "deleted",
        label: "Removed company",
        sectionId: section.id,
        itemId: "removed",
        beforeNextId: "survivor",
        before: { company: "Old company" },
      },
      {
        id: "deleted-section",
        operationId: "delete-section",
        path: "sections.removed",
        kind: "deleted",
        label: "Removed education",
        sectionId: "removed",
        beforeNextId: section.id,
        before: { title: "Education" },
      },
    ];
    const { container } = render(
      <ResumePreview
        t={t}
        resume={item.resume}
        template={template}
        fontFamily="inter"
        fontSize={16}
        diffs={diffs}
      />,
    );
    await act(() => vi.dynamicImportSettled());
    const page = container.querySelector<HTMLElement>(
      '[data-export-root="resume-page"]',
    )!;
    const block = page.querySelector<HTMLElement>(
      '[data-resume-section-id="experience"]',
    )!;
    expect(block.dataset.resumeSectionLayout).toBe(sectionLayout);
    expect(block.dataset.resumeDiffLabel).toBe(t.agentDiffMoved);
    expect(
      block.querySelectorAll(":scope > [data-resume-diff-badge]"),
    ).toHaveLength(1);
    expect(
      block.querySelector(
        '[data-resume-diff-badge][data-resume-diff-kind="added"]',
      )?.textContent,
    ).toBe(t.agentDiffAdded);
    const anchors = [
      ...page.querySelectorAll<HTMLElement>(".resume-diff-deleted-anchor"),
    ];
    expect(anchors.map((node) => node.dataset.resumeDiffPath)).toEqual([
      "sections.removed",
      "sections.experience.items.removed",
    ]);
    for (const anchor of anchors) {
      expect(
        anchor.querySelector("[data-resume-diff-badge]")?.textContent,
      ).toBe(t.agentDiffDeleted);
      expect(
        anchor.compareDocumentPosition(
          within(page).getByText("Surviving company"),
        ) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).not.toBe(0);
    }
  },
);

it.each([
  [false, false],
  [true, true],
  [false, true],
] as const)(
  "enables template image editing only with a command on a custom template (builtin=%s, command=%s)",
  async (isBuiltIn, hasCommand) => {
    const item = createResumeDetailItem();
    const template = createResumeDetailTemplate("custom", { isBuiltIn });
    template.layout.images = [
      {
        id: "image",
        name: "Photo",
        src: "data:image/png;base64,eA==",
        alt: "Template photo",
        x: 10,
        y: 20,
        width: 30,
        height: 30,
        opacity: 1,
        borderWidth: 0,
        borderColor: "#000000",
        borderRadius: 0,
        objectFit: "cover",
        visible: true,
      },
    ];
    const move = vi.fn();
    const { container, unmount } = render(
      <DocumentCanvas
        variant="template"
        t={t}
        documentT={t}
        resume={item.resume}
        template={template}
        onChangeTemplateImage={hasCommand ? move : undefined}
      />,
    );
    await act(() => vi.dynamicImportSettled());
    const frame = container.querySelector<HTMLElement>(
      '[data-template-image-frame="true"]',
    )!;
    expect(
      frame.querySelectorAll("[data-template-image-resize-handle]").length,
    ).toBe(hasCommand && !isBuiltIn ? 8 : 0);
    pointer(frame, "pointerdown");
    pointer(frame, "pointermove", { clientX: 110, clientY: 115 });
    pointer(frame, "pointerup");
    expect(move).toHaveBeenCalledTimes(hasCommand && !isBuiltIn ? 1 : 0);
    if (hasCommand && !isBuiltIn) {
      expect(move).toHaveBeenCalledWith("image", {
        x: 20,
        y: 35,
        width: 30,
        height: 30,
      });
      expect(release).toHaveBeenCalledWith(7);
    }
    unmount();
    capture.mockClear();
    const thumbnail = render(
      <ResumeThumbnail
        t={t}
        resume={item.resume}
        template={template}
        fontFamily="inter"
        fontSize={16}
      />,
    );
    pointer(
      thumbnail.container.querySelector('[data-template-image-frame="true"]')!,
      "pointerdown",
    );
    expect(capture).not.toHaveBeenCalled();
  },
);
