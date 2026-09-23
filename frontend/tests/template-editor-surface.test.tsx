import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { ErrorBoundary } from "react-error-boundary";
import { ResourceRecoveryContext } from "@/components/resource-recovery-context";
import { defaultMessages } from "@/i18n";
import zhMessages from "@/i18n/locales/zh.json";
import { getTemplateEditorMessages } from "@/components/templates/editor/editor-messages";
import { TemplateActions } from "@/components/templates/template-actions";
import { TemplatePreviewToolbar } from "@/components/templates/template-preview-toolbar";
import { TemplateEditor } from "@/components/templates/template-editor";
import { TemplateEditorTabs } from "@/components/templates/template-editor-tabs";
import { TemplateLayoutTab } from "@/components/templates/editor/layout-tab";
import { TemplateStyleTabs } from "@/components/templates/template-style-tabs";
import { TemplateDetailWorkspaceView } from "@/components/workspace/template-detail-workspace-view";
import type { TemplateDetailWorkspaceController } from "@/components/workspace/use-template-detail-workspace";
import { createResumeDetailItem } from "./helpers/resume-detail-fixtures";
import {
  createTemplateImageElement,
  getBuiltInTemplates,
} from "@/lib/templates";

const previewResource = vi.hoisted(() => ({ failed: false }));
vi.mock("@/components/preview/document-canvas", () => ({
  DocumentCanvas: () => {
    if (previewResource.failed) {
      throw new TypeError(
        "Failed to fetch dynamically imported module: /template-image-editor.js",
      );
    }
    return <div role="img" aria-label="Resume preview" />;
  },
}));

const t = getTemplateEditorMessages("en", defaultMessages);

const template = {
  ...getBuiltInTemplates(t)[0],
  id: "custom",
  isBuiltIn: false,
  name: "Custom layout",
  description: "",
};
beforeEach(() => {
  previewResource.failed = false;
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
});
function editorProps() {
  return {
    t: defaultMessages,
    locale: "en" as const,
    template,
    defaultTemplateId: "other",
    isCreating: false,
    settingDefaultTemplateId: null as string | null,
    onSetDefaultTemplate: vi.fn(),
    onCreateCustomTemplate: vi.fn(),
    onUpdateTemplate: vi.fn(),
  };
}
function actionProps() {
  return {
    messages: t,
    template,
    defaultTemplateId: "other",
    isCreating: false,
    settingDefaultTemplateId: null as string | null,
    onSetDefaultTemplate: vi.fn(),
    onCreateCustomTemplate: vi.fn(),
  };
}

it("updates inspector copy when the interface language changes", () => {
  const value = editorProps();
  const { rerender } = render(<TemplateEditor {...value} />);
  expect(screen.getByText(t.templateContentStructure)).not.toBeNull();

  const zh = getTemplateEditorMessages("zh", zhMessages);
  rerender(<TemplateEditor {...value} t={zhMessages} locale="zh" />);
  expect(screen.getByText(zh.templateContentStructure)).not.toBeNull();
  expect(screen.queryByText(t.templateContentStructure)).toBeNull();
});

it.each([t, getTemplateEditorMessages("zh", zhMessages)])(
  "keeps the selected layout preview and label in sync in $basicInfoLayout",
  (messages) => {
    const onUpdateTemplate = vi.fn();
    const view = (value: typeof template) => (
      <TemplateStyleTabs value="layout">
        <TemplateLayoutTab
          t={messages}
          template={value}
          onUpdateTemplate={onUpdateTemplate}
        />
      </TemplateStyleTabs>
    );
    const { rerender } = render(view(template));
    const previewSelector = 'span[aria-hidden="true"] > svg';
    for (const label of [
      messages.basicInfoLayout,
      messages.sectionTemplateStyle,
      messages.timelineItemLayout,
      messages.listItemLayout,
      messages.templateDividerStyle,
    ]) {
      const control = screen.getByRole("combobox", { name: label });
      expect(control.querySelector(previewSelector), label).not.toBeNull();
      expect(within(control).queryByRole("img")).toBeNull();
    }
    const section = screen.getByRole<HTMLButtonElement>("combobox", {
      name: messages.sectionTemplateStyle,
    });
    const initialPreview = section.querySelector(previewSelector)!.outerHTML;
    fireEvent.keyDown(section, { key: "ArrowDown" });
    const option = screen.getByRole("option", {
      name: messages.sectionStyleBoxed,
    });
    const nextPreview = option.querySelector(previewSelector)!.outerHTML;
    expect(nextPreview).not.toBe(initialPreview);
    fireEvent.click(option);
    expect(onUpdateTemplate).toHaveBeenCalledExactlyOnceWith({
      layout: { ...template.layout, section: "boxed" },
    });
    const next = {
      ...template,
      layout: { ...template.layout, section: "boxed" as const },
    };
    rerender(view(next));
    expect(section.textContent).toBe(messages.sectionStyleBoxed);
    expect(section.querySelector(previewSelector)!.outerHTML).toBe(nextPreview);
    expect(
      screen.getByRole("combobox", { name: messages.sectionTemplateStyle }),
    ).toBe(section);
    rerender(view({ ...next, isBuiltIn: true }));
    expect(section.disabled).toBe(true);
    expect(section.querySelector(previewSelector)!.outerHTML).toBe(nextPreview);
  },
);

