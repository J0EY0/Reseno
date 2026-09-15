import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { defaultMessages as t } from "@/i18n";
import { TemplateEditor } from "@/components/templates/template-editor";
import { TemplateEditorTabs } from "@/components/templates/template-editor-tabs";
import { TemplateLayoutTab } from "@/components/templates/editor/layout-tab";
import { Tabs } from "@/components/ui/tabs";
import { getBuiltInTemplates } from "@/lib/templates";

const template = {
  ...getBuiltInTemplates(t)[0],
  id: "custom",
  isBuiltIn: false,
  name: "Custom layout",
  description: "",
};
beforeEach(() => {
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
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
function props() {
  return {
    t,
    template,
    templateLocale: "en" as const,
    defaultTemplateId: "other",
    isImporting: false,
    isCreating: false,
    settingDefaultTemplateId: null as string | null,
    onSetDefaultTemplate: vi.fn(),
    onTemplateLocaleChange: vi.fn(),
    onCreateCustomTemplate: vi.fn(),
    onUpdateTemplate: vi.fn(),
  };
}

it.each([false, true])(
  "composes metadata beside the title with a stable empty description, builtin=%s",
  async (isBuiltIn) => {
    const value = props();
    const { container } = render(
      <TemplateEditor {...value} template={{ ...template, isBuiltIn }} />,
    );
    expect(
      container.querySelector('[data-slot="template-editor-title"]')
        ?.textContent,
    ).toBe(template.name);
    expect(
      container.querySelector('[data-slot="template-description"]')
        ?.textContent,
    ).toBe("");
    expect(
      container.querySelectorAll('[data-slot="template-description"]'),
    ).toHaveLength(1);
    expect(screen.queryByText(t.templateDescriptionFallback)).toBeNull();
    if (isBuiltIn) {
      expect(
        screen.queryByRole("button", { name: t.editTemplateInfo }),
      ).toBeNull();
      expect(screen.getByText(t.templateReadonlyStatus)).not.toBeNull();
      fireEvent.click(
        screen.getByRole("button", { name: t.createEditableCopy }),
      );
      expect(value.onCreateCustomTemplate).toHaveBeenCalledOnce();
    } else {
      const edit = screen.getByRole("button", { name: t.editTemplateInfo });
      expect(
        edit.closest('[data-slot="template-editor-header"]'),
      ).not.toBeNull();
      fireEvent.click(edit);
      const dialog = screen.getByRole("dialog");
      fireEvent.change(within(dialog).getByLabelText(t.templateName), {
        target: { value: "Renamed" },
      });
      fireEvent.click(
        within(dialog).getByRole("button", { name: t.saveTemplateInfo }),
      );
      await waitFor(() =>
        expect(value.onUpdateTemplate).toHaveBeenCalledExactlyOnceWith(
          "custom",
          { name: "Renamed", description: "" },
        ),
      );
    }
  },
);
it("keeps the default button and language selection stable while a default change is pending", () => {
  const value = props();
  const { rerender } = render(<TemplateEditor {...value} />);
  const button = screen.getByRole("button", { name: t.setDefaultTemplate });
  fireEvent.click(button);
  expect(value.onSetDefaultTemplate).toHaveBeenCalledExactlyOnceWith("custom");
  const language = screen.getByRole("combobox", { name: t.resumeLanguage });
  fireEvent.keyDown(language, { key: "ArrowDown" });
  fireEvent.click(screen.getByRole("option", { name: t.chinesePreview }));
  expect(value.onTemplateLocaleChange).toHaveBeenCalledExactlyOnceWith("zh");
  rerender(
    <TemplateEditor
      {...value}
      templateLocale="zh"
      settingDefaultTemplateId="custom"
    />,
  );
  expect(screen.getByRole("button", { name: t.setDefaultTemplate })).toBe(
    button,
  );
  expect(button.getAttribute("aria-busy")).toBe("true");
  expect((button as HTMLButtonElement).disabled).toBe(true);
  expect((language as HTMLButtonElement).disabled).toBe(true);
  expect(button.querySelector('[data-slot="spinner"]')).toBeNull();
  rerender(<TemplateEditor {...value} defaultTemplateId="custom" />);
  expect(screen.getByRole("button", { name: t.defaultTemplateLabel })).toBe(
    button,
  );
  expect(button.getAttribute("aria-busy")).toBeNull();
  expect((button as HTMLButtonElement).disabled).toBe(true);
});
it.each(
  getBuiltInTemplates(t).map((value) => ({
    preset: value.preset,
    base: value,
  })),
)("scales both avatar dimensions from the $preset preset", ({ base }) => {
  const onUpdateTemplate = vi.fn();
  render(
    <Tabs value="layout">
      <TemplateLayoutTab
        t={t}
        template={{
          ...base,
          isBuiltIn: false,
          layout: { ...base.layout, avatarPosition: "left" },
        }}
        onUpdateTemplate={onUpdateTemplate}
      />
    </Tabs>,
  );
  fireEvent.keyDown(screen.getByRole("combobox", { name: t.avatarSize }), {
    key: "ArrowDown",
  });
  fireEvent.click(screen.getByRole("option", { name: t.avatarSizeLarge }));
  const update = onUpdateTemplate.mock.calls[0][0];
  expect(update.layout.avatarWidth).toBe(
    Math.round(((base.layout.avatarWidth * 115) / 100) * 2) / 2,
  );
  expect(update.layout.avatarHeight).toBe(
    Math.round(((base.layout.avatarHeight * 115) / 100) * 2) / 2,
  );
});
it("measures the active tab indicator, coalesces resize frames and cancels them on unmount", () => {
  vi.useFakeTimers();
  const observers: {
    callback: ResizeObserverCallback;
    observe: ReturnType<typeof vi.fn>;
    disconnect: ReturnType<typeof vi.fn>;
  }[] = [];
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe = vi.fn();
      disconnect = vi.fn();
      unobserve = vi.fn();
      constructor(callback: ResizeObserverCallback) {
        observers.push({
          callback,
          observe: this.observe,
          disconnect: this.disconnect,
        });
      }
    },
  );
  let width = 80;
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
    function (this: HTMLElement) {
      const list = this.getAttribute("role") === "tablist";
      const visual = this.textContent?.includes(t.templateVisualTab) && !list;
      const left = list ? 10 : visual ? 210 : 20;
      return {
        x: left,
        y: 0,
        top: 0,
        left,
        right: left + width,
        bottom: 36,
        width,
        height: 36,
        toJSON() {},
      };
    },
  );
  const { container, unmount } = render(
    <TemplateEditorTabs t={t} template={template} onUpdateTemplate={vi.fn()} />,
  );
  const list = screen.getByRole("tablist");
  const indicator = list.querySelector<HTMLSpanElement>(
    'span[aria-hidden="true"][data-ready]',
  )!;
  expect(indicator.dataset.ready).toBe("true");
  expect(indicator.style.width).toBe("80px");
  expect(indicator.style.transform).toBe("translate3d(10px, 0, 0)");
  fireEvent.mouseDown(screen.getByRole("tab", { name: t.templateVisualTab }), {
    button: 0,
    ctrlKey: false,
  });
  expect(indicator.style.transform).toBe("translate3d(200px, 0, 0)");
  const observer = observers.findLast((item) =>
    item.observe.mock.calls.some(([element]) => element === list),
  )!;
  expect(observer.observe.mock.calls).toHaveLength(5);
  const frame = vi.spyOn(window, "requestAnimationFrame");
  width = 96;
  act(() => {
    observer.callback([], {} as ResizeObserver);
    observer.callback([], {} as ResizeObserver);
  });
  expect(frame).toHaveBeenCalledOnce();
  act(() => vi.advanceTimersToNextFrame());
  expect(indicator.style.width).toBe("96px");
  act(() => observer.callback([], {} as ResizeObserver));
  const cancel = vi.spyOn(window, "cancelAnimationFrame");
  unmount();
  expect(observer.disconnect).toHaveBeenCalledOnce();
  expect(cancel).toHaveBeenCalledWith(frame.mock.results.at(-1)?.value);
  expect(container.childElementCount).toBe(0);
});

