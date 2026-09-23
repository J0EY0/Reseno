import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getTemplateEditorMessages } from "@/components/templates/editor/editor-messages";
import { ResumeDetailWorkspaceHeader } from "@/components/workspace/resume-detail-workspace-header";
import { TemplateDetailWorkspaceHeader } from "@/components/workspace/template-detail-workspace-header";
import type { ResumeDetailWorkspaceModel } from "@/components/workspace/resume-detail-workspace-types";
import { defaultMessages as t } from "@/i18n";
import { createDefaultModelConfig } from "@/lib/model-config";
import {
  createResumeDetailItem,
  createResumeDetailTemplate,
} from "./helpers/resume-detail-fixtures";
import { installPanelBrowserApis } from "./helpers/route-view-fixtures";

let restore: () => void;
beforeEach(() => {
  restore = installPanelBrowserApis();
});
afterEach(() => {
  restore();
  vi.unstubAllGlobals();
});
function workspace(): ResumeDetailWorkspaceModel {
  const item = createResumeDetailItem({ id: "resume-1", documentLocale: "zh" });
  const template = createResumeDetailTemplate("minimal");
  return {
    state: {
      activeTemplate: template,
      previewTemplate: template,
      previewTypography: item.typography,
      agent: {
        draft: null,
        draftState: null,
        isPanelCollapsed: true,
        modelConfigs: [
          createDefaultModelConfig("en", {
            id: "model-1",
            model: "test-model",
            nickname: "Test model",
            provider: "openai",
          }),
        ],
        panelStatus: null,
        review: null,
        selectedModelConfigId: "model-1",
      },
      openSectionId: null,
      document: { isPreviewReady: true, isSmartFittingOnePage: false },
      hasLoadError: false,
      hasVersionLoadError: false,
      hasTemplateStyleOverrides: false,
      isDuplicatingResume: false,
      isExporting: false,
      isLoading: false,
      leave: { isOpen: false, isResolving: false },
      previewResume: item.resume,
      previewReview: null,
      resolvedTheme: "light",
      resume: item.resume,
      resumeItem: item,
      save: {
        activeVersionId: null,
        changeCount: 0,
        lastSavedAt: null,
        state: "saved",
        versions: [],
      },
      showSkeleton: false,
      template: "minimal",
      templates: [template],
      theme: "light",
      title: { draft: item.title, isOpen: false },
      typography: item.typography,
    },
    commands: {
      agent: {
        applyDraft: vi.fn(async () => null),
        changeSelectedModelConfig: vi.fn(),
        discardDraft: vi.fn(async () => null),
        flushUserSettings: vi.fn(async () => undefined),
        openModelSettings: vi.fn(),
        previewEdits: vi.fn(),
        reconcileDraft: vi.fn(),
        reportPanelStatus: vi.fn(),
        rollbackDraft: vi.fn(),
        setPanelCollapsed: vi.fn(),
      },
      applyTemplate: vi.fn(),
      back: vi.fn(),
      changeTheme: vi.fn(),
      changeTitleDraft: vi.fn(),
      changeView: vi.fn(),
      duplicateResume: vi.fn(),
      exportImages: vi.fn(),
      exportJson: vi.fn(),
      exportPdf: vi.fn(),
      fitOnePage: vi.fn(),
      logout: vi.fn(),
      onPreviewReadyChange: vi.fn(),
      preloadView: vi.fn(),
      restoreTemplateDefaults: vi.fn(),
      retryLoad: vi.fn(),
      save: vi.fn(),
      saveAndReload: vi.fn(),
      saveTitle: vi.fn(),
      selectVersion: vi.fn(),
      addSection: vi.fn(),
      removeSection: vi.fn(),
      toggleSection: vi.fn(),
      updateContent: vi.fn(),
      setTitleDialogOpen: vi.fn(),
      updateTemplateSettings: vi.fn(),
      updateTypography: vi.fn(),
      cancelLeave: vi.fn(),
      discardAndLeave: vi.fn(),
      saveAndLeave: vi.fn(),
    },
  };
}

function templateHeaderProps() {
  return {
    changeCount: 0,
    headerRef: { current: null },
    lastSavedAt: null,
    locale: "en" as const,
    messages: t,
    onBack: vi.fn(),
    onLocaleChange: vi.fn(),
    onLogout: vi.fn(),
    onSave: vi.fn(async () => undefined),
    onThemeChange: vi.fn(),
    onUpdateTemplate: vi.fn(),
    resolvedTheme: "light" as const,
    saveState: "saved" as const,
    template: createResumeDetailTemplate("custom"),
  };
}