it.each([false, true])(
  "offers editable copies only for built-in templates, builtin=%s",
  (isBuiltIn) => {
    const value = actionProps();
    const { rerender } = render(
      <TemplateActions {...value} template={{ ...template, isBuiltIn }} />,
    );
    const createCopy = screen.queryByRole<HTMLButtonElement>("button", {
      name: t.createEditableCopy,
    });
    if (isBuiltIn) {
      expect(createCopy).not.toBeNull();
      fireEvent.click(createCopy!);
      expect(value.onCreateCustomTemplate).toHaveBeenCalledOnce();
      rerender(
        <TemplateActions
          {...value}
          template={{ ...template, isBuiltIn }}
          isCreating
        />,
      );
      expect(createCopy!.disabled).toBe(true);
      fireEvent.click(createCopy!);
      expect(value.onCreateCustomTemplate).toHaveBeenCalledOnce();
    } else {
      expect(createCopy).toBeNull();
    }
  },
);
it("keeps the default action stable while a default change is pending", () => {
  const value = actionProps();
  const { rerender } = render(<TemplateActions {...value} />);
  const button = screen.getByRole<HTMLButtonElement>("button", {
    name: t.setDefaultTemplate,
  });
  fireEvent.click(button);
  expect(value.onSetDefaultTemplate).toHaveBeenCalledExactlyOnceWith("custom");
  rerender(<TemplateActions {...value} settingDefaultTemplateId="custom" />);
  expect(screen.getByRole("button", { name: t.setDefaultTemplate })).toBe(
    button,
  );
  expect(button.getAttribute("aria-busy")).toBe("true");
  expect(button.disabled).toBe(true);
  expect(button.querySelector('[role="status"]')).not.toBeNull();
  fireEvent.click(button);
  expect(value.onSetDefaultTemplate).toHaveBeenCalledOnce();
  rerender(<TemplateActions {...value} />);
  expect(screen.getByRole("button", { name: t.setDefaultTemplate })).toBe(
    button,
  );
  expect(button.getAttribute("aria-busy")).toBeNull();
  expect(button.disabled).toBe(false);
  expect(button.querySelector('[role="status"]')).toBeNull();
  fireEvent.click(button);
  expect(value.onSetDefaultTemplate).toHaveBeenCalledTimes(2);
  rerender(<TemplateActions {...value} defaultTemplateId="custom" />);
  expect(screen.getByRole("button", { name: t.defaultTemplateLabel })).toBe(
    button,
  );
  expect(button.getAttribute("aria-busy")).toBeNull();
  expect(button.disabled).toBe(true);
  expect(button.querySelector("svg")).toBeNull();
});
it("keeps preview language separate from the interface language and disables changes while requested", () => {
  const onTemplateLocaleChange = vi.fn();
  const { container, rerender } = render(
    <TemplatePreviewToolbar
      messages={defaultMessages}
      templateLocale="zh"
      disabled={false}
      onTemplateLocaleChange={onTemplateLocaleChange}
    />,
  );
  const language = screen.getByRole<HTMLButtonElement>("combobox", {
    name: t.resumeLanguage,
  });
  expect(language.textContent).toContain(t.chinesePreview);
  expect(container.textContent).toBe(t.resumeLanguage + t.chinesePreview);
  fireEvent.keyDown(language, { key: "ArrowDown" });
  fireEvent.click(screen.getByRole("option", { name: t.englishPreview }));
  expect(onTemplateLocaleChange).toHaveBeenCalledExactlyOnceWith("en");
  rerender(
    <TemplatePreviewToolbar
      messages={zhMessages}
      templateLocale="en"
      disabled
      onTemplateLocaleChange={onTemplateLocaleChange}
    />,
  );
  expect(
    screen.getByRole("combobox", { name: zhMessages.resumeLanguage }),
  ).toBe(language);
  expect(language.textContent).toContain(zhMessages.englishPreview);
  expect(container.textContent).toBe(
    zhMessages.resumeLanguage + zhMessages.englishPreview,
  );
  expect(language.disabled).toBe(true);
  fireEvent.keyDown(language, { key: "ArrowDown" });
  expect(screen.queryByRole("listbox")).toBeNull();
  expect(onTemplateLocaleChange).toHaveBeenCalledOnce();
});
it.each(
  getBuiltInTemplates(t).map((value) => ({
    preset: value.preset,
    base: value,
  })),
)("scales both avatar dimensions from the $preset preset", ({ base }) => {
  const onUpdateTemplate = vi.fn();
  render(
    <TemplateStyleTabs value="layout">
      <TemplateLayoutTab
        t={t}
        template={{
          ...base,
          isBuiltIn: false,
          layout: { ...base.layout, avatarPosition: "left" },
        }}
        onUpdateTemplate={onUpdateTemplate}
      />
    </TemplateStyleTabs>,
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
it("switches inspector sections with the keyboard and retains image editor state", async () => {
  render(
    <TemplateEditorTabs
      locale="en"
      t={t}
      template={{
        ...template,
        layout: {
          ...template.layout,
          images: [
            createTemplateImageElement(1, t.imageDefaultName, template.layout),
          ],
        },
      }}
      onUpdateTemplate={vi.fn()}
    />,
  );
  const layout = screen.getByRole("tab", { name: t.templateLayoutTab });
  expect(layout.getAttribute("aria-selected")).toBe("true");
  layout.focus();
  for (const label of [
    t.templateTypographyTab,
    t.templateVisualTab,
    t.templateImagesTab,
  ]) {
    fireEvent.keyDown(document.activeElement!, { key: "ArrowRight" });
    const next = screen.getByRole("tab", { name: label });
    await waitFor(() => {
      expect(document.activeElement).toBe(next);
      expect(next.getAttribute("aria-selected")).toBe("true");
      expect(
        screen
          .getByRole("tabpanel", { name: label })
          .getAttribute("aria-labelledby"),
      ).toBe(next.id);
    });
  }
  fireEvent.click(
    await screen.findByRole("button", { name: t.expandImageSettings }),
  );
  expect(
    screen.getByRole("button", { name: t.collapseImageSettings }),
  ).not.toBeNull();
  const images = screen.getByRole("tab", { name: t.templateImagesTab });
  images.focus();
  fireEvent.keyDown(images, { key: "Home" });
  await waitFor(() => {
    expect(document.activeElement).toBe(layout);
    expect(layout.getAttribute("aria-selected")).toBe("true");
  });
  fireEvent.keyDown(layout, { key: "End" });
  await waitFor(() => {
    expect(document.activeElement).toBe(images);
    expect(images.getAttribute("aria-selected")).toBe("true");
    expect(
      screen.getByRole("button", { name: t.collapseImageSettings }),
    ).not.toBeNull();
  });
});

it("opens the preloaded color tab immediately and retains its controls across tab switches", async () => {
  const onUpdateTemplate = vi.fn();
  const view = (value: typeof template) => (
    <TemplateEditorTabs
      locale="en"
      t={t}
      template={value}
      onUpdateTemplate={onUpdateTemplate}
    />
  );
  const { rerender } = render(view(template));
  await act(async () => {
    await import("@/components/templates/editor/visual-tab");
  });
  const colorLabel = `${t.headingColor} HEX`;
  expect(screen.queryByRole("textbox", { name: colorLabel })).toBeNull();

  fireEvent.click(screen.getByRole("tab", { name: t.templateVisualTab }));
  const panel = screen.getByRole("tabpanel", { name: t.templateVisualTab });
  expect(panel.querySelector('[aria-busy="true"]')).toBeNull();
  const input = screen.getByRole<HTMLInputElement>("textbox", {
    name: colorLabel,
  });
  fireEvent.change(input, { target: { value: "336699" } });
  expect(onUpdateTemplate).toHaveBeenCalledExactlyOnceWith({
    settings: { ...template.settings, headingColor: "#336699" },
  });
  rerender(
    view({
      ...template,
      settings: { ...template.settings, headingColor: "#336699" },
    }),
  );
  fireEvent.blur(input);
  fireEvent.click(screen.getByRole("tab", { name: t.templateLayoutTab }));
  expect(input.isConnected).toBe(true);
  expect(screen.queryByRole("textbox", { name: colorLabel })).toBeNull();
  expect(screen.queryByRole("dialog")).toBeNull();

  fireEvent.click(screen.getByRole("tab", { name: t.templateVisualTab }));
  expect(screen.getByRole("textbox", { name: colorLabel })).toBe(input);
  expect(input.value).toBe("#336699");
  expect(screen.getByRole("tabpanel", { name: t.templateVisualTab })).toBe(
    panel,
  );
});

function workspaceController(
  overrides: Partial<TemplateDetailWorkspaceController> = {},
): TemplateDetailWorkspaceController {
  return {
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
    updateTemplateImage: vi.fn(),
    preloadWorkspaceView: vi.fn(),
    resolvedTheme: "light",
    retryLoad: vi.fn(),
    save: vi.fn(async () => true),
    saveAndReload: vi.fn(async () => {}),
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
    ...overrides,
  };
}

it("contains a preview resource failure while preserving edits and save recovery", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  const controller = workspaceController({
    templatePreviewMessages: t,
    templatePreviewResume: createResumeDetailItem().resume,
  });
  function View() {
    return (
      <ErrorBoundary fallback={<span>Page unavailable</span>}>
        <ResourceRecoveryContext
          value={{ messages: t, saveAndReload: controller.saveAndReload }}
        >
          <TemplateDetailWorkspaceView
            controller={controller}
            locale="en"
            messages={t}
            onLocaleChange={vi.fn()}
          />
        </ResourceRecoveryContext>
      </ErrorBoundary>
    );
  }
  const { rerender } = render(<View />);
  await screen.findByRole("img", { name: "Resume preview" });
  const input = screen.getByRole<HTMLInputElement>("spinbutton", {
    name: t.lineSpacing,
  });
  fireEvent.change(input, { target: { value: "20" } });
  expect(controller.updateTemplate).toHaveBeenCalled();
  const title = screen.getByRole("heading", { level: 1, name: template.name });
  const language = screen.getByRole("combobox", { name: t.resumeLanguage });
  previewResource.failed = true;
  rerender(<View />);
  expect(screen.queryByText("Page unavailable")).toBeNull();
  expect(screen.getByRole("spinbutton", { name: t.lineSpacing })).toBe(input);
  expect(input.value).toBe("20");
  expect(screen.getByRole("heading", { level: 1, name: template.name })).toBe(
    title,
  );
  expect(screen.getByRole("combobox", { name: t.resumeLanguage })).toBe(
    language,
  );
  expect(screen.getByRole("alert").textContent).toContain(t.resourceLoadError);
  fireEvent.click(screen.getByRole("button", { name: t.saveAndReload }));
  await act(async () => {});
  expect(controller.saveAndReload).toHaveBeenCalledOnce();
});

it("retains the editor's active tab when the workspace view receives another template", async () => {
  const controller = workspaceController();
  const view = render(
    <TemplateDetailWorkspaceView
      controller={controller}
      locale="en"
      messages={t}
      onLocaleChange={vi.fn()}
    />,
  );
  const images = screen.getByRole("tab", { name: t.templateImagesTab });
  fireEvent.click(images);
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
  const editor = view.container.querySelector<HTMLElement>(
    '[data-slot="template-editor"]',
  )!;
  expect(within(editor).queryByText(t.templateReadonlyLabel)).toBeNull();
  expect(
    within(editor).getByRole("button", { name: t.setDefaultTemplate }),
  ).not.toBeNull();
  expect(
    screen.getByRole("heading", { level: 1, name: "Second template" }),
  ).not.toBeNull();
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: t.addTemplateImage }),
    ).not.toBeNull(),
  );
});

