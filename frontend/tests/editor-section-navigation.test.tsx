import { act, fireEvent, render } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import {
  useEditorSectionNavigation,
  type EditorSectionNavigation,
} from "@/components/editor/use-editor-section-navigation";
import { installFrames } from "./helpers/pdf-browser-fixtures";

function Editor({
  active = "experience",
  navigation,
  itemOpen = true,
  stacked = false,
  getAnimations,
  onScrollTo,
}: {
  active?: string;
  navigation?: EditorSectionNavigation;
  itemOpen?: boolean;
  stacked?: boolean;
  getAnimations: () => Animation[];
  onScrollTo?: (options: ScrollToOptions) => void;
}) {
  const { panelRef, onScroll, onInteraction } = useEditorSectionNavigation(
    active,
    navigation,
  );
  return (
    <section
      ref={(element) => {
        panelRef.current = element;
        if (element) {
          element.getAnimations = getAnimations;
          element.scrollTo = ((options: ScrollToOptions) => {
            onScrollTo?.(options);
            if (options.behavior !== "smooth")
              element.scrollTop = options.top ?? element.scrollTop;
          }) as HTMLElement["scrollTo"];
          element.style.setProperty("--document-sticky-top", "40px");
        }
      }}
      data-testid="panel"
      style={{ overflowY: stacked ? "visible" : "auto" }}
      onScroll={onScroll}
      onPointerDownCapture={onInteraction}
      onKeyDownCapture={onInteraction}
      onWheelCapture={onInteraction}
    >
      <div data-editor-section-id="experience">
        <button
          data-slot="editor-toggle-trigger"
          aria-expanded={active === "experience"}
        />
        <section data-resume-item-id="second" data-open={itemOpen}>
          {itemOpen ? <input aria-label="Company" /> : null}
        </section>
      </div>
      <div data-editor-section-id="basic">
        <button
          data-slot="editor-toggle-trigger"
          aria-expanded={active === "basic"}
        />
      </div>
    </section>
  );
}

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: true }));
  vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(2000);
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(600);
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
    function (this: HTMLElement) {
      if (this.dataset.testid === "panel") return new DOMRect(0, 50, 400, 600);
      const panel = this.closest<HTMLElement>('[data-testid="panel"]');
      const scrollTop =
        panel?.style.overflowY === "visible"
          ? window.scrollY
          : (panel?.scrollTop ?? 0);
      return new DOMRect(0, 500 - scrollTop, 400, 200);
    },
  );
});

it.each(["pointer", "keyboard", "wheel"] as const)(
  "cancels pending navigation on %s interaction and remembers later manual scrolling",
  async (interaction) => {
    const frames = installFrames();
    const finished = Promise.withResolvers<Animation>();
    const animation = {
      playState: "running",
      finished: finished.promise,
      effect: { getTiming: () => ({ iterations: 1 }) },
    } as Animation;
    const getAnimations = vi.fn(() => [animation]);
    const navigation = {
      sectionId: "experience",
      itemId: "second",
      requestId: 1,
    };
    const view = render(
      <Editor navigation={navigation} getAnimations={getAnimations} />,
    );
    const panel = view.getByTestId("panel");
    await frames.frame();
    expect(getAnimations).toHaveBeenCalledOnce();
    expect(panel.scrollTop).toBe(0);

    if (interaction === "pointer") fireEvent.pointerDown(panel);
    else if (interaction === "keyboard")
      fireEvent.keyDown(panel, { key: "Enter" });
    else fireEvent.wheel(panel, { deltaY: 100 });
    view.rerender(
      <Editor
        navigation={navigation}
        itemOpen={false}
        getAnimations={getAnimations}
      />,
    );
    panel.scrollTop = 180;
    fireEvent.scroll(panel);
    getAnimations.mockReturnValue([]);
    await act(async () => finished.resolve(animation));
    expect(panel.scrollTop).toBe(180);
    view.rerender(
      <Editor navigation={navigation} getAnimations={getAnimations} />,
    );
    await frames.frame();
    expect(panel.scrollTop).toBe(180);

    view.rerender(<Editor active="basic" getAnimations={getAnimations} />);
    panel.scrollTop = 0;
    fireEvent.scroll(panel);
    view.rerender(<Editor getAnimations={getAnimations} />);
    await frames.frame();
    expect(panel.scrollTop).toBe(180);

    view.rerender(
      <Editor
        navigation={{ ...navigation, requestId: 2 }}
        getAnimations={getAnimations}
      />,
    );
    await frames.frame();
    expect(panel.scrollTop).toBe(450);
  },
);

it("remembers completed smooth navigation without saving intermediate positions", async () => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  const frames = installFrames();
  const props = { getAnimations: () => [], onScrollTo: vi.fn() };
  const navigation = {
    sectionId: "experience",
    itemId: "second",
    requestId: 1,
  };
  const view = render(<Editor {...props} />);
  const panel = view.getByTestId("panel");
  panel.scrollTop = 120;
  fireEvent.scroll(panel);

  view.rerender(<Editor {...props} navigation={navigation} />);
  await frames.frame();
  expect(props.onScrollTo).toHaveBeenLastCalledWith({
    top: 450,
    behavior: "smooth",
  });
  panel.scrollTop = 240;
  fireEvent.scroll(panel);
  view.rerender(<Editor {...props} active="basic" />);
  expect(props.onScrollTo).toHaveBeenLastCalledWith({
    top: 240,
    behavior: "instant",
  });
  view.rerender(<Editor {...props} />);
  await frames.frame();
  expect(panel.scrollTop).toBe(120);

  view.rerender(
    <Editor {...props} navigation={{ ...navigation, requestId: 2 }} />,
  );
  await frames.frame();
  panel.scrollTop = 450;
  fireEvent.scroll(panel);
  fireEvent(panel, new Event("scrollend"));
  view.rerender(<Editor {...props} active="basic" />);
  panel.scrollTop = 0;
  view.rerender(<Editor {...props} />);
  await frames.frame();
  expect(panel.scrollTop).toBe(450);
});