it("keeps actual detail back buttons at the shared outline size and export menu at trigger width", async () => {
  const model = workspace();
  const view = render(
    <ResumeDetailWorkspaceHeader
      headerRef={{ current: null }}
      locale="en"
      messages={t}
      model={model}
      onLocaleChange={vi.fn()}
    />,
  );
  await act(() => vi.dynamicImportSettled());
  const back = screen.getByRole("button", { name: t.backToResumes });
  expect(back.getAttribute("data-variant")).toBe("outline");
  expect(back.getAttribute("data-size")).toBe("default");
  fireEvent.click(back);
  expect(model.commands.back).toHaveBeenCalledOnce();
  for (const [label, handler] of [
    [t.exportPdf, model.commands.exportPdf],
    [t.exportImages, model.commands.exportImages],
    [t.exportJson, model.commands.exportJson],
  ] as const) {
    const trigger = screen.getByRole("button", { name: t.export });
    expect(trigger.classList.contains("min-w-32")).toBe(true);
    fireEvent.keyDown(trigger, { key: "Enter" });
    const menu = screen.getByRole("menu");
    for (const token of [
      "w-[var(--radix-dropdown-menu-trigger-width)]",
      "min-w-[var(--radix-dropdown-menu-trigger-width)]",
    ])
      expect(menu.classList.contains(token)).toBe(true);
    fireEvent.click(screen.getByRole("menuitem", { name: label }));
    expect(handler).toHaveBeenCalledOnce();
  }
  view.unmount();
  const props = templateHeaderProps();
  render(<TemplateDetailWorkspaceHeader {...props} />);
  const templateBack = screen.getByRole("button", { name: t.backToTemplates });
  expect(templateBack.getAttribute("data-variant")).toBe("outline");
  expect(templateBack.getAttribute("data-size")).toBe("default");
  fireEvent.click(templateBack);
  expect(props.onBack).toHaveBeenCalledOnce();
});

it.each([false, true])(
  "shows template metadata in the header and edits only custom templates, builtin=%s",
  async (isBuiltIn) => {
    const props = templateHeaderProps();
    const templateMessages = getTemplateEditorMessages(
      props.locale,
      props.messages,
    );
    const template = createResumeDetailTemplate("template-1", {
      name: "Minimal",
      description: "Classic single column",
      isBuiltIn,
    });
    const { rerender } = render(
      <TemplateDetailWorkspaceHeader {...props} template={template} />,
    );
    const header = screen.getByRole("banner");
    expect(
      within(header).getByRole("heading", { level: 1, name: template.name }),
    ).not.toBeNull();
    expect(within(header).getByText(template.description)).not.toBeNull();
    const edit = within(header).queryByRole("button", {
      name: t.editTemplateInfo,
    });
    expect(
      within(header).queryByRole("button", { name: t.setDefaultTemplate }),
    ).toBeNull();
    expect(
      within(header).queryByRole("button", {
        name: templateMessages.createEditableCopy,
      }),
    ).toBeNull();
    if (isBuiltIn) {
      expect(
        within(header).getByTitle(templateMessages.templateReadonlyStatus)
          .textContent,
      ).toBe(templateMessages.templateReadonlyLabel);
      expect(edit).toBeNull();
      expect(props.onUpdateTemplate).not.toHaveBeenCalled();
    } else {
      expect(
        within(header).queryByTitle(templateMessages.templateReadonlyStatus),
      ).toBeNull();
      expect(edit).not.toBeNull();
      fireEvent.click(edit!);
      const dialog = screen.getByRole("dialog", { name: t.editTemplateInfo });
      fireEvent.change(within(dialog).getByLabelText(t.templateName), {
        target: { value: "Renamed" },
      });
      fireEvent.change(within(dialog).getByLabelText(t.templateDescription), {
        target: { value: "Updated description" },
      });
      fireEvent.click(
        within(dialog).getByRole("button", { name: t.saveTemplateInfo }),
      );
      expect(props.onUpdateTemplate).toHaveBeenCalledExactlyOnceWith(
        template.id,
        { name: "Renamed", description: "Updated description" },
      );
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
      rerender(
        <TemplateDetailWorkspaceHeader
          {...props}
          template={{
            ...template,
            name: "Renamed",
            description: "Updated description",
          }}
        />,
      );
      expect(
        within(header).getByRole("heading", { level: 1, name: "Renamed" }),
      ).not.toBeNull();
      expect(within(header).getByText("Updated description")).not.toBeNull();
    }
  },
);