it("waits for loaded template data before exposing copy and default actions", () => {
  const controller = workspaceController({
    hasLoaded: false,
    isLoading: true,
    template: getBuiltInTemplates(t)[1],
  });
  const view = render(
    <TemplateDetailWorkspaceView
      controller={controller}
      locale="en"
      messages={t}
      onLocaleChange={vi.fn()}
    />,
  );
  expect(
    screen.queryByRole("button", { name: t.createEditableCopy }),
  ).toBeNull();
  expect(
    screen.queryByRole("button", { name: t.setDefaultTemplate }),
  ).toBeNull();
  expect(
    screen.queryByRole("button", { name: t.defaultTemplateLabel }),
  ).toBeNull();

  view.rerender(
    <TemplateDetailWorkspaceView
      controller={{ ...controller, hasLoaded: true, isLoading: false }}
      locale="en"
      messages={t}
      onLocaleChange={vi.fn()}
    />,
  );
  const editor = view.container.querySelector<HTMLElement>(
    '[data-slot="template-editor"]',
  )!;
  const header = view.container.querySelector<HTMLElement>(
    '[data-slot="template-workspace-header"]',
  )!;
  expect(
    within(header).getByText(t.templateReadonlyLabel).getAttribute("title"),
  ).toBe(t.templateReadonlyStatus);
  expect(within(editor).queryByTitle(t.templateReadonlyStatus)).toBeNull();
  expect(
    within(header).queryByRole("button", { name: t.createEditableCopy }),
  ).toBeNull();
  expect(
    within(header).queryByRole("button", { name: t.setDefaultTemplate }),
  ).toBeNull();
  fireEvent.click(
    within(editor).getByRole("button", { name: t.createEditableCopy }),
  );
  fireEvent.click(
    within(editor).getByRole("button", { name: t.setDefaultTemplate }),
  );
  expect(controller.createCustomTemplate).toHaveBeenCalledOnce();
  expect(controller.setDefaultTemplate).toHaveBeenCalledExactlyOnceWith(
    controller.template!.id,
  );
});