it.each(["pointer", "keyboard", "wheel"] as const)(
  "cancels pending stacked navigation on outside %s interaction and accepts a later request",
  async (interaction) => {
    vi.stubGlobal("matchMedia", () => ({ matches: false }));
    vi.stubGlobal("scrollY", 0);
    const scrollTo = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    const frames = installFrames();
    const finished = Promise.withResolvers<Animation>();
    const animation = {
      playState: "running",
      finished: finished.promise,
      effect: { getTiming: () => ({ iterations: 1 }) },
    } as Animation;
    const getAnimations = vi.fn(() => [animation]);
    const navigation = {
      sectionId: "experience",
      itemId: "second",
      requestId: 1,
    };
    const view = render(
      <Editor stacked getAnimations={getAnimations} navigation={navigation} />,
    );
    await frames.frame();
    expect(scrollTo).not.toHaveBeenCalled();

    if (interaction === "pointer") fireEvent.pointerDown(document.body);
    else if (interaction === "keyboard")
      fireEvent.keyDown(document.body, { key: "ArrowDown" });
    else fireEvent.wheel(document.body, { deltaY: 200 });
    vi.stubGlobal("scrollY", 200);
    getAnimations.mockReturnValue([]);
    await act(async () => finished.resolve(animation));
    expect(scrollTo).not.toHaveBeenCalled();

    view.rerender(
      <Editor
        stacked
        getAnimations={getAnimations}
        navigation={{ ...navigation, requestId: 2 }}
      />,
    );
    await frames.frame();
    expect(scrollTo).toHaveBeenCalledExactlyOnceWith({
      top: 460,
      behavior: "smooth",
    });
    fireEvent(document, new Event("scrollend"));
    fireEvent.wheel(document.body, { deltaY: 100 });
    view.unmount();
    expect(scrollTo).toHaveBeenCalledOnce();
  },
);

it("stops native scrolling for a new request, manual input, and unmount", async () => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  const frames = installFrames();
  const props = { getAnimations: () => [], onScrollTo: vi.fn() };
  const navigation = {
    sectionId: "experience",
    itemId: "second",
    requestId: 1,
  };
  const view = render(<Editor {...props} navigation={navigation} />);
  const panel = view.getByTestId("panel");
  await frames.frame();
  panel.scrollTop = 180;
  view.rerender(
    <Editor {...props} navigation={{ ...navigation, requestId: 2 }} />,
  );
  expect(props.onScrollTo).toHaveBeenLastCalledWith({
    top: 180,
    behavior: "instant",
  });
  await frames.frame();
  panel.scrollTop = 250;
  fireEvent.wheel(panel, { deltaY: 100 });
  expect(props.onScrollTo).toHaveBeenLastCalledWith({
    top: 250,
    behavior: "instant",
  });
  panel.scrollTop = 320;
  fireEvent.scroll(panel);
  fireEvent(panel, new Event("scrollend"));
  view.rerender(<Editor {...props} active="basic" />);
  view.rerender(<Editor {...props} />);
  await frames.frame();
  expect(panel.scrollTop).toBe(320);

  view.rerender(
    <Editor {...props} navigation={{ ...navigation, requestId: 3 }} />,
  );
  await frames.frame();
  view.unmount();
  expect(props.onScrollTo).toHaveBeenLastCalledWith({
    top: 320,
    behavior: "instant",
  });
});

it.each([false, true])(
  "uses window scrolling below the sticky header with reduced motion %s",
  async (reducedMotion) => {
    vi.stubGlobal("matchMedia", () => ({ matches: reducedMotion }));
    vi.stubGlobal("scrollY", 0);
    const scrollTo = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    const frames = installFrames();
    const view = render(
      <Editor
        stacked
        getAnimations={() => []}
        navigation={{ sectionId: "experience", itemId: "second", requestId: 1 }}
      />,
    );
    await frames.frame();
    expect(scrollTo).toHaveBeenLastCalledWith({
      top: 460,
      behavior: reducedMotion ? "instant" : "smooth",
    });
    vi.stubGlobal("scrollY", 120);
    fireEvent.wheel(document.body, { deltaY: 100 });
    if (reducedMotion) expect(scrollTo).toHaveBeenCalledOnce();
    else
      expect(scrollTo).toHaveBeenLastCalledWith({
        top: 120,
        behavior: "instant",
      });
    fireEvent(document, new Event("scrollend"));
    view.unmount();
    expect(scrollTo).toHaveBeenCalledTimes(reducedMotion ? 1 : 2);
  },
);

it("does not wait for scrollend when the target is already at the scroll limit", async () => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(600);
  const frames = installFrames();
  const onScrollTo = vi.fn();
  const view = render(
    <Editor
      getAnimations={() => []}
      onScrollTo={onScrollTo}
      navigation={{ sectionId: "experience", itemId: "second", requestId: 1 }}
    />,
  );
  await frames.frame();
  expect(onScrollTo).toHaveBeenCalledExactlyOnceWith({
    top: 0,
    behavior: "instant",
  });
  view.unmount();
  expect(onScrollTo).toHaveBeenCalledOnce();
});