it("retains the editor's active tab when the workspace view receives another template", async () => {
  const { TemplateDetailWorkspaceView } =
    await import("@/components/workspace/template-detail-workspace-view");
  const controller: import("@/components/workspace/use-template-detail-workspace").TemplateDetailWorkspaceController =
    {
      changeTheme: vi.fn(),
      changeView: vi.fn(),
      createCustomTemplate: vi.fn(async () => {}),
      defaultTemplateId: "other",
      goBack: vi.fn(),
      hasLoadError: false,
      hasLoaded: true,
      isCreating: false,
      isLoading: false,
      leave: {
        cancelLeave: vi.fn(),
        discardAndLeave: vi.fn(async () => {}),
        isOpen: false,
        isResolving: false,
        requestLeave: vi.fn(),
        saveAndLeave: vi.fn(async () => {}),
      },
      logout: vi.fn(),
      moveTemplateImage: vi.fn(),
      preloadWorkspaceView: vi.fn(),
      resolvedTheme: "light",
      retryLoad: vi.fn(),
      save: vi.fn(async () => true),
      saveChangeCount: 0,
      saveLastSavedAt: null,
      saveState: "idle",
      setDefaultTemplate: vi.fn(async () => {}),
      settingDefaultTemplateId: null,
      setTemplateLocale: vi.fn(),
      template,
      templateLocale: "en",
      templatePreviewMessages: null,
      templatePreviewResume: null,
      theme: "light",
      updateTemplate: vi.fn(),
    };
  const view = render(
    <TemplateDetailWorkspaceView
      controller={controller}
      locale="en"
      messages={t}
      onLocaleChange={vi.fn()}
    />,
  );
  const images = screen.getByRole("tab", { name: t.templateImagesTab });
  fireEvent.mouseDown(images, { button: 0, ctrlKey: false });
  expect(images.getAttribute("aria-selected")).toBe("true");
  view.rerender(
    <TemplateDetailWorkspaceView
      controller={{
        ...controller,
        template: { ...template, id: "second", name: "Second template" },
      }}
      locale="en"
      messages={t}
      onLocaleChange={vi.fn()}
    />,
  );
  expect(screen.getByRole("tab", { name: t.templateImagesTab })).toBe(images);
  expect(images.getAttribute("aria-selected")).toBe("true");
  expect(
    screen.getByRole("heading", { level: 1, name: "Second template" }),
  ).not.toBeNull();
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: t.addTemplateImage }),
    ).not.toBeNull(),
  );
});