it("preserves the preview language selector and focus while messages load and permits switching back", async () => {
  const resume = createResumeDetailItem().resume;
  const controller = workspaceController({
    templatePreviewMessages: t,
    templatePreviewResume: resume,
  });
  const view = render(
    <TemplateDetailWorkspaceView
      controller={controller}
      locale="en"
      messages={t}
      onLocaleChange={vi.fn()}
    />,
  );
  await screen.findByRole("img", { name: "Resume preview" });
  const language = screen.getByRole("combobox", { name: t.resumeLanguage });
  language.focus();
  fireEvent.keyDown(language, { key: "ArrowDown" });
  fireEvent.click(screen.getByRole("option", { name: t.chinesePreview }));
  await waitFor(() => expect(document.activeElement).toBe(language));
  const pending = {
    ...controller,
    templateLocale: "zh" as const,
    templatePreviewMessages: null,
    templatePreviewResume: null,
  };
  view.rerender(
    <TemplateDetailWorkspaceView
      controller={pending}
      locale="en"
      messages={t}
      onLocaleChange={vi.fn()}
    />,
  );
  expect(screen.getByRole("combobox", { name: t.resumeLanguage })).toBe(
    language,
  );
  expect(document.activeElement).toBe(language);
  expect(screen.queryByRole("img", { name: "Resume preview" })).toBeNull();
  fireEvent.keyDown(language, { key: "ArrowDown" });
  fireEvent.click(screen.getByRole("option", { name: t.englishPreview }));
  expect(controller.setTemplateLocale).toHaveBeenCalledTimes(2);
  expect(controller.setTemplateLocale).toHaveBeenNthCalledWith(1, "zh");
  expect(controller.setTemplateLocale).toHaveBeenNthCalledWith(2, "en");
  await waitFor(() => expect(document.activeElement).toBe(language));

  view.rerender(
    <TemplateDetailWorkspaceView
      controller={controller}
      locale="en"
      messages={t}
      onLocaleChange={vi.fn()}
    />,
  );
  await screen.findByRole("img", { name: "Resume preview" });
  expect(screen.getByRole("combobox", { name: t.resumeLanguage })).toBe(
    language,
  );
  expect(document.activeElement).toBe(language);
});
